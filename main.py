"""Point d'entrée de l'application Ordres de travail.

Lancé via pythonw.exe (sans console) par Ordres de travail.bat : toute erreur doit donc être signalée par
une fenêtre de dialogue plutôt qu'un message dans un terminal que personne ne verrait.
"""
from __future__ import annotations

import sys


def _fatal_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Erreur au démarrage", message)
        root.destroy()
    except Exception:  # noqa: BLE001
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "Erreur au démarrage", 0x10)
        except Exception:  # noqa: BLE001
            pass


try:
    import traceback
    import tkinter as tk
    from tkinter import messagebox, ttk

    from app import db, ocr_engine
    from app.paths import icon_path
    from app.ui.main_window import APP_TITLE, MainWindow
except Exception as exc:  # noqa: BLE001
    _fatal_error(
        f"Impossible de démarrer l'application :\n{exc}\n\n"
        "Essaie de relancer Ordres de travail.bat. Si le problème persiste, consulte le README du projet."
    )
    sys.exit(1)


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

    window = MainWindow(root)
    _check_for_update_in_background(root, window)
    root.mainloop()
    return 0


def _check_for_update_in_background(root: tk.Tk, window: MainWindow) -> None:
    import threading

    def worker():
        try:
            from app import updater

            remote_version = updater.check_for_update()
        except Exception:  # noqa: BLE001
            remote_version = None
        if remote_version:
            root.after(0, lambda: window.settings_tab.set_update_available(remote_version))

    threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        _fatal_error(f"Erreur inattendue au démarrage :\n{exc}")
        sys.exit(1)
