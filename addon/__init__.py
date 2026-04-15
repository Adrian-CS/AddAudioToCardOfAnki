from aqt import mw, gui_hooks
from aqt.qt import QAction


def _open_dialog():
    from .dialog import AddAudioDialog
    dlg = AddAudioDialog(mw)
    dlg.exec()


def _add_menu():
    action = QAction("Añadir Audio a Tarjetas...", mw)
    action.triggered.connect(_open_dialog)
    mw.form.menuTools.addAction(action)


gui_hooks.main_window_did_init.append(_add_menu)
