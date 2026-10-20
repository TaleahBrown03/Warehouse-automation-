from pathlib import Path
import pandas as pd
from datetime import datetime, timezone

def load_data(data_dir="data"):
    p = Path(data_dir)
    orders = pd.read_csv(p / "orders.csv", parse_dates=["created_at","promised_ship_at","actual_ship_at"])
    inventory = pd.read_csv(p / "inventory.csv")
    events = pd.read_csv(p / "workstation_events.csv", parse_dates=["started_at","ended_at"])
    required = {
        "orders": {"order_id","created_at","promised_ship_at","actual_ship_at","status","units_ordered","units_shipped"},
        "inventory": {"sku","location_id","expected_qty","counted_qty","reorder_point"},
        "events": {"event_id","order_id","workstation","started_at","ended_at","units_processed","defects","queue_length"},
    }
    for name, df in [("orders",orders),("inventory",inventory),("events",events)]:
        missing = required[name] - set(df.columns)
        if missing:
            raise ValueError(f"{name}.csv missing columns: {sorted(missing)}")
    if orders["order_id"].duplicated().any():
        raise ValueError("Duplicate order_id values detected")
    if events["event_id"].duplicated().any():
        raise ValueError("Duplicate event_id values detected")
    if (events["ended_at"] < events["started_at"]).any():
        raise ValueError("Events contain negative cycle times")
    if (events[["units_processed","defects","queue_length"]] < 0).any().any():
        raise ValueError("Negative event quantities are invalid")
    return {"orders":orders, "inventory":inventory, "events":events}

def compute_kpis(data):
    orders, inv, events = data["orders"], data["inventory"], data["events"]
    on_time = orders["actual_ship_at"].notna() & (orders["actual_ship_at"] <= orders["promised_ship_at"])
    inv_accuracy = ((inv["counted_qty"] - inv["expected_qty"]) == 0).mean() if len(inv) else 0
    return {
        "orders": int(orders["order_id"].nunique()),
        "on_time_rate": float(on_time.mean()) if len(orders) else 0.0,
        "inventory_accuracy": float(inv_accuracy),
        "units_processed": int(events["units_processed"].sum()),
        "defect_rate": float(events["defects"].sum()/max(events["units_processed"].sum(),1)),
    }

def detect_exceptions(data, queue_threshold=25, cycle_multiplier=1.5, variance_threshold=5):
    events = data["events"].copy()
    inv = data["inventory"].copy()
    orders = data["orders"].copy()
    events["cycle_minutes"] = (events["ended_at"]-events["started_at"]).dt.total_seconds()/60
    rows = []
    network_median = events["cycle_minutes"].median()
    for station, group in events.groupby("workstation"):
        high_queue = int((group["queue_length"] >= queue_threshold).sum())
        median_cycle = float(group["cycle_minutes"].median())
        # Require multiple observations to avoid overreacting to one event
        if high_queue >= 5 and (group["queue_length"] >= queue_threshold).mean() >= .25:
            rows.append({"exception_type":"Sustained queue","severity":"High","entity":station,
                         "observed_value":f"{high_queue} events above {queue_threshold}",
                         "recommended_action":"Review staffing, upstream release rate, and workload balance."})
        if median_cycle > network_median * cycle_multiplier:
            rows.append({"exception_type":"Slow workstation","severity":"Medium","entity":station,
                         "observed_value":f"Median cycle {median_cycle:.1f} min vs network {network_median:.1f} min",
                         "recommended_action":"Check method, travel distance, equipment, and work mix."})
    inv["variance"] = inv["counted_qty"] - inv["expected_qty"]
    for _, row in inv[inv["variance"].abs() >= variance_threshold].iterrows():
        rows.append({"exception_type":"Inventory discrepancy","severity":"High" if abs(row["variance"]) >= 15 else "Medium",
                     "entity":f"{row['sku']} @ {row['location_id']}",
                     "observed_value":f"Variance {int(row['variance']):+d} units",
                     "recommended_action":"Recount location and verify recent movements before adjusting records."})
    for _, row in inv[inv["expected_qty"] <= inv["reorder_point"]].iterrows():
        rows.append({"exception_type":"Reorder risk","severity":"Medium","entity":f"{row['sku']} @ {row['location_id']}",
                     "observed_value":f"On hand {int(row['expected_qty'])}; reorder point {int(row['reorder_point'])}",
                     "recommended_action":"Review demand and replenishment lead time; buyer approval required."})
    late = orders[orders["actual_ship_at"] > orders["promised_ship_at"]]
    for _, row in late.head(50).iterrows():
        rows.append({"exception_type":"Late shipment","severity":"Medium","entity":row["order_id"],
                     "observed_value":f"Shipped {row['actual_ship_at']}; promised {row['promised_ship_at']}",
                     "recommended_action":"Trace order path and identify the stage contributing to delay."})
    return pd.DataFrame(rows, columns=["exception_type","severity","entity","observed_value","recommended_action"])

def run_pipeline(data_dir="data", queue_threshold=25, cycle_multiplier=1.5, variance_threshold=5):
    data = load_data(data_dir)
    kpis = compute_kpis(data)
    exceptions = detect_exceptions(data, queue_threshold, cycle_multiplier, variance_threshold)
    report_dir = Path("reports")
    report_dir.mkdir(exist_ok=True)
    exceptions.to_csv(report_dir / "exceptions_latest.csv", index=False)
    pd.DataFrame([{"run_at_utc":datetime.now(timezone.utc).isoformat(), **kpis}]).to_csv(report_dir / "kpis_latest.csv", index=False)
    return {"kpis":kpis, "exceptions":exceptions}
