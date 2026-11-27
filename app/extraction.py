"""Point d'entrée unique pour l'extraction : choisit Gemini (si une clé est configurée) ou
l'OCR local Tesseract, avec repli automatique sur Tesseract si Gemini échoue."""
from __future__ import annotations

from PIL import Image

from app import config, parser
from app.models import ExtractionResult

# Début de l'avertissement ajouté quand Gemini n'a pas pu lire (panne, quota, connexion) : la
# réception par e-mail s'en sert pour réessayer plus tard plutôt que de demander une relecture.
GEMINI_FAILED_PREFIX = "Échec de la lecture via Gemini"


def extract_from_pages(pages: list[Image.Image]) -> ExtractionResult:
    api_key = config.get_gemini_api_key()
    if api_key:
        from app import gemini_engine

        try:
            return gemini_engine.extract_from_pages(pages, api_key)
        except gemini_engine.GeminiError as exc:
            result = parser.extract_from_pages(pages)
            result.warnings.insert(
                0, f"{GEMINI_FAILED_PREFIX} ({exc}) : bascule sur l'OCR local."
            )
            return result
    return parser.extract_from_pages(pages)
