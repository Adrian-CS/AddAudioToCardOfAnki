from __future__ import annotations

"""
Audio fetching logic.

Priority:
  1. English Wiktionary — native human recordings (.ogg/.wav/.flac)
     Filters files by language using Wikidata Q-codes and ISO 639 prefixes.
  2. Google Translate TTS — synthetic fallback (optional, user-controlled).

Uses only stdlib (urllib) — no pip install needed.

Word extraction:
  Fields often contain phrases or mixed-language entries like:
    "floor piso planta", "already/ya", "cuál?", "de la mañana"
  _candidate_words() splits these into individual candidates and tries
  each one until Wiktionary returns an audio file in the target language.
"""

import json
import os
import re
import ssl
import tempfile
import time
import threading
import urllib.error
import urllib.parse
import urllib.request

_LOG = os.path.join(tempfile.gettempdir(), "anki_add_audio.log")


def _log(msg: str) -> None:
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Language metadata
# Each entry: display name, Wikidata Q-code (lowercase), ISO 639-3 code
# The Q-code identifies the language in LL-Q<n> (iso3) community recordings.
# ---------------------------------------------------------------------------

LANGUAGES: dict[str, tuple[str, str, str]] = {
    "ar": ("Arabic",      "q13955", "ara"),
    "zh": ("Chinese",     "q7850",  "zho"),
    "nl": ("Dutch",       "q7411",  "nld"),
    "en": ("English",     "q1860",  "eng"),
    "fr": ("French",      "q150",   "fra"),
    "de": ("German",      "q188",   "deu"),
    "it": ("Italian",     "q652",   "ita"),
    "ja": ("Japanese",    "q5287",  "jpn"),
    "ko": ("Korean",      "q9176",  "kor"),
    "pt": ("Portuguese",  "q5146",  "por"),
    "ru": ("Russian",     "q7737",  "rus"),
    "es": ("Spanish",     "q1321",  "spa"),
}

WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"
GTTS_URL = "https://translate.google.com/translate_tts"
REQUEST_TIMEOUT = 10
HEADERS = {"User-Agent": "AnkiAddOn-AddAudioToCards/1.0"}

_SSL_CTX = ssl.create_default_context()

# Separate rate limiters: Wiktionary API and upload.wikimedia.org (audio files)
# have independent rate limits — the download CDN is more aggressive.
_api_lock = threading.Lock()
_api_last = 0.0
_API_INTERVAL = 0.25   # 4 req/sec — safe for en.wiktionary.org

_dl_lock = threading.Lock()
_dl_last = 0.0
_DL_INTERVAL = 1.0     # 1 download/sec — avoids 429 from upload.wikimedia.org

# Short function words unlikely to have a standalone Wiktionary audio entry.
_STOP_WORDS = frozenset({
    "de", "la", "el", "los", "las", "del", "un", "una", "en", "a", "y", "o",
    "al", "su", "lo", "le", "me", "te", "se", "mi", "tu", "por", "para",
    "con", "sin", "que", "si", "no", "ya",
    "the", "an", "of", "in", "on", "at", "to", "for", "is", "are", "or",
})


def _candidate_words(raw: str) -> list[str]:
    """
    Extract lookup candidates from a potentially multi-word field value.

    Examples:
        "cuál?"              → ["cuál"]
        "floor piso planta"  → ["floor", "piso", "planta"]
        "already/ya"         → ["already"]        (ya filtered: stop word)
        "de la mañana"       → ["mañana"]         (de, la filtered: stop words)
        "adelante,aquí tiene"→ ["adelante", "aquí", "tiene"]
        "hablar"             → ["hablar"]
    """
    cleaned = re.sub(r"[?!.;:~()\[\]_]", " ", raw).strip()
    parts = re.split(r"[/,\s]+", cleaned)

    candidates = []
    for p in parts:
        p = p.strip()
        if (
            p
            and len(p) >= 2
            and p.lower() not in _STOP_WORDS
            and not p.isdigit()
            and not re.fullmatch(r"[^\w\u00C0-\u024F]+", p)
        ):
            candidates.append(p)

    seen: set[str] = set()
    result = []
    for c in candidates:
        if c.lower() not in seen:
            seen.add(c.lower())
            result.append(c)
    return result


def _http_get(url: str, params: dict | None = None, download: bool = False) -> bytes:
    global _api_last, _dl_last

    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    elif download and "?" in url:
        url = url.split("?")[0]  # strip UTM tracking params from Wikimedia URLs

    if download:
        with _dl_lock:
            wait = _DL_INTERVAL - (time.monotonic() - _dl_last)
            if wait > 0:
                time.sleep(wait)
            _dl_last = time.monotonic()
    else:
        with _api_lock:
            wait = _API_INTERVAL - (time.monotonic() - _api_last)
            if wait > 0:
                time.sleep(wait)
            _api_last = time.monotonic()

    timeout = 20 if download else REQUEST_TIMEOUT
    req = urllib.request.Request(url, headers=HEADERS)

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                backoff = 5 * (attempt + 1)
                _log(f"[429] {url} — waiting {backoff}s (attempt {attempt + 1})")
                time.sleep(backoff)
                if attempt < 2:
                    continue
            raise
        except Exception:
            if attempt < 2:
                time.sleep(1)
            else:
                raise


def _http_get_json(url: str, params: dict | None = None) -> dict:
    return json.loads(_http_get(url, params))


def _is_target_audio(title: str, lang: str) -> bool:
    """Return True if a Wiktionary file title is a pronunciation in *lang*."""
    name = re.sub(r"^(file|archivo):\s*", "", title, flags=re.IGNORECASE).lower()
    _, q, iso3 = LANGUAGES.get(lang, ("", "", ""))
    return (
        (q    and q           in name)          # LL-Q1321 (spa)-Speaker-word.*
        or (iso3 and f"({iso3})" in name)       # explicit ISO tag
        or name.startswith(f"{lang}-")          # Es-word.ogg / Fr-word.ogg / ...
    )


def _find_wiktionary_audio_url(word: str, lang: str) -> str | None:
    """Return the CDN URL of a native pronunciation file for *word* in *lang*."""
    try:
        data = _http_get_json(WIKTIONARY_API, {
            "action": "query",
            "titles": word,
            "prop": "images",
            "imlimit": "50",
            "format": "json",
        })
    except Exception as e:
        _log(f"[API-1 FAIL] {word!r}: {e}")
        return None

    pages = data.get("query", {}).get("pages", {})
    images = []
    for page in pages.values():
        images.extend(page.get("images", []))

    audio_titles = [
        img["title"] for img in images
        if re.search(r"\.(ogg|wav|flac)$", img["title"], re.IGNORECASE)
        and _is_target_audio(img["title"], lang)
    ]

    if not audio_titles:
        _log(f"[NO-AUDIO] {word!r} ({lang}) — images: {[i['title'] for i in images]}")
        return None

    try:
        data2 = _http_get_json(WIKTIONARY_API, {
            "action": "query",
            "titles": audio_titles[0],
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
        })
    except Exception as e:
        _log(f"[API-2 FAIL] {word!r} / {audio_titles[0]!r}: {e}")
        return None

    for page in data2.get("query", {}).get("pages", {}).values():
        for info in page.get("imageinfo", []):
            url = info.get("url")
            if url:
                _log(f"[OK] {word!r} ({lang}) → {url}")
                return url

    _log(f"[NO-URL] {word!r} — imageinfo returned no url")
    return None


def fetch_wiktionary_audio(word: str, lang: str = "es") -> bytes | None:
    """Download native audio from Wiktionary for *word* in *lang*, or None."""
    for candidate in _candidate_words(word):
        url = _find_wiktionary_audio_url(candidate, lang)
        if url:
            try:
                data = _http_get(url, download=True)
                if data:
                    return data
            except Exception as e:
                _log(f"[DOWNLOAD FAIL] {candidate!r} ({url}): {e}")
                continue
    return None


def fetch_gtts_audio(word: str, lang: str = "es") -> bytes | None:
    """Download TTS audio from Google Translate (unofficial endpoint), or None."""
    try:
        params = urllib.parse.urlencode({
            "ie": "UTF-8", "q": word, "tl": lang, "client": "tw-ob"
        })
        url = GTTS_URL + "?" + params
        req = urllib.request.Request(url, headers={**HEADERS, "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=_SSL_CTX) as resp:
            data = resp.read()
        return data if data else None
    except Exception:
        return None


def get_audio(word: str, lang: str = "es", use_tts: bool = False) -> tuple[bytes | None, str]:
    """
    Fetch audio for *word* in *lang*.

    Args:
        word:    The word/phrase from the Anki field.
        lang:    BCP-47 language code — determines both the Wiktionary filter
                 and the TTS language.
        use_tts: If True and no native audio is found, fall back to Google TTS.

    Returns:
        (audio_bytes, source) where source is 'wiktionary', 'tts', or 'none'.
    """
    data = fetch_wiktionary_audio(word, lang)
    if data:
        return data, "wiktionary"

    if use_tts:
        data = fetch_gtts_audio(word, lang)
        if data:
            return data, "tts"

    return None, "none"
