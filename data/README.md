# Data

`amazon_sale_report.csv` is a copy of a publicly shared Amazon India sales report (order dates 2022-03-31 to
2022-06-29, about 129,000 order lines, amounts in INR). It comes from an unknown seller and is used here only to
practise analysis. It is not FreshDirect data, it is not connected to any live system, and nothing in this
project describes a real warehouse's performance.

**Source and licence:** "AmazonSalesReport" by Arpit Mishra on Kaggle,
<https://www.kaggle.com/datasets/arpit2712/amazonsalesreport>, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). `amazon_sale_report.csv` is the unchanged source.
Run `python clean_report.py` from the project root to create `amazon_sale_report_cleaned.csv` as a separate
derived file with a validation summary and an audit of removed duplicate candidates. The dashboard uses the
deduplicated copy when it is newer than the selected source.

**One row = one order line.** An order ID can appear on several lines.

| Column used | Meaning in this project |
|---|---|
| `Order ID` | Order identifier (repeats for multi-line orders) |
| `Date` | Order date, no time. The file mixes `MM-DD-YY` and `MM-DD-YYYY` |
| `Status` | Line status when the file was exported (a single snapshot) |
| `Fulfilment` | `Amazon` (Amazon's fulfilment network) or `Merchant` (the seller ships via Easy Ship) |
| `ship-service-level` | `Expedited` or `Standard`. Every Merchant line is Standard |
| `Courier Status` | Courier-side status. It often disagrees with `Status`; see the Data quality table |
| `Qty`, `Amount` | Units and line amount in INR (amount is blank on 7,800 lines) |
| `Sales Channel` | Sales channel label (for example, Amazon.in) |
| `Category`, `Size` | Product grouping and apparel size; no SKU is available |
| `ship-city`, `ship-state` | Ship-to destination, not customer demographics |
| `B2B` | Business-to-business order flag |

The project loads `Sales Channel`, `ship-city`, `Courier Status`, and `fulfilled-by` for analysis. The deduplicated
copy retains every source column, including `fulfilled-by`, `New`, and `PendingS`. No blank values are filled:
missing amounts and other absent values remain unknown in the derived data. Rows are removed only when every
business field (excluding the source row-index column) exactly matches another row; because there is no SKU,
some identical-looking records could still represent legitimate separate order lines. The original file and
removed duplicate candidates are retained for audit.

There are no ship dates, promise dates, times, cancellation reasons, SKUs, or inventory counts.
