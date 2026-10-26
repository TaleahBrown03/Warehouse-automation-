"""Create an audit-friendly copy of the repository's Amazon sales report with duplicate candidates removed.

Always reads data/amazon_sale_report.csv unless a source is passed in code; nothing is discovered automatically.
The source is never modified. Retained rows are written exactly as read: no header is renamed, no value is
changed, and blanks stay blank. Removed rows are only *candidate* duplicates: without SKU or order-line
identifiers they cannot be proved to be errors, so every removed row is kept in an audit CSV.
"""
import hashlib
import json
from pathlib import Path

import pandas as pd

from engine import CLEANED_DATA_FILE, RAW_DATA_FILE, SOURCE_INDEX_COLUMN, clean, data_quality, duplicate_candidates

PROJECT_DIR = Path(__file__).parent
VALIDATION_FILE = PROJECT_DIR / "data" / "amazon_sale_report_validation.json"
DUPLICATE_AUDIT_FILE = PROJECT_DIR / "reports" / "amazon_sale_report_duplicate_candidates.csv"
REQUIRED_SOURCE_COLUMNS = [
    "Order ID",
    "Date",
    "Status",
    "Fulfilment",
    "Sales Channel",
    "ship-service-level",
    "Category",
    "Size",
    "Courier Status",
    "Qty",
]
DUPLICATE_RULE = (
    f"Duplicate candidate: identical to an earlier row in every source column except the source row-index "
    f"column ('{SOURCE_INDEX_COLUMN}'); the first occurrence is kept. Candidates are not proven errors, "
    "because the file has no SKU or order-line identifier."
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_as_text(path: Path) -> pd.DataFrame:
    """Every field as text. Only empty fields become blank; text such as 'NA' or 'null' is kept as written."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


def _line_ending(path: Path) -> str:
    with open(path, "rb") as f:
        return "\r\n" if f.readline().endswith(b"\r\n") else "\n"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_DIR.resolve()))
    except ValueError:
        return path.name


def create_clean_copy(
    source: Path = RAW_DATA_FILE,
    output: Path = CLEANED_DATA_FILE,
    validation_output: Path = VALIDATION_FILE,
    duplicate_audit_output: Path = DUPLICATE_AUDIT_FILE,
) -> dict[str, object]:
    """Remove only duplicate candidates; validate the result before it replaces the existing derived file."""
    if not source.exists():
        raise FileNotFoundError(f"Amazon sales report not found: {source}")

    source_sha256 = sha256(source)
    raw = read_as_text(source)
    missing_columns = [column for column in REQUIRED_SOURCE_COLUMNS if column not in raw.columns]
    if missing_columns:
        raise ValueError(f"Required source columns are missing: {', '.join(missing_columns)}")

    candidates = duplicate_candidates(raw)
    cleaned = raw.loc[~candidates]
    # Match the source's line endings so every retained row is byte-for-byte the source line
    line_ending = _line_ending(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(output.name + ".tmp")
    cleaned.to_csv(staged, index=False, lineterminator=line_ending)
    try:
        written = read_as_text(staged)
        problems = []
        if list(written.columns) != list(raw.columns):
            problems.append("columns differ from the source")
        if not written.equals(cleaned.reset_index(drop=True)):
            problems.append("retained rows differ from the source rows")
        if len(written) + int(candidates.sum()) != len(raw):
            problems.append("retained and removed rows do not add up to the source rows")
        if bool(duplicate_candidates(written).any()):
            problems.append("duplicate candidates remain")
        if sha256(source) != source_sha256:
            problems.append("the source file changed while the copy was being made")
        if problems:
            raise ValueError("Derived copy failed validation, existing file left unchanged: " + "; ".join(problems))
        validated_lines = clean(written)  # raises DataValidationError if the engine would reject the copy
    except Exception:
        staged.unlink(missing_ok=True)
        raise
    staged.replace(output)

    duplicate_audit_output.parent.mkdir(parents=True, exist_ok=True)
    raw.loc[candidates].to_csv(duplicate_audit_output, index=False, lineterminator=line_ending)

    quality = data_quality(written, validated_lines) if len(written) else pd.DataFrame()
    blanks = {
        column: int(count)
        for column, count in written.isna().sum().items()
        if count
    }
    report: dict[str, object] = {
        "source_file": _display_path(source),
        "source_sha256": source_sha256,
        "output_file": _display_path(output),
        "output_sha256": sha256(output),
        "source_rows": int(len(raw)),
        "output_rows": int(len(written)),
        "duplicate_candidates_removed": int(candidates.sum()),
        "duplicate_rule": DUPLICATE_RULE,
        "duplicate_candidates_audit_file": _display_path(duplicate_audit_output),
        "duplicate_candidates_audit_sha256": sha256(duplicate_audit_output),
        "remaining_duplicate_rows_by_rule": int(duplicate_candidates(written).sum()),
        "retained_rows_identical_to_source": True,
        "blank_cells_preserved_by_column": blanks,
        "columns_preserved": list(written.columns),
        "required_feature_blanks": {
            column: int(written[column].isna().sum())
            for column in REQUIRED_SOURCE_COLUMNS
        },
        "engine_validation": "passed",
        "quality_checks": quality.to_dict(orient="records"),
        "values_filled_or_inferred": 0,
        "source_modified": sha256(source) != source_sha256,
    }
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    summary = create_clean_copy()
    print(json.dumps(summary, indent=2, default=str))
