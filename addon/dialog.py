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

from .audio_fetcher import get_audio


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _safe_filename(word: str, lang: str, ext: str) -> str:
    name = f"audio_{lang}_{word}.{ext}"
    return re.sub(r"[^\w\-.]", "_", name)


class AddAudioDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Añadir Audio a Tarjetas")
        self.setMinimumWidth(420)
        self._build_ui()
        self._populate_decks()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.deck_combo = QComboBox()
        form.addRow("Mazo:", self.deck_combo)

        self.word_field_combo = QComboBox()
        form.addRow("Campo con la palabra:", self.word_field_combo)

        self.audio_field_combo = QComboBox()
        form.addRow("Campo de audio:", self.audio_field_combo)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["es", "en", "fr", "de", "it", "pt"])
        form.addRow("Idioma:", self.lang_combo)

        self.overwrite_check = QCheckBox("Sobreescribir audio existente")
        form.addRow("", self.overwrite_check)

        layout.addLayout(form)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Añadir Audio")
        self.start_btn.clicked.connect(self._start)
        self.close_btn = QPushButton("Cerrar")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

        self.deck_combo.currentIndexChanged.connect(self._populate_fields)

    # ----------------------------------------------------------- Population

    def _populate_decks(self):
        self.deck_combo.clear()
        for deck in sorted(mw.col.decks.all(), key=lambda d: d["name"]):
            self.deck_combo.addItem(deck["name"], deck["id"])
        self._populate_fields()

    def _populate_fields(self):
        self.word_field_combo.clear()
        self.audio_field_combo.clear()

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
        lang = self.lang_combo.currentText()
        overwrite = self.overwrite_check.isChecked()

        if not all([deck_name, word_field, audio_field]):
            showInfo("Por favor selecciona mazo y campos.")
            return

        # --- Pre-fetch note data on main thread (DB access must be here) ---
        note_ids = mw.col.find_notes(f'deck:"{deck_name}"')
        if not note_ids:
            showInfo("El mazo está vacío.")
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
            showInfo("No se encontraron tarjetas con ese campo.")
            return

        self.start_btn.setEnabled(False)
        self.progress_bar.setMaximum(len(note_data))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Descargando audio...")

        stats = {"wiktionary": 0, "tts": 0, "skipped": 0, "error": 0}
        # (note_id, sound_tag) pairs to apply on main thread
        updates: list[tuple[int, str]] = []

        def process():
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

                audio_bytes, source = get_audio(word, lang)

                if audio_bytes:
                    ext = "ogg" if source == "wiktionary" else "mp3"
                    filename = _safe_filename(word, lang, ext)
                    with open(os.path.join(media_dir, filename), "wb") as f:
                        f.write(audio_bytes)
                    updates.append((nid, f"[sound:{filename}]"))
                    stats[source] += 1
                else:
                    stats["error"] += 1

                mw.taskman.run_on_main(
                    lambda v=i + 1: self.progress_bar.setValue(v)
                )

            mw.taskman.run_on_main(
                lambda: self._apply_updates(updates, audio_field, stats, len(note_data))
            )

        mw.taskman.run_in_background(process)

    def _apply_updates(
        self,
        updates: list[tuple[int, str]],
        audio_field: str,
        stats: dict,
        total: int,
    ):
        """Apply note updates on the main thread (DB writes must happen here)."""
        for nid, sound_tag in updates:
            try:
                note = mw.col.get_note(nid)
                if audio_field in note.keys():
                    note[audio_field] = sound_tag
                    mw.col.update_note(note)
            except Exception:
                stats["error"] += 1

        mw.col.save()
        self.start_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("")

        showInfo(
            f"Completado — {total} tarjetas procesadas\n\n"
            f"  Wiktionary (audio nativo): {stats['wiktionary']}\n"
            f"  Google TTS (sintético):    {stats['tts']}\n"
            f"  Saltadas (ya tienen audio): {stats['skipped']}\n"
            f"  Sin audio encontrado:       {stats['error']}"
        )
