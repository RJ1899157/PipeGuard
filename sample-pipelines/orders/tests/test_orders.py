from datetime import date
from decimal import Decimal
import json

import psycopg
from psycopg import sql
import pytest

from orders_pipeline.loader import HEADERS, InvalidSource, parse_orders, replace_orders
from orders_pipeline.runner import ROOT, run

SOURCE = ROOT / "data/orders.csv"


def test_fixture_values_are_exact():
    rows = parse_orders(SOURCE)
    assert len(rows) == 5
    assert rows[0][4] == Decimal("19.99")
    assert rows[0][2].utcoffset().total_seconds() == 0


@pytest.mark.parametrize("column,value", [
    ("order_id", "DROP TABLE orders"), ("customer_id", ""), ("quantity", "0"),
    ("quantity", "1.5"), ("unit_price", "NaN"), ("unit_price", "1.234"),
    ("unit_price", "-1"), ("ordered_at", "2026-10-01T09:00:00"), ("status", "unknown"),
])
def test_invalid_source_values_rejected_without_echo(tmp_path, column, value):
    lines = SOURCE.read_text().splitlines()
    cells = lines[1].split(",")
    cells[HEADERS.index(column)] = value
    source = tmp_path / "invalid.csv"
    source.write_text(lines[0] + "\n" + ",".join(cells) + "\n")
    with pytest.raises(InvalidSource, match="invalid_") as error:
        parse_orders(source)
    if value:
        assert "DROP TABLE" not in str(error.value)


@pytest.mark.parametrize("content", ["", ",".join(HEADERS)+"\n", "wrong,columns\n1,2\n"])
def test_empty_or_wrong_columns_rejected(tmp_path, content):
    source = tmp_path / "empty.csv"
    source.write_text(content)
    with pytest.raises(InvalidSource):
        parse_orders(source)


def test_raw_replacement_is_idempotent_and_rolls_back(warehouse):
    settings, connection = warehouse
    rows = parse_orders(SOURCE)
    for _ in range(2):
        replace_orders(connection, rows, settings.prefix)
    table = sql.Identifier(settings.prefix + "raw", "orders")
    assert connection.execute(sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()[0] == 5
    bad = [rows[0][:3] + (0,) + rows[0][4:]]
    with pytest.raises(psycopg.errors.CheckViolation):
        replace_orders(connection, bad, settings.prefix)
    assert connection.execute(sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()[0] == 5


def test_malformed_input_preserves_existing_snapshot(warehouse, tmp_path):
    settings, connection = warehouse
    replace_orders(connection, parse_orders(SOURCE), settings.prefix)
    bad = tmp_path / "malformed.csv"
    bad.write_text("bad,input\n")
    with pytest.raises(InvalidSource):
        run(bad, settings)
    table = sql.Identifier(settings.prefix + "raw", "orders")
    assert connection.execute(sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()[0] == 5


def test_sample_role_cannot_connect_to_monitoring_database(warehouse):
    settings, _ = warehouse
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(host=settings.host, port=settings.port, dbname="pipeguard",
                         user=settings.user, password=settings.password, connect_timeout=3)


def test_full_dbt_build_quality_failure_and_recovery(warehouse, tmp_path):
    settings, connection = warehouse
    daily = sql.Identifier(settings.prefix + "analytics", "daily_revenue")
    expected = [(date(2026, 10, 1), 2, Decimal("139.98")),
                (date(2026, 10, 2), 2, Decimal("41.00"))]
    for _ in range(2):
        summary = run(SOURCE, settings)
        assert summary["dbt_succeeded"]
        assert connection.execute(sql.SQL("SELECT order_date, completed_order_count, revenue FROM {} ORDER BY order_date").format(daily)).fetchall() == expected
        results = json.loads((ROOT / summary["artifacts"] / "run_results.json").read_text())
        assert all(item["status"] in ("success", "pass") for item in results["results"])
    lines = SOURCE.read_text().splitlines()
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text("\n".join(lines + [lines[1]]) + "\n")
    failed = run(duplicate, settings)
    assert not failed["dbt_succeeded"]
    results = json.loads((ROOT / failed["artifacts"] / "run_results.json").read_text())
    assert any(item["status"] == "fail" and "unique" in item["unique_id"] for item in results["results"])
    assert run(SOURCE, settings)["dbt_succeeded"]
    assert connection.execute(sql.SQL("SELECT order_date, completed_order_count, revenue FROM {} ORDER BY order_date").format(daily)).fetchall() == expected


def test_embedded_newline_cannot_be_silently_normalized(tmp_path):
    source = tmp_path / "multiline.csv"
    source.write_text(",".join(HEADERS) + '\n1001,"C\n001",2026-10-01T09:00:00Z,1,1.00,completed\n')
    with pytest.raises(InvalidSource, match="invalid_values"):
        parse_orders(source)


def test_concurrent_replacement_fails_safely_when_workload_locked(warehouse):
    from orders_pipeline.loader import WAREHOUSE_LOCK
    settings, first = warehouse
    rows = parse_orders(SOURCE)
    replace_orders(first, rows, settings.prefix)
    first.execute("SELECT pg_advisory_lock(%s)", (WAREHOUSE_LOCK,))
    try:
        with settings.connect() as second:
            second.execute("SET lock_timeout = '100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                replace_orders(second, rows[:1], settings.prefix)
    finally:
        first.execute("SELECT pg_advisory_unlock(%s)", (WAREHOUSE_LOCK,))
    table = sql.Identifier(settings.prefix + "raw", "orders")
    assert first.execute(sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()[0] == 5
