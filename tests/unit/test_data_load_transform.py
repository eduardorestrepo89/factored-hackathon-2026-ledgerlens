"""Stage 2: DDL-enforced types and constraints, length check, repairs, Parquet out."""

import hashlib

import duckdb
import pytest
from data_load_fixtures import tx, write_csv, write_transactions
from data_load_s3 import FakeS3

from data_load.transform import TransformError, download_raw, load_expected, transform

TX = ["transactions"]
PRODUCT_HEADER = [
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


def product(product_id: str, opening_date: str) -> list[str]:
    return [
        product_id,
        "CLI-1",
        "Tarjeta Crédito",
        "4111",
        "USD",
        "100.00",
        opening_date,
        "Active",
        "App",
        "True",
        "2027-06-15 19:35:27",
    ]


def read(path, columns):
    return duckdb.sql(
        f"SELECT {columns} FROM '{path.as_posix()}' ORDER BY 1"
    ).fetchall()


def run(tmp_path, tables=TX, expected=None):
    return transform(
        (tmp_path / "src").as_posix(),
        tmp_path / "out",
        tables=tables,
        expected=expected,
    )


@pytest.mark.unit
def test_every_business_day_is_kept(tmp_path):
    write_transactions(
        tmp_path / "src",
        [
            tx("T1", "2023-06-17 10:00:00", "2023-06-17"),  # first day of the data
            tx(
                "T2", "2026-06-18 03:00:00", "2026-06-17"
            ),  # after midnight, same business day
        ],
    )
    [table], counts = run(tmp_path)
    assert table.rows == 2 and counts == {}
    assert read(table.path, "transaction_id") == [("T1",), ("T2",)]


@pytest.mark.unit
def test_empty_field_loads_as_null(tmp_path):
    write_transactions(
        tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17", code="")]
    )
    [table], _ = run(tmp_path)
    assert read(table.path, "transaction_id, response_code") == [("T1", None)]


@pytest.mark.unit
def test_check_violation_names_the_table(tmp_path):
    write_transactions(
        tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17", code="99")]
    )
    with pytest.raises(TransformError, match=r"^transactions: .*CHECK"):
        run(tmp_path)


@pytest.mark.unit
def test_duplicate_primary_key_is_an_error(tmp_path):
    row = tx("T1", "2026-06-17 10:00:00", "2026-06-17")
    write_transactions(tmp_path / "src", [row, row])
    with pytest.raises(TransformError, match=r"^transactions: "):
        run(tmp_path)


@pytest.mark.unit
def test_an_over_long_value_fails_before_dsql(tmp_path):
    row = tx("T1", "2026-06-17 10:00:00", "2026-06-17")
    row[9] = "X" * 51  # transaction_country varchar(50)
    write_transactions(tmp_path / "src", [row])
    with pytest.raises(
        TransformError,
        match=r"^transactions: transaction_country longer than 50 in 1 rows",
    ):
        run(tmp_path)


@pytest.mark.unit
def test_repairs_run_before_parquet_is_written(tmp_path):
    write_csv(
        tmp_path / "src" / "products.csv",
        PRODUCT_HEADER,
        [product("PRD-1", "2026-06-17")],
    )
    write_transactions(
        tmp_path / "src", [tx("T1", "2026-06-10 09:00:00", "2026-06-10")]
    )
    written, counts = run(tmp_path, tables=["products", "transactions"])
    assert counts == {"R6a": {"changed": 1}}
    products = next(t for t in written if t.name == "products")
    assert str(read(products.path, "opening_date")[0][0]) == "2026-06-10"


@pytest.mark.unit
def test_a_broken_link_stops_the_transform(tmp_path):
    write_csv(
        tmp_path / "src" / "products.csv",
        PRODUCT_HEADER,
        [product("PRD-9", "2020-01-01")],
    )
    write_transactions(
        tmp_path / "src", [tx("T1", "2026-06-10 09:00:00", "2026-06-10")]
    )  # PRD-1
    with pytest.raises(
        TransformError, match=r"transactions\.product_id -> products: 1 broken"
    ):
        run(tmp_path, tables=["products", "transactions"])
    assert not list((tmp_path / "out").glob("*.parquet"))


@pytest.mark.unit
def test_time_columns_reach_parquet_as_text(tmp_path):
    # aurora-dsql-loader v3.3.0 can't read Parquet TIME (Time64): branches failed on
    # the first cloud run. As 'HH:MM:SS' text, DSQL casts it into the time column.
    header = [
        "branch_id",
        "branch_code",
        "branch_name",
        "branch_type",
        "address",
        "city",
        "state",
        "country",
        "geographic_zone",
        "phone",
        "opening_time",
        "closing_time",
        "has_atms",
        "has_teller_windows",
        "branch_opening_date",
        "branch_status",
    ]
    row = ["SUC-1", "B001", "Centro", "Main", "Calle 1", "Bogota", "DC", "Colombia"]
    row += ["Centro", "555", "08:00:00", "17:30:00", "True", "True", "2020-01-01"]
    write_csv(tmp_path / "src" / "branches.csv", header, [row + ["Active"]])
    [table], _ = run(tmp_path, tables=["branches"])
    described = duckdb.sql(f"DESCRIBE SELECT * FROM '{table.path.as_posix()}'")
    types = {name: kind for name, kind, *_ in described.fetchall()}
    assert types["opening_time"] == "VARCHAR" and types["closing_time"] == "VARCHAR"
    assert types["branch_opening_date"] == "DATE"  # only TIME columns change
    assert read(table.path, "opening_time, closing_time") == [("08:00:00", "17:30:00")]


@pytest.mark.unit
def test_counts_must_match_expected(tmp_path):
    write_transactions(
        tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17")]
    )
    with pytest.raises(TransformError, match="transactions: 1 rows, expected 2"):
        run(tmp_path, expected={"rows": {"transactions": 2}, "repairs": {}})


@pytest.mark.unit
def test_parquet_checksum_and_count(tmp_path):
    write_transactions(
        tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17")]
    )
    [table], _ = run(tmp_path, expected={"rows": {"transactions": 1}, "repairs": {}})
    assert table.name == "transactions"
    assert table.path == tmp_path / "out" / "transactions.parquet"
    assert table.sha256 == hashlib.sha256(table.path.read_bytes()).hexdigest()
    assert read(table.path, "count(*)") == [(1,)]


@pytest.mark.unit
def test_expected_json_matches_the_spec():
    expected = load_expected()
    assert len(expected["rows"]) == 13
    assert sum(expected["rows"].values()) == 23_495_188
    assert list(expected["repairs"]) == ["R6a", "R1", "R6b", "R2", "R3", "R4"]
    assert expected["repairs"]["R1"] == {"resolved": 139_573, "set_null": 10_422}
    assert expected["repairs"]["R4"] == {"resolved": 337_760, "set_null": 1_102_562}


@pytest.mark.unit
def test_download_raw_mirrors_the_run_prefix(tmp_path):
    s3 = FakeS3(
        {
            ("team", "raw/run-1/customers.csv"): b"c",
            ("team", "raw/run-1/transactions/year=2024/month=06/day=18/t.csv"): b"t",
            ("team", "raw/run-2/customers.csv"): b"other run",
        }
    )
    assert download_raw(s3, "team", "run-1", tmp_path) == 2
    assert (tmp_path / "customers.csv").read_bytes() == b"c"
    assert (
        tmp_path / "transactions/year=2024/month=06/day=18/t.csv"
    ).read_bytes() == b"t"


@pytest.mark.unit
def test_download_raw_needs_an_ingested_run(tmp_path):
    with pytest.raises(TransformError, match="run ingest first"):
        download_raw(FakeS3(), "team", "run-1", tmp_path)
