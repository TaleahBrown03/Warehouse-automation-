# Interview demo notes

Before the interview, run `streamlit run app.py` and leave the sidebar at its defaults
(1.1× usual rate, 3 consecutive days, aged after 3 days). Check that the caption under the title reads
`amazon_sale_report_cleaned.csv` • candidate-deduplicated. All figures below are from that default file.

## Three-minute walkthrough
1. **What it is (20 s).** "This is a small monitoring prototype in Python and pandas with a Streamlit dashboard,
   built on a public Amazon India apparel sales report from spring 2022: about 128,000 order lines. It isn't FreshDirect
   data, it isn't connected to anything live, and it hasn't measured any real improvement. Alerts are prompts for a
   person to investigate; nothing changes automatically."
2. **Data first (35 s).** Point at the caption under the title, then open *Unshipped & data quality*. "Before trusting
   any number I check the data. The raw file is kept unchanged. For analysis I use a derived copy without 959 rows that
   exactly repeat an earlier row. That's an assumption, not proof they're errors: there's no SKU or line number, so I
   keep the removed rows in an audit file. The file also has two date formats and 7,563 blank amounts, which stay
   unknown rather than zero. In the status combinations I check, about 7,000 lines have an order status and a courier
   status that can't both be true. For example, every Merchant cancellation says the courier is 'On the Way', so that
   field can't tell me when an order was cancelled."
3. **Headline measures (30 s).** 14.1% of lines cancelled; 6.6% of shipped Merchant lines returned; 60 lines (52 orders)
   still unshipped three or more days before the assumed snapshot date. "Each rate has a stated denominator. Returns only
   use Merchant lines, because those are the only ones with return statuses. The file has no extraction timestamp, so I
   assume statuses are as of the last order date, June 29. That makes the 60 lines candidates to check, not a confirmed backlog."
4. **The alert (40 s).** Open *Cancellations*. "On eligible days (complete days with at least 200 lines), Merchant
   lines run at 17.5% cancelled and Amazon at 12.7%, so each channel is compared with its own usual rate. That usual rate
   includes the days being assessed, which is a limitation. The rule needs three high days in a row. Merchant was
   at 19.3%, 22.3%, and 21.6% from April 14 to 16: 351 cancelled out of 1,665 lines." Move the slider to 1.15× to show
   that it no longer fires (1.15 × 17.5% ≈ 20.1%, and April 14 was 19.3%): the threshold is a judgement call.
5. **SQL check (25 s).** Open *SQL check*: the same daily cancellation figures from SQLite, matched against pandas.
6. **Improvement workflow (30 s).** "The alert tells me where and when, not why. There are no cancellation
   reasons, and Amazon-fulfilled lines were also above their usual rate on two of those days (April 15 and 16),
   so I'd get reason codes first and then
   observe the Merchant operation. Only after that would I propose a limited, approved pilot with safety and quality
   guardrails. This is a plan; I haven't run a pilot or measured results."

## The main calculations in plain English
- **Order line vs order:** an order with a shirt and trousers is one order and two lines. Status is recorded per line, so rates use lines.
- **Cancellation rate:** cancelled lines divided by all lines.
- **Merchant return rate:** of the Merchant lines that shipped, the share returned, being returned, or rejected by the buyer.
- **Unshipped ≥ N days:** the file was exported once, at an unknown time. Assuming the last order date is "today",
  any line still pending that was ordered N or more days earlier is aged. It is a lead to check, not proof the order is stuck.
- **Repeated high cancellations:** for each channel and eligible day (complete, with at least 200 lines), divide
  cancelled lines by all lines. Compare that with the channel's usual rate: all its cancelled lines on eligible days
  divided by all its lines on those days, including the days being judged. A day at 1.1× or more is "high", and three
  high days in a row on consecutive calendar dates is an alert. If the usual rate is 0, nothing is high.
- **Return hotspot:** a state's Merchant return rate at 1.5× or more of the Merchant average, but only for states
  with at least 250 shipped lines, so a state with one line and one return isn't flagged. If there are no returns, nothing is flagged.
- **Duplicate candidates:** a row identical to an earlier row in every column except the row number. The derived copy
  drops it and keeps the first; the raw file and an audit list of the 959 removed rows are kept.

## The SQL query, line by line
```sql
SELECT order_date,
       COUNT(*) AS order_lines,
       SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled_lines,
       ROUND(100.0 * SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) / COUNT(*), 1) AS cancelled_pct
FROM order_lines
WHERE fulfilment = :fulfilment
  AND order_date BETWEEN :start_date AND :end_date
GROUP BY order_date
ORDER BY order_date;
```
- **FROM order_lines:** read the table, one row per order line.
- **WHERE:** keep one channel and a date range. Filtering happens *before* grouping. `:fulfilment` and the dates
  are parameters that Python fills in, so values are never pasted into the SQL text.
- **GROUP BY order_date:** one bucket per day.
- **COUNT(\*):** lines in each bucket. This is the denominator: every line ordered that day in that channel, cancelled or not.
- **SUM(CASE WHEN … THEN 1 ELSE 0 END):** a conditional count: add 1 for each cancelled line.
- **Dates:** SQLite has no separate date type. The source uses `04-14-22`, which as text would sort
  `01-05-23` before `12-30-22`. Python converts dates to `2022-04-14` before loading, and that format sorts in calendar order,
  so `BETWEEN` and `ORDER BY` work.
- **100.0 instead of 100:** forces decimal division. With whole numbers only, 110 / 550 would come out as 0.
- **ROUND(…, 1):** one decimal place.

Result for Merchant, 2022-04-14 to 04-16: 105 of 544 (19.3%), 113 of 506 (22.3%), 133 of 615 (21.6%).
Over the whole file: 6,788 cancelled of 38,932 Merchant lines (17.4%). The alert's 17.5% baseline differs slightly
because it leaves out the partial first and last days.

## Likely follow-up questions
**Why compare a channel with itself?** Merchant lines are cancelled more often than Amazon-fulfilled lines on 87 of
the 89 eligible days. A single threshold would either flag Merchant constantly or never flag Amazon.

**Isn't the baseline biased?** A little. The usual rate includes the days being judged, so a spike slightly raises
its own baseline. With more history I'd use a prior period, for example the previous 28 days.

**Standard service cancels more than Expedited (17.1% vs 12.7%). Is that a finding?** Not really. Every Merchant
line is Standard and almost every Amazon line is Expedited (88,003 of 89,085), so service level and fulfilment
channel are confounded. The Overview tab shows the cross-tab.

**Why no on-time shipment rate?** The file has no promise or ship dates. I'd need those, with times, to say
whether something shipped late. The closest measure available is "still unshipped after N days".

**How do you know the SQL is right?** The same calculation is in pandas (`daily_cancellations`). The app and the tests
compare them: counts must match exactly, and percentages can differ by at most one rounding step, because SQLite
and pandas round halves differently.

**How would you find aged unshipped orders in SQL?**
`SELECT order_id, order_date FROM order_lines WHERE status IN ('Pending','Pending - Waiting for Pick Up','Shipping') AND order_date <= DATE('2022-06-29', '-3 days');`
(2022-06-29 is the assumed snapshot date, not a known export time.)

**Why remove the duplicates? Couldn't they be real?** They could. A repeated row might be two identical shirts on one
order, and without a SKU or line number I can't tell. So it's a stated assumption, not a correction: the raw file
stays unchanged, the 959 removed rows are listed in an audit file, checksums record exactly which input produced
the copy, and pointing `AMAZON_SALE_REPORT_CSV` at the raw file reruns everything with the rows kept.

**How do you handle bad data?** Problems that make results wrong stop the load with a clear list: missing columns,
unreadable dates, unknown statuses, and quantities that aren't whole numbers of 0 or more (for example 1.9 or
infinity, which would otherwise be silently truncated). Problems that only limit trust are reported in the Data quality table.
Empty input loads fine, and rates show "n/a" instead of dividing by zero. A channel with no cancellations, or
no returns, can't produce an alert just because its baseline is zero.

**What would you need before using this in a real operation?** Order, ship, and promise timestamps, cancellation reason
codes, agreed KPI definitions, thresholds set with the operations team, and floor observation to check that alerts
mean what we think they mean.

## Limitations and sensible next steps
**Limitations:** no ship, promise, or time data; one status snapshot with an assumed date; no cancellation reasons;
conflicting courier status, and conflict checks that cover only selected combinations; duplicate removal that rests on
an assumption; a baseline that includes the days being judged; an unknown seller in apparel, so there's no cold chain.
It's a prototype on public data, not a measured improvement.

**Next steps:**
- Add the aged-unshipped and return-by-state queries to the SQL demo
- Use a prior-period baseline (for example, the previous 28 days) instead of the whole-file average
- With timestamped data: on-time dispatch against promise, and time from order to cancellation
- Track alerts over time: when each was raised, who reviewed it, and what was found
- Agree definitions and thresholds with an operations team before any real use
