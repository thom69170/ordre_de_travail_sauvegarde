"""Point d'entrée unique pour l'extraction : choisit Gemini (si une clé est configurée) ou
l'OCR local Tesseract, avec repli automatique sur Tesseract si Gemini échoue."""
from __future__ import annotations

from PIL import Image

from app import config, parser
from app.models import ExtractionResult


def extract_from_pages(pages: list[Image.Image]) -> ExtractionResult:
    api_key = config.get_gemini_api_key()
    if api_key:
        from app import gemini_engine

        try:
            return gemini_engine.extract_from_pages(pages, api_key)
        except gemini_engine.GeminiError as exc:
            result = parser.extract_from_pages(pages)
            result.warnings.insert(
                0, f"Échec de la lecture via Gemini ({exc}) : bascule sur l'OCR local."
            )
            return result
    return parser.extract_from_pages(pages)
