from __future__ import annotations

"""
Internationalization support.

Detects Anki's current UI language and returns the matching string.
Supported: English (default), Spanish (es), Japanese (ja).
"""

_T: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------- Menu
    "menu_item": {
        "en": "Add Audio to Cards...",
        "es": "Añadir Audio a Tarjetas...",
        "ja": "カードに音声を追加...",
    },
    # -------------------------------------------------------------- Dialog
    "window_title": {
        "en": "Add Audio to Cards",
        "es": "Añadir Audio a Tarjetas",
        "ja": "カードに音声を追加",
    },
    "label_deck": {
        "en": "Deck:",
        "es": "Mazo:",
        "ja": "デッキ:",
    },
    "label_word_field": {
        "en": "Word field:",
        "es": "Campo con la palabra:",
        "ja": "単語フィールド:",
    },
    "label_audio_field_1": {
        "en": "Audio field (1):",
        "es": "Campo de audio (1):",
        "ja": "音声フィールド (1):",
    },
    "label_audio_field_2": {
        "en": "Audio field (2):",
        "es": "Campo de audio (2):",
        "ja": "音声フィールド (2):",
    },
    "label_language": {
        "en": "Language:",
        "es": "Idioma:",
        "ja": "言語:",
    },
    "check_overwrite": {
        "en": "Overwrite existing audio",
        "es": "Sobreescribir audio existente",
        "ja": "既存の音声を上書きする",
    },
    "check_tts": {
        "en": "Use TTS as fallback if no native audio found",
        "es": "Usar TTS si no hay audio nativo",
        "ja": "ネイティブ音声がない場合はTTSを使用する",
    },
    "btn_add": {
        "en": "Add Audio",
        "es": "Añadir Audio",
        "ja": "音声を追加",
    },
    "btn_close": {
        "en": "Close",
        "es": "Cerrar",
        "ja": "閉じる",
    },
    "option_none": {
        "en": "— none —",
        "es": "— ninguno —",
        "ja": "— なし —",
    },
    # ------------------------------------------------------------ Messages
    "err_select_fields": {
        "en": "Please select a deck and fields.",
        "es": "Por favor selecciona mazo y campos.",
        "ja": "デッキとフィールドを選択してください。",
    },
    "err_empty_deck": {
        "en": "The deck is empty.",
        "es": "El mazo está vacío.",
        "ja": "デッキが空です。",
    },
    "err_no_cards": {
        "en": "No cards found with that field.",
        "es": "No se encontraron tarjetas con ese campo.",
        "ja": "そのフィールドを持つカードが見つかりません。",
    },
    "status_downloading": {
        "en": "Downloading audio...",
        "es": "Descargando audio...",
        "ja": "音声をダウンロード中...",
    },
    # ------------------------------------------------------ Results dialog
    "result_header": {
        "en": "Done — {total} cards processed\n",
        "es": "Completado — {total} tarjetas procesadas\n",
        "ja": "完了 — {total}枚のカードを処理しました\n",
    },
    "result_wiktionary": {
        "en": "  Native audio (Wiktionary): {n}",
        "es": "  Audio nativo (Wiktionary): {n}",
        "ja": "  ネイティブ音声 (Wiktionary): {n}",
    },
    "result_tts": {
        "en": "  Google TTS (synthetic):    {n}",
        "es": "  Google TTS (sintético):    {n}",
        "ja": "  Google TTS (合成音声):        {n}",
    },
    "result_skipped": {
        "en": "  Skipped (already have audio): {n}",
        "es": "  Saltadas (ya tienen audio):   {n}",
        "ja": "  スキップ (音声あり):             {n}",
    },
    "result_not_found": {
        "en": "  No audio found:               {n}",
        "es": "  Sin audio encontrado:         {n}",
        "ja": "  音声なし:                       {n}",
    },
}


def _detect_lang() -> str:
    try:
        import anki.lang
        code = (anki.lang.current_lang or "")[:2].lower()
        if code in _T["menu_item"]:
            return code
    except Exception:
        pass
    return "en"


# Cached after first call — language doesn't change during a session.
_lang: str = ""


def tr(key: str, **kwargs: object) -> str:
    """Return the translated string for *key* in Anki's current UI language."""
    global _lang
    if not _lang:
        _lang = _detect_lang()
    text = _T.get(key, {}).get(_lang) or _T.get(key, {}).get("en", key)
    return text.format(**kwargs) if kwargs else text
