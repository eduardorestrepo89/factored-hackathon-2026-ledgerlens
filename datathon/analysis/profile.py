"""Load the LATAM Bank CSVs into DuckDB (first run only) and run a profiling SQL file.

Usage:  uv pip install duckdb==1.5.5
        python analysis/profile.py analysis/profiling.sql > analysis/profiling_output.txt
"""
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA = (ROOT / "data").as_posix()
DB = ROOT / "analysis" / "bank.duckdb"
DIMS = ["customers", "products", "branches", "service_agents", "marketing_campaigns", "daily_exchange_rates"]
FACTS = ["call_center_interactions", "call_transcripts", "campaign_sends", "complaints",
         "digital_events", "satisfaction_surveys", "transactions"]


def load(con):
    for t in DIMS:
        con.execute(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM read_csv('{DATA}/{t}.csv', header=true, sample_size=-1)")
    for t in FACTS:  # partitioned year=/month=/day=/<table>_<yyyymmdd>.csv
        con.execute(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM read_csv('{DATA}/{t}/*/*/*/*.csv', header=true, "
                    "hive_partitioning=true, union_by_name=true, filename=true, sample_size=100000)")
    print("loaded:", {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in DIMS + FACTS})


def run(con, sql_file):
    for stmt in [s for s in Path(sql_file).read_text(encoding="utf-8").split(";\n") if s.strip()]:
        print("\n#####", stmt.strip().splitlines()[0])
        try:
            con.sql(stmt).show(max_rows=60, max_width=250)
        except duckdb.Error as e:  # keep going: one bad query shouldn't hide the rest
            print("ERROR:", e)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    con = duckdb.connect(str(DB))
    if len(con.execute("SHOW TABLES").fetchall()) < len(DIMS + FACTS):
        load(con)
    if len(sys.argv) > 1:
        run(con, sys.argv[1])
