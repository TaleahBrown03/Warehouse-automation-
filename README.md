# Order Fulfilment Monitoring

A small portfolio prototype: a Python/pandas monitoring pipeline with a Streamlit dashboard and a SQLite SQL
check, built on a **public Amazon India apparel sales report** (order dates 2022-03-31 to 2022-06-29). The raw
file has 128,976 rows; the default analysis uses a derived copy with 128,017 order lines after removing 959
duplicate candidates. It is not FreshDirect data, it is not connected to Amazon or any live warehouse system, and
it does not measure any business improvement. Every alert is a prompt for a person to investigate; nothing changes
inventory, orders, staffing, purchasing, or safety-critical processes.

## What it does
- Loads and validates the CSV (missing columns, blanks in key fields, unreadable dates, unknown statuses,
  quantities that are not non-negative whole numbers, negative or non-numeric amounts)
- Analyzes sales amount, order volume, product category, sales channel, fulfilment, service level, size, and carrier-status mix
- Shows order segments using the B2B flag and ship-to city/state fields without inferring demographics
- Summarizes historical ordered units by category and size as a demand signal
- Reports data-quality issues that don't stop the analysis: possible duplicates (when the raw file is used),
  selected status conflicts, blank amounts, and partial days
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

**Which file is analysed.** The choice is fixed and predictable:
1. If the `AMAZON_SALE_REPORT_CSV` environment variable is set, that file is used exactly as given. If it does not
   exist, the app stops with an error rather than switching to another file.
2. Otherwise `data/amazon_sale_report_cleaned.csv` (the candidate-deduplicated copy), if it exists.
3. Otherwise `data/amazon_sale_report.csv` (the raw source).

No other folder is searched. The dashboard shows the file name and whether it is raw or candidate-deduplicated.
`sql_demo.py --file <path>` also accepts an explicit file.

The included source file is ["AmazonSalesReport" by Arpit
Mishra](https://www.kaggle.com/datasets/arpit2712/amazonsalesreport) on Kaggle, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), and is included unchanged. See [data/README.md](data/README.md).

To rebuild the candidate-deduplicated copy and its validation report from `data/amazon_sale_report.csv`, run:

```bash
python clean_report.py
```

The raw source is never changed. A row is removed from the copy only when it is identical to an earlier row in every
column except the source row index (`index`); the first occurrence is kept. This is an **assumption**: without a SKU
or order-line ID, two identical rows could still be two genuine lines (for example, two of the same shirt), so the
959 removed rows are kept in `reports/amazon_sale_report_duplicate_candidates.csv` for audit. Every retained row is
written byte-for-byte as it appears in the source: no header is renamed, no value is changed, and blanks stay blank.
The copy is validated before it replaces the previous one, and `data/amazon_sale_report_validation.json` records the
input file name, SHA-256 checksums of the source and output, row counts, the rule, and the number of candidates removed.
A test checks that the committed copy still equals the source minus those candidates.

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
| `clean_report.py` | Creates the candidate-deduplicated CSV, duplicate-candidate audit, and validation summary from the raw source |
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
| Unshipped ≥ N days | Lines with a Pending / Waiting for Pick Up / Shipping status, ordered at least N days before the snapshot date. These are candidates to investigate, not a confirmed live backlog |
| Snapshot date | An **assumption**: the last order date in the file (2022-06-29). The file has no extraction timestamp, so statuses are assumed to be as of the end of that day |
| Cancelled % by day | Cancelled lines ÷ all lines ordered that day in that channel (same in pandas and SQL) |

## Alert rules (defaults; adjustable in the sidebar)
| Alert | Rule |
|---|---|
| Repeated high cancellations | A channel's daily cancellation rate is ≥ 1.1× **that channel's own** usual rate for 3+ consecutive calendar days. The usual rate is pooled over that channel's eligible days: complete days (not the first or last day of the file) with ≥ 200 lines, **including the days being assessed**. Only those days are judged, and a skipped day breaks the run. A day is never high when the usual rate or the day's own rate is 0 |
| Return hotspot | A state with ≥ 250 shipped Merchant lines and a return rate ≥ 1.5× the Merchant average. Nothing is flagged when the average or the state's rate is 0 |
| Aged, not shipped | One row per order with lines unshipped ≥ 3 days at the assumed snapshot |
| Data conflict | Selected incompatible combinations only: `Status` is Cancelled but `Courier Status` is On the Way; `Status` is shipped but `Courier Status` is Cancelled or Unshipped; or a non-cancelled line has quantity 0. Other disagreements are not checked |

The Cancellations tab and the exception queue use the same functions (`channel_days`,
`high_cancellation_runs`) with the same thresholds, so they always agree. With the defaults on the default data,
the eligible-day usual rates are 17.5% for Merchant and 12.7% for Amazon, and the cancellation rule finds two runs:
Merchant 2022-04-14 to 04-16 (351 cancelled of 1,665 lines) and Amazon 2022-05-02 to 05-04 (691 of 4,740).
At 1.15× it finds none. Thresholds are illustrative.

## Limitations
- **No ship or promise dates and no times.** On-time shipment and late-shipment rates can't be calculated.
  Daily figures are by order date.
- **Statuses are one snapshot, and its date is assumed.** The last order date (2022-06-29) is used as the status
  date; it is not a verified extraction timestamp. Recent orders naturally look "not shipped yet", and the 60 aged
  unshipped lines are investigation candidates, not a confirmed live backlog.
- **No cancellation reasons.** The data shows where and when cancellations rose, not why.
- **Conflicting fields.** Every Merchant cancellation has Courier Status "On the Way", so courier status
  can't show where in the process an order was cancelled. The conflict checks cover selected incompatible
  combinations, not every possible disagreement.
- **Duplicate removal is an assumption.** The default copy drops 959 rows that exactly repeat an earlier row. Without
  a SKU or line number, some could be genuine repeat lines. The raw file and the removed rows are both kept; set
  `AMAZON_SALE_REPORT_CSV=data/amazon_sale_report.csv` to analyse the raw file instead.
- **Unknown seller, apparel products.** Patterns describe this file only; there is no cold chain, and nothing here is FreshDirect data.
- The "usual" rate for a channel includes the days being checked. With more history, a prior-period baseline would be better.
