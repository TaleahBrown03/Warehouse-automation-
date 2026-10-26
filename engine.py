"""Order-fulfilment monitoring for a public Amazon India sales report (order dates 2022-03-31 to 2022-06-29).

One row in the file is one order line. Statuses are a single snapshot taken when the file was
exported. Every alert is a prompt for a person to investigate; nothing here changes inventory,
staffing, orders, or any safety-critical process.
"""
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd

RAW_DATA_FILE = Path(__file__).parent / "data" / "amazon_sale_report.csv"
CLEANED_DATA_FILE = Path(__file__).parent / "data" / "amazon_sale_report_cleaned.csv"
DATA_FILE_ENV = "AMAZON_SALE_REPORT_CSV"
SOURCE_INDEX_COLUMN = "index"  # the source file's row number; not a business field


def resolve_data_file() -> Path:
    """Pick the CSV to analyse: an explicit override, else the repository's deduplicated copy, else its raw file.

    An override is returned as given, even if it does not exist, so a wrong path fails loudly instead of
    another file being analysed in its place. No other location is searched.
    """
    override = os.environ.get(DATA_FILE_ENV)
    if override:
        return Path(override).expanduser()
    return CLEANED_DATA_FILE if CLEANED_DATA_FILE.exists() else RAW_DATA_FILE


def is_deduplicated_copy(path: str | Path) -> bool:
    """True when `path` is the repository's candidate-deduplicated copy; any other file is used as supplied."""
    return Path(path).resolve() == CLEANED_DATA_FILE.resolve()


DATA_FILE = resolve_data_file()

# Source column -> name used in the code. "Sales Channel" is kept as a feature even though it is not
# required to validate or alert on every synthetic test row.
CORE_COLUMNS = {"Order ID":"order_id", "Date":"order_date", "Status":"status", "Fulfilment":"fulfilment",
                "ship-service-level":"service_level", "Category":"category", "Size":"size",
                "Courier Status":"courier_status", "Qty":"qty", "Amount":"amount", "ship-state":"ship_state", "B2B":"b2b"}
OPTIONAL_COLUMNS = {
    "Sales Channel": "sales_channel",
    "ship-city": "ship_city",
    "fulfilled-by": "fulfilled_by",
    "New": "new",
    "PendingS": "pending_s",
}
COLUMNS = {**CORE_COLUMNS, **OPTIONAL_COLUMNS}
MUST_HAVE = ["order_id","order_date","status","fulfilment","qty"]

# Every status in the file, grouped into outcomes an operations team would recognise
OUTCOME_BY_STATUS = {
    "Cancelled":"Cancelled",
    "Pending":"Not shipped yet", "Pending - Waiting for Pick Up":"Not shipped yet", "Shipping":"Not shipped yet",
    "Shipped":"Shipped", "Shipped - Picked Up":"Shipped", "Shipped - Out for Delivery":"Shipped",
    "Shipped - Delivered to Buyer":"Delivered",
    "Shipped - Returned to Seller":"Returned", "Shipped - Returning to Seller":"Returned", "Shipped - Rejected by Buyer":"Returned",
    "Shipped - Lost in Transit":"Lost/Damaged", "Shipped - Damaged":"Lost/Damaged",
}
OUTCOMES = ["Delivered","Shipped","Returned","Lost/Damaged","Not shipped yet","Cancelled"]
SHIPPED_OUTCOMES = {"Delivered","Shipped","Returned","Lost/Damaged"}
FULFILMENT = {"Amazon","Merchant"}

STATE_FIXES = {"RAJSHTHAN":"RAJASTHAN", "RAJSTHAN":"RAJASTHAN", "RJ":"RAJASTHAN", "ORISSA":"ODISHA",
               "PONDICHERRY":"PUDUCHERRY", "NEW DELHI":"DELHI", "PB":"PUNJAB", "PUNJAB/MOHALI/ZIRAKPUR":"PUNJAB",
               "NL":"NAGALAND", "AR":"ARUNACHAL PRADESH", "APO":"UNKNOWN"}

EXCEPTION_COLUMNS = ["exception_type","severity","entity","observed_value","recommended_action"]

class DataValidationError(ValueError):
    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))

@dataclass(frozen=True)
class Thresholds:
    cancel_multiplier: float = 1.1   # a day's cancellation rate vs that channel's usual rate
    min_consecutive: int = 3         # consecutive high days needed before alerting
    min_lines_per_day: int = 200     # ignore channel-days with too few lines to judge
    return_multiplier: float = 1.5   # a state's merchant return rate vs the merchant average
    min_state_lines: int = 250       # shipped merchant lines a state needs before it is compared
    aged_days: int = 3               # days since order date before an unshipped line counts as aged

# ---------- Loading, validation, and data quality ----------

def parse_dates(s):
    """The file mixes MM-DD-YY and MM-DD-YYYY. Anything else stays blank (NaT)."""
    long = pd.to_datetime(s.where(s.str.len() == 10), format="%m-%d-%Y", errors="coerce")
    short = pd.to_datetime(s.where(s.str.len() == 8), format="%m-%d-%y", errors="coerce")
    return long.fillna(short)

def _examples(values, n=3):
    values = list(values)
    return ", ".join(map(str, values[:n])) + (f" (+{len(values) - n} more)" if len(values) > n else "")

def clean(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn the raw file (all columns as text) into typed order lines, or raise with every problem found."""
    missing = [c for c in CORE_COLUMNS if c not in raw.columns]
    if missing:
        raise DataValidationError([f"Missing columns: {', '.join(missing)}"])
    df = raw.loc[:, [c for c in COLUMNS if c in raw.columns]].copy()
    df = df.rename(columns=COLUMNS)
    for source, target in OPTIONAL_COLUMNS.items():
        if target not in df.columns:
            df[target] = pd.NA
    problems: list[str] = []
    for col in MUST_HAVE:
        if bool(df[col].isna().any()):
            problems.append(f"{int(df[col].isna().sum())} line(s) have a blank {col}")
    dates = parse_dates(df["order_date"].fillna(""))
    bad = dates.isna() & df["order_date"].notna()
    if bool(bad.any()):
        problems.append(f"{int(bad.sum())} line(s) have an unreadable date (expected MM-DD-YY or MM-DD-YYYY): "
                        f"{_examples(df.loc[bad, 'order_date'])}")
    unknown = set(df["status"].dropna()) - set(OUTCOME_BY_STATUS)
    if unknown:
        problems.append(f"Unknown status value(s): {_examples(sorted(unknown))}. Add them to OUTCOME_BY_STATUS.")
    unknown = set(df["fulfilment"].dropna()) - FULFILMENT
    if unknown:
        problems.append(f"Unknown fulfilment value(s): {_examples(sorted(unknown))}")
    # Qty must be a whole number of units: "1.9" would otherwise be silently truncated to 1. Blanks are reported above.
    qty = pd.Series(pd.to_numeric(df["qty"], errors="coerce"), index=df.index)
    whole = (qty >= 0) & (qty < float("inf")) & (qty % 1 == 0)
    bad = df["qty"].notna() & ~whole
    if bool(bad.any()):
        problems.append(f"{int(bad.sum())} line(s) have a qty that is not a non-negative whole number "
                        f"(fractional, infinite, negative, or not a number): {_examples(df.loc[bad, 'qty'])}")
    df["qty"] = qty
    amount = pd.Series(pd.to_numeric(df["amount"], errors="coerce"), index=df.index)
    bad = (amount.isna() & df["amount"].notna()) | (amount < 0)
    if bool(bad.any()):
        problems.append(f"{int(bad.sum())} line(s) have an amount that is not a non-negative number")
    df["amount"] = amount
    if problems:
        raise DataValidationError(problems)
    df["order_date"] = dates
    df["qty"] = df["qty"].astype(int)
    df["category"] = df["category"].replace({"Blazzer":"Blazer"})
    df["ship_state"] = df["ship_state"].fillna("UNKNOWN").str.upper().str.strip().replace(STATE_FIXES)
    df["ship_city"] = df["ship_city"].fillna("UNKNOWN").str.upper().str.strip()
    df["sales_channel"] = df["sales_channel"].fillna("UNKNOWN").str.strip()
    df["b2b"] = df["b2b"].str.upper().eq("TRUE")
    df["outcome"] = df["status"].map(OUTCOME_BY_STATUS)
    df["cancelled"] = df["outcome"].eq("Cancelled")
    df["shipped"] = df["outcome"].isin(SHIPPED_OUTCOMES)
    df["returned"] = df["outcome"].eq("Returned")
    return df

def duplicate_candidates(raw: pd.DataFrame) -> pd.Series:
    """Rows identical to an earlier row in every column except the source row index (the first copy is not marked).

    Only candidates: without SKU or order-line identifiers, identical rows may still be genuine separate lines.
    """
    return raw.duplicated(subset=[c for c in raw.columns if c != SOURCE_INDEX_COLUMN], keep="first")

def data_quality(raw: pd.DataFrame, lines: pd.DataFrame) -> pd.DataFrame:
    """Issues that do not stop the analysis but should be known before trusting it."""
    first, last = lines["order_date"].min(), lines["order_date"].max()
    checks = [
        ("Possible duplicate", duplicate_candidates(raw).sum(),
         "Extra copies of a row that is identical in every column except the row index. Kept in this file, because "
         "without a SKU or line number genuine repeat lines can't be told apart."),
        ("Conflict", (lines["status"].eq("Cancelled") & lines["courier_status"].eq("On the Way")).sum(),
         "Status is Cancelled but Courier Status is On the Way"),
        ("Conflict", (lines["shipped"] & lines["courier_status"].isin(["Cancelled","Unshipped"])).sum(),
         "Status is shipped but Courier Status is Cancelled or Unshipped"),
        ("Conflict", ((lines["outcome"] != "Cancelled") & lines["qty"].eq(0)).sum(),
         "Line is not cancelled but quantity is 0"),
        ("Missing value", lines["amount"].isna().sum(), "Blank amount (treated as unknown, not 0)"),
        ("Missing value", lines["ship_state"].eq("UNKNOWN").sum(), "Blank or unusable ship state"),
        ("Partial day", (lines["order_date"] == first).sum(), f"Lines on the first day in the file ({first:%Y-%m-%d}); excluded from daily alerts"),
        ("Partial day", (lines["order_date"] == last).sum(), f"Lines on the last day in the file ({last:%Y-%m-%d}); excluded from daily alerts"),
    ]
    out = pd.DataFrame([{"issue":k, "lines":int(n), "detail":d} for k, n, d in checks])
    filtered = out.loc[out["lines"] > 0].copy()
    return filtered.reset_index(drop=True)

def load_data(path: str | Path = DATA_FILE) -> dict[str, pd.DataFrame]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Put the Amazon sales report CSV there (see README).")
    raw = pd.read_csv(path, dtype=str)
    lines = clean(raw)
    return {"lines":lines, "quality":data_quality(raw, lines) if len(lines) else pd.DataFrame(columns=["issue","lines","detail"])}

# ---------- Calculations shared by the dashboard, reports, and tests ----------

def _rate(numerator: Any, denominator: Any) -> float | None:
    return float(numerator / denominator) if denominator else None


def daily_sales(lines: pd.DataFrame) -> pd.DataFrame:
    """Aggregate order volume, units, and reported amount by order date."""
    columns = ["order_date", "order_lines", "orders", "units", "sales_amount"]
    if lines.empty:
        return pd.DataFrame(columns=columns)
    return (
        lines.groupby("order_date", as_index=False)
        .agg(
            order_lines=("order_id", "size"),
            orders=("order_id", "nunique"),
            units=("qty", "sum"),
            sales_amount=("amount", "sum"),
        )
        .sort_values("order_date")
        .reset_index(drop=True)
    )


def performance_by_dimension(lines: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """Summarize sales and fulfilment outcomes for a supported report dimension."""
    supported = {
        "category", "sales_channel", "service_level", "size", "fulfilment",
        "courier_status", "fulfilled_by",
    }
    if dimension not in supported:
        raise ValueError(f"Unsupported performance dimension: {dimension}")
    columns = [dimension, "order_lines", "orders", "units", "sales_amount", "cancelled_lines", "cancellation_rate"]
    if lines.empty:
        return pd.DataFrame(columns=columns)
    out = (
        lines.groupby(dimension, dropna=False, as_index=False)
        .agg(
            order_lines=("order_id", "size"),
            orders=("order_id", "nunique"),
            units=("qty", "sum"),
            sales_amount=("amount", "sum"),
            cancelled_lines=("cancelled", "sum"),
        )
    )
    out["cancellation_rate"] = out["cancelled_lines"] / out["order_lines"]
    return out.sort_values(["sales_amount", "order_lines"], ascending=False, na_position="last").reset_index(drop=True)[columns]


def customer_segments(lines: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """Aggregate available customer proxies without claiming demographic data."""
    supported = {"sales_channel", "b2b", "ship_state", "ship_city"}
    if dimension not in supported:
        raise ValueError(f"Unsupported customer segment: {dimension}")
    columns = [dimension, "order_lines", "orders", "units", "sales_amount"]
    if lines.empty:
        return pd.DataFrame(columns=columns)
    return (
        lines.groupby(dimension, dropna=False, as_index=False)
        .agg(
            order_lines=("order_id", "size"),
            orders=("order_id", "nunique"),
            units=("qty", "sum"),
            sales_amount=("amount", "sum"),
        )
        .sort_values(["orders", "order_lines"], ascending=False)
        .reset_index(drop=True)[columns]
    )


def inventory_demand(lines: pd.DataFrame) -> pd.DataFrame:
    """Summarize historical ordered units by category and size; this is not stock on hand."""
    columns = ["category", "size", "order_lines", "orders", "units", "sales_amount"]
    if lines.empty:
        return pd.DataFrame(columns=columns)
    return (
        lines.groupby(["category", "size"], dropna=False, as_index=False)
        .agg(
            order_lines=("order_id", "size"),
            orders=("order_id", "nunique"),
            units=("qty", "sum"),
            sales_amount=("amount", "sum"),
        )
        .sort_values(["units", "order_lines"], ascending=False)
        .reset_index(drop=True)
    )


def snapshot_date(lines: pd.DataFrame) -> pd.Timestamp | None:
    """Statuses were exported once. We assume that happened at the end of the last order date in the file."""
    if len(lines) == 0:
        return None
    series = pd.to_datetime(lines["order_date"].dropna())
    max_value = series.max()
    if pd.isna(max_value):
        return None
    return pd.Timestamp(max_value)

def complete_days(lines: pd.DataFrame) -> pd.DataFrame:
    """Drop the first and last order date, which are usually partial days in an export."""
    if lines.empty:
        return lines
    lower = lines["order_date"].min()
    upper = lines["order_date"].max()
    mask = (lines["order_date"] > lower) & (lines["order_date"] < upper)
    return lines.loc[mask].copy()

def daily_cancellations(lines: pd.DataFrame, fulfilment: str | None = None) -> pd.DataFrame:
    """Order lines and cancelled lines per order date. Same logic as sql/cancellations_by_day.sql."""
    cols = ["order_date","order_lines","cancelled_lines","cancelled_pct"]
    df = lines if fulfilment is None else lines[lines["fulfilment"] == fulfilment]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = df.assign(order_date=df["order_date"].dt.strftime("%Y-%m-%d")).groupby("order_date", as_index=False).agg(
        order_lines=("order_id","size"), cancelled_lines=("cancelled","sum"))
    out["cancelled_pct"] = (100 * out["cancelled_lines"] / out["order_lines"]).round(1)
    return out.astype({"order_lines":int, "cancelled_lines":int})[cols]

def channel_days(lines: pd.DataFrame, t: Thresholds) -> pd.DataFrame:
    """Each fulfilment channel's daily cancellation rate compared with that channel's own usual rate.

    Channels behave differently (Merchant lines are cancelled more often than Amazon-fulfilled ones),
    so a channel is only compared with itself. Only complete days with enough lines are judged.
    """
    cols = ["fulfilment","order_date","order_lines","cancelled_lines","cancel_rate","usual_rate","high"]
    df = complete_days(lines)
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = df.groupby(["fulfilment","order_date"], as_index=False).agg(order_lines=("order_id","size"), cancelled_lines=("cancelled","sum"))
    out = out[out["order_lines"] >= t.min_lines_per_day].copy()
    out["cancel_rate"] = out["cancelled_lines"] / out["order_lines"]
    usual = out.groupby("fulfilment")["cancelled_lines"].sum() / out.groupby("fulfilment")["order_lines"].sum()
    out["usual_rate"] = out["fulfilment"].map(usual)
    # With a zero baseline, 0 >= 0 × multiplier would mark every day as high
    out["high"] = ((out["usual_rate"] > 0) & (out["cancel_rate"] > 0)
                   & (out["cancel_rate"] >= out["usual_rate"] * t.cancel_multiplier))
    return out[cols].reset_index(drop=True)

def high_cancellation_runs(lines: pd.DataFrame, t: Thresholds) -> pd.DataFrame:
    """Runs of consecutive calendar days where a channel's cancellation rate stayed high.

    A single bad day does not count. A day that is missing or skipped (too few lines) breaks the run.
    """
    cols = ["fulfilment","first_day","last_day","days","peak_rate","usual_rate","cancelled_lines","order_lines"]
    days = channel_days(lines, t).sort_values(["fulfilment","order_date"])
    if days.empty:
        return pd.DataFrame(columns=cols)
    by = days.groupby("fulfilment")
    continues = by["high"].shift(fill_value=False) & days["high"] & (by["order_date"].diff() == pd.Timedelta(days=1))
    days["run_id"] = (~continues).cumsum()
    runs = days[days["high"]].groupby(["fulfilment","run_id"], as_index=False).agg(
        first_day=("order_date","min"), last_day=("order_date","max"), days=("order_date","size"),
        peak_rate=("cancel_rate","max"), usual_rate=("usual_rate","first"),
        cancelled_lines=("cancelled_lines","sum"), order_lines=("order_lines","sum"))
    return runs.loc[runs["days"] >= t.min_consecutive, cols].reset_index(drop=True)

def merchant_returns_by_state(lines: pd.DataFrame, t: Thresholds) -> pd.DataFrame:
    """Return rate per ship state for shipped Merchant lines.

    The file only records return statuses for Merchant-fulfilled lines, so Amazon-fulfilled lines are left out.
    """
    cols = ["ship_state","shipped_lines","returned_lines","return_rate","flagged"]
    m = lines[lines["fulfilment"].eq("Merchant") & lines["shipped"]]
    if m.empty:
        return pd.DataFrame(columns=cols)
    out = m.groupby("ship_state", as_index=False).agg(shipped_lines=("order_id","size"), returned_lines=("returned","sum"))
    out["return_rate"] = out["returned_lines"] / out["shipped_lines"]
    average = m["returned"].mean()
    # A zero average would otherwise flag every large state, even with no returns at all
    out["flagged"] = ((out["shipped_lines"] >= t.min_state_lines) & (average > 0) & (out["return_rate"] > 0)
                      & (out["return_rate"] >= average * t.return_multiplier))
    return out[cols].sort_values("return_rate", ascending=False).reset_index(drop=True)

def aged_unshipped(lines: pd.DataFrame, t: Thresholds) -> pd.DataFrame:
    """Lines still not shipped at the snapshot and at least t.aged_days old."""
    cols = ["order_id","order_date","age_days","status","fulfilment","category","qty"]
    snap = snapshot_date(lines)
    if snap is None:
        return pd.DataFrame(columns=cols)
    pending = lines[lines["outcome"].eq("Not shipped yet")]
    out = pending.assign(age_days=(snap - pending["order_date"]).dt.days)
    return out.loc[out["age_days"] >= t.aged_days, cols].sort_values("age_days", ascending=False).reset_index(drop=True)

def compute_kpis(lines: pd.DataFrame, t: Thresholds = Thresholds()) -> dict[str, Any]:
    snap = snapshot_date(lines)
    merchant_shipped = lines[lines["fulfilment"].eq("Merchant") & lines["shipped"]]
    return {
        "snapshot_date": None if snap is None else snap.strftime("%Y-%m-%d"),
        "order_lines": int(len(lines)),
        "orders": int(lines["order_id"].nunique()),
        "units_not_cancelled": int(lines.loc[~lines["cancelled"], "qty"].sum()),
        # Denominator for the next two rates: every order line in the file
        "cancellation_rate": _rate(lines["cancelled"].sum(), len(lines)),
        "shipped_rate": _rate(lines["shipped"].sum(), len(lines)),
        # Denominator: shipped Merchant lines, the only lines with return statuses
        "merchant_return_rate": _rate(merchant_shipped["returned"].sum(), len(merchant_shipped)),
        "unshipped_lines": int(lines["outcome"].eq("Not shipped yet").sum()),
        "aged_unshipped_lines": int(len(aged_unshipped(lines, t))),
    }

def detect_exceptions(data: dict[str, pd.DataFrame], t: Thresholds = Thresholds()) -> pd.DataFrame:
    lines = data["lines"]
    rows: list[dict[str, str]] = []
    for _, r in high_cancellation_runs(lines, t).iterrows():
        rows.append({"exception_type":"Repeated high cancellations", "severity":"High", "entity":f"{r['fulfilment']} fulfilment",
                     "observed_value":f"{r['days']} days in a row ({r['first_day']:%Y-%m-%d} to {r['last_day']:%Y-%m-%d}) at or above "
                                      f"{t.cancel_multiplier}× the usual {r['usual_rate']:.1%}; peak {r['peak_rate']:.1%}",
                     "recommended_action":"Review cancellation reasons for those days and observe the fulfilment process before "
                                          "deciding on any change."})
    for _, r in merchant_returns_by_state(lines, t).query("flagged").iterrows():
        rows.append({"exception_type":"Return hotspot", "severity":"Medium", "entity":f"Ship state: {r['ship_state']}",
                     "observed_value":f"{r['return_rate']:.1%} returned of {r['shipped_lines']:,} shipped Merchant lines",
                     "recommended_action":"Check courier performance and address quality for this region before changing carriers."})
    aged = aged_unshipped(lines, t)
    for order_id, g in aged.groupby("order_id", sort=False):
        rows.append({"exception_type":"Aged, not shipped", "severity":"High", "entity":order_id,
                     "observed_value":f"{len(g)} line(s) ordered {g['order_date'].iloc[0]:%Y-%m-%d}, still '{g['status'].iloc[0]}' "
                                      f"{g['age_days'].iloc[0]} days later",
                     "recommended_action":"Locate the order and confirm its real status with the fulfilment team."})
    for _, r in data["quality"].query("issue == 'Conflict'").iterrows():
        rows.append({"exception_type":"Data conflict", "severity":"Medium", "entity":"Source data",
                     "observed_value":f"{r['detail']}: {r['lines']:,} lines",
                     "recommended_action":"Confirm with the system owner which field is correct before relying on either."})
    return pd.DataFrame(rows, columns=EXCEPTION_COLUMNS)

def run_pipeline(path: str | Path = DATA_FILE, t: Thresholds = Thresholds(), report_dir: str | Path = Path(__file__).parent / "reports") -> dict[str, Any]:
    data = load_data(path)
    kpis = compute_kpis(data["lines"], t)
    exceptions = detect_exceptions(data, t)
    out = Path(report_dir)
    out.mkdir(exist_ok=True)
    exceptions.to_csv(out / "exceptions_latest.csv", index=False)
    data["quality"].to_csv(out / "data_quality_latest.csv", index=False)
    pd.DataFrame([{"run_at_utc":datetime.now(timezone.utc).isoformat(), **kpis, **asdict(t)}]).to_csv(out / "kpis_latest.csv", index=False)
    return {"kpis":kpis, "exceptions":exceptions}
