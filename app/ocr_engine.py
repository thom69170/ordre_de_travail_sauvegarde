"""Rendu des documents (PDF/photo) en images et extraction de texte par OCR (Tesseract)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PIL import Image

from app.paths import downloaded_tessdata_dir, tesseract_exe_path, tessdata_dir

_configured = False
_available = False


def configure() -> bool:
    """Localise Tesseract (embarqué en priorité, sinon installation système) et le configure.

    Retourne True si un moteur OCR utilisable a été trouvé.
    """
    global _configured, _available
    if _configured:
        return _available

    import pytesseract

    exe = tesseract_exe_path()
    tessdata = tessdata_dir()
    if exe is not None:
        pytesseract.pytesseract.tesseract_cmd = str(exe)
        if tessdata is not None:
            os.environ["TESSDATA_PREFIX"] = str(tessdata)
        _available = True
    else:
        system_exe = shutil.which("tesseract")
        common_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        found = system_exe or next((p for p in common_paths if Path(p).exists()), None)
        if found:
            pytesseract.pytesseract.tesseract_cmd = found
            # Le moteur système n'a souvent que l'anglais : si setup/bootstrap.py a téléchargé
            # les langues (français inclus) dans le dossier local de l'app, on les préfère.
            downloaded = downloaded_tessdata_dir()
            if downloaded is not None:
                os.environ["TESSDATA_PREFIX"] = str(downloaded)
            _available = True
        else:
            _available = False

    _configured = True
    return _available


def is_available() -> bool:
    configure()
    return _available


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def load_pages(path: Path, pdf_scale: float = 2.5) -> list[Image.Image]:
    """Charge un fichier (PDF multi-page ou photo) sous forme de liste d'images PIL."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        pages = []
        for i in range(len(pdf)):
            bitmap = pdf[i].render(scale=pdf_scale)
            pages.append(bitmap.to_pil().convert("RGB"))
        return pages
    if suffix in SUPPORTED_IMAGE_EXTENSIONS:
        img = Image.open(path)
        img = img.convert("RGB")
        # Corrige l'orientation EXIF (photos prises avec un téléphone).
        from PIL import ImageOps

        img = ImageOps.exif_transpose(img)
        return [img]
    raise ValueError(f"Format de fichier non pris en charge : {suffix}")


def ocr_text(image: Image.Image, lang: str = "fra", psm: int = 6) -> str:
    import pytesseract

    configure()
    if not _available:
        return ""
    return pytesseract.image_to_string(image, lang=lang, config=f"--psm {psm}")


def ocr_word_boxes(image: Image.Image, lang: str = "fra", psm: int = 6) -> list[dict]:
    """Retourne la liste des mots détectés avec leur position (left, top, width, height, conf)."""
    import pytesseract
    from pytesseract import Output

    configure()
    if not _available:
        return []
    data = pytesseract.image_to_data(image, lang=lang, config=f"--psm {psm}", output_type=Output.DICT)
    words = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        words.append({
            "text": text,
            "left": data["left"][i],
            "top": data["top"][i],
            "width": data["width"][i],
            "height": data["height"][i],
            "conf": data["conf"][i],
        })
    return words
