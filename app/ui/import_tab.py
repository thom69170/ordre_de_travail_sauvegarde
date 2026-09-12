"""Onglet 'Importer' : ajout d'une photo/PDF d'ordre de travail, avec OCR assisté."""
from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from app import config, db, ocr_engine, storage
from app.extraction import extract_from_pages as run_extraction
from app.models import SUMMARY_FIELDS, WorkOrder
from app.ui.common import (
    ACCENT,
    BG,
    CARD_BG,
    TEXT_MUTED,
    WARN_BG,
    WARN_FG,
    LabeledEntry,
    ScrollableFrame,
    format_decimal,
    parse_decimal,
)

FILE_TYPES = [
    ("Photos et PDF", "*.pdf *.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp"),
    ("Tous les fichiers", "*.*"),
]


def _parse_user_date(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("date vide")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    for fmt_sep in ("/", "-", "."):
        parts = text.split(fmt_sep)
        if len(parts) == 3:
            try:
                d, m, y = (int(p) for p in parts)
                if y < 100:
                    y += 2000
                return date(y, m, d).isoformat()
            except ValueError:
                continue
    raise ValueError(f"Date non reconnue : {text!r}")


class ImportTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.current_path: Path | None = None
        self.current_pages: list[Image.Image] | None = None
        self.editing_id: int | None = None
        self._thumbnail_imgtk = None
        self.summary_entries: dict[str, LabeledEntry] = {}

        self._build_ui()
        self._maybe_show_ocr_banner()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        self.choose_btn = ttk.Button(top, text="Choisir une photo ou un PDF...", command=self.choose_file)
        self.choose_btn.pack(side="left")

        self.file_label = ttk.Label(top, text="Aucun fichier sélectionné", foreground=TEXT_MUTED)
        self.file_label.pack(side="left", padx=10)

        self.status_label = ttk.Label(top, text="", foreground=ACCENT)
        self.status_label.pack(side="right")

        self.banner_holder = ttk.Frame(self)
        self.banner_holder.pack(fill="x")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # Colonne gauche : aperçu image
        left = ttk.Frame(body, padding=12)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Aperçu (vérifie les valeurs par rapport à la photo)",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.thumb_label = tk.Label(left, bg=CARD_BG, relief="solid", borderwidth=1)
        self.thumb_label.pack(pady=6)
        self.open_file_btn = ttk.Button(left, text="Ouvrir le fichier original", command=self._open_source_file,
                                         state="disabled")
        self.open_file_btn.pack(anchor="w")

        # Colonne droite : formulaire scrollable
        right_container = ttk.Frame(body, padding=(0, 12, 12, 12))
        right_container.pack(side="left", fill="both", expand=True)
        scroll = ScrollableFrame(right_container)
        scroll.pack(fill="both", expand=True)
        form = scroll.inner

        header = ttk.LabelFrame(form, text="Ordre de travail", padding=10)
        header.pack(fill="x", padx=4, pady=6)

        self.date_entry = LabeledEntry(header, "Date (JJ/MM/AAAA)", width=14)
        self.date_entry.pack(side="left", padx=(0, 10))
        self.date_entry.set(date.today().strftime("%d/%m/%Y"))

        self.name_entry = LabeledEntry(header, "Nom du chauffeur", width=24)
        self.name_entry.pack(side="left", padx=(0, 10))

        self.matricule_entry = LabeledEntry(header, "Matricule", width=10)
        self.matricule_entry.pack(side="left")

        summary_frame = ttk.LabelFrame(form, text="Récapitulatif (centièmes d'heure)", padding=10)
        summary_frame.pack(fill="x", padx=4, pady=6)
        cols = 4
        for i, (field_name, label) in enumerate(SUMMARY_FIELDS):
            entry = LabeledEntry(summary_frame, label, width=8)
            entry.set_decimal(0.0)
            entry.grid(row=i // cols, column=i % cols, padx=6, pady=4, sticky="w")
            self.summary_entries[field_name] = entry

        trajets_frame = ttk.LabelFrame(form, text="Trajets / lignes détectés", padding=10)
        trajets_frame.pack(fill="x", padx=4, pady=6)
        self.trajets_count_label = ttk.Label(trajets_frame, text="0 trajet", foreground=TEXT_MUTED)
        self.trajets_count_label.pack(anchor="w")
        listbox_row = ttk.Frame(trajets_frame)
        listbox_row.pack(fill="x", side="top")
        self.trajet_listbox = tk.Listbox(listbox_row, height=8, selectmode="extended")
        self.trajet_listbox.pack(side="left", fill="both", expand=True)
        trajet_scroll = ttk.Scrollbar(listbox_row, orient="vertical", command=self.trajet_listbox.yview)
        trajet_scroll.pack(side="left", fill="y")
        self.trajet_listbox.config(yscrollcommand=trajet_scroll.set)
        add_row = ttk.Frame(trajets_frame)
        add_row.pack(fill="x", pady=(6, 0))
        self.new_trajet_var = tk.StringVar()
        ttk.Entry(add_row, textvariable=self.new_trajet_var).pack(side="left", fill="x", expand=True)
        ttk.Button(add_row, text="Ajouter", command=self._add_trajet).pack(side="left", padx=4)
        ttk.Button(add_row, text="Supprimer la sélection", command=self._remove_selected_trajets).pack(side="left")

        self.warnings_holder = ttk.Frame(form)
        self.warnings_holder.pack(fill="x", padx=4)

        notes_frame = ttk.LabelFrame(form, text="Notes (facultatif)", padding=10)
        notes_frame.pack(fill="x", padx=4, pady=6)
        self.notes_text = tk.Text(notes_frame, height=3)
        self.notes_text.pack(fill="x")

        bottom = ttk.Frame(self, padding=12)
        bottom.pack(fill="x")
        self.save_btn = ttk.Button(bottom, text="Enregistrer", command=self.save)
        self.save_btn.pack(side="right")
        ttk.Button(bottom, text="Réinitialiser le formulaire", command=self.reset_form).pack(side="right", padx=8)

    def _maybe_show_ocr_banner(self):
        for child in self.banner_holder.winfo_children():
            child.destroy()

        has_gemini = bool(config.get_gemini_api_key())
        has_tesseract = ocr_engine.is_available()

        if not has_tesseract and not has_gemini:
            bar = tk.Frame(self.banner_holder, bg=WARN_BG, padx=10, pady=8)
            bar.pack(fill="x")
            tk.Label(
                bar,
                text="Moteur OCR (Tesseract) introuvable : la lecture automatique est désactivée, "
                     "tu peux quand même saisir les données à la main ci-dessous.",
                bg=WARN_BG, fg=WARN_FG, anchor="w", justify="left", wraplength=700,
            ).pack(side="left", fill="x", expand=True)
            ttk.Button(bar, text="Installer Tesseract OCR", command=self._install_tesseract).pack(side="right")
            return

        if not has_gemini:
            bar = tk.Frame(self.banner_holder, bg=WARN_BG, padx=10, pady=8)
            bar.pack(fill="x")
            tk.Label(
                bar,
                text="La lecture automatique utilise l'OCR local (Tesseract) : rapide et gratuit, "
                     "mais souvent imprécis — attends-toi à devoir corriger plusieurs champs à la "
                     "main. Une clé API Gemini (gratuite) rend la lecture bien plus fiable.",
                bg=WARN_BG, fg=WARN_FG, anchor="w", justify="left", wraplength=700,
            ).pack(side="left", fill="x", expand=True)
            ttk.Button(
                bar, text="Configurer Gemini (onglet Paramètres)",
                command=lambda: self.app.select_tab("settings"),
            ).pack(side="right")

    def _install_tesseract(self):
        if not messagebox.askyesno(
            "Installer Tesseract OCR",
            "Ceci va lancer l'installation de Tesseract OCR (logiciel libre) via winget.\n"
            "Une fenêtre d'installation peut s'ouvrir. Continuer ?",
        ):
            return
        try:
            subprocess.Popen(
                ["winget", "install", "--id", "UB-Mannheim.TesseractOCR", "-e",
                 "--accept-package-agreements", "--accept-source-agreements"]
            )
            messagebox.showinfo(
                "Installation lancée",
                "Installation en cours. Une fois terminée, redémarre l'application pour activer l'OCR.",
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Échec", f"Impossible de lancer l'installation automatique : {exc}\n"
                                           "Tu peux installer Tesseract OCR manuellement depuis :\n"
                                           "https://github.com/UB-Mannheim/tesseract/wiki")

    # ------------------------------------------------------------- actions

    def choose_file(self):
        path_str = filedialog.askopenfilename(title="Choisir un ordre de travail", filetypes=FILE_TYPES)
        if not path_str:
            return
        self.reset_form(keep_file_dialog_open=True)
        path = Path(path_str)
        self.current_path = path
        self.file_label.config(text=path.name)
        self.status_label.config(text="Analyse en cours...")
        self.choose_btn.config(state="disabled")
        self.update_idletasks()
        threading.Thread(target=self._process_file, args=(path,), daemon=True).start()

    def _process_file(self, path: Path):
        try:
            pages = ocr_engine.load_pages(path)
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._on_process_error(exc))
            return

        extraction = None
        if ocr_engine.is_available() or config.get_gemini_api_key():
            try:
                extraction = run_extraction(pages)
            except Exception:  # noqa: BLE001
                extraction = None

        self.after(0, lambda: self._apply_extraction(pages, extraction))

    def _on_process_error(self, exc: Exception):
        self.choose_btn.config(state="normal")
        self.status_label.config(text="")
        messagebox.showerror("Erreur", f"Impossible de lire ce fichier :\n{exc}")

    def _apply_extraction(self, pages: list[Image.Image], extraction):
        self.choose_btn.config(state="normal")
        self.status_label.config(text="")
        self.current_pages = pages
        self._show_thumbnail(pages[0])
        self.open_file_btn.config(state="normal")

        for child in self.warnings_holder.winfo_children():
            child.destroy()

        if extraction is None:
            return

        if extraction.date:
            try:
                self.date_entry.set(date.fromisoformat(extraction.date).strftime("%d/%m/%Y"))
            except ValueError:
                pass
        if extraction.driver_name:
            self.name_entry.set(extraction.driver_name)
        if extraction.matricule:
            self.matricule_entry.set(extraction.matricule)

        for field_name, value in extraction.summary.items():
            if field_name in self.summary_entries:
                self.summary_entries[field_name].set_decimal(value)

        self.trajet_listbox.delete(0, "end")
        for label in extraction.trajets:
            self.trajet_listbox.insert("end", label)
        self._update_trajets_count()

        if extraction.warnings:
            from app.ui.common import show_warnings
            frame = show_warnings(self.warnings_holder, extraction.warnings)
            if frame:
                frame.pack(fill="x", pady=6)

    def _show_thumbnail(self, image: Image.Image):
        max_w = 360
        ratio = max_w / image.width
        thumb = image.resize((max_w, int(image.height * ratio)), Image.LANCZOS)
        self._thumbnail_imgtk = ImageTk.PhotoImage(thumb)
        self.thumb_label.config(image=self._thumbnail_imgtk)

    def _open_source_file(self):
        if self.current_path and self.current_path.exists():
            self._open_with_default_app(self.current_path)
        elif self.editing_id is not None:
            wo = db.get_work_order(self.editing_id)
            if wo and wo.source_filename:
                self._open_with_default_app(storage.resolve_source_path(wo.source_filename))

    @staticmethod
    def _open_with_default_app(path: Path):
        try:
            if sys.platform == "win32":
                import os
                os.startfile(str(path))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier :\n{exc}")

    def _add_trajet(self):
        label = self.new_trajet_var.get().strip()
        if label:
            self.trajet_listbox.insert("end", label)
            self.new_trajet_var.set("")
            self._update_trajets_count()

    def _remove_selected_trajets(self):
        for idx in reversed(self.trajet_listbox.curselection()):
            self.trajet_listbox.delete(idx)
        self._update_trajets_count()

    def _update_trajets_count(self):
        count = self.trajet_listbox.size()
        self.trajets_count_label.config(text=f"{count} trajet{'s' if count != 1 else ''}")

    def load_for_edit(self, work_order: WorkOrder):
        self.reset_form()
        self.editing_id = work_order.id
        self.current_path = None
        self.file_label.config(text=f"(fichier existant : {work_order.source_filename or 'aucun'})")

        self.date_entry.set(date.fromisoformat(work_order.date).strftime("%d/%m/%Y"))
        self.name_entry.set(work_order.driver_name)
        self.matricule_entry.set(work_order.matricule)
        for field_name, _label in SUMMARY_FIELDS:
            self.summary_entries[field_name].set_decimal(getattr(work_order, field_name))
        self.trajet_listbox.delete(0, "end")
        for label in work_order.trajets:
            self.trajet_listbox.insert("end", label)
        self._update_trajets_count()
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", work_order.notes)

        if work_order.source_filename:
            source_path = storage.resolve_source_path(work_order.source_filename)
            if source_path.exists():
                try:
                    pages = ocr_engine.load_pages(source_path)
                    self.current_pages = pages
                    self._show_thumbnail(pages[0])
                    self.open_file_btn.config(state="normal")
                except Exception:  # noqa: BLE001
                    pass

        self.save_btn.config(text="Mettre à jour")

    def reset_form(self, keep_file_dialog_open: bool = False):
        self.editing_id = None
        self.current_path = None
        self.current_pages = None
        self._thumbnail_imgtk = None
        self.thumb_label.config(image="")
        self.open_file_btn.config(state="disabled")
        if not keep_file_dialog_open:
            self.file_label.config(text="Aucun fichier sélectionné")
        self.date_entry.set(date.today().strftime("%d/%m/%Y"))
        self.name_entry.set("")
        self.matricule_entry.set("")
        for entry in self.summary_entries.values():
            entry.set_decimal(0.0)
        self.trajet_listbox.delete(0, "end")
        self._update_trajets_count()
        self.notes_text.delete("1.0", "end")
        for child in self.warnings_holder.winfo_children():
            child.destroy()
        self.save_btn.config(text="Enregistrer")
        self._maybe_show_ocr_banner()

    def save(self):
        try:
            date_iso = _parse_user_date(self.date_entry.get())
        except ValueError as exc:
            messagebox.showerror("Date invalide", str(exc))
            return

        target_id = self.editing_id
        if target_id is None:
            existing = db.get_work_order_by_date(date_iso)
            if existing is not None:
                if not messagebox.askyesno(
                    "Ordre de travail existant",
                    f"Un ordre de travail existe déjà pour le {date_iso}. Le remplacer ?",
                ):
                    return
                target_id = existing.id

        wo = WorkOrder(
            id=target_id,
            date=date_iso,
            driver_name=self.name_entry.get().strip(),
            matricule=self.matricule_entry.get().strip(),
            notes=self.notes_text.get("1.0", "end").strip(),
            trajets=list(self.trajet_listbox.get(0, "end")),
        )
        for field_name, _label in SUMMARY_FIELDS:
            setattr(wo, field_name, self.summary_entries[field_name].get_decimal())

        if self.current_path is not None:
            stored_name, stored_type = storage.store_source_file(self.current_path, date_iso)
            wo.source_filename = stored_name
            wo.source_type = stored_type
        elif target_id is not None:
            previous = db.get_work_order(target_id)
            if previous:
                wo.source_filename = previous.source_filename
                wo.source_type = previous.source_type

        if target_id is None:
            db.insert_work_order(wo)
        else:
            db.update_work_order(wo)

        messagebox.showinfo("Enregistré", f"Ordre de travail du {date_iso} enregistré.")
        self.reset_form()
        self.app.refresh_other_tabs("import")
