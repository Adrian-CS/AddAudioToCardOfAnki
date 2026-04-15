from __future__ import annotations

"""
Audio fetching logic.

Priority:
  1. English Wiktionary — native human recordings for Spanish (.ogg/.wav)
     Better coverage than Spanish Wiktionary (~100% vs ~57% for common words).
     Filters for files tagged as Spanish: LL-Q1321 (spa)-*, Es-*, es-*.
  2. Google Translate TTS — synthetic fallback (optional, user-controlled).

No API key required.
"""

import re
import requests

WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"
GTTS_URL = "https://translate.google.com/translate_tts"
REQUEST_TIMEOUT = 10


def _is_spanish_audio(title: str) -> bool:
    """Return True if a Wiktionary file title looks like a Spanish pronunciation."""
    # Strip namespace prefix: "File:" or "Archivo:"
    name = re.sub(r"^(file|archivo):\s*", "", title, flags=re.IGNORECASE).lower()
    return (
        "q1321" in name       # LL-Q1321 (spa)-Speaker-word.* — community recordings
        or "(spa)" in name    # explicit Spanish language tag
        or name.startswith("es-")  # Es-word.ogg / Es-am-lat-word.ogg / es-word.ogg
    )


def _find_wiktionary_audio_url(word: str) -> str | None:
    """Return the CDN URL of a native Spanish pronunciation file, or None."""
    try:
        resp = requests.get(WIKTIONARY_API, params={
            "action": "query",
            "titles": word,
            "prop": "images",
            "imlimit": "50",
            "format": "json",
        }, timeout=REQUEST_TIMEOUT)
        data = resp.json()
    except Exception:
        return None

    pages = data.get("query", {}).get("pages", {})
    images = []
    for page in pages.values():
        images.extend(page.get("images", []))

    # Keep only Spanish audio files
    audio_titles = [
        img["title"] for img in images
        if re.search(r"\.(ogg|wav|flac)$", img["title"], re.IGNORECASE)
        and _is_spanish_audio(img["title"])
    ]

    if not audio_titles:
        return None

    try:
        resp2 = requests.get(WIKTIONARY_API, params={
            "action": "query",
            "titles": audio_titles[0],
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
        }, timeout=REQUEST_TIMEOUT)
        data2 = resp2.json()
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
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception:
        pass
    return None


def fetch_gtts_audio(word: str, lang: str = "es") -> bytes | None:
    """Download TTS audio from Google Translate (unofficial endpoint), or None."""
    try:
        resp = requests.get(
            GTTS_URL,
            params={"ie": "UTF-8", "q": word, "tl": lang, "client": "tw-ob"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception:
        pass
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
