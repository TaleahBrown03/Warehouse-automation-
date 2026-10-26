"""Load the order lines into SQLite and check the SQL cancellation report against pandas.

Run:  python sql_demo.py                                  (Merchant, every date, in-memory database)
      python sql_demo.py --fulfilment Amazon --start 2022-05-01 --end 2022-05-07
      python sql_demo.py --db reports/orders.db           (also keeps a database file you can open)
"""
import argparse
import sqlite3
from pathlib import Path
import pandas as pd
from engine import load_data, daily_cancellations, DATA_FILE

QUERY_FILE = Path(__file__).parent / "sql" / "cancellations_by_day.sql"
SQL_COLUMNS = ["order_id","order_date","status","fulfilment","service_level","category","size",
               "courier_status","qty","amount","ship_state"]

def load_into_sqlite(lines, db=":memory:"):
    """Write the cleaned order lines to SQLite with order_date as 'YYYY-MM-DD' text.

    The source file uses MM-DD-YY, which would sort 01-05-23 before 12-30-22. ISO dates sort correctly.
    """
    conn = sqlite3.connect(db)
    out = lines[SQL_COLUMNS].assign(order_date=lines["order_date"].dt.strftime("%Y-%m-%d"))
    out.to_sql("order_lines", conn, if_exists="replace", index=False)
    return conn

def cancellations_by_day(
    conn,
    fulfilment: str = "Merchant",
    start_date: str = "2000-01-01",
    end_date: str = "2100-12-31",
) -> pd.DataFrame:
    params = {"fulfilment": fulfilment, "start_date": str(start_date), "end_date": str(end_date)}
    return pd.read_sql_query(QUERY_FILE.read_text(), conn, params=params)

def reconcile(
    sql_result: pd.DataFrame,
    lines: pd.DataFrame,
    fulfilment: str = "Merchant",
    start_date: str = "2000-01-01",
    end_date: str = "2100-12-31",
) -> tuple[bool, pd.DataFrame]:
    """Return (matches, comparison table) for the SQL result vs the pandas calculation.

    Counts must match exactly. Percentages may differ by one rounding step because SQLite rounds
    halves up and pandas rounds halves to even.
    """
    pandas_result = daily_cancellations(lines, fulfilment)
    pandas_result = pandas_result[pandas_result["order_date"].between(str(start_date), str(end_date))]
    both = sql_result.merge(pandas_result, on="order_date", how="outer", suffixes=("_sql", "_pandas"), indicator=True)
    counts_match = all((both[f"{c}_sql"] == both[f"{c}_pandas"]).all() for c in ["order_lines", "cancelled_lines"])
    pct_match = ((both["cancelled_pct_sql"] - both["cancelled_pct_pandas"]).abs() <= 0.1 + 1e-9).all()
    return bool(both["_merge"].eq("both").all() and counts_match and pct_match), both.drop(columns="_merge")

def main():
    description = __doc__ or "Load the order lines into SQLite and check the SQL cancellation report against pandas."
    parser = argparse.ArgumentParser(description=description.splitlines()[0])
    parser.add_argument("--file", default=DATA_FILE)
    parser.add_argument("--db", default=":memory:")
    parser.add_argument("--fulfilment", default="Merchant", choices=["Merchant","Amazon"])
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--end", default="2100-12-31")
    args = parser.parse_args()
    lines = load_data(args.file)["lines"]
    conn = load_into_sqlite(lines, args.db)
    result = cancellations_by_day(conn, args.fulfilment, args.start, args.end)
    print(QUERY_FILE.read_text())
    print(f"Result for {args.fulfilment} ({len(result)} days):")
    print(result.to_string(index=False))
    total = int(result["order_lines"].sum())
    cancelled = int(result["cancelled_lines"].sum())
    print(f"\nTotal: {cancelled:,} cancelled of {total:,} order lines ({100 * cancelled / total:.1f}%)" if total else "\nNo lines.")
    matches, _ = reconcile(result, lines, args.fulfilment, args.start, args.end)
    print("Reconciliation with pandas:", "MATCH" if matches else "MISMATCH")
    return 0 if matches else 1

if __name__ == "__main__":
    raise SystemExit(main())
