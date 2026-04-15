"""
Audio fetching logic.

Priority:
  1. Spanish Wiktionary — native human recordings (.ogg/.wav)
  2. Google Translate TTS fallback — synthetic but decent quality

Both are free and require no API key.
"""

import re
import requests

WIKTIONARY_API = "https://es.wiktionary.org/w/api.php"
GTTS_URL = "https://translate.google.com/translate_tts"
REQUEST_TIMEOUT = 10


def _find_wiktionary_audio_url(word: str) -> str | None:
    """Return the direct download URL of a pronunciation file from Spanish Wiktionary, or None."""
    try:
        # Step 1: get all files linked on the word's page
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

    # Keep only audio files (Wiktionary uses .ogg and .wav for pronunciations)
    audio_titles = [
        img["title"] for img in images
        if re.search(r"\.(ogg|wav|flac)$", img["title"], re.IGNORECASE)
    ]

    if not audio_titles:
        return None

    try:
        # Step 2: resolve to a direct CDN URL
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
    """Download native audio bytes from Spanish Wiktionary, or None if not found."""
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
    """Download TTS audio bytes from Google Translate (unofficial endpoint), or None."""
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


def get_audio(word: str, lang: str = "es") -> tuple[bytes | None, str]:
    """
    Fetch audio for a word, trying Wiktionary first then Google TTS.

    Returns:
        (audio_bytes, source) where source is 'wiktionary', 'tts', or 'none'.
    """
    data = fetch_wiktionary_audio(word)
    if data:
        return data, "wiktionary"

    data = fetch_gtts_audio(word, lang)
    if data:
        return data, "tts"

    return None, "none"
