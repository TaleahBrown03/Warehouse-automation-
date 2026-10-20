# Smart Warehouse Flow & Inventory Optimization

A portfolio project that combines a Python monitoring pipeline with a Streamlit operations dashboard. It uses synthetic distribution-center data and is not connected to Amazon, FreshDirect, or any real warehouse.

## Features
- CSV ingestion and basic data-quality checks
- KPI calculation for on-time shipment rate, inventory accuracy, throughput, and defect rate
- Exception detection for sustained queues, slow workstations, inventory discrepancies, reorder risk, and late shipments
- Configurable thresholds in the dashboard
- Exportable exception queue and CSV reports
- Synthetic sample dataset for repeatable demos

## Run locally
Python 3.10+ recommended.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Click **Run automation** in the sidebar. The latest exception and KPI CSV files are written to `reports/`.

## Data
- `data/orders.csv`: synthetic orders and promised/actual shipment timestamps
- `data/inventory.csv`: synthetic SKU/location stock and count values
- `data/workstation_events.csv`: synthetic workstation processing events, queues, and defects

## KPI definitions
- **On-time shipment rate:** share of sample orders whose actual shipment timestamp is at or before the promise timestamp.
- **Inventory accuracy:** share of SKU rows where counted quantity equals expected quantity exactly.
- **Throughput:** total units recorded across workstation events. Because each order visits multiple stations, this is station workload, not unique customer units shipped.
- **Defect rate:** defects recorded divided by units processed across all station events. This is a simple demo measure; a production definition would need to avoid double-counting.

## Important limitations
This is a prototype. Thresholds are illustrative, the data are fictional, and exceptions are recommendations for human review. The system does not adjust inventory, place orders, change staffing, or make autonomous safety-critical decisions. Validate KPI definitions, alert logic, and thresholds before real use.

## Next upgrades
- Add SQLite/SQLAlchemy persistence and a FastAPI service
- Add pytest coverage and GitHub Actions
- Add Power BI report connected to exported KPI/exception tables
- Add a controlled before/after experiment and report measured results
