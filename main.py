"""Point d'entrée de l'application Ordres de travail."""
from __future__ import annotations

import sys
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

from app import db, ocr_engine
from app.paths import icon_path
from app.ui.main_window import APP_TITLE, MainWindow


def _install_error_dialog(root: tk.Tk) -> None:
    def report_callback_exception(exc, val, tb):
        traceback.print_exception(exc, val, tb)
        messagebox.showerror(
            "Erreur inattendue",
            f"Une erreur est survenue :\n{val}\n\n"
            "L'application peut continuer, mais pense à vérifier tes dernières actions.",
        )

    root.report_callback_exception = report_callback_exception


def main() -> int:
    db.init_db()
    ocr_engine.configure()

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("1200x800")
    root.minsize(980, 640)

    icon = icon_path()
    if icon is not None:
        try:
            root.iconbitmap(str(icon))
        except tk.TclError:
            pass

    _install_error_dialog(root)

    try:
        import sv_ttk

        sv_ttk.set_theme("light")
        if sys.platform == "win32":
            try:
                import pywinstyles

                pywinstyles.apply_style(root, "light")
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        try:
            ttk.Style().theme_use("vista" if sys.platform == "win32" else "clam")
        except tk.TclError:
            pass

    MainWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
