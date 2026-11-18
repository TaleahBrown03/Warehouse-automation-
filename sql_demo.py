"""Load the order lines into SQLite and check the SQL cancellation report against pandas.

Run:  python sql_demo.py                                  (Merchant, every date, in-memory database)
      python sql_demo.py --fulfilment Amazon --start 2022-05-01 --end 2022-05-07
      python sql_demo.py --db reports/orders.db           (also keeps a database file you can open)
"""
import argparse
import sqlite3
from datetime import date
from pathlib import Path
import pandas as pd
from engine import load_data, daily_cancellations, DATA_FILE

QUERY_FILE = Path(__file__).parent / "sql" / "cancellations_by_day.sql"
SQL_COLUMNS = ["order_id","order_date","status","fulfilment","service_level","category","size",
               "courier_status","qty","amount","ship_state"]


def default_date_range(lower: date, upper: date) -> tuple[date, date]:
    """Keep the demo's preferred SQL dates inside the selected dataset's available range."""
    if lower > upper:
        raise ValueError("The lower date bound must not be after the upper date bound.")
    start = min(max(date(2022, 4, 10), lower), upper)
    end = min(max(date(2022, 4, 20), start), upper)
    return start, end


def load_into_sqlite(lines, db=":memory:"):
    """Replace the SQLite table atomically and return its open connection.

    The caller owns and must close the returned connection. Dates are stored as ISO text so they sort
    and compare chronologically.
    """
    conn = sqlite3.connect(db)
    try:
        out = lines[SQL_COLUMNS].assign(order_date=lines["order_date"].dt.strftime("%Y-%m-%d"))
        schema = """
            CREATE TABLE order_lines (
                order_id TEXT NOT NULL,
                order_date TEXT NOT NULL,
                status TEXT NOT NULL,
                fulfilment TEXT NOT NULL,
                service_level TEXT,
                category TEXT,
                size TEXT,
                courier_status TEXT,
                qty INTEGER NOT NULL,
                amount REAL,
                ship_state TEXT
            )
        """
        insert = f"INSERT INTO order_lines ({', '.join(SQL_COLUMNS)}) VALUES ({', '.join('?' for _ in SQL_COLUMNS)})"
        with conn:
            conn.execute("BEGIN")
            conn.execute("DROP TABLE IF EXISTS order_lines")
            conn.execute(schema)

            rows = (
                tuple(
                    None if pd.isna(value) else value.item() if hasattr(value, "item") else value
                    for value in row
                )
                for row in out.itertuples(index=False, name=None)
            )
            conn.executemany(insert, rows)
    except Exception:
        conn.close()
        raise
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
    try:
        result = cancellations_by_day(conn, args.fulfilment, args.start, args.end)
        print(QUERY_FILE.read_text())
        print(f"Result for {args.fulfilment} ({len(result)} days):")
        print(result.to_string(index=False))
        total = int(result["order_lines"].sum())
        cancelled = int(result["cancelled_lines"].sum())
        print(f"\nTotal: {cancelled:,} cancelled of {total:,} order lines ({100 * cancelled / total:.1f}%)" if total else "\nNo lines.")
        matches, _ = reconcile(result, lines, args.fulfilment, args.start, args.end)
    finally:
        conn.close()
    print("Reconciliation with pandas:", "MATCH" if matches else "MISMATCH")
    return 0 if matches else 1

if __name__ == "__main__":
    raise SystemExit(main())
