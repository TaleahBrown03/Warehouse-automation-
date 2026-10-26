# Interview demo notes

Before the interview, run `streamlit run app.py` and leave the sidebar at its defaults
(1.1× usual rate, 3 consecutive days, aged after 3 days).

## Three-minute walkthrough
1. **What it is (20 s).** "This is a small monitoring pipeline in Python and pandas with a Streamlit dashboard,
   built on a public Amazon India sales report: about 129,000 order lines from spring 2022. It isn't FreshDirect
   data and it isn't connected to anything live. Alerts are prompts for a person to investigate; nothing changes automatically."
2. **Data first (35 s).** Open *Unshipped & data quality*. "Before trusting any number I check the data:
   two date formats, 7,800 blank amounts, 959 possible duplicates, and about 7,000 lines where the order status
   and the courier status disagree. Every Merchant cancellation says the courier is 'On the Way', so that
   field can't tell me when an order was cancelled."
3. **Headline measures (30 s).** 14.2% of lines cancelled; 6.6% of shipped Merchant lines returned; 60 lines still
   unshipped three or more days after ordering. "Each rate has a stated denominator. Returns only use Merchant
   lines, because those are the only ones with return statuses."
4. **The alert (40 s).** Open *Cancellations*. "Merchant lines normally run at 17.5% cancelled and Amazon at 12.8%,
   so each channel is compared with its own usual rate. The rule needs three high days in a row. Merchant was
   at 20.0%, 22.3%, and 21.8% from April 14 to 16." Mention that at 1.15× it doesn't fire: the threshold is a judgement call.
5. **SQL check (25 s).** Open *SQL check*: the same daily cancellation figures from SQLite, matched against pandas.
6. **Improvement workflow (30 s).** "The alert tells me where and when, not why. There are no cancellation
   reasons, and Amazon-fulfilled lines also rose on two of those days, so I'd get reason codes first and then
   observe the Merchant operation. Only after that would I propose a limited, approved pilot with safety and quality
   guardrails. This is a plan; I haven't run a pilot or measured results."

## The main calculations in plain English
- **Order line vs order:** an order with a shirt and trousers is one order and two lines. Status is recorded per line, so rates use lines.
- **Cancellation rate:** cancelled lines divided by all lines.
- **Merchant return rate:** of the Merchant lines that shipped, the share returned, being returned, or rejected by the buyer.
- **Unshipped ≥ N days:** the file was exported once. Taking the last order date as "today", any line still
  pending that was ordered N or more days earlier is aged.
- **Repeated high cancellations:** for each channel and complete day, divide cancelled lines by all lines.
  Compare that with the channel's usual rate across all complete days. A day at 1.1× or more is "high", and three
  high days in a row on consecutive calendar dates is an alert.
- **Return hotspot:** a state's Merchant return rate at 1.5× or more of the Merchant average, but only for states
  with at least 250 shipped lines, so a state with one line and one return isn't flagged.

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

Result for Merchant, 2022-04-14 to 04-16: 110 of 550 (20.0%), 113 of 507 (22.3%), 136 of 624 (21.8%).
Over the whole file: 6,859 cancelled of 39,263 Merchant lines (17.5%).

## Likely follow-up questions
**Why compare a channel with itself?** Merchant lines are cancelled more often than Amazon-fulfilled lines on almost
every day. A single threshold would either flag Merchant constantly or never flag Amazon.

**Standard service cancels more than Expedited. Is that a finding?** Not really. Every Merchant line is Standard
and almost every Amazon line is Expedited, so service level and fulfilment channel are confounded. The Overview
tab shows the cross-tab.

**Why no on-time shipment rate?** The file has no promise or ship dates. I'd need those, with times, to say
whether something shipped late. The closest measure available is "still unshipped after N days".

**How do you know the SQL is right?** The same calculation is in pandas (`daily_cancellations`). The app and the tests
compare them: counts must match exactly, and percentages can differ by at most one rounding step, because SQLite
and pandas round halves differently.

**How would you find aged unshipped orders in SQL?**
`SELECT order_id, order_date FROM order_lines WHERE status IN ('Pending','Pending - Waiting for Pick Up','Shipping') AND order_date <= DATE('2022-06-29', '-3 days');`

**Why keep the duplicates?** They might be real repeat lines (two identical shirts on one order). Without a SKU
or line number I can't tell, so I report the count rather than silently drop rows.

**How do you handle bad data?** Problems that make results wrong stop the load with a clear list: missing columns,
unreadable dates, unknown statuses, negative quantities. Problems that only limit trust are reported in the Data quality table.
Empty input loads fine, and rates show "n/a" instead of dividing by zero.

**What would you need before using this in a real operation?** Order, ship, and promise timestamps, cancellation reason
codes, agreed KPI definitions, thresholds set with the operations team, and floor observation to check that alerts
mean what we think they mean.

## Limitations and sensible next steps
**Limitations:** no ship, promise, or time data; one status snapshot; no cancellation reasons; conflicting courier
status; possible duplicates; an unknown seller in apparel, so there's no cold chain.

**Next steps:**
- Add the aged-unshipped and return-by-state queries to the SQL demo
- Use a prior-period baseline (for example, the previous 28 days) instead of the whole-file average
- With timestamped data: on-time dispatch against promise, and time from order to cancellation
- Track alerts over time: when each was raised, who reviewed it, and what was found
- Agree definitions and thresholds with an operations team before any real use
