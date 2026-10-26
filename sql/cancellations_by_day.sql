-- Order lines and cancelled lines per order date for one fulfilment channel.
-- Denominator: every order line placed that day in that channel (cancelled or not).
-- order_date is stored as 'YYYY-MM-DD' text, so BETWEEN and ORDER BY follow calendar order.
SELECT
    order_date,
    COUNT(*)                                                    AS order_lines,
    SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END)       AS cancelled_lines,
    ROUND(100.0 * SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) / COUNT(*), 1) AS cancelled_pct
FROM order_lines
WHERE fulfilment = :fulfilment
  AND order_date BETWEEN :start_date AND :end_date
GROUP BY order_date
ORDER BY order_date;
