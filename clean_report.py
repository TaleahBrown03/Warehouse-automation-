"""Create an audit-friendly deduplicated copy of the Amazon sales report.

The source is never modified. Blank values are preserved; no values are inferred or filled.
"""
import json
from pathlib import Path

import pandas as pd

from engine import SOURCE_DATA_FILE, clean, data_quality

OUTPUT_FILE = Path(__file__).parent / "data" / "amazon_sale_report_cleaned.csv"
VALIDATION_FILE = Path(__file__).parent / "data" / "amazon_sale_report_validation.json"
DUPLICATE_AUDIT_FILE = Path(__file__).parent / "reports" / "amazon_sale_report_duplicate_candidates.csv"
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
SOURCE_ROW_INDEX_NAMES = {"index", "ndex"}


def create_clean_copy(
    source: Path = SOURCE_DATA_FILE,
    output: Path = OUTPUT_FILE,
    validation_output: Path = VALIDATION_FILE,
    duplicate_audit_output: Path = DUPLICATE_AUDIT_FILE,
) -> dict[str, object]:
    """Remove only repeated business rows and preserve all source blanks and columns."""
    if not source.exists():
        raise FileNotFoundError(f"Amazon sales report not found: {source}")

    raw = pd.read_csv(source, dtype=str)
    missing_columns = [column for column in REQUIRED_SOURCE_COLUMNS if column not in raw.columns]
    if missing_columns:
        raise ValueError(f"Required source columns are missing: {', '.join(missing_columns)}")

    duplicate_key = [
        column
        for column in raw.columns
        if column.strip().lower() not in SOURCE_ROW_INDEX_NAMES
    ]
    duplicate_mask = raw.duplicated(subset=duplicate_key, keep="first")
    duplicate_candidates = raw.loc[duplicate_mask].copy()
    cleaned = raw.loc[~duplicate_mask].copy()

    output.parent.mkdir(parents=True, exist_ok=True)
    duplicate_audit_output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(output, index=False)
    duplicate_candidates.to_csv(duplicate_audit_output, index=False)

    validated_lines = clean(cleaned)
    quality = data_quality(cleaned, validated_lines) if len(cleaned) else pd.DataFrame()
    try:
        duplicate_audit_display_path = str(duplicate_audit_output.relative_to(Path(__file__).parent))
    except ValueError:
        duplicate_audit_display_path = duplicate_audit_output.name
    blanks = {
        column: int(count)
        for column, count in cleaned.isna().sum().items()
        if count
    }
    report: dict[str, object] = {
        "source_file": source.name,
        "output_file": output.name,
        "source_rows": int(len(raw)),
        "output_rows": int(len(cleaned)),
        "duplicate_candidates_removed": int(duplicate_mask.sum()),
        "duplicate_rule": "Duplicate across all source columns except the source row-index column (index/ndex); keep first occurrence.",
        "duplicate_candidates_audit_file": duplicate_audit_display_path,
        "remaining_duplicate_rows_by_rule": int(cleaned.duplicated(subset=duplicate_key).sum()),
        "blank_cells_preserved_by_column": blanks,
        "columns_preserved": list(cleaned.columns),
        "required_feature_blanks": {
            column: int(cleaned[column].isna().sum())
            for column in REQUIRED_SOURCE_COLUMNS
        },
        "engine_validation": "passed",
        "quality_checks": quality.to_dict(orient="records"),
        "values_filled_or_inferred": 0,
        "source_modified": False,
    }
    validation_output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    summary = create_clean_copy()
    print(json.dumps(summary, indent=2, default=str))
