# LedgerLens Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-shot load built on `feat/database` with the staged pipeline in the spec: ingest → transform (contract, length and link checks, repairs R1–R6) → load → read check under Step Functions. All 13 organizer tables go into `public` as delivered, readable only by the tools role from inside a VPC.

**Architecture:**
- **Stages:** `data_load/` becomes four commands (`ingest`, `transform`, `load`, `check`). One CodeBuild project runs the first three, selected by `STAGE`. Each stage writes a JSON run record to `runs/<run-id>/` in the team bucket.
- **Transform:** DuckDB enforces `schema.sql`, checks `varchar` lengths, applies the repairs and runs the link checks before anything reaches AWS.
- **Load:** `aurora-dsql-loader` loads the Parquet files.
- **Infrastructure (CDK):**
  - a one-AZ isolated VPC with a DSQL PrivateLink endpoint;
  - a cluster resource policy that denies connections from outside the VPC, except the loader;
  - the `ledgerlens-tools` role;
  - a read-check Lambda;
  - the state machine.

**Tech Stack:**
- **Runtimes:** Python 3.12 (CodeBuild) and 3.13 (Lambda).
- **Data:** DuckDB 1.5.5, boto3, and psycopg 3 with `aurora-dsql-python-connector` 0.2.7; `aurora-dsql-loader` v3.3.0.
- **Infrastructure:** AWS CDK 2.260 (TypeScript, `@aws-cdk/aws-lambda-python-alpha`), Step Functions.
- **Tests:** pytest and jest.

**Spec:** `docs/superpowers/specs/2026-10-02-data-pipeline-design.md`. Read it first: section 6 (repairs) and section 7 (access) are the authority for every rule below.

**Starting point:** branch `feat/data-pipeline`, which holds everything `feat/database` built (through `7d18c41`) plus the spec.

**How this plan was checked:**
- **Code:** every file below ran in a scratch copy of the repo, task by task: tests first (RED), then the code (GREEN).
- **Expected results:** the RED and GREEN results quoted in each task come from that run.
- **Full rehearsal:** the complete transform ran on `datathon/data` and produced exactly the counts pinned in `expected.json`, in 429 s.
- **Infrastructure:** the CDK construct type-checks, and its 6 jest tests fail against the current construct and pass against the new one.

## Global Constraints

- **Names:**

  | Thing | Name |
  |---|---|
  | Schema | `public` |
  | Read role | `ll_read` |
  | Tools IAM role | `ledgerlens-tools` |
  | CodeBuild project | `ledgerlens-data-load` |
  | State machine | `ledgerlens-data-pipeline` |
  | Read-check Lambda | `ledgerlens-dsql-read-check` |
  | Organizer secret | `ledgerlens/hackathon-s3` |
  | Run records | `runs/<run-id>/{ingest,transform,load}.json` |
  | Data layers | `raw/<run-id>/`, `clean/<run-id>/` |

- **Counts:**
  - **Rows:** 23,495,188 in total (spec 5.2). The per-table counts are in `data_load/expected.json`.
  - **Repairs (spec 6.1):**
    - R6a changes 117,640;
    - R1 resolves 139,573 and sets 10,422 to `NULL`;
    - R6b changes 99,633;
    - R2 sets 831 to `NULL`;
    - R3 resolves 13,808 and sets 30,762 to `NULL`;
    - R4 resolves 337,760 and sets 1,102,562 to `NULL`.
  - **Enforcement:** a run on the full data with different counts fails the transform.
- **Database contents:** DSQL holds the 13 tables, `ll_read`, two grants and three indexes. No foreign keys, views, other schemas, tables or roles.
- **Organizer keys:**
  - They live only in Secrets Manager. `ingest` fetches them at runtime by the secret's name.
  - They never appear in an environment variable, a file, a run record or a log.
  - Never open `datathon/*.pdf`: the data dictionary PDF contains AWS keys. Only the human sets the secret's value.
- **Python tests:** from the repo root, run `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest <files> -q`.
  - Never use `uv run` without `--no-project`: it writes a stray `uv.lock` at the repo root.
- **CDK tests:** `cd infra-cdk && npx tsc --noEmit && npx jest test/data-construct.test.ts`.
- **Lint:** `uv run --no-project --quiet --with ruff ruff check data_load tests infra-cdk/lambdas` and `uv run --no-project --quiet --with ruff ruff format data_load tests infra-cdk/lambdas`. The repo's `ruff.toml` (rules E4, E7, E9, F, I) applies.
- **Staging files:**
  - Stage by path only: never `git add -A`, `git add .` or `git commit -a`.
  - The working tree carries the user's uncommitted `feat/design` edits:
    - `docs/LATAM_Bank_ERD.md`, `docs/LEDGERLENS_PRODUCT_DESIGN.md`, `docs/architecture-diagram/FAST-architecture.drawio`;
    - `frontend/package.json`, `frontend/package-lock.json`;
    - `infra-cdk/config.yaml` (the `admin_user_email` line);
    - `infra-cdk/lambdas/cedar-policy/index.py`, `infra-cdk/lib/backend-construct.ts`;
    - untracked `datathon/`, `frontend/pnpm-*.yaml`, `docs/architecture-diagram/ledgerlens-architecture.png` and `tests/unit/test_cedar_policy.py`.
  - None of these may be staged.
- **Commits:** messages carry no Claude or `Co-Authored-By` signature. Never push.
- **Red window:** Task 4 changes `ddl.py`, which the old `stage.py` and `__main__.py` depend on.
  - `tests/unit/test_data_load_stage.py` and `tests/unit/test_data_load_cli.py` fail from Task 4 until Task 6. Task 5 deletes the stage test and Task 6 rewrites the CLI test.
  - Each task's test command names only that task's files.
  - Task 6 ends with the whole `tests/unit` suite green, and Task 7 keeps it green. That's 86 tests: 72 for the data pipeline plus the repo's 14 others.
- **`make`:** it isn't installed on the team's Windows shell, so Tasks 8 and 9 also give the plain `aws` commands.

## Review Focus

1. **The PrivateLink hostname.**
   - **How the host is built:** the read check connects to `<cluster-id>.<service-id>.<region>.on.aws`. CDK builds it with `Fn.select(3, Fn.split(".", attrVpcEndpointServiceName))`; the service name has the form `com.amazonaws.<region>.dsql-xxxx`.
   - **How the token is signed:** the connector takes the region from the host with the regex `\.dsql[^.]*\.([^.]+)\.on\.aws$` (in `dsql_core`) and signs the token for that host.
   - **What tests can't cover:** unit tests pin only the handler's arguments. Whether DSQL accepts that token, and whether private DNS resolves the host from the isolated subnet, is first-run check 3 (spec section 13).
2. **The cluster policy.** It has two Deny statements, and each has two condition keys that must both hold.
   - **Failure modes:** a mistake either locks out the loader (the load stage fails on authentication) or leaves laptops in (layer 3 is silently absent).
   - **Coverage:** jest pins the strings. The reviewer checks the semantics against the AWS example; first-run checks 1 and 4 prove them.
3. **Rerunning one stage for an existing `RUN_ID`** (spec 4.1).
   - **Load** must work from `transform.json` alone.
   - **Transform** clears `raw/` before downloading (tested).
   - **Ingest** overwrites the same keys.
   - **CodeBuild overrides** from Step Functions or `start-build` replace only `STAGE` and `RUN_ID`; the project's other variables stay.
4. **Size on CodeBuild LARGE** (16 GiB RAM).
   - **Disk:** the on-disk DuckDB database, 5.35 GB of raw CSV and 1.2 GB of Parquet.
   - **The biggest update:** R4 updates 1.44M rows of a 15.6M-row table.
   - **Memory:** nothing may pull a whole table into Python memory. The laptop rehearsal took 429 s.
5. **Secret hygiene end to end.**
   - **Where the keys go:** only into the boto3 client arguments in `cmd_ingest`.
   - **What must not echo them:** `IngestError`, botocore errors, run records and prints.
   - **What CodeBuild carries:** only the secret's name.

## Cost

See spec section 11, which has verified prices and the arithmetic:
- **Per run:** about $3.50–4.50.
- **Per month the stack exists:** about $8.70–9.50, 80% of it the PrivateLink endpoint.
- **Hackathon window:** about $7–9 in total.

Task 9 replaces the estimates with measured stage durations and CloudWatch `TotalDPU`.

## File map

| Task | Create | Modify | Delete |
|---|---|---|---|
| 1 | `data_load/runrecord.py`, `tests/unit/data_load_s3.py`, `tests/unit/test_data_load_runrecord.py` | `data_load/source.py`, `tests/unit/test_data_load_source.py` | — |
| 2 | `data_load/ingest.py`, `tests/unit/test_data_load_ingest.py` | — | — |
| 3 | `data_load/repair.py`, `tests/unit/test_data_load_repair.py` | — | — |
| 4 | — | `data_load/schema.sql`, `data_load/ddl.py`, `data_load/dsql.py`, `tests/unit/test_data_load_ddl.py`, `tests/unit/test_data_load_dsql.py` | — |
| 5 | `data_load/transform.py`, `data_load/expected.json`, `tests/unit/test_data_load_transform.py` | `tests/unit/data_load_fixtures.py` | `data_load/stage.py`, `tests/unit/test_data_load_stage.py` |
| 6 | — | `data_load/__main__.py`, `data_load/__init__.py`, `tests/unit/test_data_load_cli.py` | — |
| 7 | `infra-cdk/lambdas/dsql-read-check/index.py`, `infra-cdk/lambdas/dsql-read-check/requirements.txt`, `tests/unit/test_dsql_read_check.py` | — | — |
| 8 | — | `infra-cdk/lib/data-construct.ts`, `infra-cdk/test/data-construct.test.ts`, `infra-cdk/lib/utils/config-manager.ts`, `infra-cdk/config.yaml` (`data:` block only), `infra-cdk/lib/fast-main-stack.ts`, `Makefile` | — |
| 9 | — | spec sections 11 and 13 (measurements) | — |
| 10 | — | `docs/LEDGERLENS_PRODUCT_DESIGN.md`, `docs/LATAM_Bank_ERD.md`, `README.md` | — |

---

### Task 1: Source listing with sizes, and run records

**Files:**
- Create: `data_load/runrecord.py`, `tests/unit/data_load_s3.py`, `tests/unit/test_data_load_runrecord.py`
- Modify: `data_load/source.py` (whole file), `tests/unit/test_data_load_source.py` (whole file)

**Interfaces:**
- **Consumes:** nothing.
- **Produces, in `source.py`:**
  - `EVENT_TABLES: frozenset[str]`, moved here from `stage.py`, which keeps its own copy until Task 5 deletes it;
  - `normalize_prefix(prefix: str) -> str`;
  - `source_prefix(prefix: str, table: str) -> str`, which takes bare table names;
  - `list_objects(s3, bucket, key_prefix) -> list[tuple[str, str, int]]`, returning (key, etag, size);
  - `etag_digest(objects) -> str`;
  - `fingerprint(s3, bucket, prefix, tables) -> dict[str, tuple[int, str]]`;
  - `drift(recorded, current) -> list[str]`.
- **Produces, in `runrecord.py`:**
  - `STAGES`;
  - `record_key(run_id, stage) -> str`, which raises `ValueError` on a bad run id or stage;
  - `write(s3, bucket, run_id, stage, record: dict) -> str`, which returns the `s3://` URI;
  - `read(s3, bucket, run_id, stage) -> dict`.
- **Produces, for tests:** `tests/unit/data_load_s3.py` defines `FakeS3`, the in-memory S3 that Tasks 2, 5 and 6 reuse.

- [ ] **Step 1: Write the fake S3 and the failing tests**

`tests/unit/data_load_s3.py`:

```python
"""An in-memory stand-in for the few boto3 S3 calls data_load makes."""

import io
from pathlib import Path


class FakeS3:
    def __init__(self, objects: dict[tuple[str, str], bytes] | None = None):
        self.objects = dict(objects or {})  # (bucket, key) -> bytes
        self.truncate: set[str] = set()  # keys whose upload loses its last byte

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        found = sorted(
            k for b, k in self.objects if b == Bucket and k.startswith(Prefix)
        )
        contents = [
            {"Key": k, "ETag": f'"etag-{k}"', "Size": len(self.objects[(Bucket, k)])}
            for k in found
        ]
        return [{"Contents": contents}, {}]

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.encode()

    def upload_fileobj(self, Fileobj, Bucket, Key):
        data = Fileobj.read()
        self.objects[(Bucket, Key)] = data[:-1] if Key in self.truncate else data

    def upload_file(self, Filename, Bucket, Key):
        self.objects[(Bucket, Key)] = Path(Filename).read_bytes()

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def keys(self, bucket: str) -> list[str]:
        return sorted(k for b, k in self.objects if b == bucket)
```

`tests/unit/test_data_load_source.py` (replace the whole file):

```python
"""Source listing and fingerprints: detect a re-upload of the organizer's files."""

import pytest
from data_load_s3 import FakeS3

from data_load.source import (
    drift,
    etag_digest,
    fingerprint,
    list_objects,
    source_prefix,
)


@pytest.mark.unit
def test_source_prefix_for_event_and_reference_tables():
    assert source_prefix("data/", "transactions") == "data/transactions/"
    assert source_prefix("data/", "customers") == "data/customers.csv"


@pytest.mark.unit
def test_source_prefix_tolerates_missing_or_extra_slashes():
    assert source_prefix("data", "transactions") == "data/transactions/"
    assert source_prefix("/data/", "customers") == "data/customers.csv"


@pytest.mark.unit
def test_list_objects_returns_key_etag_and_size():
    s3 = FakeS3({("b", "data/transactions/a.csv"): b"abc"})
    assert list_objects(s3, "b", "data/transactions/") == [
        ("data/transactions/a.csv", "etag-data/transactions/a.csv", 3)
    ]


@pytest.mark.unit
def test_digest_ignores_order_and_size_and_catches_rewrites():
    a, b = ("k1", "e1", 1), ("k2", "e2", 2)
    assert etag_digest([a, b]) == etag_digest([b, a])
    assert etag_digest([a, b]) == etag_digest([a, ("k2", "e2", 99)])
    assert etag_digest([a, b]) != etag_digest([a, ("k2", "e3", 2)])
    assert etag_digest([a, b]) != etag_digest([a])


@pytest.mark.unit
def test_fingerprint_counts_files_per_table():
    s3 = FakeS3(
        {
            ("b", "data/transactions/1.csv"): b"1",
            ("b", "data/transactions/2.csv"): b"2",
            ("b", "data/customers.csv"): b"3",
        }
    )
    prints = fingerprint(s3, "b", "data/", ["transactions", "customers"])
    assert prints["transactions"][0] == 2
    assert prints["customers"] == (
        1,
        etag_digest([("data/customers.csv", "etag-data/customers.csv", 1)]),
    )


@pytest.mark.unit
def test_drift_lists_changed_and_one_sided_tables():
    assert drift({"a": "1", "b": "2"}, {"a": "1", "b": "2"}) == []
    assert drift({"a": "1", "b": "2"}, {"a": "1", "b": "X", "c": "3"}) == ["b", "c"]
```

`tests/unit/test_data_load_runrecord.py`:

```python
"""Run records: one JSON per stage under runs/<run-id>/ in the team bucket."""

import pytest
from data_load_s3 import FakeS3

from data_load import runrecord


@pytest.mark.unit
def test_write_then_read_round_trips():
    s3 = FakeS3()
    record = {"tables": {"branches": {"files": 1}}}
    uri = runrecord.write(s3, "team", "run-1", "ingest", record)
    assert uri == "s3://team/runs/run-1/ingest.json"
    assert runrecord.read(s3, "team", "run-1", "ingest") == record


@pytest.mark.unit
@pytest.mark.parametrize("run_id", ["", "../x", "a/b", "x" * 81])
def test_run_ids_cannot_escape_the_runs_prefix(run_id):
    with pytest.raises(ValueError, match="bad run id"):
        runrecord.record_key(run_id, "ingest")


@pytest.mark.unit
def test_unknown_stage_is_rejected():
    with pytest.raises(ValueError, match="unknown stage"):
        runrecord.record_key("run-1", "stage")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_source.py tests/unit/test_data_load_runrecord.py -q`
Expected: FAIL. `1 error` during collection: `ImportError: cannot import name 'runrecord' from 'data_load'`.

- [ ] **Step 3: Implement**

`data_load/source.py` (replace the whole file):

```python
"""List the organizer's source files and fingerprint them, so a re-upload is detectable."""

import hashlib

EVENT_TABLES = frozenset(
    {
        "call_center_interactions",
        "call_transcripts",
        "campaign_sends",
        "complaints",
        "digital_events",
        "satisfaction_surveys",
        "transactions",
    }
)


def normalize_prefix(prefix: str) -> str:
    """'data', 'data/' and '/data/' all become 'data/'; an empty prefix stays empty."""
    return prefix.strip("/") + "/" if prefix.strip("/") else ""


def source_prefix(prefix: str, table: str) -> str:
    """S3 key prefix of one table's source files."""
    base = normalize_prefix(prefix)
    return f"{base}{table}/" if table in EVENT_TABLES else f"{base}{table}.csv"


def list_objects(s3, bucket: str, key_prefix: str) -> list[tuple[str, str, int]]:
    """(key, etag, size) of every object under key_prefix."""
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        objects += [
            (o["Key"], o["ETag"].strip('"'), o["Size"])
            for o in page.get("Contents", [])
        ]
    return objects


def etag_digest(objects: list[tuple[str, str, int]]) -> str:
    """SHA-256 over sorted 'key etag' lines: any added, removed or rewritten file changes it."""
    lines = "\n".join(f"{key} {etag}" for key, etag, *_ in sorted(objects))
    return hashlib.sha256(lines.encode()).hexdigest()


def fingerprint(
    s3, bucket: str, prefix: str, tables: list[str]
) -> dict[str, tuple[int, str]]:
    """table -> (number of source files, ETag digest)."""
    result = {}
    for table in tables:
        objects = list_objects(s3, bucket, source_prefix(prefix, table))
        result[table] = (len(objects), etag_digest(objects))
    return result


def drift(recorded: dict[str, str], current: dict[str, str]) -> list[str]:
    """Tables whose digest differs, or that exist on only one side."""
    tables = recorded.keys() | current.keys()
    return sorted(t for t in tables if recorded.get(t) != current.get(t))
```

`data_load/runrecord.py`:

```python
"""Per-run records in the team bucket: runs/<run-id>/<stage>.json (spec section 4.1)."""

import json
import re

STAGES = ("ingest", "transform", "load")


def record_key(run_id: str, stage: str) -> str:
    if not re.fullmatch(r"[\w-]{1,80}", run_id):  # Step Functions execution names
        raise ValueError(f"bad run id: {run_id!r}")
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage!r}")
    return f"runs/{run_id}/{stage}.json"


def write(s3, bucket: str, run_id: str, stage: str, record: dict) -> str:
    key = record_key(run_id, stage)
    body = json.dumps(record, indent=2, sort_keys=True).encode()
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    return f"s3://{bucket}/{key}"


def read(s3, bucket: str, run_id: str, stage: str) -> dict:
    body = s3.get_object(Bucket=bucket, Key=record_key(run_id, stage))["Body"].read()
    return json.loads(body)
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_source.py tests/unit/test_data_load_runrecord.py -q`
Expected: `12 passed`.

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit -q`
Expected: no failures. The data_load tests number 41, and the repo's other 14 also pass.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff check data_load tests && uv run --no-project --quiet --with ruff ruff format --check data_load tests
git add data_load/source.py data_load/runrecord.py tests/unit/data_load_s3.py tests/unit/test_data_load_source.py tests/unit/test_data_load_runrecord.py
git commit -m "feat(data-pipeline): list source files with sizes and add per-run records in S3"
```


### Task 2: Stage 1, ingest

**Files:**
- Create: `data_load/ingest.py`, `tests/unit/test_data_load_ingest.py`

**Interfaces:**
- **Consumes:** `source.list_objects`, `source.etag_digest`, `source.normalize_prefix` and `source.source_prefix` (Task 1); `FakeS3` (Task 1).
- **Produces, in `ingest.py`:**
  - `SECRET_KEYS`;
  - `IngestError`;
  - `parse_secret(raw: str) -> dict`;
  - `load_secret(secrets, secret_id: str) -> dict`;
  - `raw_key(run_id, prefix, key) -> str`;
  - `ingest(org_s3, team_s3, secret: dict, team_bucket: str, run_id: str, tables: list[str], workers: int = 16) -> dict`.
- **The record:** `{"run_id", "source": {"bucket", "prefix", "region"}, "raw_prefix", "tables": {table: {"files", "bytes", "etag_digest", "objects": [[key, etag, size], ...]}}}`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_data_load_ingest.py`:

```python
"""Stage 1: byte-for-byte copy of the organizer's files, secret hygiene, lineage record."""

import json

import pytest
from data_load_s3 import FakeS3

from data_load.ingest import IngestError, ingest, load_secret, parse_secret
from data_load.source import etag_digest

SECRET = {
    "aws_access_key_id": "fake-key-id",
    "aws_secret_access_key": "fake-secret-value",
    "bucket": "org",
    "region": "us-east-2",
    "prefix": "data/",
}
ORG_FILES = {
    (
        "org",
        "data/transactions/year=2024/month=06/day=18/transactions_20240618.csv",
    ): b"t1",
    (
        "org",
        "data/transactions/year=2024/month=06/day=19/transactions_20240619.csv",
    ): b"t22",
    ("org", "data/customers.csv"): b"c333",
    ("org", "data_backup_20260831/customers.csv"): b"old",  # outside the prefix
}


class FakeSecrets:
    def __init__(self, value: str):
        self.value, self.asked = value, []

    def get_secret_value(self, SecretId):
        self.asked.append(SecretId)
        return {"SecretString": self.value}


@pytest.mark.unit
def test_copies_every_file_under_the_run_prefix():
    org, team = FakeS3(ORG_FILES), FakeS3()
    ingest(org, team, SECRET, "team", "run-1", ["transactions", "customers"])
    assert team.keys("team") == [
        "raw/run-1/customers.csv",
        "raw/run-1/transactions/year=2024/month=06/day=18/transactions_20240618.csv",
        "raw/run-1/transactions/year=2024/month=06/day=19/transactions_20240619.csv",
    ]
    assert team.objects[("team", "raw/run-1/customers.csv")] == b"c333"


@pytest.mark.unit
def test_record_holds_counts_bytes_and_digest_per_table():
    record = ingest(
        FakeS3(ORG_FILES), FakeS3(), SECRET, "team", "run-1", ["transactions"]
    )
    tx = record["tables"]["transactions"]
    assert (tx["files"], tx["bytes"]) == (2, 5)
    assert tx["etag_digest"] == etag_digest([tuple(o) for o in tx["objects"]])
    assert record["raw_prefix"] == "s3://team/raw/run-1/"
    assert record["source"] == {
        "bucket": "org",
        "prefix": "data/",
        "region": "us-east-2",
    }
    assert "fake-secret-value" not in json.dumps(record)


@pytest.mark.unit
def test_a_table_without_files_stops_before_copying():
    team = FakeS3()
    with pytest.raises(IngestError, match="no source files: complaints"):
        ingest(
            FakeS3(ORG_FILES),
            team,
            SECRET,
            "team",
            "run-1",
            ["customers", "complaints"],
        )
    assert team.keys("team") == []


@pytest.mark.unit
def test_a_short_copy_fails_the_stage():
    team = FakeS3()
    team.truncate.add("raw/run-1/customers.csv")
    with pytest.raises(IngestError, match=r"data/customers.csv \(3 of 4 bytes\)"):
        ingest(FakeS3(ORG_FILES), team, SECRET, "team", "run-1", ["customers"])


@pytest.mark.unit
def test_secret_comes_from_secrets_manager():
    secrets = FakeSecrets(json.dumps(SECRET))
    assert load_secret(secrets, "ledgerlens/hackathon-s3") == SECRET
    assert secrets.asked == ["ledgerlens/hackathon-s3"]


@pytest.mark.unit
def test_secret_errors_name_keys_never_values():
    partial = {k: v for k, v in SECRET.items() if k != "bucket"}
    with pytest.raises(IngestError) as err:
        parse_secret(json.dumps(partial))
    assert str(err.value) == "the organizer secret is missing: bucket"
    with pytest.raises(IngestError) as err:
        parse_secret('{"aws_secret_access_key": "fake-secret-value"')  # truncated JSON
    assert "fake-secret-value" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_ingest.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_load.ingest'`.

- [ ] **Step 3: Implement**

`data_load/ingest.py`:

```python
"""Stage 1: copy the organizer's CSVs into raw/<run-id>/ and record their ETags (spec 4.1).

The organizer's keys are fetched from Secrets Manager here and nowhere else; they never
sit in an environment variable, a file, the run record or a log (spec section 12).
"""

import json
from concurrent.futures import ThreadPoolExecutor

from data_load.source import etag_digest, list_objects, normalize_prefix, source_prefix

SECRET_KEYS = (
    "aws_access_key_id",
    "aws_secret_access_key",
    "bucket",
    "region",
    "prefix",
)


class IngestError(RuntimeError):
    """A table has no files, a copy came up short, or the secret is malformed.
    Messages name keys and files, never secret values."""


def parse_secret(raw: str) -> dict:
    try:
        secret = json.loads(raw)
    except json.JSONDecodeError:
        raise IngestError("the organizer secret is not valid JSON") from None
    if not isinstance(secret, dict):
        raise IngestError("the organizer secret must be a JSON object")
    missing = [key for key in SECRET_KEYS if not secret.get(key)]
    if missing:
        raise IngestError(f"the organizer secret is missing: {', '.join(missing)}")
    return secret


def load_secret(secrets, secret_id: str) -> dict:
    return parse_secret(secrets.get_secret_value(SecretId=secret_id)["SecretString"])


def raw_key(run_id: str, prefix: str, key: str) -> str:
    """data/transactions/year=2024/.../x.csv -> raw/<run-id>/transactions/year=2024/.../x.csv"""
    return f"raw/{run_id}/{key[len(normalize_prefix(prefix)) :]}"


def ingest(
    org_s3,
    team_s3,
    secret: dict,
    team_bucket: str,
    run_id: str,
    tables: list[str],
    workers: int = 16,
) -> dict:
    """Copy every source file byte for byte; return the ingest record."""
    bucket, prefix = secret["bucket"], secret["prefix"]
    listed = {t: list_objects(org_s3, bucket, source_prefix(prefix, t)) for t in tables}
    empty = [t for t, objects in listed.items() if not objects]
    if empty:  # usually a wrong bucket or prefix in the secret
        raise IngestError(f"no source files: {', '.join(empty)}")

    def copy(obj: tuple[str, str, int]) -> str | None:
        key, _etag, size = obj
        dest = raw_key(run_id, prefix, key)
        body = org_s3.get_object(Bucket=bucket, Key=key)["Body"]
        team_s3.upload_fileobj(body, team_bucket, dest)
        copied = team_s3.head_object(Bucket=team_bucket, Key=dest)["ContentLength"]
        return None if copied == size else f"{key} ({copied:,} of {size:,} bytes)"

    everything = [obj for objects in listed.values() for obj in objects]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        short = [s for s in pool.map(copy, everything) if s]
    if short:
        raise IngestError(
            f"{len(short)} incomplete copies, e.g. {', '.join(short[:5])}"
        )
    return {
        "run_id": run_id,
        "source": {"bucket": bucket, "prefix": prefix, "region": secret["region"]},
        "raw_prefix": f"s3://{team_bucket}/raw/{run_id}/",
        "tables": {
            table: {
                "files": len(objects),
                "bytes": sum(size for _, _, size in objects),
                "etag_digest": etag_digest(objects),
                "objects": [list(obj) for obj in objects],
            }
            for table, objects in listed.items()
        },
    }
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_ingest.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff check data_load tests && uv run --no-project --quiet --with ruff ruff format --check data_load tests
git add data_load/ingest.py tests/unit/test_data_load_ingest.py
git commit -m "feat(data-pipeline): ingest stage copies the organizer files to raw/<run-id>/"
```


### Task 3: Repairs R1–R6 and link checks

**Files:**
- Create: `data_load/repair.py`, `tests/unit/test_data_load_repair.py`

**Interfaces:**
- **Consumes:** a DuckDB connection holding some or all of the 13 tables.
- **Produces, in `repair.py`:**
  - `LINKS` (the ERD's 24 declared links) and `OWNED`;
  - `LinkError`;
  - `repair(con) -> dict[str, dict[str, int]]`, keyed by rule id `"R6a"`, `"R1"`, `"R6b"`, `"R2"`, `"R3"`, `"R4"`;
  - `check_links(con) -> None`, which raises `LinkError` naming every failed check.
- **Partial data:** a rule or check runs only when all of its tables are loaded, so unit tests can load a few.
- **Rule order:** R6a → R1 → R6b → R2 → R3 → R4 (spec 6.1).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_data_load_repair.py`:

```python
"""Repairs R1-R6 and link checks (spec section 6), on tiny hand-built tables."""

from datetime import date, datetime

import duckdb
import pytest

from data_load.repair import LinkError, check_links, repair

# Only the columns the repairs and link checks touch
COLUMNS = {
    "branches": "branch_id VARCHAR PRIMARY KEY",
    "customers": "customer_id VARCHAR PRIMARY KEY, registration_branch_id VARCHAR, registration_date TIMESTAMP",
    "products": "product_id VARCHAR PRIMARY KEY, customer_id VARCHAR, product_type VARCHAR, "
    "opening_branch_id VARCHAR, opening_date DATE",
    "transactions": "transaction_id VARCHAR PRIMARY KEY, product_id VARCHAR, customer_id VARCHAR, "
    "branch_id VARCHAR, transaction_date TIMESTAMP",
    "service_agents": "agent_id VARCHAR PRIMARY KEY, assigned_branch_id VARCHAR",
    "complaints": "complaint_id VARCHAR PRIMARY KEY, customer_id VARCHAR, affected_product_id VARCHAR, "
    "related_branch_id VARCHAR, assigned_agent_id VARCHAR, origin_interaction_id VARCHAR",
    "digital_events": "event_id VARCHAR PRIMARY KEY, customer_id VARCHAR, product_id VARCHAR",
}
CARD, SAVINGS = "Tarjeta Crédito", "Cuenta Ahorro"
OLD = datetime(2020, 1, 1)


def db(**tables: list[tuple]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for name, rows in tables.items():
        con.execute(f"CREATE TABLE {name} ({COLUMNS[name]})")
        if rows:
            marks = ", ".join("?" * len(rows[0]))
            con.executemany(f"INSERT INTO {name} VALUES ({marks})", rows)
    return con


def column(con, table: str, key: str, col: str) -> dict:
    return dict(con.execute(f"SELECT {key}, {col} FROM {table}").fetchall())


@pytest.mark.unit
def test_r6a_moves_opening_date_back_to_the_first_transaction():
    con = db(
        products=[
            ("P1", "C1", CARD, "B1", date(2025, 1, 10)),
            ("P2", "C1", SAVINGS, "B1", date(2024, 1, 1)),
        ],
        transactions=[
            ("T1", "P1", "C1", None, datetime(2024, 12, 31, 23, 0)),
            ("T2", "P1", "C1", None, datetime(2025, 2, 1)),
            ("T3", "P2", "C1", None, datetime(2024, 5, 1)),
        ],
    )
    assert repair(con) == {"R6a": {"changed": 1}}
    assert column(con, "products", "product_id", "opening_date") == {
        "P1": date(2024, 12, 31),
        "P2": date(2024, 1, 1),
    }
    check_links(con)


@pytest.mark.unit
def test_r1_takes_the_branch_of_the_earliest_product_or_null():
    con = db(
        branches=[("B1",), ("B2",)],
        customers=[("C1", "SUC-X", OLD), ("C2", "B2", OLD), ("C3", "SUC-Y", OLD)],
        products=[
            ("P1", "C1", CARD, "B2", date(2024, 2, 1)),
            ("P2", "C1", SAVINGS, "B1", date(2024, 1, 1)),
            ("P3", "C2", CARD, "B1", date(2024, 1, 1)),
        ],
    )
    counts = repair(con)
    assert counts["R1"] == {"resolved": 1, "set_null": 1}
    assert column(con, "customers", "customer_id", "registration_branch_id") == {
        "C1": "B1",  # earliest product P2
        "C2": "B2",  # valid: kept
        "C3": None,  # no products
    }
    check_links(con)


@pytest.mark.unit
def test_r1_breaks_ties_on_product_id():
    con = db(
        branches=[("B1",), ("B2",)],
        customers=[("C1", "SUC-X", OLD)],
        products=[
            ("P2", "C1", CARD, "B2", date(2024, 1, 1)),
            ("P1", "C1", SAVINGS, "B1", date(2024, 1, 1)),
        ],
    )
    repair(con)
    assert column(con, "customers", "customer_id", "registration_branch_id") == {
        "C1": "B1"
    }


@pytest.mark.unit
def test_r6b_uses_the_opening_dates_r6a_fixed():
    con = db(
        branches=[("B1",)],
        customers=[
            ("C1", "B1", datetime(2024, 3, 5, 10, 0)),
            ("C2", "B1", datetime(2024, 1, 1, 8, 0)),
        ],
        products=[
            ("P1", "C1", CARD, "B1", date(2024, 3, 1)),
            ("P2", "C2", CARD, "B1", date(2024, 1, 1)),  # same day: not before
        ],
        transactions=[("T1", "P1", "C1", None, datetime(2024, 2, 15, 9, 30))],
    )
    counts = repair(con)
    assert counts["R6a"] == {"changed": 1} and counts["R6b"] == {"changed": 1}
    assert column(con, "customers", "customer_id", "registration_date") == {
        "C1": datetime(2024, 2, 15),  # R6a moved P1 to 2024-02-15 first
        "C2": datetime(2024, 1, 1, 8, 0),
    }
    check_links(con)


@pytest.mark.unit
def test_r2_nulls_broken_agent_branches():
    con = db(
        branches=[("B1",)],
        service_agents=[("A1", "B1"), ("A2", "SUC-X"), ("A3", None)],
    )
    assert repair(con) == {"R2": {"set_null": 1}}
    assert column(con, "service_agents", "agent_id", "assigned_branch_id") == {
        "A1": "B1",
        "A2": None,
        "A3": None,
    }


@pytest.mark.unit
def test_r3_relinks_to_the_complainants_only_product_of_that_type():
    con = db(
        products=[
            ("P1", "C1", CARD, "B1", date(2024, 1, 1)),
            ("P2", "C2", CARD, "B1", date(2024, 1, 1)),
            ("P3", "C3", CARD, "B1", date(2024, 1, 1)),
            ("P4", "C3", CARD, "B1", date(2024, 1, 1)),
            ("P5", "C4", SAVINGS, "B1", date(2024, 1, 1)),
        ],
        complaints=[
            ("K1", "C2", "P1", None, None, None),  # C2 has one card: P2
            ("K2", "C3", "P1", None, None, None),  # C3 has two cards: ambiguous
            ("K3", "C4", "P1", None, None, None),  # C4 has no card
            ("K4", "C1", "P1", None, None, None),  # already the complainant's
            ("K5", "C1", None, None, None, None),  # no product: untouched
        ],
    )
    assert repair(con) == {"R3": {"resolved": 1, "set_null": 2}}
    assert column(con, "complaints", "complaint_id", "affected_product_id") == {
        "K1": "P2",
        "K2": None,
        "K3": None,
        "K4": "P1",
        "K5": None,
    }
    check_links(con)


@pytest.mark.unit
def test_r4_nulls_anonymous_events_and_relinks_the_rest():
    con = db(
        products=[
            ("P1", "C1", CARD, "B1", date(2024, 1, 1)),
            ("P2", "C2", CARD, "B1", date(2024, 1, 1)),
        ],
        digital_events=[
            ("E1", "C2", "P1"),  # someone else's card: C2's only card is P2
            ("E2", None, "P1"),  # anonymous: ownership can't be checked
            ("E3", "C1", "P1"),  # own card: kept
            ("E4", "C2", None),  # no product: untouched
        ],
    )
    assert repair(con) == {"R4": {"resolved": 1, "set_null": 1}}
    assert column(con, "digital_events", "event_id", "product_id") == {
        "E1": "P2",
        "E2": None,
        "E3": "P1",
        "E4": None,
    }
    check_links(con)


@pytest.mark.unit
def test_rules_run_only_when_their_tables_are_loaded():
    assert repair(db(branches=[("B1",)])) == {}


@pytest.mark.unit
def test_check_links_names_every_broken_check():
    con = db(
        products=[("P1", "C1", CARD, "B1", date(2025, 1, 1))],
        transactions=[
            ("T1", "P9", "C1", None, datetime(2025, 2, 1)),  # no such product
            ("T2", "P1", "C9", None, datetime(2025, 2, 1)),  # another customer's card
            ("T3", "P1", "C1", None, datetime(2024, 6, 1)),  # before the card opened
        ],
    )
    with pytest.raises(LinkError) as err:
        check_links(con)
    message = str(err.value)
    assert "transactions.product_id -> products: 1 broken" in message
    assert "transactions.product_id: 1 owned by another customer" in message
    assert "transactions before their product's opening_date: 1" in message
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_repair.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_load.repair'`.

- [ ] **Step 3: Implement**

`data_load/repair.py`:

```python
"""Repairs R1-R6 and the link checks, run in DuckDB before anything reaches DSQL.

Spec: docs/superpowers/specs/2026-10-02-data-pipeline-design.md, section 6. Each rule
writes its fixes to a temp table first, so the counts come from the same rows the
UPDATE applies. A rule runs only when all its tables are loaded (unit tests load a few).
"""

# The ERD's 24 declared links: (child table, column, parent table, parent column)
LINKS = (
    ("customers", "registration_branch_id", "branches", "branch_id"),
    ("products", "opening_branch_id", "branches", "branch_id"),
    ("service_agents", "assigned_branch_id", "branches", "branch_id"),
    ("transactions", "branch_id", "branches", "branch_id"),
    ("complaints", "related_branch_id", "branches", "branch_id"),
    ("products", "customer_id", "customers", "customer_id"),
    ("transactions", "customer_id", "customers", "customer_id"),
    ("call_center_interactions", "customer_id", "customers", "customer_id"),
    ("call_transcripts", "customer_id", "customers", "customer_id"),
    ("satisfaction_surveys", "customer_id", "customers", "customer_id"),
    ("digital_events", "customer_id", "customers", "customer_id"),
    ("complaints", "customer_id", "customers", "customer_id"),
    ("campaign_sends", "customer_id", "customers", "customer_id"),
    ("transactions", "product_id", "products", "product_id"),
    ("digital_events", "product_id", "products", "product_id"),
    ("complaints", "affected_product_id", "products", "product_id"),
    ("call_center_interactions", "agent_id", "service_agents", "agent_id"),
    ("call_transcripts", "agent_id", "service_agents", "agent_id"),
    ("satisfaction_surveys", "agent_id", "service_agents", "agent_id"),
    ("complaints", "assigned_agent_id", "service_agents", "agent_id"),
    ("campaign_sends", "campaign_id", "marketing_campaigns", "campaign_id"),
    (
        "call_transcripts",
        "interaction_id",
        "call_center_interactions",
        "interaction_id",
    ),
    (
        "satisfaction_surveys",
        "interaction_id",
        "call_center_interactions",
        "interaction_id",
    ),
    (
        "complaints",
        "origin_interaction_id",
        "call_center_interactions",
        "interaction_id",
    ),
)
# A product reference must belong to the row's own customer
OWNED = (
    ("transactions", "product_id"),
    ("complaints", "affected_product_id"),
    ("digital_events", "product_id"),
)


class LinkError(RuntimeError):
    """A link, ownership or date check failed after the repairs."""


def _count(con, sql: str) -> int:
    return con.execute(sql).fetchone()[0]


def _tables(con) -> set[str]:
    return {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE NOT temporary"
        ).fetchall()
    }


def _resolved_and_nulled(con, fixes: str, column: str) -> dict[str, int]:
    resolved, total = con.execute(
        f"SELECT count({column}), count(*) FROM {fixes}"
    ).fetchone()
    return {"resolved": resolved, "set_null": total - resolved}


def _one_product_per_type(con) -> None:
    """A customer's only product of each type: the unambiguous relink target for R3/R4."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE one_per_type AS "
        "SELECT customer_id, product_type, min(product_id) AS product_id "
        "FROM products GROUP BY customer_id, product_type HAVING count(*) = 1"
    )


def r6a(con) -> dict[str, int]:
    """products.opening_date: no earlier than the product's first transaction."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r6a AS "
        "SELECT p.product_id, f.first_use FROM products p JOIN ("
        " SELECT product_id, min(transaction_date)::DATE AS first_use"
        " FROM transactions GROUP BY product_id) f USING (product_id) "
        "WHERE f.first_use < p.opening_date"
    )
    con.execute(
        "UPDATE products SET opening_date = f.first_use FROM fix_r6a f "
        "WHERE products.product_id = f.product_id"
    )
    return {"changed": _count(con, "SELECT count(*) FROM fix_r6a")}


def r1(con) -> dict[str, int]:
    """customers.registration_branch_id: broken -> branch of the earliest product, or NULL."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r1 AS "
        "SELECT c.customer_id, f.branch_id FROM customers c LEFT JOIN ("
        " SELECT customer_id, arg_min(opening_branch_id, (opening_date, product_id)) AS branch_id"
        " FROM products GROUP BY customer_id) f USING (customer_id) "
        "WHERE c.registration_branch_id NOT IN (SELECT branch_id FROM branches)"
    )
    con.execute(
        "UPDATE customers SET registration_branch_id = f.branch_id FROM fix_r1 f "
        "WHERE customers.customer_id = f.customer_id"
    )
    return _resolved_and_nulled(con, "fix_r1", "branch_id")


def r6b(con) -> dict[str, int]:
    """customers.registration_date: no later than the customer's first product (after R6a)."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r6b AS "
        "SELECT c.customer_id, f.first_open::TIMESTAMP AS registered FROM customers c JOIN ("
        " SELECT customer_id, min(opening_date) AS first_open"
        " FROM products GROUP BY customer_id) f USING (customer_id) "
        "WHERE f.first_open < c.registration_date::DATE"
    )
    con.execute(
        "UPDATE customers SET registration_date = f.registered FROM fix_r6b f "
        "WHERE customers.customer_id = f.customer_id"
    )
    return {"changed": _count(con, "SELECT count(*) FROM fix_r6b")}


def r2(con) -> dict[str, int]:
    """service_agents.assigned_branch_id: broken -> NULL (nothing else links agents to branches)."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r2 AS SELECT agent_id FROM service_agents "
        "WHERE assigned_branch_id NOT IN (SELECT branch_id FROM branches)"
    )
    con.execute(
        "UPDATE service_agents SET assigned_branch_id = NULL "
        "WHERE agent_id IN (SELECT agent_id FROM fix_r2)"
    )
    return {"set_null": _count(con, "SELECT count(*) FROM fix_r2")}


def r3(con) -> dict[str, int]:
    """complaints.affected_product_id: someone else's -> the complainant's only product of that type."""
    _one_product_per_type(con)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r3 AS "
        "SELECT x.complaint_id, o.product_id FROM complaints x "
        "JOIN products p ON p.product_id = x.affected_product_id "
        "LEFT JOIN one_per_type o ON o.customer_id = x.customer_id AND o.product_type = p.product_type "
        "WHERE p.customer_id <> x.customer_id"
    )
    con.execute(
        "UPDATE complaints SET affected_product_id = f.product_id FROM fix_r3 f "
        "WHERE complaints.complaint_id = f.complaint_id"
    )
    return _resolved_and_nulled(con, "fix_r3", "product_id")


def r4(con) -> dict[str, int]:
    """digital_events.product_id: as R3; anonymous events can't be checked, so NULL."""
    _one_product_per_type(con)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r4 AS "
        "SELECT x.event_id, CASE WHEN x.customer_id IS NOT NULL THEN o.product_id END AS product_id "
        "FROM digital_events x JOIN products p ON p.product_id = x.product_id "
        "LEFT JOIN one_per_type o ON o.customer_id = x.customer_id AND o.product_type = p.product_type "
        "WHERE x.customer_id IS NULL OR p.customer_id <> x.customer_id"
    )
    con.execute(
        "UPDATE digital_events SET product_id = f.product_id FROM fix_r4 f "
        "WHERE digital_events.event_id = f.event_id"
    )
    return _resolved_and_nulled(con, "fix_r4", "product_id")


# Order matters: R1 and R6b use the opening dates R6a fixed
RULES = (
    ("R6a", {"products", "transactions"}, r6a),
    ("R1", {"customers", "products", "branches"}, r1),
    ("R6b", {"customers", "products"}, r6b),
    ("R2", {"service_agents", "branches"}, r2),
    ("R3", {"complaints", "products"}, r3),
    ("R4", {"digital_events", "products"}, r4),
)


def repair(con) -> dict[str, dict[str, int]]:
    """Apply every rule whose tables are loaded, in order; return counts per rule."""
    loaded = _tables(con)
    return {rule: fix(con) for rule, needs, fix in RULES if needs <= loaded}


def check_links(con) -> None:
    """Fail, naming every broken check, unless links, ownership and dates all hold."""
    loaded, failures = _tables(con), []
    for child, column, parent, parent_column in LINKS:
        if {child, parent} <= loaded:
            broken = _count(
                con,
                f"SELECT count(*) FROM {child} c WHERE c.{column} IS NOT NULL AND NOT EXISTS "
                f"(SELECT 1 FROM {parent} p WHERE p.{parent_column} = c.{column})",
            )
            if broken:
                failures.append(f"{child}.{column} -> {parent}: {broken:,} broken")
    for child, column in OWNED:
        if {child, "products"} <= loaded:
            foreign = _count(
                con,
                f"SELECT count(*) FROM {child} c JOIN products p ON p.product_id = c.{column} "
                "WHERE p.customer_id IS DISTINCT FROM c.customer_id",
            )
            if foreign:
                failures.append(
                    f"{child}.{column}: {foreign:,} owned by another customer"
                )
    if {"transactions", "products"} <= loaded:
        early = _count(
            con,
            "SELECT count(*) FROM transactions t JOIN products p USING (product_id) "
            "WHERE t.transaction_date::DATE < p.opening_date",
        )
        if early:
            failures.append(
                f"transactions before their product's opening_date: {early:,}"
            )
    if {"products", "customers"} <= loaded:
        early = _count(
            con,
            "SELECT count(*) FROM products p JOIN customers c USING (customer_id) "
            "WHERE p.opening_date < c.registration_date::DATE",
        )
        if early:
            failures.append(
                f"products opened before their customer registered: {early:,}"
            )
    if failures:
        raise LinkError("link checks failed: " + "; ".join(failures))
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_repair.py -q`
Expected: `9 passed`.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff check data_load tests && uv run --no-project --quiet --with ruff ruff format --check data_load tests
git add data_load/repair.py tests/unit/test_data_load_repair.py
git commit -m "feat(data-pipeline): repairs R1-R6 and the 24 link checks in DuckDB"
```


### Task 4: The schema as delivered, and the DSQL setup

**Files:**
- Modify (whole files): `data_load/schema.sql`, `data_load/ddl.py`, `data_load/dsql.py`, `tests/unit/test_data_load_ddl.py`, `tests/unit/test_data_load_dsql.py`

**Interfaces:**
- **Produces, in `ddl.py`:**
  - `SchemaPlan(data_tables: dict[str, str], roles: dict[str, str], grants: list[str], indexes: list[str])`, keyed by bare table names;
  - `split_statements(sql)`;
  - `load_plan(sql=None) -> SchemaPlan`;
  - `varchar_limits(ddl: str) -> dict[str, int]`.
- **Produces, in `dsql.py`:**
  - `connect(endpoint, profile=None)`, unchanged;
  - `schema_statements(plan) -> list[str]`;
  - `apply_schema(conn, plan, tools_role_arn: str) -> None`;
  - `build_indexes(conn, statements, sleep=time.sleep)`, unchanged;
  - `loader_cmd(endpoint, uri, table, dry_run=False)`, which targets `--schema public`;
  - `load_all(endpoint, uris, run=subprocess.run, parallel=4, dry_run=False)`.
- **Removed:**
  - `SchemaPlan.schemas`, `.views`, `.app_tables`, `.data_indexes` and `.app_indexes`;
  - `dsql.ManifestRow`, `record_manifest` and `recorded_digests`.
- **The red window opens:** after this task, `stage.py` and the old `__main__.py` no longer match `ddl.py`. `test_data_load_stage.py` and `test_data_load_cli.py` fail until Task 6, as the Global Constraints expect.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_data_load_ddl.py` (replace the whole file):

```python
"""schema.sql is the single contract for DuckDB (validation) and Aurora DSQL."""

import re

import duckdb
import pytest

from data_load.ddl import load_plan, varchar_limits

TABLES = {
    "customers",
    "service_agents",
    "products",
    "branches",
    "marketing_campaigns",
    "daily_exchange_rates",
    "transactions",
    "call_center_interactions",
    "call_transcripts",
    "satisfaction_surveys",
    "digital_events",
    "complaints",
    "campaign_sends",
}


@pytest.mark.unit
def test_plan_groups_every_statement():
    plan = load_plan()
    assert set(plan.data_tables) == TABLES
    assert plan.roles == {"ll_read": "CREATE ROLE ll_read WITH LOGIN"}
    assert plan.grants == [
        "GRANT USAGE ON SCHEMA public TO ll_read",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO ll_read",
    ]
    assert [re.search(r"ON (\w+)", s)[1] for s in plan.indexes] == [
        "transactions",
        "products",
        "complaints",
    ]


@pytest.mark.unit
def test_unknown_statement_is_rejected():
    with pytest.raises(ValueError, match="unclassified"):
        load_plan("DROP TABLE transactions;")


@pytest.mark.unit
def test_duckdb_builds_every_data_table():
    con = duckdb.connect()
    for stmt in load_plan().data_tables.values():
        con.execute(stmt)
    assert {r[0] for r in con.sql("SHOW TABLES").fetchall()} == TABLES


@pytest.mark.unit
def test_tables_as_delivered_without_foreign_keys():
    plan = load_plan()
    assert not any("." in name for name in plan.data_tables)  # one schema: public
    assert not any("REFERENCES" in ddl for ddl in plan.data_tables.values())
    assert (
        "duration_seconds integer NOT NULL" not in plan.data_tables["call_transcripts"]
    )
    assert "AI Assistant" not in plan.data_tables["complaints"]


@pytest.mark.unit
def test_read_role_can_only_read():
    for grant in load_plan().grants:
        privileges = re.fullmatch(r"GRANT (.+) ON .+ TO ll_read", grant)[1]
        assert privileges in ("USAGE", "SELECT"), grant


@pytest.mark.unit
def test_varchar_limits_come_from_the_ddl():
    limits = varchar_limits(load_plan().data_tables["branches"])
    assert limits["branch_code"] == 10 and limits["branch_id"] == 30
    assert "latitude" not in limits  # numeric, not varchar
```

`tests/unit/test_data_load_dsql.py` (replace the whole file):

```python
"""DSQL steps, tested against a fake connection (no cluster needed)."""

import subprocess
from contextlib import contextmanager

import pytest

from data_load.ddl import load_plan
from data_load.dsql import (
    apply_schema,
    build_indexes,
    load_all,
    loader_cmd,
    schema_statements,
)

TOOLS_ROLE = "arn:aws:iam::111111111111:role/ledgerlens-tools"


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        self.rows = self.conn.respond(sql)

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, respond=lambda sql: []):
        self.executed, self.respond = [], respond

    def cursor(self):
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        yield

    def sql(self):
        return [s for s, _ in self.executed]


def existing(roles=(), mappings=()):
    def respond(sql):
        if sql.startswith("SELECT rolname"):
            return [(r,) for r in roles]
        if "sys.iam_pg_role_mappings" in sql:
            return [(arn,) for arn in mappings]
        return []

    return respond


@pytest.mark.unit
def test_schema_statements_drop_then_create_every_table():
    plan = load_plan()
    stmts = schema_statements(plan)
    assert len(stmts) == 26
    for table, ddl in plan.data_tables.items():
        assert stmts.index(f"DROP TABLE IF EXISTS {table}") < stmts.index(ddl)


@pytest.mark.unit
def test_first_load_creates_the_role_maps_it_and_grants():
    plan, conn = load_plan(), FakeConn(existing())
    apply_schema(conn, plan, TOOLS_ROLE)
    sql = conn.sql()
    assert "CREATE ROLE ll_read WITH LOGIN" in sql
    assert f"AWS IAM GRANT ll_read TO '{TOOLS_ROLE}'" in sql
    assert sql.index(f"AWS IAM GRANT ll_read TO '{TOOLS_ROLE}'") < sql.index(
        plan.grants[0]
    )
    assert sql[-2:] == plan.grants  # grants last: they must see the new tables


@pytest.mark.unit
def test_reload_keeps_the_role_and_mapping_but_regrants():
    plan = load_plan()
    conn = FakeConn(existing(roles=["ll_read"], mappings=[TOOLS_ROLE]))
    apply_schema(conn, plan, TOOLS_ROLE)
    sql = conn.sql()
    assert not any(s.startswith(("CREATE ROLE", "AWS IAM GRANT")) for s in sql)
    assert sql[-2:] == plan.grants


@pytest.mark.unit
@pytest.mark.parametrize(
    "arn",
    [
        "",
        "ledgerlens-tools",
        "arn:aws:iam::111111111111:role/x'; DROP TABLE customers; --",
    ],
)
def test_a_bad_role_arn_is_refused_before_any_sql(arn):
    conn = FakeConn(existing())
    with pytest.raises(ValueError, match="not an IAM role ARN"):
        apply_schema(conn, load_plan(), arn)
    assert conn.sql() == []


@pytest.mark.unit
def test_build_indexes_fails_when_a_job_fails():
    def respond(sql):
        if sql.startswith("CREATE INDEX"):
            return [("job-9",)]
        return [("failed", "Found duplicate key")]  # sys.jobs

    with pytest.raises(RuntimeError, match="job-9, failed: Found duplicate key"):
        build_indexes(
            FakeConn(respond),
            ["CREATE INDEX ASYNC i ON products (customer_id)"],
            sleep=lambda seconds: None,
        )


@pytest.mark.unit
def test_build_indexes_polls_sys_jobs_until_complete():
    statuses = iter([[("processing", None)], [("completed", None)]])

    def respond(sql):
        return [("job-1",)] if sql.startswith("CREATE INDEX") else next(statuses)

    conn, sleeps = FakeConn(respond), []
    build_indexes(
        conn, ["CREATE INDEX ASYNC i ON products (customer_id)"], sleep=sleeps.append
    )
    assert sleeps == [10]
    # short polls only: a long sys.wait_for_job could outlive DSQL's 5-min transaction limit
    assert not any("wait_for_job" in s for s in conn.sql())


@pytest.mark.unit
def test_loader_cmd_targets_public():
    assert loader_cmd(
        "c.dsql.us-east-1.on.aws", "s3://t/clean/r/transactions.parquet", "transactions"
    ) == [
        "aurora-dsql-loader",
        "load",
        "--endpoint",
        "c.dsql.us-east-1.on.aws",
        "--source-uri",
        "s3://t/clean/r/transactions.parquet",
        "--schema",
        "public",
        "--table",
        "transactions",
        "--on-conflict",
        "do-nothing",
        "--verify",
        "count",
    ]


@pytest.mark.unit
def test_loader_dry_run_cmd_validates_without_loading():
    assert loader_cmd(
        "c.dsql.us-east-1.on.aws", "s3://t/x.parquet", "branches", dry_run=True
    )[-5:] == ["--schema", "public", "--table", "branches", "--dry-run"]


@pytest.mark.unit
def test_load_all_fails_after_every_table_was_attempted():
    attempted = []

    def fake_run(cmd, check):
        table = cmd[cmd.index("--table") + 1]
        attempted.append(table)
        if table == "transactions":
            raise subprocess.CalledProcessError(2, cmd)

    uris = {
        "digital_events": "s3://t/a",
        "transactions": "s3://t/b",
        "customers": "s3://t/c",
    }
    with pytest.raises(RuntimeError, match=r"transactions \(exit 2\)") as err:
        load_all("c.dsql.us-east-1.on.aws", uris, run=fake_run)
    assert sorted(attempted) == ["customers", "digital_events", "transactions"]
    assert "digital_events" not in str(err.value)


@pytest.mark.unit
def test_dsql_driver_imports():
    """requirements.txt must install everything aurora_dsql_psycopg imports."""
    import aurora_dsql_psycopg

    assert callable(aurora_dsql_psycopg.connect)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_ddl.py tests/unit/test_data_load_dsql.py -q`
Expected: FAIL. `1 error` during collection: `ImportError: cannot import name 'varchar_limits' from 'data_load.ddl'`.

- [ ] **Step 3: Rewrite `schema.sql`**

These are the 13 `CREATE TABLE` statements validated on 2026-09-29, with these changes:
- the `bank.` and `pii.` qualifiers are gone, so the tables land in `public`;
- the views, `app` tables, write roles and their grants are gone.

`data_load/schema.sql` (replace the whole file):

```sql
-- LedgerLens Aurora DSQL schema: the organizer's 13 tables as delivered, in public.
-- The single source of truth for types and constraints: the transform runs the CREATE TABLE
-- statements in DuckDB (validation), the load runs everything here in DSQL.
-- Design: docs/superpowers/specs/2026-10-02-data-pipeline-design.md (section 5.1)
-- File rules: statements end with a semicolon; no semicolon or double dash inside string literals.
-- No foreign keys: links are checked in the transform (spec decision D6).

CREATE TABLE customers (
  customer_id varchar(30) PRIMARY KEY, document_number varchar(30) NOT NULL, document_type varchar(12) NOT NULL,
  first_name varchar(100) NOT NULL, last_name varchar(100) NOT NULL, date_of_birth date NOT NULL, gender varchar(1),
  email varchar(100), mobile_phone varchar(20), landline_phone varchar(20), address varchar(200), city varchar(100) NOT NULL,
  state varchar(100) NOT NULL, country varchar(50) NOT NULL, postal_code varchar(10), detected_accent varchar(50),
  segment varchar(50) NOT NULL, credit_score integer, estimated_monthly_income numeric(15,2), occupation varchar(100),
  marital_status varchar(20), education_level varchar(50), registration_date timestamp NOT NULL,
  registration_branch_id varchar(30), customer_status varchar(20) NOT NULL, last_updated timestamp NOT NULL,
  accepts_marketing boolean NOT NULL
);
CREATE TABLE service_agents (
  agent_id varchar(30) PRIMARY KEY, employee_code varchar(15) NOT NULL, first_name varchar(100) NOT NULL,
  last_name varchar(100) NOT NULL, email varchar(100), phone varchar(20), native_accent varchar(50) NOT NULL,
  country_of_origin varchar(50) NOT NULL, assigned_branch_id varchar(30), agent_type varchar(30) NOT NULL,
  experience_level varchar(20) NOT NULL, languages varchar(100) NOT NULL, specialty varchar(100), hire_date date NOT NULL,
  avg_csat numeric(3,2), total_monthly_interactions integer, agent_status varchar(20) NOT NULL, work_shift varchar(20) NOT NULL
);
CREATE TABLE products (
  product_id varchar(30) PRIMARY KEY, customer_id varchar(30) NOT NULL,
  product_type varchar(50) NOT NULL CHECK (product_type IN ('Cuenta Ahorro','Tarjeta Crédito','Cuenta Corriente','Tarjeta Débito','Préstamo Personal','Préstamo Hipotecario','Inversión','Seguro')),
  product_number varchar(30) NOT NULL, currency varchar(3) NOT NULL, current_balance numeric(15,2) NOT NULL,
  credit_limit numeric(15,2), interest_rate numeric(5,2), opening_date date NOT NULL, expiration_date date,
  opening_branch_id varchar(30), product_status varchar(20) NOT NULL CHECK (product_status IN ('Active','Blocked','Closed','Suspended')),
  opening_channel varchar(30) NOT NULL, has_linked_app boolean NOT NULL, days_past_due integer,
  last_transaction_date timestamp, last_updated timestamp NOT NULL
);
CREATE TABLE branches (
  branch_id varchar(30) PRIMARY KEY, branch_code varchar(10) NOT NULL, branch_name varchar(100) NOT NULL,
  branch_type varchar(30) NOT NULL, address varchar(200) NOT NULL, city varchar(100) NOT NULL, state varchar(100) NOT NULL,
  country varchar(50) NOT NULL, postal_code varchar(10), geographic_zone varchar(50) NOT NULL, phone varchar(20) NOT NULL,
  email varchar(100), opening_time time NOT NULL, closing_time time NOT NULL, has_atms boolean NOT NULL, atm_count integer,
  has_teller_windows boolean NOT NULL, teller_window_count integer, latitude numeric(10,7), longitude numeric(10,7),
  branch_opening_date date NOT NULL, branch_status varchar(20) NOT NULL
);
CREATE TABLE marketing_campaigns (
  campaign_id varchar(30) PRIMARY KEY, campaign_name varchar(150) NOT NULL, description text, campaign_type varchar(50) NOT NULL,
  campaign_objective varchar(100) NOT NULL, promoted_product varchar(50), target_segment varchar(50), target_country varchar(50),
  start_date date NOT NULL, end_date date NOT NULL, budget numeric(12,2), campaign_status varchar(20) NOT NULL,
  expected_conversion_rate numeric(5,2)
);
CREATE TABLE daily_exchange_rates (
  date date NOT NULL, source_currency varchar(3) NOT NULL, target_currency varchar(3) NOT NULL,
  exchange_rate numeric(12,6) NOT NULL, buy_rate numeric(12,6), sell_rate numeric(12,6), source varchar(50),
  PRIMARY KEY (date, source_currency, target_currency)
);
CREATE TABLE transactions (
  transaction_id varchar(30) PRIMARY KEY, transaction_date timestamp NOT NULL, process_date date NOT NULL,
  product_id varchar(30) NOT NULL, customer_id varchar(30) NOT NULL, transaction_type varchar(50) NOT NULL,
  transaction_category varchar(50), amount numeric(15,2) NOT NULL, currency varchar(3) NOT NULL, amount_usd numeric(15,2),
  channel varchar(30) NOT NULL, branch_id varchar(30), merchant_name varchar(150), merchant_category varchar(50),
  transaction_country varchar(50) NOT NULL, transaction_city varchar(100),
  transaction_status varchar(20) NOT NULL CHECK (transaction_status IN ('Approved','Declined','Pending','Reversed')),
  response_code varchar(10) CHECK (response_code IN ('00','05','14','51','54')),
  is_fraud boolean NOT NULL, fraud_score numeric(5,2), latitude numeric(10,7), longitude numeric(10,7)
);
CREATE TABLE call_center_interactions (
  interaction_id varchar(30) PRIMARY KEY, interaction_date timestamp NOT NULL, process_date date NOT NULL,
  customer_id varchar(30) NOT NULL, agent_id varchar(30), interaction_type varchar(30) NOT NULL, channel varchar(30) NOT NULL,
  contact_reason varchar(100) NOT NULL, reason_category varchar(50) NOT NULL, duration_seconds integer, wait_time_seconds integer,
  was_resolved boolean, requires_followup boolean NOT NULL, detected_sentiment varchar(20), sentiment_score numeric(3,2),
  customer_detected_accent varchar(50), agent_used_accent varchar(50), was_escalated boolean NOT NULL,
  mentioned_products varchar(200), has_transcript boolean NOT NULL, has_recording boolean NOT NULL
);
CREATE TABLE call_transcripts (
  transcript_id varchar(30) PRIMARY KEY, interaction_id varchar(30) NOT NULL, process_date date NOT NULL,
  customer_id varchar(30) NOT NULL, agent_id varchar(30) NOT NULL, full_text text NOT NULL, customer_text text, agent_text text,
  detected_language varchar(10) NOT NULL, detected_accent varchar(50), accent_confidence numeric(3,2),
  detected_keywords varchar(500), mentioned_entities text, detected_intents varchar(300), main_topics varchar(300),
  transcription_model varchar(50) NOT NULL, audio_quality varchar(20), duration_seconds integer
);
CREATE TABLE satisfaction_surveys (
  survey_id varchar(30) PRIMARY KEY, survey_date timestamp NOT NULL, process_date date NOT NULL,
  interaction_id varchar(30) NOT NULL, customer_id varchar(30), agent_id varchar(30), survey_type varchar(20) NOT NULL,
  send_channel varchar(30), main_score smallint, nps_category varchar(20), question_1_text text, question_1_response smallint,
  question_2_text text, question_2_response smallint, question_3_text text, question_3_response smallint, open_comments text,
  comment_sentiment varchar(20), response_time_hours numeric(8,2), campaign_response_rate numeric(5,2)
);
CREATE TABLE digital_events (
  event_id varchar(30) PRIMARY KEY, event_date timestamp NOT NULL, process_date date NOT NULL, customer_id varchar(30),
  session_id varchar(50) NOT NULL, event_type varchar(50) NOT NULL, event_category varchar(50) NOT NULL, channel varchar(30) NOT NULL,
  platform varchar(30), browser varchar(50), app_version varchar(20), page_url varchar(300), page_title varchar(200),
  action varchar(100), element_id varchar(100), product_id varchar(30), event_value numeric(15,2), duration_seconds integer,
  ip_address varchar(45), ip_country varchar(50), ip_city varchar(100), is_mobile boolean NOT NULL, referrer varchar(300),
  utm_source varchar(100), utm_medium varchar(100), utm_campaign varchar(100)
);
CREATE TABLE complaints (
  complaint_id varchar(30) PRIMARY KEY, creation_date timestamp NOT NULL, process_date date NOT NULL,
  customer_id varchar(30) NOT NULL, case_type varchar(30) NOT NULL,
  category varchar(100) NOT NULL CHECK (category IN ('Branch','Fees','Service','Technical','Transactions')),
  subcategory varchar(100),
  reception_channel varchar(30) NOT NULL CHECK (reception_channel IN ('Call Center','Email','Web','App','Branch','Regulator')),
  affected_product_id varchar(30), related_branch_id varchar(30), origin_interaction_id varchar(30), description text NOT NULL,
  claimed_amount numeric(15,2), currency varchar(3), priority varchar(20) NOT NULL, status varchar(30) NOT NULL,
  assigned_agent_id varchar(30), assignment_date timestamp, first_response_date timestamp, resolution_date timestamp,
  closing_date timestamp, sla_breached boolean NOT NULL, resolution_days integer, resolution text,
  compensation_granted numeric(15,2), resolution_satisfaction smallint, is_repeat_complainer boolean NOT NULL
);
CREATE TABLE campaign_sends (
  send_id varchar(30) PRIMARY KEY, send_date timestamp NOT NULL, process_date date NOT NULL, campaign_id varchar(30) NOT NULL,
  customer_id varchar(30) NOT NULL, send_channel varchar(30) NOT NULL, template_used varchar(100), subject varchar(200),
  send_status varchar(20) NOT NULL, was_delivered boolean NOT NULL, was_opened boolean, open_date timestamp, was_clicked boolean,
  click_date timestamp, click_count integer, had_conversion boolean NOT NULL, conversion_date timestamp,
  conversion_value numeric(15,2), open_device varchar(30), open_country varchar(50), failure_reason varchar(200),
  send_cost numeric(10,4)
);

-- The tools' read-only role. Created if missing; mapped to the tools IAM role by the load.
CREATE ROLE ll_read WITH LOGIN;
-- Re-applied after every load: recreated tables lose their grants.
GRANT USAGE ON SCHEMA public TO ll_read;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ll_read;

-- Secondary indexes, only for queries the read tools run. Rebuilt after every load.
CREATE INDEX ASYNC idx_transactions_customer_date ON transactions (customer_id, transaction_date);
CREATE INDEX ASYNC idx_products_customer ON products (customer_id);
CREATE INDEX ASYNC idx_complaints_customer_date ON complaints (customer_id, creation_date);
```

Lint the new DSQL statements with the `dsql_lint` MCP tool. Pass the `CREATE TABLE branches (...)` statement, `DROP TABLE IF EXISTS branches`, the role, both grants and the three indexes.
Expected: `errors: 0, warnings: 0`. `AWS IAM GRANT` is DSQL syntax that the linter's parser doesn't know, so leave it out of the lint. Its form comes from the DSQL user guide ("Authorizing database roles").

- [ ] **Step 4: Implement `ddl.py` and `dsql.py`**

`data_load/ddl.py` (replace the whole file):

```python
"""Split schema.sql into the groups the pipeline runs at different moments."""

import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_SQL = Path(__file__).with_name("schema.sql")


@dataclass
class SchemaPlan:
    data_tables: dict[str, str] = field(default_factory=dict)  # "transactions" -> DDL
    roles: dict[str, str] = field(default_factory=dict)  # "ll_read" -> CREATE ROLE
    grants: list[str] = field(default_factory=list)  # re-applied after every load
    indexes: list[str] = field(default_factory=list)  # rebuilt after every load


def split_statements(sql: str) -> list[str]:
    """Drop '--' comments, split on ';', collapse whitespace."""
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [" ".join(s.split()) for s in without_comments.split(";") if s.strip()]


def load_plan(sql: str | None = None) -> SchemaPlan:
    if sql is None:
        sql = SCHEMA_SQL.read_text(encoding="utf-8")
    plan = SchemaPlan()
    for stmt in split_statements(sql):
        if m := re.match(r"CREATE TABLE (\w+) \(", stmt):
            plan.data_tables[m[1]] = stmt
        elif m := re.fullmatch(r"CREATE ROLE (\w+) WITH LOGIN", stmt):
            plan.roles[m[1]] = stmt
        elif stmt.startswith("GRANT "):
            plan.grants.append(stmt)
        elif re.match(r"CREATE INDEX ASYNC \w+ ON \w+ \(", stmt):
            plan.indexes.append(stmt)
        else:
            raise ValueError(f"schema.sql: unclassified statement: {stmt[:80]}")
    return plan


def varchar_limits(ddl: str) -> dict[str, int]:
    """column -> n for every varchar(n) column of one CREATE TABLE statement."""
    return {m[1]: int(m[2]) for m in re.finditer(r"(\w+) varchar\((\d+)\)", ddl)}
```

`data_load/dsql.py` (replace the whole file):

```python
"""Everything that touches Aurora DSQL: tables, the read role and its IAM mapping, bulk load, indexes."""

import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from data_load.ddl import SchemaPlan

LOADER = "aurora-dsql-loader"
POLL_SECONDS = 10
READ_ROLE = "ll_read"
ROLE_ARN = re.compile(r"arn:aws:iam::\d{12}:role/[\w+=,.@/-]+")


def connect(endpoint: str, profile: str | None = None):
    """Connect as admin; autocommit because DSQL allows one DDL per transaction."""
    import aurora_dsql_psycopg as dsql  # lazy: unit tests don't need the driver

    params = {"host": endpoint, "user": "admin"}
    if profile:
        params["profile"] = profile
    conn = dsql.connect(**params)
    conn.autocommit = True
    return conn


def schema_statements(plan: SchemaPlan) -> list[str]:
    """Every load recreates the 13 tables: DSQL has no TRUNCATE (spec section 5.4)."""
    return [
        *(f"DROP TABLE IF EXISTS {table}" for table in plan.data_tables),
        *plan.data_tables.values(),
    ]


def apply_schema(conn, plan: SchemaPlan, tools_role_arn: str) -> None:
    """Tables, then ll_read and its IAM mapping (if missing), then the grants."""
    if not ROLE_ARN.fullmatch(tools_role_arn):  # it is spliced into AWS IAM GRANT below
        raise ValueError(f"not an IAM role ARN: {tools_role_arn!r}")
    with conn.cursor() as cur:
        for stmt in schema_statements(plan):
            cur.execute(stmt)
        cur.execute("SELECT rolname FROM pg_roles")
        existing_roles = {row[0] for row in cur.fetchall()}
        for role, stmt in plan.roles.items():
            if role not in existing_roles:
                cur.execute(stmt)
        cur.execute(
            "SELECT arn FROM sys.iam_pg_role_mappings WHERE pg_role_name = %s",
            (READ_ROLE,),
        )
        if tools_role_arn not in {row[0] for row in cur.fetchall()}:
            cur.execute(f"AWS IAM GRANT {READ_ROLE} TO '{tools_role_arn}'")
        for stmt in plan.grants:  # recreated tables lose their grants
            cur.execute(stmt)


def build_indexes(conn, statements: list[str], sleep=time.sleep) -> None:
    """Submit every CREATE INDEX ASYNC, then wait for each job."""
    with conn.cursor() as cur:
        jobs = []
        for stmt in statements:
            cur.execute(stmt)
            jobs.append((cur.fetchone()[0], stmt))
        for job_id, stmt in jobs:
            _wait_for_job(cur, job_id, stmt, sleep)


def _wait_for_job(cur, job_id: str, stmt: str, sleep) -> None:
    """Poll sys.jobs with short statements: a long sys.wait_for_job call could
    outlive DSQL's 5-minute transaction limit on a big index."""
    while True:
        cur.execute("SELECT status, details FROM sys.jobs WHERE job_id = %s", (job_id,))
        rows = cur.fetchall()
        status, details = rows[0] if rows else ("missing", "job not found")
        if status == "completed":
            return
        if status not in ("submitted", "processing"):
            raise RuntimeError(
                f"index build failed (job {job_id}, {status}: {details}): {stmt}"
            )
        sleep(POLL_SECONDS)


def loader_cmd(endpoint: str, uri: str, table: str, dry_run: bool = False) -> list[str]:
    cmd = [LOADER, "load", "--endpoint", endpoint, "--source-uri", uri]
    cmd += ["--schema", "public", "--table", table]
    if (
        dry_run
    ):  # checks the file against the table without loading: seconds, not an hour
        return [*cmd, "--dry-run"]
    return [*cmd, "--on-conflict", "do-nothing", "--verify", "count"]


def load_all(
    endpoint: str,
    uris: dict[str, str],
    run=subprocess.run,
    parallel: int = 4,
    dry_run: bool = False,
) -> None:
    """Load (or dry-run) every Parquet file; once all finish, fail if any table failed."""

    def load_one(table: str) -> str | None:
        try:
            run(loader_cmd(endpoint, uris[table], table, dry_run), check=True)
        except subprocess.CalledProcessError as e:
            return f"{table} (exit {e.returncode})"
        return None

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        failed = [f for f in pool.map(load_one, uris) if f]
    if failed:
        step = "dry run" if dry_run else "load"
        raise RuntimeError(
            f"aurora-dsql-loader {step} failed for: " + ", ".join(failed)
        )
```

- [ ] **Step 5: Run them to verify they pass**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_ddl.py tests/unit/test_data_load_dsql.py -q`
Expected: `18 passed`.

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff check data_load tests && uv run --no-project --quiet --with ruff ruff format --check data_load tests
git add data_load/schema.sql data_load/ddl.py data_load/dsql.py tests/unit/test_data_load_ddl.py tests/unit/test_data_load_dsql.py
git commit -m "feat(data-pipeline): 13 tables as delivered in public; ll_read mapped to the tools role"
```


### Task 5: Stage 2, transform, with the full rehearsal

**Files:**
- Create: `data_load/transform.py`, `data_load/expected.json`, `tests/unit/test_data_load_transform.py`
- Modify: `tests/unit/data_load_fixtures.py`: delete the `from datetime import datetime` line and the `AS_OF = ...` line. Nothing uses them now that there's no load window.
- Delete: `data_load/stage.py`, `tests/unit/test_data_load_stage.py`

**Interfaces:**
- **Consumes:**
  - `ddl.load_plan`, `ddl.varchar_limits` and `ddl.SchemaPlan` (Task 4);
  - `repair.repair`, `repair.check_links` and `repair.LinkError` (Task 3);
  - `source.EVENT_TABLES` (Task 1);
  - `FakeS3` (Task 1).
- **Produces, in `transform.py`:**
  - `EXPECTED`;
  - `TransformError`;
  - `Table(name, path, rows, sha256)`;
  - `load_expected(path=EXPECTED) -> dict`;
  - `source_glob(source, table)`;
  - `sha256_file(path)`;
  - `download_raw(s3, bucket, run_id, dest: Path, workers=16) -> int`;
  - `transform(source: str, out_dir: Path, *, plan=None, tables=None, expected=None) -> tuple[list[Table], dict]`.
- **`expected.json` format:** `{"rows": {table: n}, "repairs": {rule: {...}}}`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_data_load_transform.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_transform.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_load.transform'`.

- [ ] **Step 3: Implement**

`data_load/transform.py`:

```python
"""Stage 2: raw CSVs -> typed, checked, repaired Parquet (spec sections 4.1 and 6).

schema.sql is the contract: every row is read as text and inserted into tables built
from that DDL, so DuckDB casts each column and enforces NOT NULL, CHECK and PRIMARY
KEY. DuckDB ignores varchar(n), so lengths are checked separately. Then the repairs
run, then the link checks; nothing reaches S3 or DSQL unless all of them pass.
"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import duckdb

from data_load import repair
from data_load.ddl import SchemaPlan, load_plan, varchar_limits
from data_load.source import EVENT_TABLES

EXPECTED = Path(__file__).with_name("expected.json")


class TransformError(RuntimeError):
    """A row broke schema.sql, a check failed, or counts differ from expected.json."""


@dataclass(frozen=True)
class Table:
    name: str
    path: Path
    rows: int
    sha256: str


def load_expected(path: Path = EXPECTED) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_glob(source: str, table: str) -> str:
    base = source.rstrip("/")
    if table in EVENT_TABLES:  # year=/month=/day=/<table>_<yyyymmdd>.csv
        return f"{base}/{table}/*/*/*/*.csv"
    return f"{base}/{table}.csv"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_raw(s3, bucket: str, run_id: str, dest: Path, workers: int = 16) -> int:
    """Mirror raw/<run-id>/ to dest, keeping the organizer's folder layout."""
    prefix = f"raw/{run_id}/"
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix
    ):
        keys += [o["Key"] for o in page.get("Contents", [])]
    if not keys:
        raise TransformError(f"nothing under s3://{bucket}/{prefix}: run ingest first")

    def get(key: str) -> None:
        target = dest / key[len(prefix) :]
        target.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(target))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(get, keys))
    return len(keys)


def transform(
    source: str,
    out_dir: Path,
    *,
    plan: SchemaPlan | None = None,
    tables: list[str] | None = None,
    expected: dict | None = None,
) -> tuple[list[Table], dict]:
    """Return the Parquet files and the per-rule repair counts."""
    plan = plan or load_plan()
    names = [t for t in plan.data_tables if not tables or t in tables]
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "transform.duckdb"  # on disk: digital_events has 15.6M rows
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("SET enable_progress_bar = false")  # keeps CodeBuild logs readable
    try:
        for name in names:
            _read_table(con, source, name, plan.data_tables[name])
        try:
            counts = repair.repair(con)
            repair.check_links(con)
        except (duckdb.Error, repair.LinkError) as e:
            raise TransformError(str(e)) from None
        rows = {
            n: con.execute(f"SELECT count(*) FROM {n}").fetchone()[0] for n in names
        }
        if expected is not None:
            _compare(expected, rows, counts)
        return [_write(con, out_dir, n, rows[n]) for n in names], counts
    finally:
        con.close()


def _read_table(con, source: str, name: str, ddl: str) -> None:
    con.execute(ddl)
    csv = (
        f"read_csv('{source_glob(source, name)}', header=true, all_varchar=true, "
        "union_by_name=true, hive_partitioning=false)"
    )
    try:
        con.execute(f"INSERT INTO {name} BY NAME SELECT * FROM {csv}")
    except duckdb.Error as e:
        raise TransformError(f"{name}: {e}") from None
    _check_lengths(con, name, ddl)
    rows = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    print(f"read {name}: {rows:,} rows", flush=True)


def _check_lengths(con, name: str, ddl: str) -> None:
    limits = varchar_limits(ddl)
    if not limits:
        return
    over = con.execute(
        "SELECT "
        + ", ".join(
            f"count(*) FILTER (WHERE length({c}) > {n})" for c, n in limits.items()
        )
        + f" FROM {name}"
    ).fetchone()
    bad = [
        f"{c} longer than {n} in {k:,} rows"
        for (c, n), k in zip(limits.items(), over)
        if k
    ]
    if bad:
        raise TransformError(f"{name}: " + "; ".join(bad))


def _compare(expected: dict, rows: dict[str, int], counts: dict) -> None:
    diffs = [
        f"{name}: {n:,} rows, expected {expected['rows'].get(name)}"
        for name, n in rows.items()
        if expected["rows"].get(name) != n
    ]
    if counts != expected["repairs"]:
        diffs.append(f"repairs {counts}, expected {expected['repairs']}")
    if diffs:
        raise TransformError("differs from expected.json: " + "; ".join(diffs))


def _write(con, out_dir: Path, name: str, rows: int) -> Table:
    path = out_dir / f"{name}.parquet"
    con.execute(f"COPY {name} TO '{path.as_posix()}' (FORMAT parquet)")
    print(f"wrote {path.name}: {rows:,} rows", flush=True)
    return Table(name, path, rows, sha256_file(path))
```

`data_load/expected.json`:

```json
{
  "rows": {
    "branches": 350,
    "call_center_interactions": 686296,
    "call_transcripts": 171321,
    "campaign_sends": 1746801,
    "complaints": 67095,
    "customers": 150000,
    "daily_exchange_rates": 13164,
    "digital_events": 15620994,
    "marketing_campaigns": 200,
    "products": 400000,
    "satisfaction_surveys": 212759,
    "service_agents": 1200,
    "transactions": 4425008
  },
  "repairs": {
    "R6a": {"changed": 117640},
    "R1": {"resolved": 139573, "set_null": 10422},
    "R6b": {"changed": 99633},
    "R2": {"set_null": 831},
    "R3": {"resolved": 13808, "set_null": 30762},
    "R4": {"resolved": 337760, "set_null": 1102562}
  }
}
```

Remove the replaced module and its test, and clean up the fixture:

```bash
git rm data_load/stage.py tests/unit/test_data_load_stage.py
```

In `tests/unit/data_load_fixtures.py`, delete the line `from datetime import datetime` and the line `AS_OF = datetime(2026, 6, 17, 23, 59, 59)`. Keep the blank-line layout `ruff format` expects.

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_transform.py tests/unit/test_data_load_repair.py tests/unit/test_data_load_ddl.py -q`
Expected: `27 passed`.

- [ ] **Step 5: Run the full rehearsal on the local copy**

This takes about 7 minutes and needs about 8 GB of free disk for the DuckDB database and the Parquet files. `--out` must be outside the repo.

```bash
uv run --no-project --quiet --with-requirements data_load/requirements.txt python -c "
import tempfile
from pathlib import Path
from data_load.transform import load_expected, transform
out = Path(tempfile.gettempdir()) / 'ledgerlens-rehearsal'
tables, counts = transform('datathon/data', out, expected=load_expected())
print('TOTAL', sum(t.rows for t in tables), 'rows in', len(tables), 'tables')
print('REPAIRS', counts)
print('PARQUET MB', round(sum(t.path.stat().st_size for t in tables) / 1e6, 1))
"
```

Expected (the prototype's run on 2026-10-02):
- `TOTAL 23495188 rows in 13 tables`;
- `REPAIRS {'R6a': {'changed': 117640}, 'R1': {'resolved': 139573, 'set_null': 10422}, 'R6b': {'changed': 99633}, 'R2': {'set_null': 831}, 'R3': {'resolved': 13808, 'set_null': 30762}, 'R4': {'resolved': 337760, 'set_null': 1102562}}`;
- `PARQUET MB 1217.1`.

No `TransformError` should appear, because the link checks and `expected.json` both pass. Note the wall time for spec section 11, then delete the output directory.

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff check data_load tests && uv run --no-project --quiet --with ruff ruff format --check data_load tests
git add data_load/transform.py data_load/expected.json tests/unit/test_data_load_transform.py tests/unit/data_load_fixtures.py
git commit -m "feat(data-pipeline): transform stage checks, repairs and writes Parquet; rehearsal matches expected counts"
```

(`git rm` in Step 3 already staged the two deletions.)


### Task 6: The stage commands

**Files:**
- Modify (whole files): `data_load/__main__.py`, `data_load/__init__.py`, `tests/unit/test_data_load_cli.py`

**Interfaces:**
- **Consumes:**
  - `ingest.load_secret` and `ingest.ingest` (Task 2);
  - `transform.transform`, `transform.download_raw`, `transform.load_expected` and `transform.Table` (Task 5);
  - `dsql.connect`, `apply_schema`, `load_all` and `build_indexes` (Task 4);
  - `runrecord.read` and `runrecord.write` (Task 1);
  - `source.fingerprint` and `source.drift` (Task 1).
- **Produces:** `python -m data_load {ingest,transform,load,check}`. The CodeBuild environment Task 8 relies on:
  - `ingest` needs `RUN_ID`, `TEAM_BUCKET` and `HACKATHON_SECRET_ID`;
  - `transform` needs `RUN_ID` and `TEAM_BUCKET`, unless it gets `--source`;
  - `load` needs `RUN_ID`, `TEAM_BUCKET`, `DSQL_ENDPOINT` and `TOOLS_ROLE_ARN`.
- **The red window closes here.**

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_data_load_cli.py` (replace the whole file):

```python
"""python -m data_load: stage commands, their environment, and the load order."""

import json
from pathlib import Path
from unittest import mock

import pytest
from data_load_fixtures import tx, write_transactions
from data_load_s3 import FakeS3

from data_load import runrecord
from data_load.__main__ import main
from data_load.ddl import load_plan
from data_load.source import EVENT_TABLES, etag_digest, source_prefix
from data_load.transform import Table, load_expected


@pytest.mark.unit
def test_transform_command_writes_parquet_locally(tmp_path, capsys):
    write_transactions(
        tmp_path / "src",
        [
            tx("T1", "2026-06-17 10:00:00", "2026-06-17"),
            tx("T2", "2026-06-18 03:00:00", "2026-06-17"),
        ],
    )
    code = main(
        [
            "transform",
            "--source",
            (tmp_path / "src").as_posix(),
            "--out",
            str(tmp_path / "out"),
            "--tables",
            "transactions",
        ]
    )
    assert code == 0
    assert (tmp_path / "out" / "transactions.parquet").exists()
    assert "total 2 rows in 1 tables" in capsys.readouterr().out


@pytest.mark.unit
def test_tables_subset_is_for_local_runs_only():
    with pytest.raises(SystemExit, match="only for local runs"):
        main(["transform", "--tables", "transactions"])


@pytest.mark.unit
@pytest.mark.parametrize(
    "command, names",
    [
        (["ingest"], "RUN_ID, TEAM_BUCKET, HACKATHON_SECRET_ID"),
        (["transform"], "RUN_ID, TEAM_BUCKET"),
        (["load"], "RUN_ID, TEAM_BUCKET, DSQL_ENDPOINT, TOOLS_ROLE_ARN"),
    ],
)
def test_stages_list_missing_environment(monkeypatch, command, names):
    for name in (
        "RUN_ID",
        "TEAM_BUCKET",
        "HACKATHON_SECRET_ID",
        "DSQL_ENDPOINT",
        "TOOLS_ROLE_ARN",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match=f"missing environment variables: {names}$"):
        main(command)


@pytest.mark.unit
def test_cloud_transform_starts_clean_uploads_parquet_and_records(
    monkeypatch, tmp_path
):
    for name, value in {"RUN_ID": "run-1", "TEAM_BUCKET": "team"}.items():
        monkeypatch.setenv(name, value)
    s3 = FakeS3({("team", "raw/run-1/customers.csv"): b"c"})
    monkeypatch.setattr("boto3.client", lambda *a, **k: s3)
    stale = tmp_path / "raw" / "transactions" / "stale.csv"  # left by an earlier run
    stale.parent.mkdir(parents=True)
    stale.write_text("old run")
    seen = {}

    def fake_transform(source, out_dir, expected=None, **kwargs):
        files = Path(source).rglob("*")
        seen["files"] = sorted(
            p.relative_to(source).as_posix() for p in files if p.is_file()
        )
        seen["expected"] = expected
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "customers.parquet"
        path.write_bytes(b"parquet")
        return [Table("customers", path, 150_000, "s" * 64)], {
            "R1": {"resolved": 1, "set_null": 0}
        }

    monkeypatch.setattr("data_load.transform.transform", fake_transform)
    assert main(["transform", "--out", str(tmp_path)]) == 0
    assert seen["files"] == ["customers.csv"]  # the stale file is gone
    assert seen["expected"] == load_expected()
    assert s3.objects[("team", "clean/run-1/customers.parquet")] == b"parquet"
    assert s3.objects[("team", "clean/run-1/customers.parquet.sha256")] == b"s" * 64
    record = runrecord.read(s3, "team", "run-1", "transform")
    assert record["tables"]["customers"] == {
        "rows": 150_000,
        "uri": "s3://team/clean/run-1/customers.parquet",
        "sha256": "s" * 64,
    }
    assert record["repairs"] == {"R1": {"resolved": 1, "set_null": 0}}


@pytest.mark.unit
def test_ingest_takes_the_organizer_keys_from_secrets_manager(monkeypatch, capsys):
    secret = {
        "aws_access_key_id": "fake-key-id",
        "aws_secret_access_key": "fake-secret-value",
        "bucket": "org",
        "region": "us-east-2",
        "prefix": "data/",
    }
    org = FakeS3(
        {
            (
                "org",
                source_prefix("data/", t) + ("x.csv" if t in EVENT_TABLES else ""),
            ): b"x"
            for t in load_plan().data_tables
        }
    )
    team, clients = FakeS3(), []

    class Secrets:
        def get_secret_value(self, SecretId):
            assert SecretId == "ledgerlens/hackathon-s3"
            return {"SecretString": json.dumps(secret)}

    def client(service, **kwargs):
        clients.append((service, kwargs.get("aws_access_key_id")))
        if service == "secretsmanager":
            return Secrets()
        return org if kwargs.get("aws_access_key_id") else team

    monkeypatch.setattr("boto3.client", client)
    monkeypatch.delenv("HACKATHON_S3", raising=False)
    for name, value in {
        "RUN_ID": "run-1",
        "TEAM_BUCKET": "team",
        "HACKATHON_SECRET_ID": "ledgerlens/hackathon-s3",
    }.items():
        monkeypatch.setenv(name, value)
    assert main(["ingest"]) == 0
    assert ("s3", "fake-key-id") in clients  # organizer reads use the organizer's keys
    record = runrecord.read(team, "team", "run-1", "ingest")
    assert len(record["tables"]) == 13
    assert "fake-secret-value" not in capsys.readouterr().out


def fake_check_env(monkeypatch, org_files):
    """cmd_check reads ingest.json with one profile and the organizer bucket with another."""
    team, org = FakeS3(), FakeS3(org_files)
    objects = [["data/customers.csv", "etag-data/customers.csv", 1]]
    record = {
        "source": {"bucket": "org", "prefix": "data/", "region": "us-east-2"},
        "tables": {"customers": {"etag_digest": etag_digest(objects)}},
    }
    runrecord.write(team, "team", "run-1", "ingest", record)
    sessions = {"ledgerlens": team, "hackathon": org}

    class Session:
        def __init__(self, profile_name):
            self.profile = profile_name

        def client(self, service, **kwargs):
            return sessions[self.profile]

    monkeypatch.setattr("boto3.Session", Session)


@pytest.mark.unit
def test_check_reports_no_drift_when_the_bucket_is_unchanged(monkeypatch, capsys):
    fake_check_env(monkeypatch, {("org", "data/customers.csv"): b"c"})
    assert main(["check", "--run", "run-1", "--team-bucket", "team"]) == 0
    assert "no drift: the bucket matches run run-1" in capsys.readouterr().out


@pytest.mark.unit
def test_check_names_tables_that_changed_since_the_ingest(monkeypatch, capsys):
    # a second object under the customers prefix changes the ETag digest
    fake_check_env(
        monkeypatch,
        {("org", "data/customers.csv"): b"c", ("org", "data/customers.csv.bak"): b"x"},
    )
    assert main(["check", "--run", "run-1", "--team-bucket", "team"]) == 1
    assert "changed since the ingest: customers" in capsys.readouterr().out


def fake_load_env(monkeypatch, tables):
    """Everything cmd_load touches, faked; returns the S3 fake and recorded calls."""
    env = {
        "RUN_ID": "run-1",
        "TEAM_BUCKET": "team",
        "DSQL_ENDPOINT": "c.dsql.us-east-1.on.aws",
        "TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-tools",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    s3 = FakeS3()
    record = {
        "tables": {
            t: {
                "rows": rows,
                "uri": f"s3://team/clean/run-1/{t}.parquet",
                "sha256": "s",
            }
            for t, rows in tables.items()
        }
    }
    runrecord.write(s3, "team", "run-1", "transform", record)
    monkeypatch.setattr("boto3.client", lambda *a, **k: s3)
    calls = []
    monkeypatch.setattr("data_load.dsql.connect", lambda *a, **k: mock.MagicMock())
    monkeypatch.setattr(
        "data_load.dsql.apply_schema",
        lambda conn, plan, arn: calls.append(("schema", arn)),
    )
    monkeypatch.setattr(
        "data_load.dsql.load_all",
        lambda endpoint, uris, dry_run=False: calls.append(
            ("dry" if dry_run else "load", list(uris))
        ),
    )
    monkeypatch.setattr(
        "data_load.dsql.build_indexes",
        lambda conn, stmts: calls.append(("indexes", len(stmts))),
    )
    return s3, calls


@pytest.mark.unit
def test_load_dry_runs_every_table_largest_first_then_loads(monkeypatch):
    tables = {t: i for i, t in enumerate(load_plan().data_tables)}
    s3, calls = fake_load_env(monkeypatch, tables)
    assert main(["load"]) == 0
    order = sorted(tables, key=tables.get, reverse=True)
    assert calls == [
        ("schema", "arn:aws:iam::111111111111:role/ledgerlens-tools"),
        ("dry", order),
        ("load", order),
        ("indexes", 3),
    ]
    loaded = runrecord.read(s3, "team", "run-1", "load")["tables"]
    assert loaded[order[0]] == {"rows_loaded": tables[order[0]]}


@pytest.mark.unit
def test_load_refuses_an_incomplete_transform_record(monkeypatch):
    _, calls = fake_load_env(monkeypatch, {"branches": 350})
    with pytest.raises(
        SystemExit, match="transform.json lacks tables: call_center_interactions"
    ):
        main(["load"])
    assert calls == []  # stopped before touching DSQL
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_cli.py -q`
Expected: FAIL. `1 error` during collection: `ModuleNotFoundError: No module named 'data_load.stage'`, because the old `__main__.py` still imports it.

- [ ] **Step 3: Implement**

`data_load/__main__.py` (replace the whole file):

```python
"""python -m data_load {ingest,transform,load,check}: the data pipeline's stages.

CodeBuild runs `python -m data_load $STAGE` for stages 1-3; Step Functions sets STAGE
and RUN_ID. Design: docs/superpowers/specs/2026-10-02-data-pipeline-design.md
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from data_load.ddl import load_plan

WORK = Path(tempfile.gettempdir()) / "ledgerlens-pipeline"


def require_env(*names: str) -> list[str]:
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"missing environment variables: {', '.join(missing)}")
    return [os.environ[name] for name in names]


def cmd_ingest(args) -> int:
    run_id, bucket, secret_id = require_env(
        "RUN_ID", "TEAM_BUCKET", "HACKATHON_SECRET_ID"
    )
    import boto3

    from data_load import ingest, runrecord

    secret = ingest.load_secret(boto3.client("secretsmanager"), secret_id)
    org_s3 = boto3.client(
        "s3",
        region_name=secret["region"],
        aws_access_key_id=secret["aws_access_key_id"],
        aws_secret_access_key=secret["aws_secret_access_key"],
    )
    team_s3 = boto3.client("s3")
    tables = list(load_plan().data_tables)
    record = ingest.ingest(org_s3, team_s3, secret, bucket, run_id, tables)
    uri = runrecord.write(team_s3, bucket, run_id, "ingest", record)
    files = sum(t["files"] for t in record["tables"].values())
    print(
        f"ingest: {files:,} files copied to {record['raw_prefix']}, record {uri}",
        flush=True,
    )
    return 0


def cmd_transform(args) -> int:
    from data_load.transform import download_raw, load_expected, transform

    if args.tables and not args.source:
        raise SystemExit("--tables is only for local runs with --source")
    tables = args.tables.split(",") if args.tables else None
    expected = None if tables else load_expected()
    if args.source:  # local rehearsal: nothing in AWS is read or written
        written, counts = transform(
            args.source, Path(args.out), tables=tables, expected=expected
        )
        print(f"total {sum(t.rows for t in written):,} rows in {len(written)} tables")
        print(f"repairs {counts}")
        return 0

    run_id, bucket = require_env("RUN_ID", "TEAM_BUCKET")
    import boto3

    from data_load import runrecord

    s3 = boto3.client("s3")
    raw = Path(args.out) / "raw"
    shutil.rmtree(raw, ignore_errors=True)  # a stale file would join the CSV globs
    download_raw(s3, bucket, run_id, raw)
    written, counts = transform(
        raw.as_posix(), Path(args.out) / "clean", expected=expected
    )
    record = {"run_id": run_id, "repairs": counts, "tables": {}}
    for table in written:
        key = f"clean/{run_id}/{table.path.name}"
        s3.upload_file(str(table.path), bucket, key)
        s3.put_object(Bucket=bucket, Key=f"{key}.sha256", Body=table.sha256.encode())
        record["tables"][table.name] = {
            "rows": table.rows,
            "uri": f"s3://{bucket}/{key}",
            "sha256": table.sha256,
        }
    uri = runrecord.write(s3, bucket, run_id, "transform", record)
    print(f"transform: {sum(t.rows for t in written):,} rows, record {uri}", flush=True)
    return 0


def cmd_load(args) -> int:
    run_id, bucket, endpoint, tools_role = require_env(
        "RUN_ID", "TEAM_BUCKET", "DSQL_ENDPOINT", "TOOLS_ROLE_ARN"
    )
    import boto3

    from data_load import dsql, runrecord

    s3 = boto3.client("s3")
    staged = runrecord.read(s3, bucket, run_id, "transform")["tables"]
    plan = load_plan()
    if set(staged) != set(plan.data_tables):
        missing = sorted(set(plan.data_tables) - set(staged))
        raise SystemExit(f"transform.json lacks tables: {', '.join(missing)}")
    # largest first, so the longest load starts first
    order = sorted(staged, key=lambda t: staged[t]["rows"], reverse=True)
    uris = {table: staged[table]["uri"] for table in order}

    conn = dsql.connect(endpoint)
    try:
        dsql.apply_schema(conn, plan, tools_role)
    finally:
        conn.close()
    dsql.load_all(
        endpoint, uris, dry_run=True
    )  # seconds: catches type mismatches early
    dsql.load_all(endpoint, uris)  # --verify count fails the stage on any shortfall
    conn = dsql.connect(endpoint)  # a DSQL connection lives at most 60 minutes
    try:
        dsql.build_indexes(conn, plan.indexes)
    finally:
        conn.close()
    record = {
        "run_id": run_id,
        "tables": {t: {"rows_loaded": staged[t]["rows"]} for t in order},
    }
    uri = runrecord.write(s3, bucket, run_id, "load", record)
    total = sum(staged[t]["rows"] for t in order)
    print(f"load: {total:,} rows in {len(order)} tables, record {uri}", flush=True)
    return 0


def cmd_check(args) -> int:
    import boto3

    from data_load import runrecord, source

    team_s3 = boto3.Session(profile_name=args.team_profile).client("s3")
    record = runrecord.read(team_s3, args.team_bucket, args.run, "ingest")
    origin = record["source"]
    org_s3 = boto3.Session(profile_name=args.bucket_profile).client(
        "s3", region_name=origin["region"]
    )
    current = source.fingerprint(
        org_s3, origin["bucket"], origin["prefix"], list(record["tables"])
    )
    changed = source.drift(
        {t: v["etag_digest"] for t, v in record["tables"].items()},
        {t: digest for t, (_, digest) in current.items()},
    )
    if changed:
        print("changed since the ingest: " + ", ".join(changed))
        return 1
    print(f"no drift: the bucket matches run {args.run}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m data_load")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "ingest", help="stage 1: copy the organizer's CSVs to raw/<run-id>/"
    )
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("transform", help="stage 2: check, repair and write Parquet")
    p.add_argument(
        "--source", help="local directory in the organizer layout (skips S3)"
    )
    p.add_argument("--out", default=str(WORK))
    p.add_argument("--tables", help="comma-separated subset; local runs only")
    p.set_defaults(func=cmd_transform)

    p = sub.add_parser("load", help="stage 3: recreate the tables and bulk-load DSQL")
    p.set_defaults(func=cmd_load)

    p = sub.add_parser(
        "check", help="compare the organizer bucket with a run's ingest record"
    )
    p.add_argument("--run", required=True, help="Step Functions execution name")
    p.add_argument("--team-bucket", required=True)
    p.add_argument("--team-profile", default="ledgerlens")
    p.add_argument("--bucket-profile", default="hackathon")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

`data_load/__init__.py` (replace the whole file):

```python
"""LedgerLens data pipeline: organizer CSVs -> raw copy -> checked, repaired Parquet -> Aurora DSQL.

Design: docs/superpowers/specs/2026-10-02-data-pipeline-design.md
"""
```

- [ ] **Step 4: Run them to verify they pass, along with the whole suite**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_cli.py -q`
Expected: `11 passed`.

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit -q`
Expected: `82 passed`. That's 68 data_load tests plus the repo's 14 others.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff check data_load tests && uv run --no-project --quiet --with ruff ruff format --check data_load tests
git add data_load/__main__.py data_load/__init__.py tests/unit/test_data_load_cli.py
git commit -m "feat(data-pipeline): ingest, transform, load and check commands for the pipeline stages"
```


### Task 7: Stage 4, the read-check Lambda

**Files:**
- Create: `infra-cdk/lambdas/dsql-read-check/index.py`, `infra-cdk/lambdas/dsql-read-check/requirements.txt`, `tests/unit/test_dsql_read_check.py`

**Interfaces:**
- **Consumes:** the `DSQL_HOST` environment variable (Task 8).
- **Produces:**
  - `handler(event, context) -> {"tables_read": 13, "insert_denied": True}`;
  - `check(conn) -> dict`, which raises `RuntimeError` on an empty table or an allowed INSERT.
- **Packaging:** Task 8 bundles this directory with `PythonFunction`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_dsql_read_check.py`:

```python
"""Stage 4 read check: ll_read reads every table and is refused an INSERT."""

import importlib.util
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

_LAMBDA = (
    Path(__file__).resolve().parents[2]
    / "infra-cdk"
    / "lambdas"
    / "dsql-read-check"
    / "index.py"
)
spec = importlib.util.spec_from_file_location("dsql_read_check", _LAMBDA)
read_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(read_check)


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        if sql.startswith("INSERT") and not self.conn.insert_allowed:
            raise psycopg.errors.InsufficientPrivilege(
                "permission denied for table branches"
            )
        table = sql.split()[3] if sql.startswith("SELECT 1 FROM") else None
        self.rows = [] if table in self.conn.empty else [(1,)]

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, insert_allowed=False, empty=()):
        self.executed, self.insert_allowed, self.empty = [], insert_allowed, set(empty)
        self.transactions = 0

    def cursor(self):
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield

    def close(self):
        pass


@pytest.mark.unit
def test_reads_every_table_and_is_refused_an_insert():
    conn = FakeConn()
    assert read_check.check(conn) == {"tables_read": 13, "insert_denied": True}
    reads = [s for s in conn.executed if s.startswith("SELECT")]
    assert len(reads) == 13
    assert conn.transactions == 1  # the INSERT attempt runs inside a transaction


@pytest.mark.unit
def test_an_allowed_insert_fails_the_check():
    with pytest.raises(RuntimeError, match="could INSERT"):
        read_check.check(FakeConn(insert_allowed=True))


@pytest.mark.unit
def test_an_empty_table_fails_the_check():
    with pytest.raises(RuntimeError, match="complaints is empty"):
        read_check.check(FakeConn(empty={"complaints"}))


@pytest.mark.unit
def test_handler_logs_in_as_ll_read_at_the_private_host(monkeypatch):
    seen = {}

    def connect(**kwargs):
        seen.update(kwargs)
        return FakeConn()

    monkeypatch.setattr(read_check.dsql, "connect", connect)
    monkeypatch.setenv("DSQL_HOST", "abc.dsql-fnh4.us-east-1.on.aws")
    assert read_check.handler({}, None)["insert_denied"] is True
    assert seen == {
        "host": "abc.dsql-fnh4.us-east-1.on.aws",
        "user": "ll_read",
        "autocommit": True,
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_dsql_read_check.py -q`
Expected: FAIL with `FileNotFoundError` for `infra-cdk/lambdas/dsql-read-check/index.py`.

- [ ] **Step 3: Implement**

`infra-cdk/lambdas/dsql-read-check/index.py`:

```python
"""Stage 4 of the data pipeline: prove the tools' access path (spec sections 4.1 and 7).

Runs in the VPC with the tools role and logs in as ll_read through the private
endpoint. Every table must return a row; an INSERT must be refused.
"""

import os

import aurora_dsql_psycopg as dsql
import psycopg

TABLES = (
    "branches",
    "call_center_interactions",
    "call_transcripts",
    "campaign_sends",
    "complaints",
    "customers",
    "daily_exchange_rates",
    "digital_events",
    "marketing_campaigns",
    "products",
    "satisfaction_surveys",
    "service_agents",
    "transactions",
)


def check(conn) -> dict:
    with conn.cursor() as cur:
        for table in TABLES:
            cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
            if not cur.fetchall():
                raise RuntimeError(f"{table} is empty")
    try:
        with conn.transaction(), conn.cursor() as cur:
            # inserts nothing, but needs INSERT privilege; rolled back either way
            cur.execute("INSERT INTO branches SELECT * FROM branches WHERE false")
            raise RuntimeError(
                "ll_read could INSERT into branches: access is misconfigured"
            )
    except psycopg.errors.InsufficientPrivilege:
        return {"tables_read": len(TABLES), "insert_denied": True}


def handler(event, context):
    conn = dsql.connect(host=os.environ["DSQL_HOST"], user="ll_read", autocommit=True)
    try:
        return check(conn)
    finally:
        conn.close()
```

`infra-cdk/lambdas/dsql-read-check/requirements.txt` (the same pins as `data_load/requirements.txt`):

```text
aurora-dsql-python-connector[psycopg]==0.2.7
psycopg[binary]==3.3.6
psycopg-pool==3.3.3
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_dsql_read_check.py -q`
Expected: `4 passed`.

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit -q`
Expected: `86 passed`.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff check infra-cdk/lambdas tests && uv run --no-project --quiet --with ruff ruff format --check infra-cdk/lambdas tests
git add infra-cdk/lambdas/dsql-read-check/index.py infra-cdk/lambdas/dsql-read-check/requirements.txt tests/unit/test_dsql_read_check.py
git commit -m "feat(data-pipeline): read-check Lambda proves ll_read reads every table and cannot write"
```


### Task 8: CDK: VPC, cluster policy, tools role, read check and state machine

**Files:**
- Modify (whole files): `infra-cdk/lib/data-construct.ts`, `infra-cdk/test/data-construct.test.ts`
- Modify (exact edits below): `infra-cdk/lib/utils/config-manager.ts`, `infra-cdk/lib/fast-main-stack.ts`, `Makefile`, and the `data:` block of `infra-cdk/config.yaml`

**Interfaces:**
- **Consumes:**
  - the CodeBuild environment Task 6 relies on: `TEAM_BUCKET`, `DSQL_ENDPOINT`, `TOOLS_ROLE_ARN` and `HACKATHON_SECRET_ID`, with `STAGE` and `RUN_ID` from Step Functions;
  - the Lambda directory from Task 7.
- **Produces, on `DataConstruct`:**
  - `clusterEndpoint`, `clusterArn`, `privateHost`, `loadProjectName` and `stateMachineArn`;
  - `vpc`, `toolsRole` and `toolsSecurityGroup`, for the tool Lambdas later.
- **Produces, as stack outputs:** `DsqlEndpoint` (kept), `DataLoadProject` (kept), `DataPipelineStateMachine` and `DsqlPrivateHost`.

- [ ] **Step 1: Write the failing test**

The test synthesizes with `"aws:cdk:bundling-stacks": []`, so jest never runs Docker to bundle the Lambda.

`infra-cdk/test/data-construct.test.ts` (replace the whole file):

```ts
import * as cdk from "aws-cdk-lib"
import { Match, Template } from "aws-cdk-lib/assertions"
import { DataConstruct } from "../lib/data-construct"
import { AppConfig } from "../lib/utils/config-manager"

const config = {
  stack_name_base: "ledgerlens-test",
  data: { as_of: "2026-06-17T23:59:59" },
} as unknown as AppConfig

function synth(): Template {
  // skip Docker bundling of the read-check Lambda: these tests read the template only
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } })
  const stack = new cdk.Stack(app, "T", { env: { account: "111111111111", region: "us-east-1" } })
  new DataConstruct(stack, "Data", { config })
  return Template.fromStack(stack)
}

const t = synth()
const logicalId = (type: string, props: object) => Object.keys(t.findResources(type, { Properties: props }))[0]
const actionsOf = (roleId: string) =>
  Object.values(t.findResources("AWS::IAM::Policy"))
    .filter((p) => JSON.stringify(p.Properties.Roles).includes(roleId))
    .flatMap((p) => p.Properties.PolicyDocument.Statement.flatMap((s: { Action: string | string[] }) => s.Action))

test("cluster policy denies DSQL connections from outside the VPC, except the loader", () => {
  const cluster = Object.values(t.findResources("AWS::DSQL::Cluster"))[0]
  expect(cluster.Properties.DeletionProtectionEnabled).toBe(true)
  const policy = JSON.stringify(cluster.Properties.PolicyDocument)
  expect(policy).toContain("DenyOutsideAnyVpcExceptLoader")
  expect(policy).toContain('\\"Null\\":{\\"aws:SourceVpc\\":\\"true\\"}')
  expect(policy).toContain("DenyOtherVpcsExceptLoader")
  expect(policy).toContain('\\"aws:SourceVpc\\":\\"')
  const vpcId = logicalId("AWS::EC2::VPC", {})
  const loaderId = logicalId("AWS::IAM::Role", {
    AssumeRolePolicyDocument: Match.objectLike({
      Statement: [Match.objectLike({ Principal: { Service: "codebuild.amazonaws.com" } })],
    }),
  })
  expect(policy).toContain(`{"Ref":"${vpcId}"}`)
  expect(policy).toContain(`{"Fn::GetAtt":["${loaderId}","Arn"]}`)
})

test("tools role can connect to DSQL, never as admin", () => {
  const toolsId = logicalId("AWS::IAM::Role", { RoleName: "ledgerlens-tools" })
  const actions = actionsOf(toolsId)
  expect(actions).toContain("dsql:DbConnect")
  expect(actions).not.toContain("dsql:DbConnectAdmin")
})

test("the VPC has no NAT or internet gateway; the endpoint admits only the tools", () => {
  t.resourceCountIs("AWS::EC2::NatGateway", 0)
  t.resourceCountIs("AWS::EC2::InternetGateway", 0)
  t.hasResourceProperties("AWS::EC2::VPCEndpoint", { VpcEndpointType: "Interface", PrivateDnsEnabled: true })
  t.hasResourceProperties("AWS::EC2::SecurityGroupIngress", { IpProtocol: "tcp", FromPort: 5432, ToPort: 5432 })
})

test("read check runs in the VPC with the tools role and the private host", () => {
  const toolsId = logicalId("AWS::IAM::Role", { RoleName: "ledgerlens-tools" })
  t.hasResourceProperties("AWS::Lambda::Function", {
    FunctionName: "ledgerlens-dsql-read-check",
    Role: { "Fn::GetAtt": [toolsId, "Arn"] },
    VpcConfig: Match.objectLike({ SubnetIds: Match.anyValue() }),
    Environment: { Variables: { DSQL_HOST: Match.anyValue() } },
  })
  // <cluster-id>.<service-id>.<region>.on.aws, service-id = 4th part of com.amazonaws.<region>.dsql-xxxx
  const fn = Object.values(t.findResources("AWS::Lambda::Function", { Properties: { FunctionName: "ledgerlens-dsql-read-check" } }))[0]
  const clusterId = logicalId("AWS::DSQL::Cluster", {})
  const host = JSON.stringify(fn.Properties.Environment.Variables.DSQL_HOST)
  expect(host).toContain(`{"Fn::GetAtt":["${clusterId}","Identifier"]}`)
  expect(host).toContain(`{"Fn::Select":[3,{"Fn::Split":[".",{"Fn::GetAtt":["${clusterId}","VpcEndpointServiceName"]}]}]}`)
  expect(host).toContain('"us-east-1.on.aws"')
})

test("state machine runs ingest, transform, load, then the read check", () => {
  const machine = Object.values(t.findResources("AWS::StepFunctions::StateMachine"))[0]
  expect(machine.Properties.StateMachineName).toBe("ledgerlens-data-pipeline")
  const definition = JSON.stringify(machine.Properties.DefinitionString)
  for (const fragment of [
    '\\"StartAt\\":\\"Ingest\\"',
    '\\"Next\\":\\"Transform\\"',
    '\\"Next\\":\\"Load\\"',
    '\\"Next\\":\\"ReadCheck\\"',
    '\\"Name\\":\\"STAGE\\",\\"Type\\":\\"PLAINTEXT\\",\\"Value\\":\\"transform\\"',
    '\\"Name\\":\\"RUN_ID\\",\\"Type\\":\\"PLAINTEXT\\",\\"Value.$\\":\\"$$.Execution.Name\\"',
  ]) {
    expect(definition).toContain(fragment)
  }
})

test("CodeBuild gets the secret's name, never its value; one build at a time", () => {
  t.hasResourceProperties("AWS::CodeBuild::Project", {
    Name: "ledgerlens-data-load",
    TimeoutInMinutes: 180,
    ConcurrentBuildLimit: 1,
    Environment: Match.objectLike({
      Type: "ARM_CONTAINER",
      ComputeType: "BUILD_GENERAL1_LARGE",
      EnvironmentVariables: Match.arrayWith([
        Match.objectLike({ Name: "TEAM_BUCKET" }),
        Match.objectLike({ Name: "DSQL_ENDPOINT" }),
        Match.objectLike({ Name: "TOOLS_ROLE_ARN" }),
        { Name: "HACKATHON_SECRET_ID", Type: "PLAINTEXT", Value: "ledgerlens/hackathon-s3" },
      ]),
    }),
  })
  const project = Object.values(t.findResources("AWS::CodeBuild::Project"))[0]
  const types = project.Properties.Environment.EnvironmentVariables.map((v: { Type: string }) => v.Type)
  expect(types).not.toContain("SECRETS_MANAGER")
  const buildSpec = project.Properties.Source.BuildSpec
  expect(buildSpec).toContain('python -m data_load \\"$STAGE\\"')
  expect(buildSpec).toContain("import duckdb, psycopg, aurora_dsql_psycopg, boto3")
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd infra-cdk && npx jest test/data-construct.test.ts`
Expected: `Tests: 6 failed, 6 total`. The current construct has no VPC, cluster policy, tools role, Lambda or state machine.

- [ ] **Step 3: Implement the construct**

`infra-cdk/lib/data-construct.ts` (replace the whole file):

```ts
import * as path from "path"
import * as cdk from "aws-cdk-lib"
import * as codebuild from "aws-cdk-lib/aws-codebuild"
import * as dsql from "aws-cdk-lib/aws-dsql"
import * as ec2 from "aws-cdk-lib/aws-ec2"
import * as iam from "aws-cdk-lib/aws-iam"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as logs from "aws-cdk-lib/aws-logs"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as s3assets from "aws-cdk-lib/aws-s3-assets"
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager"
import * as sfn from "aws-cdk-lib/aws-stepfunctions"
import * as tasks from "aws-cdk-lib/aws-stepfunctions-tasks"
import { PythonFunction } from "@aws-cdk/aws-lambda-python-alpha"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"

// Pinned aurora-dsql-loader release; the hash is GitHub's published asset digest
const LOADER_URL =
  "https://github.com/aws-samples/aurora-dsql-loader/releases/download/v3.3.0/aurora-dsql-loader-aarch64-unknown-linux-musl.tar.gz"
const LOADER_SHA256 = "eb7a559f13aa3603704aae0e3e27b4f5e2bd3904ae9e656161df60170ce3dff5"
const SECRET_NAME = "ledgerlens/hackathon-s3"

export interface DataConstructProps {
  config: AppConfig
}

/**
 * Aurora DSQL, readable only by the tools role from inside the VPC, plus the staged
 * pipeline that loads it (docs/superpowers/specs/2026-10-02-data-pipeline-design.md).
 */
export class DataConstruct extends Construct {
  public readonly clusterEndpoint: string
  public readonly clusterArn: string
  public readonly privateHost: string
  public readonly loadProjectName: string
  public readonly stateMachineArn: string
  public readonly vpc: ec2.Vpc
  public readonly toolsRole: iam.Role
  public readonly toolsSecurityGroup: ec2.SecurityGroup

  constructor(scope: Construct, id: string, props: DataConstructProps) {
    super(scope, id)
    const stack = cdk.Stack.of(this)

    // Network (spec 7.2): one AZ, isolated subnet, no NAT or internet gateway
    this.vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [{ name: "tools", subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 }],
    })
    this.toolsSecurityGroup = new ec2.SecurityGroup(this, "ToolsSg", {
      vpc: this.vpc,
      description: "LedgerLens tool Lambdas",
    })
    const endpointSg = new ec2.SecurityGroup(this, "DsqlEndpointSg", {
      vpc: this.vpc,
      description: "Aurora DSQL PrivateLink endpoint",
      allowAllOutbound: false,
    })
    endpointSg.addIngressRule(this.toolsSecurityGroup, ec2.Port.tcp(5432), "PostgreSQL from the tools")

    // Identities (spec 7.3). The loader role exists before the cluster: the cluster policy names it.
    const loaderRole = new iam.Role(this, "LoaderRole", {
      assumedBy: new iam.ServicePrincipal("codebuild.amazonaws.com"),
      description: "Data pipeline CodeBuild stages; the only identity allowed into DSQL from outside the VPC",
    })
    this.toolsRole = new iam.Role(this, "ToolsRole", {
      roleName: "ledgerlens-tools",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Tool Lambdas: read-only DSQL access as ll_read, from the VPC only",
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaVPCAccessExecutionRole"),
      ],
    })

    // Layer 3 (spec 7.1): deny DSQL connections from outside our VPC, except the loader
    const denyOutside = (sid: string, condition: Record<string, unknown>) => ({
      Sid: sid,
      Effect: "Deny",
      Principal: { AWS: "*" },
      Resource: "*",
      Action: ["dsql:DbConnect", "dsql:DbConnectAdmin"],
      Condition: condition,
    })
    const cluster = new dsql.CfnCluster(this, "Cluster", {
      deletionProtectionEnabled: true,
      tags: [{ key: "Name", value: `${props.config.stack_name_base}-dsql` }],
      policyDocument: stack.toJsonString({
        Version: "2012-10-17",
        Statement: [
          denyOutside("DenyOutsideAnyVpcExceptLoader", {
            Null: { "aws:SourceVpc": "true" },
            StringNotEquals: { "aws:PrincipalArn": loaderRole.roleArn },
          }),
          denyOutside("DenyOtherVpcsExceptLoader", {
            StringNotEquals: { "aws:SourceVpc": this.vpc.vpcId, "aws:PrincipalArn": loaderRole.roleArn },
          }),
        ],
      }),
    })
    cluster.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN)
    this.clusterEndpoint = cluster.attrEndpoint
    this.clusterArn = cluster.attrResourceArn

    new ec2.InterfaceVpcEndpoint(this, "DsqlEndpoint", {
      vpc: this.vpc,
      service: new ec2.InterfaceVpcEndpointService(cluster.attrVpcEndpointServiceName, 5432),
      privateDnsEnabled: true,
      securityGroups: [endpointSg],
      open: false,
    })
    // com.amazonaws.<region>.dsql-xxxx -> <cluster-id>.dsql-xxxx.<region>.on.aws
    const serviceId = cdk.Fn.select(3, cdk.Fn.split(".", cluster.attrVpcEndpointServiceName))
    this.privateHost = cdk.Fn.join(".", [cluster.attrIdentifier, serviceId, stack.region, "on.aws"])

    // Layer 1 (spec 7.1): the tools may connect, never as admin
    this.toolsRole.addToPolicy(
      new iam.PolicyStatement({ actions: ["dsql:DbConnect"], resources: [cluster.attrResourceArn] })
    )

    const teamBucket = new s3.Bucket(this, "StagingBucket", {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    })

    // Created with a generated placeholder; a teammate sets the real JSON once (spec section 12)
    const hackathonSecret = new secretsmanager.Secret(this, "HackathonS3", {
      secretName: SECRET_NAME,
      description: "Organizer S3 read keys for the datathon bucket (JSON). Set manually; never commit.",
    })

    const source = new s3assets.Asset(this, "DataLoadSource", {
      path: path.join(__dirname, "..", "..", "data_load"),
      exclude: ["__pycache__", "*.pyc"],
    })

    const project = new codebuild.Project(this, "DataLoad", {
      projectName: "ledgerlens-data-load",
      description: "Data pipeline stages 1-3: python -m data_load $STAGE (ingest, transform, load)",
      role: loaderRole,
      source: codebuild.Source.s3({ bucket: source.bucket, path: source.s3ObjectKey }),
      environment: {
        buildImage: codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0,
        computeType: codebuild.ComputeType.LARGE,
      },
      timeout: cdk.Duration.minutes(180),
      concurrentBuildLimit: 1, // two loads would race on drop/create/load
      environmentVariables: {
        TEAM_BUCKET: { value: teamBucket.bucketName },
        DSQL_ENDPOINT: { value: cluster.attrEndpoint },
        TOOLS_ROLE_ARN: { value: this.toolsRole.roleArn },
        HACKATHON_SECRET_ID: { value: SECRET_NAME }, // the name, never the value
      },
      buildSpec: codebuild.BuildSpec.fromObject({
        version: "0.2",
        phases: {
          install: {
            "runtime-versions": { python: "3.12" },
            commands: [
              "pip install --quiet -r requirements.txt",
              // fail in seconds, not after an hour, if a dependency is missing
              'python -c "import duckdb, psycopg, aurora_dsql_psycopg, boto3"',
              `curl --proto '=https' --tlsv1.2 -sSfL -o /tmp/loader.tar.gz ${LOADER_URL}`,
              `echo "${LOADER_SHA256}  /tmp/loader.tar.gz" | sha256sum -c -`,
              "tar -xzf /tmp/loader.tar.gz -C /usr/local/bin aurora-dsql-loader",
              "aurora-dsql-loader load --help",
            ],
          },
          build: {
            commands: [
              // The asset unpacks data_load's contents at the source root; python -m needs the package dir
              'mkdir -p /tmp/src/data_load && cp -r . /tmp/src/data_load/ && cd /tmp/src && python -m data_load "$STAGE"',
            ],
          },
        },
      }),
    })
    teamBucket.grantReadWrite(project)
    hackathonSecret.grantRead(project)
    project.addToRolePolicy(
      new iam.PolicyStatement({ actions: ["dsql:DbConnectAdmin"], resources: [cluster.attrResourceArn] })
    )
    this.loadProjectName = project.projectName

    // Stage 4: the read check runs where the tools will run (spec 4.1)
    const readCheck = new PythonFunction(this, "ReadCheckFn", {
      functionName: "ledgerlens-dsql-read-check",
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64, // matches the Cedar Lambda's bundling
      entry: path.join(__dirname, "..", "lambdas", "dsql-read-check"),
      handler: "handler",
      role: this.toolsRole,
      vpc: this.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [this.toolsSecurityGroup],
      timeout: cdk.Duration.minutes(2),
      environment: { DSQL_HOST: this.privateHost },
      logGroup: new logs.LogGroup(this, "ReadCheckLogs", {
        logGroupName: `/aws/lambda/${props.config.stack_name_base}-dsql-read-check`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })

    // Stages 1-4 in order (spec 4.2); RUN_ID is the execution name
    const stage = (name: string) =>
      new tasks.CodeBuildStartBuild(this, name, {
        project,
        integrationPattern: sfn.IntegrationPattern.RUN_JOB,
        environmentVariablesOverride: {
          STAGE: { type: codebuild.BuildEnvironmentVariableType.PLAINTEXT, value: name.toLowerCase() },
          RUN_ID: {
            type: codebuild.BuildEnvironmentVariableType.PLAINTEXT,
            value: sfn.JsonPath.stringAt("$$.Execution.Name"),
          },
        },
        resultPath: sfn.JsonPath.DISCARD,
      })
    const pipeline = new sfn.StateMachine(this, "Pipeline", {
      stateMachineName: "ledgerlens-data-pipeline",
      definitionBody: sfn.DefinitionBody.fromChainable(
        stage("Ingest")
          .next(stage("Transform"))
          .next(stage("Load"))
          .next(new tasks.LambdaInvoke(this, "ReadCheck", { lambdaFunction: readCheck, payloadResponseOnly: true }))
      ),
      timeout: cdk.Duration.hours(5),
    })
    this.stateMachineArn = pipeline.stateMachineArn
  }
}
```

- [ ] **Step 4: Drop `window_years` from the config**

In `infra-cdk/lib/utils/config-manager.ts`, replace

```ts
/** Organizer snapshot load (docs/superpowers/specs/2026-09-29-data-loading-design.md). */
export interface DataConfig {
  /** Bank "today" for the load and every tool: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS, no time zone. */
  as_of: string
  /** Event tables keep process_date in [as_of::date - (365 * window_years - 1), as_of::date]. */
  window_years: number
}
```

with

```ts
/** Data settings (docs/superpowers/specs/2026-10-02-data-pipeline-design.md, section 5.3). */
export interface DataConfig {
  /** Bank "today" for the tools: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS, no time zone. */
  as_of: string
}
```

then replace

```ts
      // Validate the data-load snapshot settings
      const asOf = String(parsedConfig.data?.as_of ?? "2026-06-17T23:59:59")
      if (!/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$/.test(asOf)) {
        throw new Error(
          `data.as_of '${asOf}' in ${configPath} must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.`
        )
      }
      const windowYears = parsedConfig.data?.window_years ?? 2
      if (!Number.isInteger(windowYears) || windowYears < 1) {
        throw new Error(`data.window_years in ${configPath} must be a positive integer.`)
      }
```

with

```ts
      // Validate the bank's "today" for the tools
      const asOf = String(parsedConfig.data?.as_of ?? "2026-06-17T23:59:59")
      if (!/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$/.test(asOf)) {
        throw new Error(
          `data.as_of '${asOf}' in ${configPath} must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.`
        )
      }
```

and finally replace `data: { as_of: asOf, window_years: windowYears },` with `data: { as_of: asOf },`.

In `infra-cdk/config.yaml`, replace this block (lines 48–52), and only this block:

```yaml
# Organizer snapshot load (docs/superpowers/specs/2026-09-29-data-loading-design.md).
# Change, then deploy and run `make load-data`. Reloads recreate bank/pii: never during a demo.
data:
  as_of: "2026-06-17T23:59:59"   # bank "today" for the load and for every tool
  window_years: 2                # event tables: process_date in [as_of::date - (365 * window_years - 1), as_of::date]
```

with

```yaml
# Bank "today" for the tools (docs/superpowers/specs/2026-10-02-data-pipeline-design.md, 5.3).
# The pipeline loads every row; tools read process_date BETWEEN <from> AND as_of.
data:
  as_of: "2026-06-17T23:59:59"
```

- [ ] **Step 5: Add the stack outputs**

In `infra-cdk/lib/fast-main-stack.ts`, replace

```ts
    new cdk.CfnOutput(this, "DataLoadProject", {
      value: this.data.loadProjectName,
      description: "CodeBuild project that loads the organizer snapshot (make load-data)",
    })
```

with

```ts
    new cdk.CfnOutput(this, "DataLoadProject", {
      value: this.data.loadProjectName,
      description: "CodeBuild project that runs pipeline stages 1-3 (STAGE=ingest|transform|load)",
    })

    new cdk.CfnOutput(this, "DataPipelineStateMachine", {
      value: this.data.stateMachineArn,
      description: "Step Functions data pipeline: ingest, transform, load, read check (make load-data)",
    })

    new cdk.CfnOutput(this, "DsqlPrivateHost", {
      value: this.data.privateHost,
      description: "Aurora DSQL host inside the VPC (DSQL_HOST for the tool Lambdas)",
    })
```

- [ ] **Step 6: Run the checks to verify they pass**

Run: `cd infra-cdk && npx tsc --noEmit && npx jest test/data-construct.test.ts`
Expected: `tsc` exits 0, then `Tests: 6 passed, 6 total`.

Also confirm the real config still parses:

```bash
cd infra-cdk && npx ts-node -e "const {ConfigManager} = require('./lib/utils/config-manager'); console.log(JSON.stringify(new ConfigManager('config.yaml').getProps().data))"
```

Expected: `{"as_of":"2026-06-17T23:59:59"}`.

- [ ] **Step 7: Update the Makefile target**

In `Makefile`, replace

```make
# Load the organizer snapshot into Aurora DSQL with the CodeBuild job from
# infra-cdk/lib/data-construct.ts. Run as: AWS_PROFILE=ledgerlens make load-data
# Waits for the build's log, then follows it; press Ctrl-C after "data_load: done".
# The project allows one build at a time, so a second run cannot race the first.
load-data:
	aws codebuild start-build --project-name ledgerlens-data-load --query build.id --output text
	@until aws logs describe-log-streams --log-group-name /aws/codebuild/ledgerlens-data-load --max-items 1 --query 'logStreams[0].logStreamName' --output text 2>/dev/null | grep -qv None; do echo "waiting for the build log..."; sleep 5; done
	aws logs tail /aws/codebuild/ledgerlens-data-load --follow --since 1m
```

with

```make
# Run the data pipeline once: ingest, transform, load, read check
# (docs/superpowers/specs/2026-10-02-data-pipeline-design.md, section 4.2).
# Run as: AWS_PROFILE=ledgerlens make load-data. Without make, run the two aws commands by hand.
# Follow a stage's log with: aws logs tail /aws/codebuild/ledgerlens-data-load --follow
load-data:
	@arn=$$(aws stepfunctions list-state-machines --query "stateMachines[?name=='ledgerlens-data-pipeline'].stateMachineArn" --output text) && \
	exe=$$(aws stepfunctions start-execution --state-machine-arn "$$arn" --query executionArn --output text) && \
	echo "started $$exe" && \
	echo "https://console.aws.amazon.com/states/home#/v2/executions/details/$$exe"
```

The recipe lines must start with a tab, and each `\` must end its line; don't write a literal `\n`. Check:

```bash
grep -nP '^\t' Makefile | tail -4
bash -n <(sed -n '/^load-data:/,$p' Makefile | tail -n +2 | sed 's/^\t//; s/\$\$/$/g')
```

Expected: the four recipe lines print, each starting with a tab, and `bash -n` prints nothing (valid syntax).

- [ ] **Step 8: Commit, staging only the `data:` block of `config.yaml`**

`config.yaml` also holds the user's uncommitted `admin_user_email` edit, which must stay unstaged. Interactive `git add -p` isn't available, so stage HEAD's version plus this change:

```bash
git show HEAD:infra-cdk/config.yaml > /tmp/config.head.yaml
python - <<'PY'
from pathlib import Path
p = Path("/tmp/config.head.yaml")
s = p.read_text(encoding="utf-8")
old = '''# Organizer snapshot load (docs/superpowers/specs/2026-09-29-data-loading-design.md).
# Change, then deploy and run `make load-data`. Reloads recreate bank/pii: never during a demo.
data:
  as_of: "2026-06-17T23:59:59"   # bank "today" for the load and for every tool
  window_years: 2                # event tables: process_date in [as_of::date - (365 * window_years - 1), as_of::date]'''
new = '''# Bank "today" for the tools (docs/superpowers/specs/2026-10-02-data-pipeline-design.md, 5.3).
# The pipeline loads every row; tools read process_date BETWEEN <from> AND as_of.
data:
  as_of: "2026-06-17T23:59:59"'''
assert old in s, "HEAD's data block changed; re-read config.yaml"
p.write_text(s.replace(old, new), encoding="utf-8", newline="\n")
PY
git update-index --cacheinfo 100644,$(git hash-object -w --path infra-cdk/config.yaml /tmp/config.head.yaml),infra-cdk/config.yaml
git diff --cached infra-cdk/config.yaml   # only the data block
git diff infra-cdk/config.yaml            # only admin_user_email remains unstaged
git add infra-cdk/lib/data-construct.ts infra-cdk/test/data-construct.test.ts infra-cdk/lib/utils/config-manager.ts infra-cdk/lib/fast-main-stack.ts Makefile
git commit -m "feat(infra): VPC-only DSQL access, tools role, read-check Lambda and the pipeline state machine"
```

Read both diffs before committing. If anything outside the `data:` block is staged, run `git reset -- infra-cdk/config.yaml` and repeat.


### Task 9: The first cloud run (needs the user)

**Files:** spec sections 11 and 13, for the measurements.

This task has outward side effects: a deploy, a secret, and about $4 of spend. Every step below that touches AWS waits for the user.

- [ ] **Step 1: Stop and ask the user**

1. Deploy with or without the uncommitted `feat/design` edits in `infra-cdk/lib/backend-construct.ts` and `infra-cdk/lambdas/cedar-policy/index.py`? The deploy builds from the working tree.
2. The user sets the organizer secret themselves (Step 3). The agent never sees or handles the values.

- [ ] **Step 2: Deploy (user approved)**

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py
```

Expected: the stack update completes. Read the outputs `DsqlEndpoint`, `DsqlPrivateHost`, `DataPipelineStateMachine` and `DataLoadProject`:

```bash
aws cloudformation describe-stacks --profile ledgerlens --query "Stacks[].Outputs[?contains(OutputKey,'Dsql') || contains(OutputKey,'Data')]" --output table
```

- [ ] **Step 3: The user sets the secret**

The user writes a JSON file outside the repo with the keys `aws_access_key_id`, `aws_secret_access_key`, `bucket`, `region` (`us-east-2`) and `prefix` (`data/`), then runs:

```bash
aws secretsmanager put-secret-value --profile ledgerlens --secret-id ledgerlens/hackathon-s3 --secret-string file://<path-outside-the-repo>.json
```

They then delete the file.

- [ ] **Step 4: Start the pipeline**

```bash
AWS_PROFILE=ledgerlens make load-data
```

Without `make`, run the two commands it wraps:

```bash
arn=$(aws stepfunctions list-state-machines --profile ledgerlens --query "stateMachines[?name=='ledgerlens-data-pipeline'].stateMachineArn" --output text)
aws stepfunctions start-execution --profile ledgerlens --state-machine-arn "$arn" --query executionArn --output text
```

Expected: an execution ARN. Its last segment is the `RUN_ID`.

- [ ] **Step 5: Watch it run**

```bash
aws stepfunctions describe-execution --profile ledgerlens --execution-arn <arn> --query "[status, output]"
aws logs tail /aws/codebuild/ledgerlens-data-load --profile ledgerlens --follow
```

Expected: `SUCCEEDED`, with output `{"insert_denied": true, "tables_read": 13}`. If a stage fails, its log names the cause; fix it, then rerun only that stage (spec 4.1):

```bash
aws codebuild start-build --profile ledgerlens --project-name ledgerlens-data-load --environment-variables-override name=STAGE,value=<stage> name=RUN_ID,value=<run-id>
```

These first-run checks (spec 13) show up here:
- **Check 1:** the load authenticates through the policy's `aws:PrincipalArn` exception.
- **Check 2:** the dry run accepts the Parquet files.
- **Check 3:** the read check reaches the private host.

- [ ] **Step 6: Verify the run records**

```bash
aws s3 cp --profile ledgerlens s3://<team-bucket>/runs/<run-id>/transform.json - | python -c "import json,sys; r=json.load(sys.stdin); print(r['repairs']); print(sum(t['rows'] for t in r['tables'].values()))"
```

Expected: the repairs equal `data_load/expected.json`, and the total is `23495188`. `load.json` lists 13 tables.

- [ ] **Step 7: Prove layer 3 refuses a laptop (spec 13, check 4)**

```bash
uv run --no-project --quiet --with-requirements data_load/requirements.txt python -c "
import aurora_dsql_psycopg as d
try:
    d.connect(host='<DsqlEndpoint>', user='admin', profile='ledgerlens').close()
    print('CONNECTED: layer 3 is NOT enforced')
except Exception as e:
    print('refused:', type(e).__name__)
"
```

Expected: `refused: ...` (an access-denied error). If it prints `CONNECTED`, stop: the cluster policy is wrong, and the user must hear about it before anything else.

- [ ] **Step 8: Check for drift**

```bash
uv run --no-project --quiet --with-requirements data_load/requirements.txt python -m data_load check --run <run-id> --team-bucket <team-bucket>
```

Expected: `no drift: the bucket matches run <run-id>`.

- [ ] **Step 9: Record the measurements and commit**

- **Stage durations:** read them from the execution history or the console.
- **DPU:** for the load window, get `TotalDPU` with dimension `ResourceId` = the cluster id:

  ```bash
  aws cloudwatch get-metric-statistics --profile ledgerlens --namespace AWS/AuroraDSQL --metric-name TotalDPU --dimensions Name=ResourceId,Value=<cluster-id> --start-time <load start, ISO 8601> --end-time <load end> --period 3600 --statistics Sum
  ```

  If it returns no datapoints, find the namespace with `aws cloudwatch list-metrics --profile ledgerlens --metric-name TotalDPU`.
- **Spec 11.3:** add a "Measured on the first run" table with the stage durations, CodeBuild minutes, `TotalDPU` and its cost, and the DSQL storage from the console.
- **Spec 13:** record the outcome of each check.

```bash
git add docs/superpowers/specs/2026-10-02-data-pipeline-design.md
git commit -m "docs(spec): record the first pipeline run's durations, DPU and checks"
```


### Task 10: Align the design doc, the ERD and the README (needs the user)

**Files:** `docs/LEDGERLENS_PRODUCT_DESIGN.md`, `docs/LATAM_Bank_ERD.md`, `README.md`

- [ ] **Step 1: Stop and ask the user**

The design doc and the ERD carry the user's uncommitted v3 edits. Ask which they want:
- **(a)** commit their edits as-is on this branch first, then apply this task's changes on top;
- **(b)** commit them on `feat/design` and merge that branch here first;
- **(c)** leave both files alone and update only the README.

Make no edits to these two files before the answer.

- [ ] **Step 2: The design doc** (if allowed)

- **Architecture line:** "Lambda tools (no VPC) → Aurora DSQL (schemas bank / pii / app)" becomes "Lambda tools in a VPC → DSQL PrivateLink endpoint → Aurora DSQL (`public`, the 13 tables as delivered; cluster policy allows only our VPC and the loader)".
- **Offline pipeline line:** replace it with the four stages (spec 4.1).
- **Section 8 and Appendix A:** point to the spec and to `data_load/schema.sql` instead of repeating the DDL.
- **Roles table:** only `admin` (the loader) and `ll_read` (the tools, mapped to `ledgerlens-tools`). Writes are "designed later".
- **Tool catalog reads:** `bank.products` becomes `products`, and so on. `bank.customer_profile` becomes "`customers`, selecting only the columns the tool needs (spec 12)".
- **Section 16 cost:** point to spec section 11. Keep the old number only as the comparison.

- [ ] **Step 3: The ERD** (if allowed)

- **"Physical store" paragraph:** one schema, `public`, with all rows.
- **⚠ labels:** "registers (registration_branch_id)" becomes "repaired in the transform (R1): branch of the earliest product, else NULL". Do the same for R2, R3 and R4.
- **App schema:** remove the app-schema relationships and section.

- [ ] **Step 4: The README**

Add a "Data pipeline" section:
1. Deploy.
2. The human sets `ledgerlens/hackathon-s3`.
3. Run `make load-data` (or the two `aws` commands).
4. Watch the execution.
5. Run `python -m data_load check --run <run-id> --team-bucket <bucket>`.

Mention that a reload makes tools see missing tables for about 1.5 hours.

- [ ] **Step 5: Commit**

```bash
git add README.md   # plus the two docs if the user chose (a) or (b)
git commit -m "docs: align design doc, ERD and README with the data pipeline"
```

