"""Surveillance périodique de la boîte mail dédiée (voir app/mail_import.py) : tant que l'app est
ouverte, relève les nouveaux messages toutes les N minutes et traite les photos reçues."""
from __future__ import annotations

import threading
from datetime import date, datetime

from app import mail_import
from app.mail_import import MailError

STARTUP_DELAY_MS = 4000


def _short_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m")
    except ValueError:
        return iso or "date inconnue"


class MailWatcher:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self._after_id = None
        self._busy = False
        self._last_error = ""

    # ------------------------------------------------------------------ planification

    def start(self) -> None:
        self.reconfigure(STARTUP_DELAY_MS)

    def reconfigure(self, first_delay_ms: int | None = None) -> None:
        """À appeler au démarrage et chaque fois que les réglages changent."""
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        settings = mail_import.get_settings()
        if settings["enabled"] and mail_import.is_configured(settings):
            delay = first_delay_ms if first_delay_ms is not None else mail_import.interval_seconds(settings) * 1000
            self._after_id = self.root.after(delay, self._tick)
        else:
            self.app.set_mail_status("")

    def _tick(self) -> None:
        self._after_id = None
        settings = mail_import.get_settings()
        if settings["enabled"] and mail_import.is_configured(settings):
            self.check_now()
            self._after_id = self.root.after(mail_import.interval_seconds(settings) * 1000, self._tick)

    def check_now(self, on_done=None) -> None:
        """Lance une relève maintenant (en arrière-plan). on_done(texte_resume, erreur) est appelé
        dans le fil d'affichage à la fin."""
        if self._busy:
            if on_done:
                on_done("", "Une relève est déjà en cours.")
            return
        settings = mail_import.get_settings()
        if not mail_import.is_configured(settings):
            if on_done:
                on_done("", "Réglages incomplets (adresse, mot de passe, serveur, expéditeur autorisé).")
            return
        self._busy = True
        threading.Thread(target=self._cycle, args=(settings, on_done), daemon=True).start()

    # ------------------------------------------------------------------ relève (fil d'arrière-plan)

    def _cycle(self, settings: dict, on_done) -> None:
        outcomes = []
        error = ""
        ignored = 0
        try:
            mail_import.cleanup_old_folders()
            mails = mail_import.pending_mails()
            try:
                report = mail_import.fetch_new_mails(settings)
                mails += report.mails
                ignored = report.ignored
            except MailError as exc:
                error = str(exc)
            for mail in mails:
                outcomes.append(self._process(mail))
        except Exception as exc:  # noqa: BLE001
            error = error or f"Erreur inattendue : {exc}"
        finally:
            self._busy = False
        self.root.after(0, lambda: self._deliver(outcomes, error, ignored, on_done))

    def _process(self, mail):
        outcome = mail_import.process_mail(mail)
        who = mail.sender or "expéditeur inconnu"
        if outcome.status == "error":
            mail.attempts += 1
            if mail.attempts < mail_import.MAX_PROCESS_ATTEMPTS:
                mail.save_manifest("pending")  # nouvel essai à la prochaine relève
                mail_import.log_event(
                    f"Lecture impossible pour le message de {who} ({outcome.reasons[0]}) : nouvel essai plus tard.",
                    "warn")
                return outcome
            outcome.status = "review"  # trop d'échecs : à l'utilisateur de voir la photo
            outcome.reasons = ["lecture automatique impossible : " + outcome.reasons[0]]
        if outcome.status == "saved":
            mail_import.discard(mail)
            mail_import.log_event(f"✓ OT du {_short_date(outcome.date)} enregistré automatiquement ({who}).")
        else:
            mail.save_manifest("queued")
            mail_import.log_event(
                f"À relire : OT reçu de {who} ({'; '.join(outcome.reasons)}).", "warn")
        return outcome

    # ------------------------------------------------------------------ résultat (fil d'affichage)

    def _deliver(self, outcomes, error: str, ignored: int, on_done) -> None:
        saved = [o for o in outcomes if o.status == "saved"]
        review = [o for o in outcomes if o.status == "review"]
        retry = [o for o in outcomes if o.status == "error"]
        for outcome in review:
            self.app.import_tab.receive_from_mail(outcome.mail.files, outcome.extraction)
        if saved:
            self.app.refresh_other_tabs("mail")  # historique, statistiques...

        parts = []
        if saved:
            parts.append(f"{len(saved)} OT enregistré{'s' if len(saved) > 1 else ''} "
                         f"({', '.join(_short_date(o.date) for o in saved)})")
        if review:
            parts.append(f"{len(review)} à relire dans l'onglet Importer")
        if retry:
            parts.append(f"{len(retry)} à réessayer")
        summary = " · ".join(parts)

        previous_error = self._last_error
        if error:
            if error != self._last_error:
                mail_import.log_event(error, "error")
            self._last_error = error
            self.app.set_mail_status(f"✉ Réception par e-mail : {error}", alert=True)
        else:
            self._last_error = ""
            if summary:
                self.app.set_mail_status(f"✉ {datetime.now():%H:%M} — {summary}", alert=bool(review))
            elif self.app.mail_status_is_error():
                self.app.set_mail_status("")
        if self.app.tray.is_hidden() and (summary or (error and error != previous_error)):
            self.app.tray.notify(summary or error)
        if summary:
            self.app.tray.set_tooltip(f"Ordres de travail — {summary}")
        if on_done:
            text = summary or ("Aucun nouvel ordre de travail." + (f" ({ignored} message(s) ignoré(s))" if ignored else ""))
            on_done(text, error)
