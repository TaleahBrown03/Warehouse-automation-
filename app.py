from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from engine import (CLEANED_DATA_FILE, DATA_FILE, OUTCOMES, DataValidationError, Thresholds, aged_unshipped,
                    channel_days, complete_days, compute_kpis, customer_segments, daily_cancellations,
                    daily_sales, detect_exceptions, high_cancellation_runs, inventory_demand, load_data,
                    merchant_returns_by_state, performance_by_dimension, run_pipeline)
from sql_demo import load_into_sqlite, cancellations_by_day, reconcile, QUERY_FILE

APP_DIR = Path(__file__).parent

st.set_page_config(page_title="Order Fulfilment Monitoring", page_icon="📦", layout="wide")
st.title("📦 Order Fulfilment Monitoring")
st.caption("Portfolio demo • Public Amazon India sales report (order dates 2022-03-31 to 2022-06-29) • "
           "Not connected to FreshDirect, Amazon, or any live system")
if DATA_FILE == CLEANED_DATA_FILE:
    st.caption("Using the validated deduplicated copy. Missing source values are preserved as unknown, not filled.")

@st.cache_data(show_spinner="Loading order lines…")
def cached_data(path):
    return load_data(path)

def pct(x):
    return "n/a" if x is None else f"{x:.1%}"

with st.sidebar:
    st.header("Control Center")
    st.subheader("Detection thresholds")
    t = Thresholds(
        cancel_multiplier=st.slider("High cancellation day (× channel's usual rate)", 1.05, 1.5, Thresholds.cancel_multiplier, 0.01),
        min_consecutive=st.slider("Consecutive high days needed", 2, 7, Thresholds.min_consecutive),
        return_multiplier=st.slider("Return hotspot (× merchant average)", 1.1, 3.0, Thresholds.return_multiplier, 0.1),
        aged_days=st.slider("Aged unshipped after (days)", 1, 14, Thresholds.aged_days),
    )
    st.divider()
    run_clicked = st.button("Write report CSVs", type="primary", width="stretch")

try:
    data = cached_data(DATA_FILE)
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()
except DataValidationError as exc:
    st.error("The data did not pass validation. Fix these problems and reload:")
    st.markdown("\n".join(f"- {p}" for p in exc.problems))
    st.stop()

if run_clicked:
    result = run_pipeline(DATA_FILE, t, APP_DIR / "reports")
    st.toast(f"Wrote reports/ with {len(result['exceptions'])} exceptions.")

lines = data["lines"]
kpis = compute_kpis(lines, t)
exceptions = detect_exceptions(data, t)

a,b,c,d,e = st.columns(5)
a.metric("Order lines", f"{kpis['order_lines']:,}", help=f"{kpis['orders']:,} distinct orders. One order can have several lines.")
b.metric("Cancellation rate", pct(kpis["cancellation_rate"]), help="Cancelled order lines ÷ all order lines")
c.metric("Merchant return rate", pct(kpis["merchant_return_rate"]),
         help="Returned or rejected lines ÷ shipped Merchant lines. Only Merchant lines carry return statuses.")
d.metric(f"Unshipped ≥ {t.aged_days} days", f"{kpis['aged_unshipped_lines']:,}",
         help=f"Lines still pending at the snapshot ({kpis['snapshot_date']}) and ordered at least {t.aged_days} days earlier. "
              f"{kpis['unshipped_lines']:,} lines are unshipped in total.")
e.metric("Open exceptions", f"{len(exceptions):,}")
st.caption(f"Statuses are a single snapshot from when the file was exported, assumed to be the end of {kpis['snapshot_date']}. "
           "Daily figures are by order date; the file has no ship dates or times.")

tab1, tab_sales, tab_customers, tab_inventory, tab_fulfilment, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["Overview", "Sales analysis", "Customer insights", "Inventory demand", "Fulfilment details",
     "Cancellations", "Returns by state", "Unshipped & data quality", "Exceptions", "SQL check", "Improvement workflow"]
)
with tab1:
    left,right = st.columns(2)
    with left:
        st.subheader("Order lines by day")
        daily = complete_days(lines).groupby(["order_date","fulfilment"]).size().unstack()
        st.line_chart(daily)
        st.caption("First and last days of the file are left out because they are partial.")
    with right:
        st.subheader("Outcome of each line at the snapshot")
        st.bar_chart(lines["outcome"].value_counts().reindex(OUTCOMES, fill_value=0), horizontal=True)
    st.subheader("Lines by fulfilment channel and service level")
    combo = lines.groupby(["fulfilment","service_level"], as_index=False).agg(order_lines=("order_id","size"), cancel_rate=("cancelled","mean"))
    st.dataframe(combo, hide_index=True, column_config={"cancel_rate":st.column_config.NumberColumn("Cancellation rate", format="percent")})
    st.caption("Every Merchant line is Standard service, so Standard vs Expedited differences are mostly Merchant vs Amazon differences.")
    st.subheader("Sales channel mix")
    if "sales_channel" in lines.columns:
        st.bar_chart(lines["sales_channel"].value_counts().head(10))
    else:
        st.info("This dataset snapshot does not include a Sales Channel column.")
with tab_sales:
    st.subheader("Sales and order trends")
    trends = daily_sales(lines).set_index("order_date")
    if trends.empty:
        st.info("No order rows are available for the selected data.")
    else:
        left, right = st.columns(2)
        with left:
            st.caption("Order lines and distinct orders by order date")
            st.line_chart(trends[["order_lines", "orders"]])
        with right:
            st.caption("Reported sales amount by order date (INR; blank amounts excluded)")
            st.line_chart(trends[["sales_amount"]])

    st.subheader("Performance by product category")
    category_performance = performance_by_dimension(lines, "category")
    st.dataframe(category_performance, hide_index=True, column_config={
        "sales_amount": st.column_config.NumberColumn("Reported amount (INR)", format="₹%.2f"),
        "cancellation_rate": st.column_config.NumberColumn("Cancellation rate", format="percent"),
    })
    st.subheader("Marketing channel performance")
    channel_performance = performance_by_dimension(lines, "sales_channel")
    st.dataframe(channel_performance, hide_index=True, column_config={
        "sales_amount": st.column_config.NumberColumn("Reported amount (INR)", format="₹%.2f"),
        "cancellation_rate": st.column_config.NumberColumn("Cancellation rate", format="percent"),
    })
with tab_customers:
    st.subheader("Available customer and destination segments")
    st.caption("The report has no customer demographics or customer IDs. These are order segments and shipping destinations, not demographic profiles.")
    st.markdown("**Business-to-business flag**")
    st.dataframe(customer_segments(lines, "b2b"), hide_index=True)
    left, right = st.columns(2)
    with left:
        st.markdown("**Orders by destination state**")
        st.dataframe(customer_segments(lines, "ship_state").head(20), hide_index=True)
    with right:
        st.markdown("**Orders by destination city**")
        st.dataframe(customer_segments(lines, "ship_city").head(20), hide_index=True)
    st.markdown("**Sales channel segments**")
    st.dataframe(customer_segments(lines, "sales_channel"), hide_index=True)
with tab_inventory:
    st.subheader("Historical product demand by category and size")
    demand = inventory_demand(lines)
    st.caption("Ordered units and lines are historical demand proxies. The CSV has no SKU, inventory balance, or replenishment data.")
    if demand.empty:
        st.info("No order rows are available for the selected data.")
    else:
        category_demand = (
            demand.groupby("category", as_index=False)["units"]
            .sum()
            .sort_values("units", ascending=False)
            .head(15)
            .set_index("category")
        )
        st.bar_chart(category_demand)
        st.dataframe(demand, hide_index=True, column_config={
            "sales_amount": st.column_config.NumberColumn("Reported amount (INR)", format="₹%.2f"),
        })
with tab_fulfilment:
    st.subheader("Fulfilment method and shipping service")
    st.dataframe(performance_by_dimension(lines, "fulfilment"), hide_index=True)
    st.dataframe(performance_by_dimension(lines, "service_level"), hide_index=True)
    st.subheader("Fulfilled by")
    st.dataframe(performance_by_dimension(lines, "fulfilled_by"), hide_index=True)
    st.caption("Blank fulfilled-by values are preserved from the source; they are not filled with inferred values.")
    st.subheader("Source placeholder columns")
    st.caption(
        f"New: {int(lines['new'].notna().sum()):,} populated values; "
        f"PendingS: {int(lines['pending_s'].notna().sum()):,} populated values. "
        "Both columns are retained as supplied by the source."
    )
    st.subheader("Order status")
    status_counts = lines["status"].value_counts().rename_axis("status").rename("order_lines")
    st.bar_chart(status_counts)
    st.subheader("Carrier status")
    courier_counts = lines["courier_status"].fillna("Unknown").value_counts().rename_axis("courier_status").rename("order_lines")
    st.bar_chart(courier_counts)
    st.caption("Carrier status is a snapshot field, not a timestamped transit history. Delivery time and on-time performance cannot be calculated.")
with tab2:
    st.subheader("Daily cancellation rate vs each channel's usual rate")
    days = channel_days(lines, t)
    st.line_chart(days.pivot(index="order_date", columns="fulfilment", values="cancel_rate"))
    st.caption(f"A day is high when its rate is at least {t.cancel_multiplier}× that channel's usual rate (complete days with "
               f"≥ {t.min_lines_per_day} lines only). An alert needs {t.min_consecutive}+ high days in a row; a single bad day is not flagged.")
    st.markdown("**Repeated high cancellation runs**")
    runs = high_cancellation_runs(lines, t)
    if runs.empty:
        st.write("None under the current thresholds.")
    else:
        st.dataframe(runs, hide_index=True, column_config={
            "peak_rate":st.column_config.NumberColumn(format="percent"), "usual_rate":st.column_config.NumberColumn(format="percent")})
    with st.expander("All channel-days"):
        st.dataframe(days, hide_index=True)
with tab3:
    st.subheader("Merchant return rate by ship state")
    st.dataframe(merchant_returns_by_state(lines, t), hide_index=True,
                 column_config={"return_rate":st.column_config.NumberColumn(format="percent")})
    st.caption(f"Flagged: at least {t.min_state_lines} shipped Merchant lines and a return rate ≥ {t.return_multiplier}× the "
               "Merchant average. Small states can show high rates by chance, so they are listed but not flagged.")
with tab4:
    st.subheader(f"Lines unshipped for {t.aged_days}+ days at the snapshot")
    st.dataframe(aged_unshipped(lines, t), hide_index=True)
    st.subheader("Data quality")
    st.dataframe(data["quality"], hide_index=True)
    st.caption("These issues do not stop the analysis, but each one changes how far the numbers can be trusted.")
with tab5:
    st.subheader("Exception queue")
    if exceptions.empty:
        st.success("No exceptions under the selected thresholds.")
    else:
        st.dataframe(exceptions, hide_index=True)
    st.download_button("Download exceptions.csv", exceptions.to_csv(index=False).encode("utf-8"), "exceptions.csv", "text/csv")
with tab6:
    st.subheader("Cancellations by day in SQLite")
    left, mid, right = st.columns(3)
    fulfilment = left.selectbox("Fulfilment", ["Merchant","Amazon"])
    valid_dates = lines["order_date"].dropna()
    if valid_dates.empty:
        lo = date(2022, 1, 1)
        hi = date(2022, 12, 31)
    else:
        lo = valid_dates.min().date()
        hi = valid_dates.max().date()
    start = mid.date_input("Start date", value=date(2022, 4, 10), min_value=lo, max_value=hi)
    end = right.date_input("End date", value=date(2022, 4, 20), min_value=lo, max_value=hi)
    st.code(QUERY_FILE.read_text(), language="sql")
    sql_result = cancellations_by_day(load_into_sqlite(lines), fulfilment, str(start), str(end))
    st.dataframe(sql_result, hide_index=True)
    matches, comparison = reconcile(sql_result, lines, fulfilment, str(start), str(end))
    if matches:
        st.success("SQL result matches the pandas calculation (engine.daily_cancellations).")
    else:
        st.error("SQL and pandas results differ:")
    with st.expander("Side-by-side comparison"):
        st.dataframe(comparison, hide_index=True)
with tab7:
    st.markdown("**Current repeated-high-cancellation alerts (live, using the sidebar thresholds)**")
    if runs.empty:
        st.write("None under the current thresholds.")
    else:
        st.dataframe(runs, hide_index=True)
    st.markdown((APP_DIR / "IMPROVEMENT_WORKFLOW.md").read_text())
st.caption("Alerts are recommendations for human review. The system does not change inventory, orders, staffing, "
           "purchasing, or safety-critical processes.")
