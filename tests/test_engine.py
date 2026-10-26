import json
import pandas as pd
import pytest
import engine
from engine import (clean, load_data, data_quality, compute_kpis, detect_exceptions, daily_cancellations, channel_days,
                    high_cancellation_runs, merchant_returns_by_state, aged_unshipped, daily_sales,
                    performance_by_dimension, customer_segments, inventory_demand, run_pipeline, resolve_data_file,
                    is_deduplicated_copy, duplicate_candidates, Thresholds, DataValidationError, COLUMNS,
                    CLEANED_DATA_FILE, RAW_DATA_FILE)
from sql_demo import load_into_sqlite, cancellations_by_day, reconcile
from clean_report import create_clean_copy, read_as_text, sha256, VALIDATION_FILE

LINE = {"Order ID":"O1", "Date":"04-10-22", "Status":"Shipped", "Fulfilment":"Merchant", "ship-service-level":"Standard",
        "Category":"Shirt", "Size":"M", "Courier Status":"Shipped", "Qty":"1", "Amount":"500", "ship-state":"KERALA", "B2B":"FALSE"}

def raw(rows):
    return pd.DataFrame([{**LINE, **r} for r in rows], columns=list(COLUMNS))

def lines(rows):
    return clean(raw(rows))

def days(first, n, cancelled_per_day, total=10, fulfilment="Merchant"):
    """`total` lines per day for n consecutive days; cancelled_per_day gives how many are cancelled each day."""
    out = []
    for i in range(n):
        date = (pd.Timestamp(first) + pd.Timedelta(days=i)).strftime("%m-%d-%y")
        for j in range(total):
            out.append({"Order ID":f"{fulfilment}{i}-{j}", "Date":date, "Fulfilment":fulfilment,
                        "Status":"Cancelled" if j < cancelled_per_day[i] else "Shipped"})
    return out

LOW = Thresholds(min_lines_per_day=1, min_consecutive=3, cancel_multiplier=1.5)

# ---------- Cleaning and validation ----------

def test_both_date_formats_and_cleaning():
    df = lines([{"Date":"04-10-22", "Category":"Blazzer", "ship-state":" rajshthan "}, {"Order ID":"O2", "Date":"04-11-2022"}])
    assert list(df["order_date"]) == [pd.Timestamp("2022-04-10"), pd.Timestamp("2022-04-11")]
    assert (df.loc[0, "category"], df.loc[0, "ship_state"]) == ("Blazer", "RAJASTHAN")

def test_optional_sales_channel_and_city_features():
    df = lines([{"Sales Channel":"Amazon.in", "ship-city":"Mumbai"}])
    assert (df.loc[0, "sales_channel"], df.loc[0, "ship_city"]) == ("Amazon.in", "MUMBAI")
    raw_without_optional = raw([{}]).drop(columns=["Sales Channel", "ship-city"])
    cleaned = clean(raw_without_optional)
    assert cleaned.loc[0, "sales_channel"] == "UNKNOWN"
    assert cleaned.loc[0, "ship_city"] == "UNKNOWN"

def test_fulfilled_by_and_empty_source_columns_are_retained():
    df = lines([{"fulfilled-by":"Easy Ship"}])
    assert df.loc[0, "fulfilled_by"] == "Easy Ship"
    assert pd.isna(df.loc[0, "new"])
    assert pd.isna(df.loc[0, "pending_s"])

def test_clean_copy_deduplicates_but_preserves_blanks_and_source_columns(tmp_path):
    source = raw([{"Order ID":"A", "Amount":None, "ship-city":"HASSAN (Arun)"},
                  {"Order ID":"A", "Amount":None, "ship-city":"HASSAN (Arun)"},
                  {"Order ID":"B", "ship-city":"NA"}])                          # text 'NA' is a value, not a blank
    source.insert(0, "index", ["0", "1", "2"])
    source["New"] = pd.NA
    source["PendingS"] = pd.NA
    source["fulfilled-by"] = ["Easy Ship", "Easy Ship", "Easy Ship"]
    source_path = tmp_path / "source.csv"
    output_path = tmp_path / "cleaned.csv"
    validation_path = tmp_path / "validation.json"
    duplicate_audit_path = tmp_path / "duplicates.csv"
    source.to_csv(source_path, index=False)
    source_checksum = sha256(source_path)

    report = create_clean_copy(source_path, output_path, validation_path, duplicate_audit_path)
    result = read_as_text(output_path)
    assert list(result.columns) == list(source.columns)                       # header 'index' kept as written
    assert result["index"].tolist() == ["0", "2"]
    assert result["ship-city"].tolist() == ["HASSAN (Arun)", "NA"]
    assert pd.isna(result.loc[0, "Amount"])
    assert result.loc[0, "fulfilled-by"] == "Easy Ship"
    assert "New" in result.columns and "PendingS" in result.columns
    assert report["duplicate_candidates_removed"] == 1
    assert (report["source_rows"], report["output_rows"]) == (3, 2)
    assert report["source_file"] == "source.csv"
    assert report["values_filled_or_inferred"] == 0
    assert sha256(source_path) == source_checksum == report["source_sha256"]
    assert report["output_sha256"] == sha256(output_path)
    assert json.loads(validation_path.read_text()) == report
    assert read_as_text(duplicate_audit_path)["index"].tolist() == ["1"]
    assert not list(tmp_path.glob("*.tmp"))

def test_clean_copy_leaves_existing_output_alone_when_validation_fails(tmp_path):
    source_path = tmp_path / "source.csv"
    raw([{"Qty":"1.9"}]).to_csv(source_path, index=False)                     # the engine rejects this
    output_path = tmp_path / "cleaned.csv"
    output_path.write_text("previous derived file")
    with pytest.raises(DataValidationError, match="whole number"):
        create_clean_copy(source_path, output_path, tmp_path / "v.json", tmp_path / "d.csv")
    assert output_path.read_text() == "previous derived file"
    assert not list(tmp_path.glob("*.tmp")) and not (tmp_path / "v.json").exists()

# ---------- Choosing the data file ----------

def test_default_file_is_the_repository_copy_and_never_a_discovered_file(monkeypatch, tmp_path):
    monkeypatch.delenv(engine.DATA_FILE_ENV, raising=False)
    cleaned = tmp_path / "cleaned.csv"
    monkeypatch.setattr(engine, "CLEANED_DATA_FILE", cleaned)
    monkeypatch.setattr(engine, "RAW_DATA_FILE", tmp_path / "raw.csv")
    (tmp_path / "Amazon Sale Report.csv").write_text("an unrelated attachment")
    assert resolve_data_file() == tmp_path / "raw.csv"                         # no derived copy yet
    cleaned.write_text("")
    assert resolve_data_file() == cleaned

def test_explicit_override_is_used_even_if_missing(monkeypatch, tmp_path):
    missing = tmp_path / "typo.csv"
    monkeypatch.setenv(engine.DATA_FILE_ENV, str(missing))
    assert resolve_data_file() == missing                                     # not replaced by another file
    with pytest.raises(FileNotFoundError):
        load_data(resolve_data_file())

def test_dashboard_label_distinguishes_raw_from_deduplicated():
    assert is_deduplicated_copy(CLEANED_DATA_FILE)
    assert not is_deduplicated_copy(RAW_DATA_FILE)

def test_sales_customer_and_inventory_analyses():
    df = lines([
        {"Order ID":"A", "Date":"04-10-22", "Sales Channel":"Amazon.in", "Category":"Shirt",
         "Size":"M", "Qty":"2", "Amount":"500", "B2B":"TRUE", "ship-state":"KERALA", "ship-city":"KOCHI"},
        {"Order ID":"B", "Date":"04-10-22", "Sales Channel":"Amazon.in", "Category":"Shirt",
         "Size":"M", "Qty":"1", "Amount":"250", "B2B":"FALSE", "ship-state":"KERALA", "ship-city":"KOCHI"},
        {"Order ID":"C", "Date":"04-11-22", "Sales Channel":"Other", "Category":"Dress",
         "Size":"L", "Qty":"1", "Amount":"300", "B2B":"FALSE", "ship-state":"GOA", "ship-city":"PANAJI"},
    ])
    trend = daily_sales(df)
    assert trend[["order_lines", "orders", "units", "sales_amount"]].values.tolist() == [
        [2, 2, 3, 750.0], [1, 1, 1, 300.0]
    ]
    category = performance_by_dimension(df, "category").set_index("category")
    assert category.loc["Shirt", "units"] == 3
    assert category.loc["Shirt", "sales_amount"] == 750
    assert customer_segments(df, "b2b").set_index("b2b").loc[True, "orders"] == 1
    assert customer_segments(df, "ship_city").iloc[0]["ship_city"] == "KOCHI"
    demand = inventory_demand(df).set_index(["category", "size"])
    assert demand.loc[("Shirt", "M"), "units"] == 3

@pytest.mark.parametrize("row,message", [
    ({"Date":"2022/04/10"}, "unreadable date"),
    ({"Status":"Teleported"}, "Unknown status"),
    ({"Qty":"-1"}, "qty that is not a non-negative whole number"),
    ({"Qty":"1.9"}, "qty that is not a non-negative whole number.*1.9"),
    ({"Qty":"inf"}, "qty that is not a non-negative whole number.*inf"),
    ({"Qty":"-inf"}, "qty that is not a non-negative whole number"),
    ({"Qty":"two"}, "qty that is not a non-negative whole number"),
    ({"Qty":None}, "blank qty"),
    ({"Amount":"abc"}, "amount that is not a non-negative number"),
    ({"Order ID":None}, "blank order_id"),
])
def test_bad_values_are_reported_clearly(row, message):
    with pytest.raises(DataValidationError, match=message):
        lines([row])

def test_whole_number_quantities_are_accepted():
    df = lines([{"Order ID":"A", "Qty":"0", "Status":"Cancelled"}, {"Order ID":"B", "Qty":"2"}, {"Order ID":"C", "Qty":"3.0"}])
    assert df["qty"].tolist() == [0, 2, 3] and df["qty"].dtype.kind == "i"

def test_zero_quantity_on_a_live_line_is_still_a_quality_warning():
    r = raw([{"Order ID":"A", "Qty":"0", "Status":"Shipped"}])
    q = data_quality(r, clean(r)).set_index("detail")["lines"]
    assert q["Line is not cancelled but quantity is 0"] == 1

def test_missing_column_and_missing_file(tmp_path):
    with pytest.raises(DataValidationError, match="Missing columns: Qty"):
        clean(raw([{}]).drop(columns="Qty"))
    with pytest.raises(FileNotFoundError, match="README"):
        load_data(tmp_path / "nope.csv")

def test_blank_amount_stays_unknown_not_zero():
    assert pd.isna(lines([{"Amount":None}]).loc[0, "amount"])

def test_data_quality_counts_duplicates_and_conflicts():
    r = raw([{}, {}, {"Order ID":"O2", "Status":"Cancelled", "Courier Status":"On the Way", "Qty":"0"}])
    q = data_quality(r, clean(r)).set_index("detail")["lines"]
    assert q.filter(like="Extra copies").iloc[0] == 1  # the second copy; the first is the original
    assert q["Status is Cancelled but Courier Status is On the Way"] == 1

# ---------- KPIs ----------

def test_kpi_denominators():
    df = lines([
        {"Order ID":"A", "Status":"Shipped - Delivered to Buyer"},
        {"Order ID":"A", "Status":"Shipped - Returned to Seller"},           # same order, second line
        {"Order ID":"B", "Status":"Cancelled", "Qty":"0"},
        {"Order ID":"C", "Status":"Shipped", "Fulfilment":"Amazon"},        # Amazon lines have no return statuses
    ])
    k = compute_kpis(df)
    assert (k["order_lines"], k["orders"]) == (4, 3)
    assert k["cancellation_rate"] == pytest.approx(1 / 4)
    assert k["merchant_return_rate"] == pytest.approx(1 / 2)

def test_empty_file_gives_no_rates_and_no_exceptions(tmp_path):
    path = tmp_path / "empty.csv"
    raw([]).to_csv(path, index=False)
    data = load_data(path)
    k = compute_kpis(data["lines"])
    assert k["order_lines"] == 0 and k["cancellation_rate"] is None and k["merchant_return_rate"] is None
    assert detect_exceptions(data).empty
    assert run_pipeline(path, report_dir=tmp_path / "reports")["exceptions"].empty

# ---------- Aged unshipped ----------

def test_aged_unshipped_uses_snapshot_and_threshold():
    df = lines([
        {"Order ID":"OLD", "Date":"04-01-22", "Status":"Pending"},
        {"Order ID":"EDGE", "Date":"04-07-22", "Status":"Pending - Waiting for Pick Up"},
        {"Order ID":"NEW", "Date":"04-09-22", "Status":"Pending"},
        {"Order ID":"DONE", "Date":"04-01-22", "Status":"Shipped"},
        {"Order ID":"LAST", "Date":"04-10-22"},                             # sets the snapshot date
    ])
    assert list(aged_unshipped(df, Thresholds(aged_days=3))["order_id"]) == ["OLD", "EDGE"]  # 9 and exactly 3 days
    assert list(aged_unshipped(df, Thresholds(aged_days=4))["order_id"]) == ["OLD"]

# ---------- Repeated high cancellation rule ----------
# First and last days are dropped as partial, so each scenario pads one normal day on each side.

def test_isolated_high_days_do_not_alert():
    df = lines(days("2022-04-01", 9, [1, 1, 5, 1, 5, 1, 5, 1, 1]))
    assert channel_days(df, LOW)["high"].sum() == 3
    assert high_cancellation_runs(df, LOW).empty

def test_consecutive_high_days_alert_once():
    df = lines(days("2022-04-01", 9, [1, 1, 5, 5, 5, 1, 1, 1, 1]))
    runs = high_cancellation_runs(df, LOW)
    assert len(runs) == 1 and runs.loc[0, "days"] == 3
    assert runs.loc[0, "first_day"] == pd.Timestamp("2022-04-03")
    assert detect_exceptions({"lines":df, "quality":data_quality(raw([]), df)}, LOW)["exception_type"].tolist() == ["Repeated high cancellations"]

def test_missing_day_breaks_a_run():
    rows = [r for r in days("2022-04-01", 8, [1, 1, 5, 5, 5, 5, 1, 1]) if r["Date"] != "04-04-22"]
    assert high_cancellation_runs(lines(rows), LOW).empty

def test_each_channel_compared_with_its_own_usual_rate():
    # Merchant is always at 30% and Amazon always at 10%: steady, so neither should alert
    df = lines(days("2022-04-01", 7, [3] * 7) + days("2022-04-01", 7, [1] * 7, fulfilment="Amazon"))
    assert not channel_days(df, LOW)["high"].any()

def test_zero_cancellation_channel_never_alerts():
    # Amazon has no cancellations at all; Merchant still has a genuine run
    df = lines(days("2022-04-01", 9, [0] * 9, fulfilment="Amazon") + days("2022-04-01", 9, [1, 1, 5, 5, 5, 1, 1, 1, 1]))
    out = channel_days(df, LOW)
    assert not out.loc[out["fulfilment"].eq("Amazon"), "high"].any()
    assert high_cancellation_runs(df, LOW)["fulfilment"].tolist() == ["Merchant"]
    assert high_cancellation_runs(lines(days("2022-04-01", 9, [0] * 9)), LOW).empty

def test_zero_returns_never_make_a_hotspot():
    rows = [{"Order ID":f"{s}{i}", "ship-state":s, "Status":"Shipped - Delivered to Buyer"} for s in ["KERALA", "GOA"] for i in range(30)]
    out = merchant_returns_by_state(lines(rows), Thresholds(min_state_lines=5, return_multiplier=1.5))
    assert out["returned_lines"].sum() == 0 and not out["flagged"].any()

def test_return_hotspot_needs_volume_and_rate():
    rows = [{"Order ID":f"K{i}", "ship-state":"KERALA", "Status":"Shipped - Returned to Seller" if i < 3 else "Shipped - Delivered to Buyer"} for i in range(10)]
    rows += [{"Order ID":f"G{i}", "ship-state":"GOA", "Status":"Shipped - Delivered to Buyer"} for i in range(30)]
    rows += [{"Order ID":"S1", "ship-state":"SIKKIM", "Status":"Shipped - Returned to Seller"}]
    out = merchant_returns_by_state(lines(rows), Thresholds(min_state_lines=5, return_multiplier=1.5)).set_index("ship_state")
    assert out.loc["KERALA", "flagged"] and not out.loc["GOA", "flagged"]
    assert not out.loc["SIKKIM", "flagged"]  # 100% returned, but only one line

# ---------- SQL ----------

def test_sql_matches_pandas_and_respects_where_clause():
    df = lines(days("2022-04-01", 4, [1, 2, 3, 4]) + days("2022-04-01", 4, [0, 0, 0, 9], fulfilment="Amazon"))
    conn = load_into_sqlite(df)
    result = cancellations_by_day(conn, "Merchant", "2022-04-02", "2022-04-03")
    assert result.to_dict("list") == {"order_date":["2022-04-02", "2022-04-03"], "order_lines":[10, 10],
                                      "cancelled_lines":[2, 3], "cancelled_pct":[20.0, 30.0]}
    assert reconcile(result, df, "Merchant", "2022-04-02", "2022-04-03")[0]

def test_sql_dates_sort_across_years():
    df = lines([{"Order ID":"A", "Date":"12-31-21"}, {"Order ID":"B", "Date":"01-01-22"}])
    assert cancellations_by_day(load_into_sqlite(df))["order_date"].tolist() == ["2021-12-31", "2022-01-01"]

# ---------- The real file ----------

# These use the repository's files explicitly, so an AMAZON_SALE_REPORT_CSV override cannot change what they check.
real = pytest.mark.skipif(not (RAW_DATA_FILE.exists() and CLEANED_DATA_FILE.exists()), reason="Amazon sales report not present")

@real
def test_derived_copy_is_the_source_minus_only_the_duplicate_candidates():
    source = read_as_text(RAW_DATA_FILE)
    candidates = duplicate_candidates(source)
    derived = read_as_text(CLEANED_DATA_FILE)
    assert list(derived.columns) == list(source.columns) and derived.columns[0] == "index"
    pd.testing.assert_frame_equal(derived, source.loc[~candidates].reset_index(drop=True))
    # Byte level too: each retained row is the source line exactly as written
    source_lines = RAW_DATA_FILE.read_bytes().splitlines()
    kept = [source_lines[0]] + [line for line, dup in zip(source_lines[1:], candidates) if not dup]
    assert CLEANED_DATA_FILE.read_bytes().splitlines() == kept

    report = json.loads(VALIDATION_FILE.read_text())
    assert report["source_file"] == "data/amazon_sale_report.csv"
    assert report["source_sha256"] == sha256(RAW_DATA_FILE)
    assert report["output_sha256"] == sha256(CLEANED_DATA_FILE)
    assert (report["source_rows"], report["output_rows"], report["duplicate_candidates_removed"]) == (
        len(source), len(derived), int(candidates.sum())) == (128976, 128017, 959)

@real
def test_real_file_headline_numbers():
    # The figures quoted in README.md, INTERVIEW_DEMO.md, and IMPROVEMENT_WORKFLOW.md
    data = load_data(CLEANED_DATA_FILE)
    k = compute_kpis(data["lines"])
    assert (k["order_lines"], k["orders"], k["snapshot_date"]) == (128017, 120229, "2022-06-29")
    assert (round(k["cancellation_rate"], 3), round(k["merchant_return_rate"], 3)) == (0.141, 0.066)
    assert (k["aged_unshipped_lines"], int(data["lines"]["amount"].isna().sum())) == (60, 7563)
    usual = channel_days(data["lines"], Thresholds()).groupby("fulfilment")["usual_rate"].first().round(3)
    assert usual.to_dict() == {"Amazon":0.127, "Merchant":0.175}
    runs = high_cancellation_runs(data["lines"], Thresholds())
    assert runs[["fulfilment","days","cancelled_lines","order_lines"]].values.tolist() == [
        ["Amazon", 3, 691, 4740], ["Merchant", 3, 351, 1665]
    ]
    assert high_cancellation_runs(data["lines"], Thresholds(cancel_multiplier=1.15)).empty

@real
def test_real_file_sql_matches_pandas_for_both_channels():
    df = load_data(CLEANED_DATA_FILE)["lines"]
    conn = load_into_sqlite(df)
    for channel in ["Merchant", "Amazon"]:
        result = cancellations_by_day(conn, channel)
        assert reconcile(result, df, channel)[0]
        assert result["order_lines"].sum() == (df["fulfilment"] == channel).sum()
