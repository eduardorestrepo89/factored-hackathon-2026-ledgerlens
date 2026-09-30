"""stage(): window by business date, DDL-enforced types and constraints, Parquet out."""

import hashlib
from datetime import date

import duckdb
import pytest
from data_load_fixtures import AS_OF, tx, write_csv, write_transactions

from data_load.stage import StageError, _create_s3_secret, load_window, stage

TX = ["bank.transactions"]


def read(path, columns):
    return duckdb.sql(
        f"SELECT {columns} FROM '{path.as_posix()}' ORDER BY 1"
    ).fetchall()


@pytest.mark.unit
def test_load_window_is_two_years_ending_at_as_of():
    assert load_window(AS_OF, 2) == (date(2024, 6, 18), date(2026, 6, 17))


@pytest.mark.unit
def test_window_keeps_business_day_rows(tmp_path):
    write_transactions(
        tmp_path / "src",
        [
            tx("T1", "2026-06-17 10:00:00", "2026-06-17"),
            tx("T2", "2024-06-17 10:00:00", "2024-06-17"),  # one day before the window
            tx(
                "T3", "2026-06-18 03:00:00", "2026-06-17"
            ),  # after midnight, same business day
            tx("T4", "2024-06-18 00:00:01", "2024-06-18"),  # first day of the window
        ],
    )
    [staged] = stage(
        (tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX
    )
    assert staged.rows == 3
    assert read(staged.path, "transaction_id") == [("T1",), ("T3",), ("T4",)]


@pytest.mark.unit
def test_empty_field_loads_as_null(tmp_path):
    write_transactions(
        tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17", code="")]
    )
    [staged] = stage(
        (tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX
    )
    assert read(staged.path, "transaction_id, response_code") == [("T1", None)]


@pytest.mark.unit
def test_check_violation_names_the_table(tmp_path):
    write_transactions(
        tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17", code="99")]
    )
    with pytest.raises(StageError, match=r"^bank\.transactions: .*CHECK"):
        stage((tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX)


@pytest.mark.unit
def test_duplicate_primary_key_is_an_error(tmp_path):
    row = tx("T1", "2026-06-17 10:00:00", "2026-06-17")
    write_transactions(tmp_path / "src", [row, row])
    with pytest.raises(StageError, match=r"^bank\.transactions: "):
        stage((tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX)


@pytest.mark.unit
def test_reference_tables_load_in_full(tmp_path):
    header = [
        "product_id",
        "customer_id",
        "product_type",
        "product_number",
        "currency",
        "current_balance",
        "opening_date",
        "product_status",
        "opening_channel",
        "has_linked_app",
        "last_updated",
    ]
    write_csv(
        tmp_path / "src" / "products.csv",
        header,
        [
            [
                "PRD-1",
                "CLI-1",
                "Tarjeta Crédito",
                "4111",
                "USD",
                "100.00",
                "2026-06-17",
                "Active",
                "App",
                "True",
                "2027-06-15 19:35:27",
            ],
            [
                "PRD-2",
                "CLI-1",
                "Cuenta Ahorro",
                "5222",
                "USD",
                "5.00",
                "2018-06-18",
                "Active",
                "Branch",
                "False",
                "2018-06-20 05:21:54",
            ],
        ],
    )
    [staged] = stage(
        (tmp_path / "src").as_posix(),
        tmp_path / "out",
        AS_OF,
        2,
        tables=["bank.products"],
    )
    assert read(staged.path, "product_id, product_type") == [
        ("PRD-1", "Tarjeta Crédito"),
        ("PRD-2", "Cuenta Ahorro"),
    ]


@pytest.mark.unit
def test_exchange_rates_are_cut_by_date(tmp_path):
    header = ["date", "source_currency", "target_currency", "exchange_rate"]
    write_csv(
        tmp_path / "src" / "daily_exchange_rates.csv",
        header,
        [
            ["2024-06-17", "USD", "COP", "4000.000000"],
            ["2024-06-18", "USD", "COP", "4000.000000"],
            ["2026-06-17", "USD", "COP", "4000.000000"],
        ],
    )
    [staged] = stage(
        (tmp_path / "src").as_posix(),
        tmp_path / "out",
        AS_OF,
        2,
        tables=["bank.daily_exchange_rates"],
    )
    assert staged.rows == 2


@pytest.mark.unit
def test_parquet_checksum_and_count(tmp_path):
    write_transactions(
        tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17")]
    )
    [staged] = stage(
        (tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX
    )
    assert staged.table == "bank.transactions"
    assert staged.path == tmp_path / "out" / "transactions.parquet"
    assert staged.sha256 == hashlib.sha256(staged.path.read_bytes()).hexdigest()
    assert (
        duckdb.sql(f"SELECT count(*) FROM '{staged.path.as_posix()}'").fetchone()[0]
        == 1
    )


@pytest.mark.unit
def test_s3_secret_failure_does_not_echo_keys():
    con = duckdb.connect()
    try:
        con.execute("INSTALL httpfs")
    except duckdb.Error:
        pytest.skip("httpfs extension not downloadable (offline)")
    secret = {
        "aws_access_key_id": "fake-key-id",
        "aws_secret_access_key": "fake-secret-value",
        "region": "us-east-2",
        "bucket": "b",
    }
    _create_s3_secret(con, secret)
    with pytest.raises(
        StageError
    ) as err:  # second CREATE SECRET with the same name fails
        _create_s3_secret(con, secret)
    assert "fake-key-id" not in str(err.value) and "fake-secret-value" not in str(
        err.value
    )
    assert err.value.__cause__ is None and err.value.__suppress_context__
