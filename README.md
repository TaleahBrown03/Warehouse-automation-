# Order Fulfilment Monitoring

A small portfolio project: a Python/pandas monitoring pipeline with a Streamlit dashboard and a SQLite SQL
check, built on a **public Amazon India sales report** (order dates 2022-03-31 to 2022-06-29, ~129k order
lines). The project is not connected to FreshDirect, Amazon, or any live system. Every alert is a prompt for
a person to investigate; nothing changes inventory, orders, staffing, purchasing, or safety-critical processes.

## What it does
- Loads and validates the CSV (missing columns, blanks in key fields, unreadable dates, unknown statuses,
  negative or non-numeric quantities and amounts)
- Analyzes sales amount, order volume, product category, sales channel, fulfilment, service level, size, and carrier-status mix
- Shows order segments using the B2B flag and ship-to city/state fields without inferring demographics
- Summarizes historical ordered units by category and size as a demand signal
- Reports data-quality issues that don't stop the analysis: possible duplicates, status conflicts, blank
  amounts, and partial days
- Groups the 13 raw statuses into outcomes (Delivered, Shipped, Returned, Lost/Damaged, Not shipped yet, Cancelled)
- Calculates cancellation, return, and unshipped measures with stated denominators
- Raises exceptions for repeated high-cancellation days, return hotspots by state, orders still unshipped
  after N days, and conflicting source fields
- Runs one SQL report in SQLite (cancellations by day) and checks it against pandas
- Walks through one alert as a human-led improvement plan ([IMPROVEMENT_WORKFLOW.md](IMPROVEMENT_WORKFLOW.md))

## Setup
Python 3.10 or newer. From the project folder:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The project uses `data/amazon_sale_report_cleaned.csv` for analysis when it is newer than the source; otherwise it
prefers the newest attached Amazon sales report CSV and falls back to `data/amazon_sale_report.csv`. The included
source file is ["AmazonSalesReport" by Arpit
Mishra](https://www.kaggle.com/datasets/arpit2712/amazonsalesreport) on Kaggle, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), and is included unchanged. See [data/README.md](data/README.md).

To create a separate deduplicated copy with a validation report, run:

```bash
python clean_report.py
```

This keeps the original file unchanged, retains the `New`, `PendingS`, and `fulfilled-by` columns, preserves
unknown values as blanks, and writes the duplicate candidates to an audit CSV. The dashboard uses this copy
when it is current. It does not invent values or claim the result has no missing data.

## Commands
```bash
streamlit run app.py                                     # open the dashboard
python sql_demo.py                                       # SQL query, result, and pandas reconciliation (Merchant, all dates)
python sql_demo.py --fulfilment Merchant --start 2022-04-10 --end 2022-04-20
python sql_demo.py --db reports/orders.db                # also keep a SQLite file you can open
pytest                                                   # run the tests
```

In the dashboard, **Write report CSVs** saves `reports/exceptions_latest.csv`, `reports/kpis_latest.csv`, and
`reports/data_quality_latest.csv` using the current sidebar settings.

## Core features tracked
- Order ID
- Date
- Status
- Fulfilment
- Sales Channel
- Category
- Ship service level
- Size
- Courier Status
- Qty
- Amount
- Ship state
- Ship-to city
- B2B flag

The CSV supports sales trends, channel/category performance, destination and B2B order segments, and historical
category/size demand analysis. It does not include customer demographics or IDs, SKU-level product identity,
inventory balances, shipping dates, or delivery times, so those cannot be inferred from these features.

## Files
| File | Purpose |
|---|---|
| `engine.py` | Loading, validation, data-quality checks, KPIs, and alert rules. Dashboard, reports, and tests all use these functions |
| `clean_report.py` | Creates a separate deduplicated CSV, duplicate-candidate audit, and validation summary |
| `app.py` | Streamlit dashboard |
| `sql/cancellations_by_day.sql` | The SQL query |
| `sql_demo.py` | Loads the cleaned lines into SQLite, runs the query, and reconciles it with pandas |
| `tests/test_engine.py` | pytest tests: small hand-built cases for each rule and edge case, plus checks on the real file |
| `IMPROVEMENT_WORKFLOW.md` | Plan for investigating the Merchant cancellation alert (also shown in the dashboard) |
| `INTERVIEW_DEMO.md` | Demo script, plain-English explanations, Q&A, and limitations |

## KPI definitions
| KPI | Definition |
|---|---|
| Order lines / orders | Rows in the file / distinct `Order ID`s |
| Cancellation rate | Cancelled lines ÷ all order lines |
| Merchant return rate | Returned, returning, or rejected lines ÷ shipped Merchant lines. Only Merchant lines carry return statuses, so Amazon-fulfilled lines are left out |
| Unshipped ≥ N days | Lines with a Pending / Waiting for Pick Up / Shipping status, ordered at least N days before the snapshot date |
| Snapshot date | The last order date in the file (2022-06-29). Statuses are assumed to be as of the end of that day |
| Cancelled % by day | Cancelled lines ÷ all lines ordered that day in that channel (same in pandas and SQL) |

## Alert rules (defaults; adjustable in the sidebar)
| Alert | Rule |
|---|---|
| Repeated high cancellations | A channel's daily cancellation rate is ≥ 1.1× **that channel's own** usual rate for 3+ consecutive calendar days. Only complete days (not the first or last day of the file) with ≥ 200 lines count. A skipped day breaks the run |
| Return hotspot | A state with ≥ 250 shipped Merchant lines and a return rate ≥ 1.5× the Merchant average |
| Aged, not shipped | One row per order with lines unshipped ≥ 3 days at the snapshot |
| Data conflict | `Status` and `Courier Status` disagree, or a non-cancelled line has quantity 0 |

The Cancellations tab and the exception queue use the same functions (`channel_days`,
`high_cancellation_runs`) with the same thresholds, so they always agree. With the defaults, the cancellation
rule finds two runs: Merchant 2022-04-14 to 04-16 and Amazon 2022-05-02 to 05-04. At 1.15× it finds none.
Thresholds are illustrative.

## Limitations
- **No ship or promise dates and no times.** On-time shipment and late-shipment rates can't be calculated.
  Daily figures are by order date.
- **Statuses are one snapshot.** Recent orders naturally look "not shipped yet". The as-of date is assumed to be the last order date.
- **No cancellation reasons.** The data shows where and when cancellations rose, not why.
- **Conflicting fields.** Every Merchant cancellation has Courier Status "On the Way", so courier status
  can't show where in the process an order was cancelled.
- **Possible duplicates are kept.** There are 959 extra copies of identical rows, but without a SKU column genuine repeat lines can't be told apart.
- **Unknown seller, apparel products.** Patterns describe this file only; there is no cold chain, and nothing here is FreshDirect data.
- The "usual" rate for a channel includes the days being checked. With more history, a prior-period baseline would be better.
