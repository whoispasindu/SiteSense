"""Parse and validate a bill of quantities from Excel (.xlsx) or CSV.

The parser is written for spreadsheets as quantity surveyors actually produce them: header names
vary ("Qty", "Unit rate"), section headings and notes sit between items, numbers come formatted
("1,250.50") or as numbers. It is also written for hostile files:

- only .xlsx (a zip) and plain-text CSV are accepted, checked by content, not by name
- zip bombs are refused before decompression (member count and declared uncompressed size)
- XML is parsed through defusedxml (openpyxl uses it automatically when installed)
- formulas are never evaluated: only cached values are read, a formula without one is an error
- rows, columns and cell lengths are capped

Validation never stops at the first problem: every row gets a result, so the user can fix the
whole file in one pass. Nothing is imported unless every row is valid.
"""

import csv
import io
import re
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from openpyxl import load_workbook

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_DATA_ROWS = 5000
MAX_COLUMNS = 30
MAX_HEADER_SEARCH_ROWS = 20
MAX_ZIP_MEMBERS = 500
MAX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024

MAX_QUANTITY = Decimal("99999999999.999")
MAX_RATE = Decimal("999999999999.99")
CENTS = Decimal("0.01")

Column = Literal[
    "section_code", "section_name", "item_code", "description", "unit", "quantity", "rate", "budget_rate"
]

# Accepted header spellings, compared after lower-casing and dropping punctuation and "(LKR)".
HEADER_ALIASES: dict[Column, tuple[str, ...]] = {
    "section_code": ("section code", "section", "section no", "section ref", "sec"),
    "section_name": ("section name", "section title", "section description"),
    "item_code": ("item code", "item", "item no", "item ref", "ref", "code"),
    "description": ("description", "item description", "desc", "particulars"),
    "unit": ("unit", "units", "uom"),
    "quantity": ("quantity", "qty"),
    "rate": ("rate", "unit rate", "contract rate"),
    "budget_rate": ("budget rate", "cost rate", "budget unit rate"),
}
REQUIRED: tuple[Column, ...] = (
    "section_code",
    "section_name",
    "item_code",
    "description",
    "unit",
    "quantity",
    "rate",
)

TEXT_LIMITS: dict[Column, int] = {
    "section_code": 16,
    "section_name": 160,
    "item_code": 24,
    "description": 500,
    "unit": 16,
}


class BoqFileError(ValueError):
    """The file as a whole cannot be read (wrong type, unsafe, no header...)."""


@dataclass
class CellError:
    column: str
    message: str


@dataclass
class RowResult:
    row: int
    status: Literal["ok", "skipped", "error"]
    section_code: str | None = None
    item_code: str | None = None
    description: str | None = None
    errors: list[CellError] = field(default_factory=list)


@dataclass
class ParsedItem:
    row: int
    section_code: str
    section_name: str
    item_code: str
    description: str
    unit: str
    quantity: Decimal
    rate: Decimal
    amount: Decimal
    budget_amount: Decimal


@dataclass
class SectionSummary:
    code: str
    name: str
    items: int = 0
    amount: Decimal = Decimal("0.00")
    budget: Decimal = Decimal("0.00")


@dataclass
class ParseResult:
    rows: list[RowResult]
    items: list[ParsedItem]
    sections: list[SectionSummary]
    has_budget_rates: bool

    @property
    def error_count(self) -> int:
        return sum(r.status == "error" for r in self.rows)

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0 and len(self.items) > 0


# --- Reading files ------------------------------------------------------------------------


def _detect_kind(filename: str, content: bytes) -> Literal["xlsx", "csv"]:
    if content.startswith(b"PK\x03\x04"):
        return "xlsx"
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        raise BoqFileError("Old .xls files are not supported. Save the sheet as .xlsx or CSV and try again.")
    if b"\x00" in content[:4096]:
        raise BoqFileError("This file is not a spreadsheet. Upload an .xlsx or CSV file.")
    if filename.lower().endswith((".xlsx", ".xlsm")):
        raise BoqFileError("This .xlsx file is damaged or not really an Excel workbook.")
    return "csv"


def _check_zip_safety(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise BoqFileError("The workbook has an unusual structure and was refused.")
            if sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
                raise BoqFileError("The workbook expands to an unsafe size and was refused.")
            if any(m.filename.endswith("vbaProject.bin") for m in members):
                raise BoqFileError("Workbooks with macros are not accepted. Save as .xlsx without macros.")
    except zipfile.BadZipFile as exc:
        raise BoqFileError("This .xlsx file is damaged or not really an Excel workbook.") from exc


def _xlsx_rows(content: bytes) -> Iterator[tuple[int, list[object]]]:
    _check_zip_safety(content)
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types for malformed files
        raise BoqFileError("The workbook could not be read. Re-save it in Excel and try again.") from exc
    try:
        names = {name.strip().lower(): name for name in workbook.sheetnames}
        sheet = workbook[names["boq"]] if "boq" in names else workbook.worksheets[0]
        for index, values in enumerate(sheet.iter_rows(max_col=MAX_COLUMNS, values_only=True), start=1):
            yield index, list(values)
            if index > MAX_DATA_ROWS + MAX_HEADER_SEARCH_ROWS:
                break
    finally:
        workbook.close()


def _csv_rows(content: bytes) -> Iterator[tuple[int, list[object]]]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes almost anything
        raise BoqFileError("The CSV file's text encoding was not recognised. Save it as UTF-8.")
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for index, values in enumerate(reader, start=1):
        yield index, list(values[:MAX_COLUMNS])
        if index > MAX_DATA_ROWS + MAX_HEADER_SEARCH_ROWS:
            break


# --- Header detection ---------------------------------------------------------------------


def _normalise_header(value: object) -> str:
    text = str(value or "").lower().replace("(lkr)", "").replace("lkr", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


def _match_header(cells: list[object]) -> dict[Column, int] | None:
    found: dict[Column, int] = {}
    for position, cell in enumerate(cells):
        name = _normalise_header(cell)
        for column, aliases in HEADER_ALIASES.items():
            if column not in found and name in aliases:
                found[column] = position
                break
    return found if all(c in found for c in REQUIRED) else None


# --- Cell parsing -------------------------------------------------------------------------


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def _number(value: object, *, places: int, maximum: Decimal) -> tuple[Decimal | None, str | None]:
    """Return (value, error). Accepts numbers and text like "1,250.50" or "LKR 1,250"."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "Required."
    if isinstance(value, bool):
        return None, "Must be a number."
    if isinstance(value, int | float | Decimal):
        raw = str(value)
    else:
        raw = re.sub(r"(?i)^\s*(lkr|rs\.?)\s*", "", str(value)).replace(",", "").strip()
        if raw.startswith("="):
            return None, "Formula without a saved value. Open the file in Excel and save it again."
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None, "Must be a number."
    if not number.is_finite():
        return None, "Must be a number."
    exponent = number.normalize().as_tuple().exponent
    if isinstance(exponent, int) and -exponent > places:
        return None, f"Use at most {places} decimal places."
    if number > maximum:
        return None, "Value is too large."
    return number, None


# --- Validation ---------------------------------------------------------------------------


def _cell(cells: list[object], header: dict[Column, int], column: Column) -> object:
    position = header.get(column)
    return cells[position] if position is not None and position < len(cells) else None


def _is_blank(cells: Iterable[object]) -> bool:
    return all(_text(c) == "" for c in cells)


def parse_boq(filename: str, content: bytes) -> ParseResult:
    if not content:
        raise BoqFileError("The file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise BoqFileError("The file is larger than 5 MB.")

    rows_iter = _xlsx_rows(content) if _detect_kind(filename, content) == "xlsx" else _csv_rows(content)

    header: dict[Column, int] | None = None
    results: list[RowResult] = []
    items: list[ParsedItem] = []
    sections: dict[str, SectionSummary] = {}
    seen_items: dict[str, int] = {}
    has_budget_rates = False
    data_rows = 0

    for row_number, cells in rows_iter:
        if header is None:
            header = _match_header(cells)
            if header is None and row_number >= MAX_HEADER_SEARCH_ROWS:
                break
            continue
        if _is_blank(cells):
            continue
        data_rows += 1
        if data_rows > MAX_DATA_ROWS:
            raise BoqFileError(f"The BOQ has more than {MAX_DATA_ROWS} rows. Split it into smaller files.")

        def cell(column: Column, cells: list[object] = cells, header: dict[Column, int] = header) -> object:
            return _cell(cells, header, column)

        texts = {column: _text(cell(column)) for column in TEXT_LIMITS}
        raw_qty, raw_rate = cell("quantity"), cell("rate")
        result = RowResult(
            row=row_number,
            status="ok",
            section_code=texts["section_code"] or None,
            item_code=texts["item_code"] or None,
            description=texts["description"] or None,
        )

        # Headings and notes: no item code, no quantity, no rate. Kept in the report, not imported.
        if not texts["item_code"] and _text(raw_qty) == "" and _text(raw_rate) == "":
            result.status = "skipped"
            results.append(result)
            continue

        errors = result.errors
        for column in ("section_code", "section_name", "item_code", "description", "unit"):
            value = texts[column]
            if not value:
                errors.append(CellError(column, "Required."))
            elif len(value) > TEXT_LIMITS[column]:
                errors.append(CellError(column, f"Use at most {TEXT_LIMITS[column]} characters."))

        quantity, qty_error = _number(raw_qty, places=3, maximum=MAX_QUANTITY)
        if qty_error:
            errors.append(CellError("quantity", qty_error))
        elif quantity is not None and quantity <= 0:
            errors.append(CellError("quantity", "Must be greater than zero."))

        rate, rate_error = _number(raw_rate, places=2, maximum=MAX_RATE)
        if rate_error:
            errors.append(CellError("rate", rate_error))
        elif rate is not None and rate < 0:
            errors.append(CellError("rate", "Cannot be negative."))

        budget_rate: Decimal | None = None
        raw_budget = cell("budget_rate")
        if "budget_rate" in (header or {}) and _text(raw_budget) != "":
            budget_rate, budget_error = _number(raw_budget, places=2, maximum=MAX_RATE)
            if budget_error:
                errors.append(CellError("budget_rate", budget_error))
            elif budget_rate is not None and budget_rate < 0:
                errors.append(CellError("budget_rate", "Cannot be negative."))
            else:
                has_budget_rates = True

        code = texts["section_code"]
        if code and texts["section_name"]:
            existing = sections.get(code)
            if existing and existing.name.lower() != texts["section_name"].lower():
                errors.append(
                    CellError(
                        "section_name",
                        f'Section {code} is already named "{existing.name}" on an earlier row.',
                    )
                )

        item_code = texts["item_code"]
        if item_code:
            first = seen_items.get(item_code.upper())
            if first is not None:
                errors.append(CellError("item_code", f"Duplicate item code (first used on row {first})."))
            else:
                seen_items[item_code.upper()] = row_number

        if errors or quantity is None or rate is None:
            result.status = "error"
            results.append(result)
            continue

        amount = (quantity * rate).quantize(CENTS, rounding=ROUND_HALF_UP)
        budget_amount = (
            amount if budget_rate is None else (quantity * budget_rate).quantize(CENTS, ROUND_HALF_UP)
        )
        summary = sections.setdefault(code, SectionSummary(code=code, name=texts["section_name"]))
        summary.items += 1
        summary.amount += amount
        summary.budget += budget_amount
        items.append(
            ParsedItem(
                row=row_number,
                section_code=code,
                section_name=summary.name,
                item_code=item_code,
                description=texts["description"],
                unit=texts["unit"],
                quantity=quantity,
                rate=rate,
                amount=amount,
                budget_amount=budget_amount,
            )
        )
        results.append(result)

    if header is None:
        expected = ", ".join(a[0].title() for a in (HEADER_ALIASES[c] for c in REQUIRED))
        raise BoqFileError(f"No header row found. The first rows must include the columns: {expected}.")
    if data_rows == 0:
        raise BoqFileError("The file has a header row but no BOQ items.")

    return ParseResult(
        rows=results, items=items, sections=list(sections.values()), has_budget_rates=has_budget_rates
    )
