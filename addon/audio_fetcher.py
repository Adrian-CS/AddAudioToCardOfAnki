from __future__ import annotations

"""
Audio fetching logic.

Priority:
  1. English Wiktionary — native human recordings for Spanish (.ogg/.wav)
     Better coverage than Spanish Wiktionary (~100% vs ~57% for common words).
     Filters for files tagged as Spanish: LL-Q1321 (spa)-*, Es-*, es-*.
  2. Google Translate TTS — synthetic fallback (optional, user-controlled).

Uses only stdlib (urllib) so it works in any Anki Python environment.

Word extraction:
  Fields often contain phrases or mixed-language entries like:
    "floor piso planta", "already/ya", "cuál?", "de la mañana"
  _candidate_words() splits these into individual candidates and tries
  each one until Wiktionary returns a Spanish audio file.
"""

import json
import os
import re
import ssl
import tempfile
import time
import threading
import urllib.parse
import urllib.request

_LOG = os.path.join(tempfile.gettempdir(), "anki_add_audio.log")


def _log(msg: str) -> None:
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"
GTTS_URL = "https://translate.google.com/translate_tts"
REQUEST_TIMEOUT = 10
HEADERS = {"User-Agent": "AnkiAddOn-AddAudioToCards/1.0"}

_SSL_CTX = ssl.create_default_context()

# Rate limiter: max 4 requests/sec to stay well within Wiktionary's limits.
_rate_lock = threading.Lock()
_last_request_time = 0.0
_MIN_INTERVAL = 0.25  # seconds between requests

# Short function words that are unlikely to have useful Spanish pronunciation
# audio entries on Wiktionary, or would give a wrong match for a phrase.
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
        "already/ya"         → ["already"]          (ya filtered: stop word)
        "de la mañana"       → ["mañana"]           (de, la filtered: stop words)
        "adelante,aquí tiene"→ ["adelante", "aquí", "tiene"]
        "hablar"             → ["hablar"]
    """
    # Remove punctuation that doesn't belong in a word lookup
    cleaned = re.sub(r"[?!.;:~()\[\]_]", " ", raw).strip()

    # Split on slashes, commas, and whitespace
    parts = re.split(r"[/,\s]+", cleaned)

    candidates = []
    for p in parts:
        p = p.strip()
        if (
            p
            and len(p) >= 2
            and p.lower() not in _STOP_WORDS
            and not p.isdigit()
            and not re.fullmatch(r"[^\w\u00C0-\u024F]+", p)  # skip pure punctuation
        ):
            candidates.append(p)

    # Deduplicate preserving order
    seen: set[str] = set()
    result = []
    for c in candidates:
        if c.lower() not in seen:
            seen.add(c.lower())
            result.append(c)
    return result


def _http_get(url: str, params: dict | None = None, download: bool = False) -> bytes:
    global _last_request_time
    if params:
        url = url + "?" + urllib.parse.urlencode(params)

    # Rate limiting: enforce minimum interval between requests
    with _rate_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.monotonic()

    timeout = 20 if download else REQUEST_TIMEOUT
    req = urllib.request.Request(url, headers=HEADERS)

    # Retry once on failure (handles transient network errors)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                return resp.read()
        except Exception:
            if attempt == 0:
                time.sleep(1)
            else:
                raise


def _http_get_json(url: str, params: dict | None = None) -> dict:
    return json.loads(_http_get(url, params))


def _is_spanish_audio(title: str) -> bool:
    """Return True if a Wiktionary file title looks like a Spanish pronunciation."""
    name = re.sub(r"^(file|archivo):\s*", "", title, flags=re.IGNORECASE).lower()
    return (
        "q1321" in name        # LL-Q1321 (spa)-Speaker-word.* — community recordings
        or "(spa)" in name     # explicit Spanish language tag
        or name.startswith("es-")  # Es-word.ogg / Es-am-lat-word.ogg / es-word.ogg
    )


def _find_wiktionary_audio_url(word: str) -> str | None:
    """Return the CDN URL of a native Spanish pronunciation file for word, or None."""
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
        and _is_spanish_audio(img["title"])
    ]

    if not audio_titles:
        _log(f"[NO-AUDIO] {word!r} — images: {[i['title'] for i in images]}")
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
                _log(f"[OK] {word!r} → {url}")
                return url

    _log(f"[NO-URL] {word!r} — imageinfo returned no url")
    return None


def fetch_wiktionary_audio(word: str) -> bytes | None:
    """
    Download native Spanish audio from Wiktionary, or None if not found.

    Tries each candidate word extracted from the field value in order,
    returning the first audio found.
    """
    for candidate in _candidate_words(word):
        url = _find_wiktionary_audio_url(candidate)
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
    Fetch audio for a word.

    Args:
        word:    The word/phrase from the Anki field.
        lang:    BCP-47 language code (used for TTS fallback).
        use_tts: If True and no native audio is found, fall back to Google TTS.

    Returns:
        (audio_bytes, source) where source is 'wiktionary', 'tts', or 'none'.
    """
    data = fetch_wiktionary_audio(word)
    if data:
        return data, "wiktionary"

    if use_tts:
        data = fetch_gtts_audio(word, lang)
        if data:
            return data, "tts"

    return None, "none"
