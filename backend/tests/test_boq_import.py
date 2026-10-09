import io
import zipfile
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.services.boq_import import MAX_DATA_ROWS, BoqFileError, parse_boq

SAMPLE = Path(__file__).resolve().parent.parent / "app" / "seed_data" / "boq-havelock-residences.csv"
HEADER = "Section Code,Section Name,Item Code,Description,Unit,Quantity,Rate\n"


def csv_bytes(*rows: str, header: str = HEADER) -> bytes:
    return (header + "\n".join(rows) + "\n").encode()


def xlsx_bytes(rows: Sequence[Sequence[object]], sheet_title: str = "BOQ") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = sheet_title
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def errors_by_row(result: object) -> dict[int, dict[str, str]]:
    return {r.row: {e.column: e.message for e in r.errors} for r in result.rows if r.errors}  # type: ignore[attr-defined]


# --- Happy paths ------------------------------------------------------------------------------


def test_realistic_sample_parses_with_section_totals() -> None:
    result = parse_boq(SAMPLE.name, SAMPLE.read_bytes())

    assert result.is_valid
    assert len(result.items) == 40
    assert sum(r.status == "skipped" for r in result.rows) == 8  # section heading rows
    by_code = {s.code: s for s in result.sections}
    assert [s.code for s in result.sections] == ["A", "B", "C", "D", "E", "F", "G", "H"]
    assert by_code["B"].items == 5
    assert by_code["B"].amount == Decimal("91490000.00")
    assert by_code["B"].budget == Decimal("80583500.00")
    assert sum(s.amount for s in result.sections) == Decimal("1113985000.00")
    assert result.has_budget_rates


def test_xlsx_with_numbers_and_header_aliases() -> None:
    content = xlsx_bytes(
        [
            ["Havelock Residences - Bill of Quantities"],
            [],
            ["Sec", "Section Title", "Ref", "Particulars", "UOM", "Qty", "Unit Rate (LKR)"],
            ["B", "Substructure", "B.01", "Excavation", "m3", 2850, 1450],
            ["B", "Substructure", "B.02", "Piles", "m", 1920.5, 18500.25],
        ]
    )

    result = parse_boq("boq.xlsx", content)

    assert result.is_valid
    assert [i.amount for i in result.items] == [Decimal("4132500.00"), Decimal("35529730.13")]
    assert result.items[1].quantity == Decimal("1920.5")
    assert not result.has_budget_rates
    assert result.sections[0].budget == result.sections[0].amount  # no budget rates: budget = contract


def test_prefers_a_sheet_named_boq() -> None:
    workbook = Workbook()
    cover = workbook.active
    assert cover is not None
    cover.title = "Cover"
    cover.append(["Prepared by QS"])
    boq = workbook.create_sheet("BOQ")
    boq.append(HEADER.strip().split(","))
    boq.append(["A", "Prelims", "A.01", "Site setup", "item", 1, 1000])
    buffer = io.BytesIO()
    workbook.save(buffer)

    assert parse_boq("boq.xlsx", buffer.getvalue()).is_valid


def test_formatted_numbers_semicolons_and_windows_encoding() -> None:
    content = (
        "Section Code;Section Name;Item Code;Description;Unit;Quantity;Rate\n"
        'C;Superstructure;C.01;Concrete — grade 30 "columns";m3;1,180;LKR 41,000.00\n'
    ).encode("cp1252")

    result = parse_boq("boq.csv", content)

    assert result.is_valid
    assert result.items[0].amount == Decimal("48380000.00")
    assert "grade 30" in result.items[0].description


def test_budget_rate_is_optional_per_row() -> None:
    result = parse_boq(
        "boq.csv",
        csv_bytes(
            "A,Prelims,A.01,Setup,item,1,1000,800",
            "A,Prelims,A.02,Security,month,2,500,",
            header="Section Code,Section Name,Item Code,Description,Unit,Quantity,Rate,Budget Rate\n",
        ),
    )

    assert result.is_valid
    assert result.sections[0].budget == Decimal("1800.00")  # 800 + (2 x 500 fallback)


# --- Row validation ---------------------------------------------------------------------------


def test_every_bad_row_is_reported_with_its_column() -> None:
    result = parse_boq(
        "boq.csv",
        csv_bytes(
            "A,Prelims,A.01,Setup,item,1,1000",  # row 2 ok
            "A,Prelims,A.02,Security,month,-2,500",  # row 3 negative quantity
            "A,Prelims,A.03,Water,month,two,500",  # row 4 text quantity
            "A,Prelims,A.04,Power,month,3,12.345",  # row 5 too many decimals
            "A,Prelims,A.01,Duplicate,item,1,10",  # row 6 duplicate code
            "A,Preliminaries,A.05,Bond,item,1,10",  # row 7 conflicting section name
            ",Prelims,A.06,,item,1,10",  # row 8 missing section code and description
            "A,Prelims,A.07,Formula,item,1,=B2*C2",  # row 9 formula text
            "A,Prelims,A.08,Big,item,1,9999999999999999",  # row 10 too large
        ),
    )

    assert not result.is_valid
    assert result.error_count == 8
    errors = errors_by_row(result)
    assert errors[3] == {"quantity": "Must be greater than zero."}
    assert errors[4] == {"quantity": "Must be a number."}
    assert errors[5] == {"rate": "Use at most 2 decimal places."}
    assert errors[6] == {"item_code": "Duplicate item code (first used on row 2)."}
    assert "already named" in errors[7]["section_name"]
    assert errors[8] == {"section_code": "Required.", "description": "Required."}
    assert "Formula" in errors[9]["rate"]
    assert errors[10] == {"rate": "Value is too large."}
    assert 2 not in errors


def test_long_text_is_rejected_not_truncated() -> None:
    result = parse_boq("boq.csv", csv_bytes(f"A,Prelims,A.01,{'x' * 501},item,1,10"))

    assert errors_by_row(result)[2] == {"description": "Use at most 500 characters."}


def test_headings_and_notes_are_skipped_not_errors() -> None:
    result = parse_boq(
        "boq.csv",
        csv_bytes(
            "B,Substructure,,SUBSTRUCTURE,,,",
            ",,,Note: rates include transport to site,,,",
            "B,Substructure,B.01,Excavation,m3,10,100",
        ),
    )

    assert result.is_valid
    assert [r.status for r in result.rows] == ["skipped", "skipped", "ok"]


def test_header_with_no_items_is_an_error() -> None:
    with pytest.raises(BoqFileError, match="no BOQ items"):
        parse_boq("boq.csv", csv_bytes())


def test_file_with_only_headings_is_not_valid() -> None:
    result = parse_boq("boq.csv", csv_bytes("B,Substructure,,SUBSTRUCTURE,,,"))

    assert not result.is_valid


# --- Hostile and broken files -----------------------------------------------------------------


def test_missing_header_names_the_expected_columns() -> None:
    with pytest.raises(BoqFileError, match="Section Code, Section Name, Item Code"):
        parse_boq("boq.csv", b"Code,Thing\n1,2\n")


def test_empty_file() -> None:
    with pytest.raises(BoqFileError, match="empty"):
        parse_boq("boq.csv", b"")


def test_oversized_file() -> None:
    with pytest.raises(BoqFileError, match="5 MB"):
        parse_boq("boq.csv", b"x" * (5 * 1024 * 1024 + 1))


def test_old_xls_and_binary_files_are_refused() -> None:
    with pytest.raises(BoqFileError, match=r"Old \.xls"):
        parse_boq("boq.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    with pytest.raises(BoqFileError, match="not a spreadsheet"):
        parse_boq("boq.csv", b"\x7fELF\x00\x00\x00binary")


def test_fake_xlsx_is_refused() -> None:
    with pytest.raises(BoqFileError, match="damaged"):
        parse_boq("boq.xlsx", b"Section Code,Section Name\n")
    with pytest.raises(BoqFileError, match="damaged"):
        parse_boq("boq.xlsx", b"PK\x03\x04" + b"garbage" * 20)


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_zip_bomb_is_refused_before_decompression() -> None:
    bomb = _zip({"xl/worksheets/sheet1.xml": b"0" * (61 * 1024 * 1024)})
    assert len(bomb) < 1024 * 1024  # tiny on disk, huge when expanded

    with pytest.raises(BoqFileError, match="unsafe size"):
        parse_boq("boq.xlsx", bomb)


def test_workbook_with_too_many_parts_is_refused() -> None:
    with pytest.raises(BoqFileError, match="unusual structure"):
        parse_boq("boq.xlsx", _zip({f"part{i}.xml": b"x" for i in range(501)}))


def test_macro_workbooks_are_refused() -> None:
    with pytest.raises(BoqFileError, match="macros"):
        parse_boq("boq.xlsx", _zip({"xl/vbaProject.bin": b"macro", "[Content_Types].xml": b"<x/>"}))


def test_xml_entity_expansion_is_blocked() -> None:
    billion_laughs = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">&lol2;</workbook>"""
    content = _zip({"[Content_Types].xml": billion_laughs, "xl/workbook.xml": billion_laughs})

    with pytest.raises(BoqFileError):
        parse_boq("boq.xlsx", content)


def test_formulas_are_never_evaluated() -> None:
    content = xlsx_bytes([HEADER.strip().split(","), ["A", "Prelims", "A.01", "Setup", "item", 2, "=10*100"]])

    result = parse_boq("boq.xlsx", content)

    # openpyxl wrote no cached value, so the rate is missing rather than computed.
    assert not result.is_valid
    assert errors_by_row(result)[2] == {"rate": "Required."}


def test_row_limit() -> None:
    rows = [f"A,Prelims,A.{i},Item,nr,1,1" for i in range(MAX_DATA_ROWS + 1)]
    with pytest.raises(BoqFileError, match="more than 5000 rows"):
        parse_boq("boq.csv", csv_bytes(*rows))


def test_openpyxl_parses_xml_through_defusedxml() -> None:
    """The real guarantee behind the entity-expansion test above: if defusedxml were missing,
    openpyxl would silently fall back to the standard, unsafe XML parser."""
    from openpyxl import xml as openpyxl_xml

    assert openpyxl_xml.DEFUSEDXML is True
