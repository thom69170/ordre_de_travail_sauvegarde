"""Lecture d'un bulletin de paie (PDF numérique) - sans OCR ni IA, à partir du texte du PDF.

Particularité de ces bulletins : dans le corps du tableau, le texte extrait ne contient PAS les
virgules ("15167 134010 203253" pour 151,67 x 13,4010 = 2 032,53). La position de la virgule est
fixée par la colonne (2 décimales pour Quantité/Base, Montant/Part salarié et Part employeur, 4
pour Valeur unitaire/Taux), et la colonne se reconnaît à la position horizontale du nombre, aligné
à droite. Le pied de page, lui, contient de vrais nombres à virgule (net payé, brut fiscal...) :
ils servent à recouper la lecture du corps.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Bord droit maximal (en points PDF) des 4 colonnes de nombres, de gauche à droite, et nombre de
# décimales de chacune. Mesuré sur un bulletin réel : bords droits à ~300, ~338, ~386 et ~430.
_COLUMNS = (
    (310.0, 2),  # Quantité / Base
    (350.0, 4),  # Valeur unitaire / Taux
    (400.0, 2),  # Montant / Part salarié
    (440.0, 2),  # Part employeur
)
_BODY_MAX_X = 440.0  # au-delà : tableau "Date / Motif" des absences, hors du corps
_ROW_TOLERANCE = 4.5  # écart vertical maximal entre caractères d'une même ligne (lignes à ~8 pt)

SECTION_BRUT = "brut"
SECTION_COTISATIONS = "cotisations"
SECTION_AUTRES = "autres"

_MARKER = re.compile(r"##(\d{4}-\d{2}-\d{2})##(\d{4}-\d{2}-\d{2})##Bulletin de paie##")
_PERIOD = re.compile(r"(\d{2})/(\d{2})/(\d{4}) au (\d{2})/(\d{2})/(\d{4})")
_PAYMENT = re.compile(r"Paiement effectué le (\d{2})/(\d{2})/(\d{4}) par (\S+) (-?[\d ]+,\d{2})")
_DECIMAL = r"-?\d[\d ]*,\d{2}"
_FOUR_DECIMALS = re.compile(rf"^({_DECIMAL}) ({_DECIMAL}) ({_DECIMAL}) ({_DECIMAL})$")
_INTEGER_TOKEN = re.compile(r"^-?\d+$")
_ABSENCE = re.compile(r"^[A-Z]{1,5} \d{2}/\d{2} au \d{2}/\d{2}")


class BulletinError(Exception):
    pass


@dataclass
class BulletinLine:
    section: str
    label: str
    quantity: float | None = None  # Quantité, ou Base pour une cotisation
    rate: float | None = None  # Valeur unitaire, ou Taux pour une cotisation
    amount: float | None = None  # Montant, ou Part salarié pour une cotisation
    employer: float | None = None  # Part employeur


@dataclass
class BulletinData:
    period_start: str = ""
    period_end: str = ""
    payment_date: str = ""
    payment_mode: str = ""
    net_paye: float = 0.0
    brut: float = 0.0
    net_fiscal: float = 0.0
    heures: float = 0.0
    lines: list[BulletinLine] = field(default_factory=list)
    cumuls: dict[str, float] = field(default_factory=dict)
    absences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _to_float(text: str) -> float:
    return float(text.replace(" ", "").replace(",", "."))


def normalize(text: str) -> str:
    """Minuscules sans accents ni espaces multiples, pour comparer des libellés."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def _open(path: Path):
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(str(path))
    except Exception as exc:  # noqa: BLE001
        raise BulletinError(f"PDF illisible : {exc}") from exc


def is_bulletin(path: Path) -> bool:
    """Ce PDF est-il un bulletin de paie (et non une feuille de prépaie ou autre chose) ?"""
    if path.suffix.lower() != ".pdf":
        return False
    try:
        pdf = _open(path)
        try:
            text = pdf[0].get_textpage().get_text_range() if len(pdf) else ""
        finally:
            pdf.close()  # sinon le fichier reste verrouillé sous Windows (suppression impossible)
    except Exception:  # noqa: BLE001
        return False
    return "BULLETIN DE PAIE" in text and "Eléments de revenu brut" in text


def _page_rows(textpage) -> list[tuple[float, list[tuple[float, float, str]]]]:
    """Lignes du corps de la page : [(y, [(x_gauche, x_droite, texte_du_jeton), ...]), ...] de
    haut en bas. Les caractères sont regroupés par proximité verticale (un signe "-" ou une
    apostrophe sont parfois posés 3 pt plus haut que le reste de leur ligne)."""
    chars = []
    for i in range(textpage.count_chars()):
        ch = textpage.get_text_range(i, 1)
        if not ch.strip():
            continue
        left, bottom, right, _top = textpage.get_charbox(i)
        if 38.0 <= left < _BODY_MAX_X:  # < 38 : texte vertical dans la marge
            chars.append((bottom, left, right, ch))
    chars.sort(key=lambda c: -c[0])

    rows: list[tuple[float, list[tuple[float, float, str]]]] = []
    current: list[tuple[float, float, str]] = []
    row_y = None
    for bottom, left, right, ch in chars:
        if row_y is None or row_y - bottom > _ROW_TOLERANCE:
            if current:
                rows.append((row_y, current))
            current, row_y = [], bottom
        current.append((left, right, ch))
    if current:
        rows.append((row_y, current))

    result = []
    for y, row_chars in rows:
        row_chars.sort()
        tokens: list[list] = []
        for left, right, ch in row_chars:
            # 4 pt : le chiffre "1", plus étroit, laisse jusqu'à ~2 pt de vide autour de lui à
            # l'intérieur d'un même nombre, alors que deux colonnes sont séparées d'au moins 15 pt.
            if tokens and left - tokens[-1][1] < 4.0:
                tokens[-1][1] = max(tokens[-1][1], right)
                tokens[-1][2] += ch
            else:
                tokens.append([left, right, ch])
        result.append((y, [(t[0], t[1], t[2]) for t in tokens]))
    return result


def _column_value(right_edge: float, digits: str) -> tuple[int, float] | None:
    """(indice de colonne, valeur) d'un nombre sans virgule, d'après son bord droit."""
    for index, (max_right, decimals) in enumerate(_COLUMNS):
        if right_edge <= max_right:
            return index, int(digits) / (10 ** decimals)
    return None


def _parse_page(textpage, data: BulletinData) -> None:
    rows = _page_rows(textpage)

    # Repères verticaux des sections (les en-têtes sont répétés sur chaque page).
    sections: list[tuple[float, str]] = []
    body_bottom = 0.0
    for y, tokens in rows:
        joined = normalize("".join(t[2] for t in tokens)).replace(" ", "")
        if "revenubrut" in joined:
            sections.append((y, SECTION_BRUT))
        elif "contributionssociales" in joined and "total" not in joined:
            sections.append((y, SECTION_COTISATIONS))
        elif joined.startswith("autres") and "paie" in joined:
            sections.append((y, SECTION_AUTRES))
        elif "netpaye" in joined or "totalverse" in joined:
            body_bottom = max(body_bottom, y)
    if not sections:
        return
    sections.sort(reverse=True)

    def section_at(y: float) -> str | None:
        found = None
        for section_y, name in sections:
            if y < section_y - 1:
                found = name
        return found

    # Lignes du corps avec leurs nombres répartis par colonne, indexées par la suite de chiffres
    # telle qu'elle apparaît dans le texte ("203253 60000 12195").
    numeric_rows: list[dict] = []
    for y, tokens in rows:
        if y <= body_bottom:
            continue
        section = section_at(y)
        if section is None:
            continue
        numbers = []
        tokens = list(tokens)
        index = 0
        while index < len(tokens):
            left, right, text = tokens[index]
            # Un "-" isolé juste avant un nombre (posé un peu plus haut) en est le signe.
            if text == "-" and index + 1 < len(tokens) and re.fullmatch(r"\d+", tokens[index + 1][2]) \
                    and tokens[index + 1][0] - right < 3.0 and left > 250:
                next_left, next_right, next_text = tokens[index + 1]
                numbers.append((next_right, "-" + next_text))
                index += 2
                continue
            if left > 250 and re.fullmatch(r"-?\d+", text):
                numbers.append((right, text))
            index += 1
        if not numbers:
            continue
        columns: dict[int, float] = {}
        for right, text in numbers:
            placed = _column_value(right, text.lstrip("-"))
            if placed is None:
                continue
            column, value = placed
            columns[column] = -value if text.startswith("-") else value
        numeric_rows.append({
            "key": tuple(text for _right, text in numbers), "section": section,
            "columns": columns, "used": False,
        })

    # Libellés : pris dans le texte "linéaire" de la page (espaces et accents corrects), puis
    # rattachés à la ligne positionnée qui porte la même suite de nombres.
    pending: list[str] = []
    for raw_line in textpage.get_text_range().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(" ")
        numbers: list[str] = []
        while parts and _INTEGER_TOKEN.match(parts[-1]):
            numbers.insert(0, parts.pop())
        label = " ".join(parts).strip()
        if not numbers:
            pending.append(label)
            continue
        if not label:
            label = " ".join(pending[-2:]) if pending else ""
        pending = []
        key = tuple(numbers)
        match = next((r for r in numeric_rows if not r["used"] and r["key"] == key), None)
        if match is None or not label:
            continue
        match["used"] = True
        columns = match["columns"]
        data.lines.append(BulletinLine(
            section=match["section"], label=label.lstrip("> ").strip(),
            quantity=columns.get(0), rate=columns.get(1), amount=columns.get(2),
            employer=columns.get(3),
        ))


def _parse_footer(text: str, data: BulletinData) -> None:
    marker = _MARKER.search(text)
    if marker:
        data.period_start, data.period_end = marker.group(1), marker.group(2)
    else:
        period = _PERIOD.search(text)
        if period:
            d1, m1, y1, d2, m2, y2 = period.groups()
            data.period_start, data.period_end = f"{y1}-{m1}-{d1}", f"{y2}-{m2}-{d2}"

    payment = _PAYMENT.search(text)
    if payment:
        day, month, year, mode, amount = payment.groups()
        data.payment_date = f"{year}-{month}-{day}"
        data.payment_mode = mode
        data.net_paye = _to_float(amount)

    # Bloc "DU MOIS / CUMULE" : 4 lignes de 4 nombres à virgule, dans cet ordre.
    labels = (
        ("Brut fiscal", "Cotisations salariales"),
        ("Brut abattu", "Cotisations patronales"),
        ("Net fiscal", "Heures déclarées"),
        ("Plafond", "Avantage en nature"),
    )
    blocks = [m.groups() for m in map(_FOUR_DECIMALS.match, (l.strip() for l in text.splitlines())) if m]
    if len(blocks) >= 4:
        for (left_label, right_label), values in zip(labels, blocks[-4:]):
            month_left, cumul_left, month_right, cumul_right = (_to_float(v) for v in values)
            data.cumuls[f"{left_label} (mois)"] = month_left
            data.cumuls[f"{left_label} (cumul annuel)"] = cumul_left
            data.cumuls[f"{right_label} (mois)"] = month_right
            data.cumuls[f"{right_label} (cumul annuel)"] = cumul_right
        data.net_fiscal = data.cumuls["Net fiscal (mois)"]
        data.heures = data.cumuls["Heures déclarées (mois)"]

    for line in text.splitlines():
        line = line.strip()
        if _ABSENCE.match(line) and line not in data.absences:
            data.absences.append(line)


def find_line(data_lines: list[BulletinLine], pattern: str, section: str | None = None) -> BulletinLine | None:
    regex = re.compile(pattern)
    for line in data_lines:
        if (section is None or line.section == section) and regex.search(normalize(line.label)):
            return line
    return None


def extract_bulletin(path: Path) -> BulletinData:
    pdf = _open(path)
    data = BulletinData()
    full_text = []
    try:
        for i in range(len(pdf)):
            textpage = pdf[i].get_textpage()
            full_text.append(textpage.get_text_range())
            _parse_page(textpage, data)
    finally:
        pdf.close()
    text = "\n".join(full_text)
    if "BULLETIN DE PAIE" not in text:
        raise BulletinError("Ce document n'est pas un bulletin de paie reconnu.")
    _parse_footer(text, data)

    if not data.period_start:
        data.warnings.append("Période du bulletin non trouvée.")

    brut_line = find_line(data.lines, r"^salaire brut$", SECTION_BRUT)
    if brut_line and brut_line.amount is not None:
        data.brut = brut_line.amount
        # Recoupement n°1 : la somme des éléments de revenu brut doit donner le salaire brut.
        total = sum(
            line.amount for line in data.lines
            if line.section == SECTION_BRUT and line is not brut_line and line.amount is not None
        )
        if abs(total - data.brut) > 0.02:
            data.warnings.append(
                f"La somme des éléments de revenu brut lus ({total:.2f}) ne correspond pas au "
                f"salaire brut ({data.brut:.2f}) : certaines lignes sont peut-être mal lues."
            )
    else:
        data.brut = data.cumuls.get("Brut fiscal (mois)", 0.0)
        data.warnings.append("Ligne « SALAIRE BRUT » non trouvée dans le corps du bulletin.")

    # Recoupement n°2 : net à payer (corps, sans virgule) = net payé (pied de page, avec virgule).
    net_line = find_line(data.lines, r"^net a payer")
    pas_line = find_line(data.lines, r"^prelevement a la source/dgfip")
    if net_line and net_line.amount is not None:
        expected = net_line.amount - (pas_line.amount if pas_line and pas_line.amount else 0.0)
        if data.net_paye:
            if abs(expected - data.net_paye) > 0.02:
                data.warnings.append(
                    f"Le net à payer lu dans le tableau ({expected:.2f}) ne correspond pas au "
                    f"montant payé indiqué en bas du bulletin ({data.net_paye:.2f})."
                )
        else:
            data.net_paye = round(expected, 2)
    if not data.net_paye:
        data.warnings.append("Montant net payé non trouvé.")
    if not data.lines:
        data.warnings.append("Aucune ligne du bulletin n'a pu être lue.")
    return data


def previous_month_start(period_start: str) -> str:
    """Premier jour du mois précédant period_start (les éléments variables "RAP ..." d'un bulletin
    sont ceux de la feuille de prépaie du mois d'avant)."""
    d = date.fromisoformat(period_start)
    year, month = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return date(year, month, 1).isoformat()
