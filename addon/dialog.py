from __future__ import annotations

"""
Main UI dialog for the add-on.

Flow:
  1. User picks deck, word field, audio field, language.
  2. On click: pre-fetch all note words on main thread.
  3. Background thread: download audio + write to media folder.
  4. Main thread: update notes in the collection.
"""

import os
import re

from aqt import mw
from aqt.qt import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QVBoxLayout,
)
from aqt.utils import showInfo

from .audio_fetcher import (
    get_audio, fetch_gtts_audio, LANGUAGES, LANG_COVERAGE,
    is_cdn_blocked, reset_cdn_blocked, _LOG,
)
from .i18n import tr


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _safe_filename(word: str, lang: str, ext: str) -> str:
    name = f"audio_{lang}_{word}.{ext}"
    return re.sub(r"[^\w\-.]", "_", name)


class AddAudioDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle(tr("window_title"))
        self.setMinimumWidth(420)
        self._build_ui()
        self._populate_decks()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.deck_combo = QComboBox()
        form.addRow(tr("label_deck"), self.deck_combo)

        self.word_field_combo = QComboBox()
        form.addRow(tr("label_word_field"), self.word_field_combo)

        self.audio_field_combo = QComboBox()
        form.addRow(tr("label_audio_field_1"), self.audio_field_combo)

        self.audio_field2_combo = QComboBox()
        form.addRow(tr("label_audio_field_2"), self.audio_field2_combo)

        self.lang_combo = QComboBox()
        for code, (name, _, _) in sorted(LANGUAGES.items(), key=lambda x: x[1][0]):
            self.lang_combo.addItem(f"{name} — {code}", code)
        # Default to Spanish
        idx = self.lang_combo.findData("es")
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        form.addRow(tr("label_language"), self.lang_combo)

        self.coverage_label = QLabel("")
        self.coverage_label.setWordWrap(True)
        self.coverage_label.setStyleSheet("color: #b35900; font-size: 11px;")
        form.addRow("", self.coverage_label)
        self.lang_combo.currentIndexChanged.connect(self._update_coverage_warning)

        self.overwrite_check = QCheckBox(tr("check_overwrite"))
        form.addRow("", self.overwrite_check)

        self.tts_check = QCheckBox(tr("check_tts"))
        form.addRow("", self.tts_check)

        layout.addLayout(form)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton(tr("btn_add"))
        self.start_btn.clicked.connect(self._start)
        self.close_btn = QPushButton(tr("btn_close"))
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

        self.deck_combo.currentIndexChanged.connect(self._populate_fields)
        self._update_coverage_warning()

    # --------------------------------------------------------- Coverage warn

    _COVERAGE_MESSAGES = {
        "low":     "⚠ Very limited native audio for this language. Enable TTS fallback for best results.",
        "limited": "⚠ Limited native audio for this language. TTS fallback recommended for uncommon words.",
    }

    def _update_coverage_warning(self):
        code = self.lang_combo.currentData() or ""
        tier = LANG_COVERAGE.get(code, "")
        msg = self._COVERAGE_MESSAGES.get(tier, "")
        self.coverage_label.setText(msg)
        self.coverage_label.setVisible(bool(msg))

    # ----------------------------------------------------------- Population

    def _populate_decks(self):
        self.deck_combo.clear()
        for deck in sorted(mw.col.decks.all(), key=lambda d: d["name"]):
            self.deck_combo.addItem(deck["name"], deck["id"])
        self._populate_fields()

    def _populate_fields(self):
        self.word_field_combo.clear()
        self.audio_field_combo.clear()
        self.audio_field2_combo.clear()
        self.audio_field2_combo.addItem(tr("option_none"))

        deck_name = self.deck_combo.currentText()
        if not deck_name:
            return

        note_ids = mw.col.find_notes(f'deck:"{deck_name}"')
        if not note_ids:
            return

        note = mw.col.get_note(note_ids[0])
        field_names = note.keys()

        for name in field_names:
            self.word_field_combo.addItem(name)
            self.audio_field_combo.addItem(name)
            self.audio_field2_combo.addItem(name)

        # Auto-select sensible defaults
        for i, name in enumerate(field_names):
            lower = name.lower()
            if any(k in lower for k in ("front", "word", "palabra", "term")):
                self.word_field_combo.setCurrentIndex(i)
            if any(k in lower for k in ("audio", "sound", "pronunciation", "back")):
                self.audio_field_combo.setCurrentIndex(i)

    # ----------------------------------------------------------- Processing

    def _start(self):
        deck_name = self.deck_combo.currentText()
        word_field = self.word_field_combo.currentText()
        audio_field = self.audio_field_combo.currentText()
        audio_field2_raw = self.audio_field2_combo.currentText()
        audio_field2 = None if audio_field2_raw == tr("option_none") else audio_field2_raw
        lang = self.lang_combo.currentData() or self.lang_combo.currentText()
        overwrite = self.overwrite_check.isChecked()
        use_tts = self.tts_check.isChecked()

        if not all([deck_name, word_field, audio_field]):
            showInfo(tr("err_select_fields"))
            return

        note_ids = mw.col.find_notes(f'deck:"{deck_name}"')
        if not note_ids:
            showInfo(tr("err_empty_deck"))
            return

        note_data = []  # (note_id, word, already_has_audio)
        for nid in note_ids:
            try:
                note = mw.col.get_note(nid)
                if word_field not in note.keys():
                    continue
                word = _strip_html(note[word_field])
                has_audio = "[sound:" in (note[audio_field] if audio_field in note.keys() else "")
                note_data.append((nid, word, has_audio))
            except Exception:
                continue

        if not note_data:
            showInfo(tr("err_no_cards"))
            return

        self.start_btn.setEnabled(False)
        self.progress_bar.setMaximum(len(note_data))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText(tr("status_downloading"))

        stats = {"wiktionary": 0, "tts": 0, "skipped": 0, "cached": 0, "error": 0}
        updates: list[tuple[int, str]] = []

        def process():
            reset_cdn_blocked()
            tts_fallback_active = False  # True once CDN is blocked and TTS takes over
            stopped_early = False

            media_dir = mw.col.media.dir()
            for i, (nid, word, has_audio) in enumerate(note_data):
                if not overwrite and has_audio:
                    stats["skipped"] += 1
                    mw.taskman.run_on_main(
                        lambda v=i + 1: self.progress_bar.setValue(v)
                    )
                    continue

                if not word:
                    stats["error"] += 1
                    mw.taskman.run_on_main(
                        lambda v=i + 1: self.progress_bar.setValue(v)
                    )
                    continue

                # Reuse a file already on disk from a previous run — avoids
                # re-downloading and burning CDN rate limits unnecessarily.
                cached_file = None
                if not overwrite:
                    for ext in ("ogg", "mp3"):
                        candidate = _safe_filename(word, lang, ext)
                        if os.path.exists(os.path.join(media_dir, candidate)):
                            cached_file = candidate
                            break

                if cached_file:
                    updates.append((nid, f"[sound:{cached_file}]"))
                    stats["cached"] += 1
                elif tts_fallback_active:
                    # CDN already known blocked — go straight to TTS.
                    audio_bytes = fetch_gtts_audio(word, lang)
                    if audio_bytes:
                        filename = _safe_filename(word, lang, "mp3")
                        with open(os.path.join(media_dir, filename), "wb") as f:
                            f.write(audio_bytes)
                        updates.append((nid, f"[sound:{filename}]"))
                        stats["tts"] += 1
                    else:
                        stats["error"] += 1
                else:
                    # Normal path: try Wiktionary only (no TTS yet).
                    audio_bytes, source = get_audio(word, lang, use_tts=False)

                    if audio_bytes:
                        ext = "ogg" if source == "wiktionary" else "mp3"
                        filename = _safe_filename(word, lang, ext)
                        with open(os.path.join(media_dir, filename), "wb") as f:
                            f.write(audio_bytes)
                        updates.append((nid, f"[sound:{filename}]"))
                        stats[source] += 1
                    elif is_cdn_blocked():
                        if use_tts:
                            # Switch to TTS for this card and all remaining ones.
                            tts_fallback_active = True
                            audio_bytes = fetch_gtts_audio(word, lang)
                            if audio_bytes:
                                filename = _safe_filename(word, lang, "mp3")
                                with open(os.path.join(media_dir, filename), "wb") as f:
                                    f.write(audio_bytes)
                                updates.append((nid, f"[sound:{filename}]"))
                                stats["tts"] += 1
                            else:
                                stats["error"] += 1
                        else:
                            # TTS disabled — stop here and save what we have.
                            stopped_early = True
                            stats["error"] += len(note_data) - i
                            mw.taskman.run_on_main(
                                lambda v=i: self.progress_bar.setValue(v)
                            )
                            break
                    else:
                        stats["error"] += 1

                mw.taskman.run_on_main(
                    lambda v=i + 1: self.progress_bar.setValue(v)
                )

            audio_fields = [f for f in [audio_field, audio_field2] if f]
            mw.taskman.run_on_main(
                lambda: self._apply_updates(
                    updates, audio_fields, stats, len(note_data),
                    stopped_early, tts_fallback_active,
                )
            )

        mw.taskman.run_in_background(process)

    def _apply_updates(
        self,
        updates: list[tuple[int, str]],
        audio_fields: list[str],
        stats: dict,
        total: int,
        stopped_early: bool = False,
        tts_fallback_active: bool = False,
    ):
        """Apply note updates on the main thread (DB writes must happen here)."""
        for nid, sound_tag in updates:
            try:
                note = mw.col.get_note(nid)
                changed = False
                for field in audio_fields:
                    if field in note.keys():
                        note[field] = sound_tag
                        changed = True
                if changed:
                    mw.col.update_note(note)
            except Exception:
                stats["error"] += 1

        mw.col.save()
        self.start_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("")

        done = stats["wiktionary"] + stats["tts"] + stats["cached"] + stats["skipped"]
        lines = [tr("result_header", total=total),
                 tr("result_wiktionary", n=stats["wiktionary"])]
        if stats["tts"]:
            lines.append(tr("result_tts", n=stats["tts"]))
        if stats["cached"]:
            lines.append(tr("result_cached", n=stats["cached"]))
        lines += [
            tr("result_skipped", n=stats["skipped"]),
            tr("result_not_found", n=stats["error"]),
        ]
        if tts_fallback_active:
            lines.append(tr("result_cdn_tts_switch"))
        if stopped_early:
            lines.append(tr("result_cdn_stopped"))
        if stats["error"] and not stopped_early:
            lines.append(f"\nDebug log: {_LOG}")
        showInfo("\n".join(lines))
