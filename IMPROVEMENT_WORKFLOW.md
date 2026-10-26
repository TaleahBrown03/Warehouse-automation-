# Improvement workflow: Merchant cancellation example

> **This is a plan, not a result.** The pattern below is in a public sales report from an unknown seller.
> I have no access to that operation, its cancellation reasons, or its floor. No pilot has been run and
> no improvement has been measured.

## 1. What triggered the alert
With the default thresholds, the **Repeated high cancellations** rule fires for **Merchant fulfilment,
2022-04-14 to 2022-04-16**: three days in a row at 20.0%, 22.3%, and 21.8% of order lines cancelled, against
Merchant's usual 17.5%. That's 359 cancelled out of 1,681 lines.

The rule compares Merchant only with Merchant's own usual rate, because Merchant lines are cancelled more often than
Amazon-fulfilled ones across the whole file. It needs 3 or more consecutive complete days at or above 1.1× that rate,
so single bad days are not flagged. The threshold is a judgement call: at 1.15× this run does not fire,
because Apr 14 is at exactly 20.0%.

Merchant ("Easy Ship") lines are packed and handed to the courier by the seller's own operation, so they are
the part of this data where warehouse process could plausibly matter.

What the data already says, and what it doesn't:
- The rise is spread across the main categories (Shirt 23%, Blazer 22%, T-shirt 20% in those days), not one product.
- Amazon-fulfilled lines were also higher than usual on Apr 15–16. Something affecting buyers or listings, not only
  the seller's warehouse, is a real possibility.
- Every Merchant cancellation in the file has Courier Status "On the Way". That looks like a recording convention,
  so courier status can't be used to tell when in the process an order was cancelled.
- The file has **no cancellation reason** and no timestamps. The data shows where and when to look, not why.

## 2. What to look at and observe
Before going to the floor, get the information the file lacks:
- Cancellation reasons by day from the seller's order system (buyer-initiated, out of stock, not shipped in time, address)
- How long after ordering each cancellation happened, measured against the dispatch cut-off

Then, if the reasons point at fulfilment, observe a comparable period in the Merchant operation:
- Orders released vs orders packed and handed over, per hour
- Pick failures: items not in the expected location, count mismatches, damaged stock
- Staffing compared with plan, and how a volume spike is handled (Apr 14–16 was a busy period in this data)
- Packing materials, label printing, and courier pickup timing compared with the cut-off

## 3. Possible causes (all still need checking)
- Buyer-side cancellations, such as a promotion or listing issue (supported by Amazon-fulfilled lines also rising)
- Stock not available at the time of order, which would show up as pick failures
- Orders missing the dispatch cut-off during higher volume
- Courier pickup problems
- Something not on this list. The reason codes and observation exist to find it.

## 4. A limited pilot (only once evidence supports a cause)
Example, **if** reason codes and observation show that Merchant cancellations come mainly from items not being found at pick:

- **Change:** with the operations manager's approval, a short daily cycle count of the fastest-selling Merchant
  locations before the first pick wave. Discrepancies are reported to the inventory owner. The count never
  adjusts stock automatically.
- **Scope:** one shift and the top locations only, for an agreed period of about two to four weeks.
- **Comparison:** the same weekdays before the pilot. Record volume, promotions, and staffing changes so they aren't mistaken for the pilot's effect.
- **Decision rights:** operations decides staffing and inventory adjustments. The dashboard only raises the prompt.

## 5. Measures of success (set targets with operations before starting)
- **Primary:** the Merchant cancellation rate (cancelled lines ÷ all Merchant lines), and cancellations whose reason is
  "out of stock" or "not shipped in time"
- **Dispatch:** lines still unshipped after the agreed number of days, and on-time handover to the courier
- **Quality:** merchant return rate (returned ÷ shipped Merchant lines) and mis-pick reports
- **Balancing:** time the counts take away from picking, and whether pick rates fall
- **People and safety:** near misses and incidents during the extra counting, and associate feedback

## 6. Safety and cold-chain guardrails
- Counts follow the existing safety rules for ladders, racking, and equipment. No step is skipped to save time.
- Nothing is adjusted in the stock system without the inventory owner's approval.
- This dataset is apparel, so there is no cold chain. At a grocery site, any change must keep chilled and frozen
  product within the site's existing temperature-control limits and must not leave cold items staged outside
  them for longer than the approved time.
- **Stop rule:** if quality, safety, or dispatch measures get worse, stop the pilot and go back to the current
  method while the team reviews it.

## 7. Sustaining a successful change
- **SOP / standard work:** which locations are counted, when, by whom, how discrepancies are recorded, and who decides on adjustments
- **Training:** counting method and recording for the people doing it, plus a briefing for shift leads
- **Ownership:** a named inventory or shift lead owns the daily count; the engineer owns the data and the review
- **Follow-up:** review the measures at about 30, 60, and 90 days, keep the monitoring rule running, and update the SOP if the process changes
- **If the pilot does not help:** record what was learned and test the next most likely cause
