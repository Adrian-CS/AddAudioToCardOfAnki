from __future__ import annotations

"""
Audio fetching logic.

Priority:
  1. English Wiktionary — native human recordings for Spanish (.ogg/.wav)
     Better coverage than Spanish Wiktionary (~100% vs ~57% for common words).
     Filters for files tagged as Spanish: LL-Q1321 (spa)-*, Es-*, es-*.
  2. Google Translate TTS — synthetic fallback (optional, user-controlled).

Uses only stdlib (urllib) so it works in any Anki Python environment.
"""

import json
import re
import ssl
import urllib.parse
import urllib.request

WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"
GTTS_URL = "https://translate.google.com/translate_tts"
REQUEST_TIMEOUT = 10
HEADERS = {"User-Agent": "AnkiAddOn-AddAudioToCards/1.0"}

# Use default SSL context (system certs). Works in Anki's bundled Python.
_SSL_CTX = ssl.create_default_context()


def _http_get(url: str, params: dict | None = None) -> bytes:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=_SSL_CTX) as resp:
        return resp.read()


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
    """Return the CDN URL of a native Spanish pronunciation file, or None."""
    try:
        data = _http_get_json(WIKTIONARY_API, {
            "action": "query",
            "titles": word,
            "prop": "images",
            "imlimit": "50",
            "format": "json",
        })
    except Exception:
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
        return None

    try:
        data2 = _http_get_json(WIKTIONARY_API, {
            "action": "query",
            "titles": audio_titles[0],
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
        })
    except Exception:
        return None

    for page in data2.get("query", {}).get("pages", {}).values():
        for info in page.get("imageinfo", []):
            url = info.get("url")
            if url:
                return url

    return None


def fetch_wiktionary_audio(word: str) -> bytes | None:
    """Download native Spanish audio from Wiktionary, or None if not found."""
    url = _find_wiktionary_audio_url(word)
    if not url:
        return None
    try:
        return _http_get(url)
    except Exception:
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
        word:    The word to look up.
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
