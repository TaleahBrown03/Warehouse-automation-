import streamlit as st
import pandas as pd
from pathlib import Path
from engine import run_pipeline, load_data, detect_exceptions, compute_kpis

st.set_page_config(page_title="Smart Warehouse Ops", page_icon="📦", layout="wide")
st.title("📦 Smart Warehouse Flow & Inventory Optimization")
st.caption("Portfolio demo • Synthetic warehouse data • Not connected to any real company's systems")

data_dir = Path("data")
with st.sidebar:
    st.header("Control Center")
    st.write("Run the monitoring pipeline to refresh KPIs and exceptions.")
    run_clicked = st.button("▶ Run automation", type="primary", use_container_width=True)
    st.divider()
    st.subheader("Detection thresholds")
    queue_threshold = st.slider("Queue warning threshold", 10, 50, 25)
    cycle_multiplier = st.slider("Slow cycle-time multiplier", 1.2, 3.0, 1.5, 0.1)
    variance_threshold = st.slider("Inventory variance alert (units)", 3, 25, 5)

if run_clicked:
    result = run_pipeline(data_dir, queue_threshold, cycle_multiplier, variance_threshold)
    st.session_state["pipeline_result"] = result
    st.success(f"Automation completed. {len(result['exceptions'])} exceptions detected.")
    st.rerun()

try:
    data = load_data(data_dir)
    kpis = compute_kpis(data)
    exceptions = detect_exceptions(data, queue_threshold, cycle_multiplier, variance_threshold)
except Exception as exc:
    st.error(f"Could not load data: {exc}")
    st.stop()

a,b,c,d = st.columns(4)
a.metric("Orders monitored", f"{kpis['orders']:,}")
b.metric("On-time shipment rate", f"{kpis['on_time_rate']:.1%}")
c.metric("Inventory accuracy", f"{kpis['inventory_accuracy']:.1%}")
d.metric("Open exceptions", f"{len(exceptions):,}")

tab1, tab2, tab3, tab4 = st.tabs(["Operations overview", "Bottlenecks", "Inventory", "Exceptions"])
with tab1:
    st.subheader("Daily throughput")
    daily = data["events"].assign(event_date=pd.to_datetime(data["events"]["started_at"]).dt.date).groupby("event_date", as_index=False).agg(units_processed=("units_processed","sum"), defects=("defects","sum"))
    st.line_chart(daily.set_index("event_date")[["units_processed"]])
    left,right = st.columns(2)
    with left:
        st.subheader("Station performance")
        station = data["events"].assign(cycle_minutes=(pd.to_datetime(data["events"]["ended_at"])-pd.to_datetime(data["events"]["started_at"])).dt.total_seconds()/60).groupby("workstation", as_index=False).agg(median_cycle_min=("cycle_minutes","median"), avg_queue=("queue_length","mean"), units=("units_processed","sum"))
        st.dataframe(station.round(2), use_container_width=True, hide_index=True)
    with right:
        st.subheader("Order status")
        st.bar_chart(data["orders"]["status"].value_counts())
with tab2:
    st.subheader("Bottleneck candidates")
    station = data["events"].copy()
    station["cycle_minutes"] = (pd.to_datetime(station["ended_at"])-pd.to_datetime(station["started_at"])).dt.total_seconds()/60
    summary = station.groupby("workstation", as_index=False).agg(median_cycle_min=("cycle_minutes","median"), avg_queue=("queue_length","mean"), high_queue_events=("queue_length", lambda x: int((x >= queue_threshold).sum())))
    baseline = summary["median_cycle_min"].median()
    summary["cycle_vs_network_median"] = (summary["median_cycle_min"]/baseline).round(2)
    summary["flagged"] = (summary["avg_queue"] >= queue_threshold) | (summary["cycle_vs_network_median"] >= cycle_multiplier)
    st.dataframe(summary.sort_values(["flagged","avg_queue"], ascending=False), use_container_width=True, hide_index=True)
    st.info("Recommendation: validate sustained queue and cycle-time patterns, then test workload balancing. A flag is a prompt for investigation, not an automatic operational change.")
with tab3:
    st.subheader("Inventory health")
    inv = data["inventory"].copy()
    inv["variance"] = inv["counted_qty"] - inv["expected_qty"]
    inv["low_stock"] = inv["expected_qty"] <= inv["reorder_point"]
    x,y,z = st.columns(3)
    x.metric("SKUs monitored", len(inv))
    y.metric("Low-stock SKUs", int(inv["low_stock"].sum()))
    z.metric("Count variances", int((inv["variance"].abs() >= variance_threshold).sum()))
    st.dataframe(inv.sort_values("variance", key=lambda s: s.abs(), ascending=False), use_container_width=True, hide_index=True)
with tab4:
    st.subheader("Exception queue")
    if exceptions.empty:
        st.success("No exceptions under the selected thresholds.")
    else:
        st.dataframe(exceptions, use_container_width=True, hide_index=True)
    if st.button("Export exceptions CSV"):
        out = exceptions.to_csv(index=False).encode("utf-8")
        st.download_button("Download exceptions.csv", out, "exceptions.csv", "text/csv")
st.caption("All records and metrics are synthetic. Validate definitions and thresholds before using this pattern in a real operation.")
