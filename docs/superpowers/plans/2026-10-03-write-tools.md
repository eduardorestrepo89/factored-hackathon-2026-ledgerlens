# Write Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build three Gateway tool Lambdas, `block_credit_card`, `open_claim` and `human_agent_hand_off`, and deploy them from the data stack. Add the `ll_write` database role and the `access` pipeline stage that maps it.

**Architecture:**
- **The two write tools** are self-contained folders on Aurora DSQL. They copy the `list_credit_cards` hexagonal layers and connect as a new database role, `ll_write`.
- **Every write is idempotent:**
  - a guarded `UPDATE` for the block;
  - an `INSERT` whose primary key is a hash of the claim's content.
  The repository can therefore retry DSQL conflicts (`40001`) and lost connections safely, and map duplicate keys (`23505`).
- **The hand-off tool** has the same layers. It has no database: a `HandOffPublisher` port with an SNS adapter, and it runs outside the VPC.
- **CDK:** only `infra-cdk/lib/data-construct.ts` changes. No Gateway target, no Cedar rule, no agent prompt.

**Tech Stack:** Python 3.13 Lambdas (tests run on the uv-managed Python), psycopg 3, boto3/botocore, pytest, ruff 0.14.1, AWS CDK v2 (TypeScript, `@aws-cdk/aws-lambda-python-alpha`), Jest, Git Bash on Windows.

**Spec:** `docs/superpowers/specs/2026-10-03-write-tools-design.md`. Layout rules: `docs/superpowers/specs/2026-10-01-self-contained-tool-folders-design.md`.

## Global Constraints

- **Branch** `feat/write-tools`; run everything from the repo root `D:\Proyectos\ledgerlens-bank-assistant` in Git Bash.
- **Commits:** one per task, at its last step. Stage the task's paths explicitly with `git add <paths>`, never `git add -A`. Commit messages carry **no** `Co-Authored-By` trailer: that's the user's standing rule for this repo. Never stage the untracked `datathon/` files, `infra-cdk/config.yaml`, `frontend/public/aws-exports.json` or `frontend/.env`.
- **Python tests:** `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest --with requests --with pyjwt python -m pytest <paths> -q -p no:cacheprovider`. Below, `PYTEST <paths>` means that command. The baseline on this branch is **975 passed**.
- **Ruff:**
  - `uvx ruff@0.14.1 check --fix <paths>`, then `uvx ruff@0.14.1 format <paths>`. Finish with `uvx ruff@0.14.1 check <paths>` and `uvx ruff@0.14.1 format --check <paths>`, both clean.
  - The rules are `E4`, `E7`, `E9`, `F` and `I` (sorted imports), so `--fix` sorts imports.
- **CDK tests:** `cd infra-cdk && npx jest <file>`. A full `npx jest` takes about 2 minutes.
- **No AWS calls** until Task 12. Task 12 runs only after two things: the branch's code review has finished, and the user says go. Never deploy while a review is still running.
- **Out of bounds:** `infra-cdk/lib/backend-construct.ts`, `gateway/policies/policy.cedar` and `patterns/` (the agent and its prompt) don't change (spec §10). Nothing in `gateway/tools/list_*` or `gateway/tools/get_session_context` changes.
- **Self-contained:** a tool folder never imports from another tool folder. Code is copied with `sed` and then edited, never shared. Never copy `__pycache__`.
- **Line endings:** keep each file's current endings.
  - These files are CRLF: `README.md`, `docs/LEDGERLENS_PRODUCT_DESIGN.md`, `data_load/__main__.py` and `infra-cdk/lib/data-construct.ts`.
  - These are LF: `data_load/dsql.py`, `data_load/schema.sql` and `tests/unit/test_data_load_dsql.py`.
  - New files are LF.
- **Names:**

  | Tool | Asset root | Package | Function name | Construct id |
  |---|---|---|---|---|
  | `block_credit_card` | `gateway/tools/block_credit_card/` | `block_credit_card_lambda` | `ledgerlens-block-credit-card` | `BlockCreditCard` |
  | `open_claim` | `gateway/tools/open_claim/` | `open_claim_lambda` | `ledgerlens-open-claim` | `OpenClaim` |
  | `human_agent_hand_off` | `gateway/tools/human_agent_hand_off/` | `human_agent_hand_off_lambda` | `ledgerlens-human-agent-hand-off` | `HumanAgentHandOff` |

  Database role `ll_write`; IAM role `ledgerlens-write-tools`; SNS topic `ledgerlens-human-handoff`; CodeBuild variable `WRITE_TOOLS_ROLE_ARN`; new pipeline stage `access`.
- **Exact values from the spec:**
  - card filter `p.product_type = 'Tarjeta Crédito'` (NFC UTF-8, no BOM)
  - block statuses `'Blocked'`, `'Closed'`
  - claim columns: `case_type 'Claim'`, `category 'Transactions'`, `reception_channel 'Web'`, `status 'Open'`
  - subcategories `'Cargo no reconocido'` (fraud) and `'Cobro indebido'` (dispute)
  - priority `High` when any `amount_usd` is NULL or the USD total is above 500, else `Medium`
  - claim ID `CMP-` + the first 20 characters of the base32 SHA-256 of `customer_id|claim_type|product_id|currency|<sorted ids joined by ",">`
  - estimate window 365 days, at least 20 cases
  - limits: at most 10 transaction IDs (each at most 30 characters); statement 1–500 characters; summary 1–2,000 characters; at most 20 related IDs matching `[A-Z0-9-]{1,40}`
  - `40001`: at most 3 attempts in all, sleeping `uniform(0.05, 0.15) × attempt` seconds between them
  - Lambda timeouts: 30 s for the write tools, 10 s for the hand-off.

## Review Focus

1. **`customer_confirmed` sent as `"true"`, `1`, `null` or left out.** A model can send any of these. Expected: the `customer_confirmed` input error, and no database call. *Pinned by Task 3 `test_only_the_boolean_true_confirms_the_block`, Task 6 `test_only_the_boolean_true_confirms_the_claim`, and the handler tests in Tasks 4 and 7.*
2. **Odd last 4 digits:** `"48 21"`, full-width `"４８２１"`, `"04821"` or `4821` as a number. Expected: the `card_last4` input error. `" 4821 "` is accepted as `"4821"`. *Pinned by Task 3 `test_card_last4_must_be_exactly_4_ascii_digits`.*
3. **The same claim asked for twice:** the IDs in another order or case, a retry after a lost commit, or the model calling again. Expected: the same claim ID, `already_existed: true` the second time, and never a second row or an error. *Pinned by Task 2 `test_a_retry_after_a_lost_commit_reports_the_duplicate`, and Task 6 `test_the_same_transactions_in_another_order_give_the_same_claim_id` and `test_an_existing_claim_is_returned_as_already_existed`.*
4. **The estimate query fails on DSQL** (for example `percentile_cont` unsupported) after the claims were inserted. Expected: success with `"resolution_estimate": null`. *Pinned by Task 7 `test_a_failing_estimate_still_returns_the_open_claims`.*
5. **The card changes between the find and the update,** or a retry finds its own committed `UPDATE`. Expected: the answer comes from a fresh read (`already_blocked: true`, or the closed-card error), never a false internal error. *Pinned by Task 3 `test_an_update_that_changes_nothing_rereads_the_card` and `test_a_card_closed_between_the_statements_raises_card_closed`.*

---

## File map

| Path | Task | Kind |
|---|---|---|
| `data_load/schema.sql`, `data_load/dsql.py`, `data_load/__main__.py` | 1 | modified |
| `tests/unit/test_data_load_{ddl,dsql,cli}.py` | 1 | modified |
| `gateway/tools/block_credit_card/` (infrastructure, ports, settings, connectors) | 2 | copied, then edited |
| `tests/unit/block_credit_card/{__init__,conftest,fakes}.py` and infrastructure tests | 2 | copied, or new |
| `block_credit_card_lambda/domain/**`, `use_cases/block_credit_card.py`, `queries/postgresql/*.sql` | 3 | new |
| `block_credit_card_lambda/delivery/{handler.py, presenters/card_block.py, dependencies/dependencies_builder.py}`, `tool_spec.json` | 4 | new, or copied |
| `gateway/tools/open_claim/` (infrastructure, ports, settings, connectors) | 5 | copied from `block_credit_card` |
| `open_claim_lambda/domain/**`, `use_cases/open_claim.py`, `queries/postgresql/*.sql` | 6 | new |
| `open_claim_lambda/delivery/**`, `tool_spec.json` | 7 | new, or copied |
| `gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/{domain,application,infrastructure}/**` | 8 | new |
| `human_agent_hand_off_lambda/delivery/**`, `tool_spec.json` | 9 | new |
| `infra-cdk/lib/data-construct.ts`, `infra-cdk/test/data-construct.test.ts`, `tests/unit/test_tool_requirements.py` | 10 | modified |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md`, `README.md` | 11 | modified |
| (AWS: deploy, access stage, smoke, restore) | 12 | operations |

---

### Task 1: `ll_write` and the `access` stage

**Files:**
- Modify: `data_load/schema.sql`, `data_load/dsql.py`, `data_load/__main__.py`
- Test: `tests/unit/test_data_load_ddl.py`, `tests/unit/test_data_load_dsql.py`, `tests/unit/test_data_load_cli.py`

**Interfaces:**
- Produces:
  - `data_load.dsql.READ_ROLE = "ll_read"`, `data_load.dsql.WRITE_ROLE = "ll_write"`
  - `apply_schema(conn, plan: SchemaPlan, role_arns: Mapping[str, str]) -> None`
  - `apply_access(conn, plan: SchemaPlan, role_arns: Mapping[str, str]) -> None`
  - the CLI stage `python -m data_load access`, which needs `DSQL_ENDPOINT`, `TOOLS_ROLE_ARN` and `WRITE_TOOLS_ROLE_ARN`
  - `load` now also needs `WRITE_TOOLS_ROLE_ARN`
  - Task 10 sets `WRITE_TOOLS_ROLE_ARN` in CodeBuild.

- [ ] **Step 1: Write the failing ddl tests**

In `tests/unit/test_data_load_ddl.py`, replace the two `assert plan.roles … / assert plan.grants …` lines in `test_plan_groups_every_statement` with:

```python
    assert plan.roles == {
        "ll_read": "CREATE ROLE ll_read WITH LOGIN",
        "ll_write": "CREATE ROLE ll_write WITH LOGIN",
    }
    assert plan.grants == [
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO ll_read",
        "GRANT SELECT ON products, transactions, complaints TO ll_write",
        "GRANT UPDATE ON products TO ll_write",
        "GRANT INSERT ON complaints TO ll_write",
    ]
```

Replace the whole `test_read_role_can_only_read` function with:

```python
@pytest.mark.unit
def test_read_role_can_only_read():
    read_grants = [g for g in load_plan().grants if g.endswith(" TO ll_read")]
    assert read_grants
    for grant in read_grants:
        privileges = re.fullmatch(r"GRANT (.+) ON .+ TO ll_read", grant)[1]
        assert privileges in ("USAGE", "SELECT"), grant


@pytest.mark.unit
def test_write_role_can_only_block_cards_and_open_claims():
    write_grants = {
        re.fullmatch(r"GRANT (\w+) ON (.+) TO ll_write", grant).groups()
        for grant in load_plan().grants
        if grant.endswith(" TO ll_write")
    }
    assert write_grants == {
        ("SELECT", "products, transactions, complaints"),
        ("UPDATE", "products"),
        ("INSERT", "complaints"),
    }
```

- [ ] **Step 2: Write the failing dsql tests**

In `tests/unit/test_data_load_dsql.py`:

(a) Change the import block to:

```python
from data_load.ddl import load_plan
from data_load.dsql import (
    apply_access,
    apply_schema,
    build_indexes,
    load_all,
    loader_cmd,
    schema_statements,
)

TOOLS_ROLE = "arn:aws:iam::111111111111:role/ledgerlens-tools"
WRITE_TOOLS_ROLE = "arn:aws:iam::111111111111:role/ledgerlens-write-tools"
ROLE_ARNS = {"ll_read": TOOLS_ROLE, "ll_write": WRITE_TOOLS_ROLE}
```

(b) Make the fakes see query params:
- In `FakeCursor.execute`, change `self.rows = self.conn.respond(sql)` to `self.rows = self.conn.respond(sql, params)`.
- In `FakeConn.__init__`, change the default `respond=lambda sql: []` to `respond=lambda sql, params=None: []`.
- In `test_build_indexes_fails_when_a_job_fails` and `test_build_indexes_polls_sys_jobs_until_complete`, change `def respond(sql):` to `def respond(sql, params=None):`.

(c) Replace the whole `existing` function with:

```python
def existing(roles=(), mappings=None):
    """pg_roles holds ``roles``; ``mappings`` maps a role to its mapped IAM ARNs."""
    mappings = mappings or {}

    def respond(sql, params=None):
        if sql.startswith("SELECT rolname"):
            return [(r,) for r in roles]
        if "sys.iam_pg_role_mappings" in sql:
            return [(arn,) for arn in mappings.get(params[0], ())]
        return []

    return respond
```

(d) Replace `test_first_load_creates_the_role_maps_it_and_grants`, `test_reload_keeps_the_role_and_mapping_but_regrants` and `test_a_bad_role_arn_is_refused_before_any_sql` with:

```python
@pytest.mark.unit
def test_first_load_creates_both_roles_maps_them_and_grants():
    plan, conn = load_plan(), FakeConn(existing())
    apply_schema(conn, plan, ROLE_ARNS)
    sql = conn.sql()
    assert "CREATE ROLE ll_read WITH LOGIN" in sql
    assert "CREATE ROLE ll_write WITH LOGIN" in sql
    for role, arn in ROLE_ARNS.items():
        assert sql.index(f"AWS IAM GRANT {role} TO '{arn}'") < sql.index(plan.grants[0])
    assert sql[-len(plan.grants) :] == plan.grants  # last: they must see the new tables


@pytest.mark.unit
def test_reload_keeps_the_roles_and_mappings_but_regrants():
    plan = load_plan()
    conn = FakeConn(
        existing(
            roles=["ll_read", "ll_write"],
            mappings={"ll_read": [TOOLS_ROLE], "ll_write": [WRITE_TOOLS_ROLE]},
        )
    )
    apply_schema(conn, plan, ROLE_ARNS)
    sql = conn.sql()
    assert not any(s.startswith(("CREATE ROLE", "AWS IAM GRANT")) for s in sql)
    assert sql[-len(plan.grants) :] == plan.grants


@pytest.mark.unit
def test_an_existing_read_mapping_still_maps_the_new_write_role():
    plan = load_plan()
    conn = FakeConn(existing(roles=["ll_read"], mappings={"ll_read": [TOOLS_ROLE]}))
    apply_schema(conn, plan, ROLE_ARNS)
    sql = conn.sql()
    assert "CREATE ROLE ll_write WITH LOGIN" in sql
    assert "CREATE ROLE ll_read WITH LOGIN" not in sql
    assert f"AWS IAM GRANT ll_write TO '{WRITE_TOOLS_ROLE}'" in sql
    assert not any(s.startswith("AWS IAM GRANT ll_read") for s in sql)


@pytest.mark.unit
@pytest.mark.parametrize("role", ["ll_read", "ll_write"])
@pytest.mark.parametrize(
    "arn",
    [
        "",
        "ledgerlens-tools",
        "arn:aws:iam::111111111111:role/x'; DROP TABLE customers; --",
    ],
)
def test_a_bad_role_arn_is_refused_before_any_sql(role, arn):
    conn = FakeConn(existing())
    with pytest.raises(ValueError, match=f"not an IAM role ARN for {role}"):
        apply_schema(conn, load_plan(), {**ROLE_ARNS, role: arn})
    assert conn.sql() == []


@pytest.mark.unit
def test_a_missing_role_arn_is_refused_before_any_sql():
    conn = FakeConn(existing())
    with pytest.raises(ValueError, match="not an IAM role ARN for ll_write"):
        apply_schema(conn, load_plan(), {"ll_read": TOOLS_ROLE})
    assert conn.sql() == []


@pytest.mark.unit
def test_access_maps_and_grants_without_touching_the_tables():
    plan, conn = load_plan(), FakeConn(existing(roles=["ll_read"]))
    apply_access(conn, plan, ROLE_ARNS)
    sql = conn.sql()
    assert not any(s.startswith(("DROP TABLE", "CREATE TABLE")) for s in sql)
    assert "CREATE ROLE ll_write WITH LOGIN" in sql
    assert f"AWS IAM GRANT ll_read TO '{TOOLS_ROLE}'" in sql
    assert f"AWS IAM GRANT ll_write TO '{WRITE_TOOLS_ROLE}'" in sql
    assert sql[-len(plan.grants) :] == plan.grants


@pytest.mark.unit
def test_access_refuses_a_bad_arn_before_any_sql():
    conn = FakeConn(existing())
    with pytest.raises(ValueError, match="not an IAM role ARN for ll_write"):
        apply_access(conn, load_plan(), {**ROLE_ARNS, "ll_write": "nope"})
    assert conn.sql() == []
```

- [ ] **Step 3: Write the failing CLI tests**

In `tests/unit/test_data_load_cli.py`:

(a) In `test_stages_list_missing_environment`:
- Change the `load` row to `(["load"], "RUN_ID, TEAM_BUCKET, DSQL_ENDPOINT, TOOLS_ROLE_ARN, WRITE_TOOLS_ROLE_ARN"),`.
- Add the row `(["access"], "DSQL_ENDPOINT, TOOLS_ROLE_ARN, WRITE_TOOLS_ROLE_ARN"),`.
- Add `"WRITE_TOOLS_ROLE_ARN",` to the names deleted in the loop.

(b) In `test_a_failed_rerun_removes_the_stages_old_record` and `fake_load_env`, add this to their `env` dicts:

```python
        "WRITE_TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-write-tools",
```

(c) In `fake_load_env`, change the `apply_schema` fake to:

```python
    monkeypatch.setattr(
        "data_load.dsql.apply_schema",
        lambda conn, plan, role_arns: calls.append(("schema", role_arns)),
    )
```

(d) In `test_load_dry_runs_every_table_largest_first_then_loads`, change the first expected call to:

```python
        (
            "schema",
            {
                "ll_read": "arn:aws:iam::111111111111:role/ledgerlens-tools",
                "ll_write": "arn:aws:iam::111111111111:role/ledgerlens-write-tools",
            },
        ),
```

(e) Append:

```python
@pytest.mark.unit
def test_access_applies_roles_mappings_and_grants_only(monkeypatch, capsys):
    env = {
        "DSQL_ENDPOINT": "c.dsql.us-east-1.on.aws",
        "TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-tools",
        "WRITE_TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-write-tools",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    conn = mock.MagicMock()
    calls = []
    monkeypatch.setattr("data_load.dsql.connect", lambda endpoint: conn)
    monkeypatch.setattr(
        "data_load.dsql.apply_access",
        lambda c, plan, role_arns: calls.append((c, set(plan.roles), role_arns)),
    )
    monkeypatch.setattr(
        "data_load.dsql.apply_schema",
        lambda *a: pytest.fail("access must not recreate the tables"),
    )

    assert main(["access"]) == 0

    assert calls == [
        (
            conn,
            {"ll_read", "ll_write"},
            {
                "ll_read": env["TOOLS_ROLE_ARN"],
                "ll_write": env["WRITE_TOOLS_ROLE_ARN"],
            },
        )
    ]
    conn.close.assert_called_once()
    assert "access: roles ll_read, ll_write mapped and granted" in capsys.readouterr().out
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `PYTEST tests/unit/test_data_load_ddl.py tests/unit/test_data_load_dsql.py tests/unit/test_data_load_cli.py`
Expected: FAIL. You'll see an `ImportError` for `apply_access`, the ddl assertions failing on the missing `ll_write`, and the CLI tests failing on the missing `access` command.

- [ ] **Step 5: Add `ll_write` to `data_load/schema.sql`**

After the line `GRANT SELECT ON ALL TABLES IN SCHEMA public TO ll_read;`, insert:

```sql

-- The write tools' role (block_credit_card, open_claim). Created if missing; mapped to
-- the ledgerlens-write-tools IAM role by the load and access stages. These grants are
-- the only limit on what those tools can change: DSQL rejects default_transaction_read_only.
CREATE ROLE ll_write WITH LOGIN;
GRANT SELECT ON products, transactions, complaints TO ll_write;
GRANT UPDATE ON products TO ll_write;
GRANT INSERT ON complaints TO ll_write;
```

- [ ] **Step 6: Split `apply_schema` in `data_load/dsql.py`**

(a) Change the module docstring to: `"""Everything that touches Aurora DSQL: tables, the tool roles and their IAM mappings, bulk load, indexes."""`

(b) Add `from collections.abc import Mapping` after `import time`.

(c) Replace `READ_ROLE = "ll_read"` with:

```python
READ_ROLE = "ll_read"  # the read tools, IAM role ledgerlens-tools
WRITE_ROLE = "ll_write"  # block_credit_card and open_claim, IAM role ledgerlens-write-tools
```

(d) Replace the whole `apply_schema` function with:

```python
def apply_schema(conn, plan: SchemaPlan, role_arns: Mapping[str, str]) -> None:
    """Recreate the tables, then apply_access: the roles, their IAM mappings, the grants."""
    _check_role_arns(plan, role_arns)  # before the drops: a bad ARN must not cost the tables
    with conn.cursor() as cur:
        for stmt in schema_statements(plan):
            cur.execute(stmt)
    apply_access(conn, plan, role_arns)


def apply_access(conn, plan: SchemaPlan, role_arns: Mapping[str, str]) -> None:
    """Create missing roles and IAM mappings, then re-run every grant. Drops nothing.

    ``role_arns`` maps every role in schema.sql to the IAM role it is granted to:
    ll_read -> ledgerlens-tools, ll_write -> ledgerlens-write-tools. The access
    stage calls this alone, to add a role to a loaded cluster.
    """
    _check_role_arns(plan, role_arns)
    with conn.cursor() as cur:
        cur.execute("SELECT rolname FROM pg_roles")
        existing_roles = {row[0] for row in cur.fetchall()}
        for role, stmt in plan.roles.items():
            if role not in existing_roles:
                cur.execute(stmt)
        for role in plan.roles:
            cur.execute(
                "SELECT arn FROM sys.iam_pg_role_mappings WHERE pg_role_name = %s",
                (role,),
            )
            if role_arns[role] not in {row[0] for row in cur.fetchall()}:
                cur.execute(f"AWS IAM GRANT {role} TO '{role_arns[role]}'")
        for stmt in plan.grants:  # recreated tables lose their grants
            cur.execute(stmt)


def _check_role_arns(plan: SchemaPlan, role_arns: Mapping[str, str]) -> None:
    """Every role needs a well-formed IAM role ARN: it is spliced into AWS IAM GRANT."""
    for role in plan.roles:
        arn = role_arns.get(role, "")
        if not ROLE_ARN.fullmatch(arn):
            raise ValueError(f"not an IAM role ARN for {role}: {arn!r}")
```

- [ ] **Step 7: Add the stage to `data_load/__main__.py`**

(a) In the module docstring, change `{ingest,transform,curate,load,check}` to `{ingest,transform,curate,load,access,check}`.

(b) In `cmd_load`, replace the `require_env` call and the `apply_schema` call. The new `require_env`:

```python
    run_id, bucket, endpoint, tools_role, write_tools_role = require_env(
        "RUN_ID", "TEAM_BUCKET", "DSQL_ENDPOINT", "TOOLS_ROLE_ARN", "WRITE_TOOLS_ROLE_ARN"
    )
```

The new `apply_schema` call:

```python
        dsql.apply_schema(
            conn,
            plan,
            {dsql.READ_ROLE: tools_role, dsql.WRITE_ROLE: write_tools_role},
        )
```

(c) Insert this function after `cmd_load`:

```python
def cmd_access(args) -> int:
    """Create the tool roles, map them to their IAM roles and re-run the grants.

    No table is dropped, so a role added to schema.sql reaches a loaded cluster
    without a reload. CodeBuild runs it with STAGE=access.
    """
    endpoint, tools_role, write_tools_role = require_env(
        "DSQL_ENDPOINT", "TOOLS_ROLE_ARN", "WRITE_TOOLS_ROLE_ARN"
    )
    from data_load import dsql

    plan = load_plan()
    conn = dsql.connect(endpoint)
    try:
        dsql.apply_access(
            conn,
            plan,
            {dsql.READ_ROLE: tools_role, dsql.WRITE_ROLE: write_tools_role},
        )
    finally:
        conn.close()
    print(f"access: roles {', '.join(plan.roles)} mapped and granted", flush=True)
    return 0
```

(d) In `main`, after the `load` parser lines, add:

```python
    p = sub.add_parser(
        "access",
        help="create the tool roles, map them to IAM roles and re-run the grants (no reload)",
    )
    p.set_defaults(func=cmd_access)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `PYTEST tests/unit/test_data_load_ddl.py tests/unit/test_data_load_dsql.py tests/unit/test_data_load_cli.py`
Expected: PASS.

Run: `PYTEST tests/unit`
Expected: PASS, with more than 975 tests.

- [ ] **Step 9: Lint and commit**

```bash
uvx ruff@0.14.1 check --fix data_load tests/unit/test_data_load_ddl.py tests/unit/test_data_load_dsql.py tests/unit/test_data_load_cli.py
uvx ruff@0.14.1 format data_load/dsql.py data_load/__main__.py tests/unit/test_data_load_ddl.py tests/unit/test_data_load_dsql.py tests/unit/test_data_load_cli.py
git add data_load/schema.sql data_load/dsql.py data_load/__main__.py tests/unit/test_data_load_ddl.py tests/unit/test_data_load_dsql.py tests/unit/test_data_load_cli.py
git commit -m "feat(data): ll_write role for the write tools and an access stage that maps it without a reload"
```

---

### Task 2: `block_credit_card`, the write infrastructure

**Files:**
- Create (copied from `gateway/tools/list_credit_cards/`, then edited): `requirements.txt`, every `__init__.py`, `application/ports/{database_repository,query_provider,errors}.py`, `infrastructure/queries/file_query_provider.py`, `utils/connectors/{base,dsql}.py`, `delivery/settings.py`
- Create (new): `block_credit_card_lambda/infrastructure/repositories/dsql_repository.py`
- Create: `tests/unit/block_credit_card/{__init__,conftest,fakes}.py`
- Test (copied, then edited): `tests/unit/block_credit_card/test_{file_query_provider,dsql_repository,psycopg_connector,dsql_connector,settings}.py`

**Interfaces:**
- Produces:
  - Port errors `DuplicateKeyError(DataAccessError)` and `WriteConflictError(DataAccessError)` in `block_credit_card_lambda.application.ports.errors`.
  - `DsqlRepository(connector, sleep=time.sleep)`; `execute_query(query, params) -> list[dict]` raises `WriteConflictError` and `DuplicateKeyError` as well as the read copy's errors.
  - `DatabaseSettings(engine)` with no `max_rows`; `DEFAULT_DSQL_DB_USER = "ll_write"`; `ClockSettings` unchanged.
  - Test fakes in `tests/unit/block_credit_card/fakes.py`:
    - `CUSTOMER_ID`, `QUERY_NAMES = ("find_credit_card", "block_credit_card")`, `Outcome`, `Outcomes`
    - `FakeDatabaseRepository(results: Mapping[str, Outcomes] | None)`, with `.calls` and `.params_of(name)`
    - `FakeQueryProvider(names=QUERY_NAMES)`, which serves each name as its own SQL text
    - `make_row(**overrides)`, a `find_credit_card` row
    - `FakeCursor`
    - `FakeConnection(outcome)`: a tuple outcome is served cursor by cursor, and the last one repeats
    - `FakeConnector(*outcomes)`, `FakeClock`, `FakeDsqlTokenClient`

- [ ] **Step 1: Create the test package and copy the infrastructure tests**

```bash
SRC_T=tests/unit/list_credit_cards
DST_T=tests/unit/block_credit_card
mkdir -p "$DST_T"
: > "$DST_T/__init__.py"
for f in conftest.py test_file_query_provider.py test_dsql_repository.py \
         test_psycopg_connector.py test_dsql_connector.py test_settings.py; do
  sed 's/list_credit_cards/block_credit_card/g' "$SRC_T/$f" > "$DST_T/$f"
done
```

- [ ] **Step 2: Write `tests/unit/block_credit_card/fakes.py`**

```python
"""Test doubles and builders for the block_credit_card tests."""

import time
from collections.abc import Callable, Iterable, Mapping
from datetime import timedelta
from typing import Any, Final

from block_credit_card_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from block_credit_card_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from block_credit_card_lambda.application.ports.query_provider import QueryProvider
from block_credit_card_lambda.utils.connectors.base import PsycopgConnector

# A customer id in the format the customer system issues.
CUSTOMER_ID: Final = "CLI-ITIECUE8PRH9"
# The queries this tool runs. FakeQueryProvider serves each name as its own SQL text.
QUERY_NAMES: Final = ("find_credit_card", "block_credit_card")

Outcome = list[dict[str, Any]] | Exception
# One outcome, or a tuple of outcomes served call by call (the last one repeats).
Outcomes = Outcome | tuple[Outcome, ...]


def _queue(outcomes: Outcomes) -> list[Outcome]:
    """Turn one outcome, or a tuple of them, into a queue."""
    return list(outcomes) if isinstance(outcomes, tuple) else [outcomes]


def _next(queue: list[Outcome]) -> Outcome:
    """Pop the next outcome, keeping the last one for every later call."""
    return queue.pop(0) if len(queue) > 1 else queue[0]


class FakeDatabaseRepository(DatabaseRepository):
    """DatabaseRepository double keyed by query text.

    FakeQueryProvider serves each query's name as its SQL text, so ``results``
    maps a query name to its outcomes. Unlisted queries return no rows.
    """

    def __init__(self, results: Mapping[str, Outcomes] | None = None) -> None:
        """Serve ``results`` per query name."""
        self._results: dict[str, list[Outcome]] = {
            name: _queue(outcomes) for name, outcomes in (results or {}).items()
        }
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Record the call, then raise or return the query's next outcome."""
        self.calls.append((query, dict(params)))
        outcome = _next(self._results.setdefault(query, [[]]))
        if isinstance(outcome, Exception):
            raise outcome
        return [dict(row) for row in outcome]

    def params_of(self, query: str) -> list[dict[str, object]]:
        """Return the params of every call to ``query``, in order."""
        return [params for name, params in self.calls if name == query]


class FakeQueryProvider(QueryProvider):
    """QueryProvider double that serves each known name as its own SQL text."""

    def __init__(self, names: Iterable[str] = QUERY_NAMES) -> None:
        """Know only ``names``; any other name raises QueryNotFoundError."""
        self.names: frozenset[str] = frozenset(names)
        self.requested: list[str] = []

    def get(self, name: str) -> str:
        """Record the name and return it as the SQL text."""
        self.requested.append(name)
        if name not in self.names:
            raise QueryNotFoundError(f"no query named {name!r}")
        return name


def make_row(**overrides: Any) -> dict[str, Any]:
    """Build a find_credit_card row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {"product_id": "PRD-1", "product_status": "Active"}
    row.update(overrides)
    return row


class FakeCursor:
    """psycopg cursor double: records execute() and returns or raises its outcome."""

    def __init__(self, outcome: Outcome) -> None:
        """Serve ``outcome`` from execute()/fetchall()."""
        self._outcome = outcome
        self.executed: list[tuple[str, Mapping[str, object]]] = []

    def __enter__(self) -> "FakeCursor":
        """Support ``with connection.cursor() as cursor``."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Nothing to clean up."""

    def execute(self, query: str, params: Mapping[str, object]) -> None:
        """Record the call; raise the outcome if it is an exception."""
        self.executed.append((query, params))
        if isinstance(self._outcome, Exception):
            raise self._outcome

    def fetchall(self) -> list[dict[str, Any]]:
        """Return the canned rows."""
        assert not isinstance(self._outcome, Exception)
        return self._outcome


class FakeConnection:
    """psycopg connection double exposing cursor(), close() and closed."""

    def __init__(self, outcome: Outcomes | None = None) -> None:
        """Serve ``outcome`` from every cursor, or a tuple's items cursor by cursor."""
        self._outcomes: list[Outcome] = _queue(outcome if outcome is not None else [])
        self.cursors: list[FakeCursor] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        """Open a new cursor double serving the next outcome."""
        cursor = FakeCursor(_next(self._outcomes))
        self.cursors.append(cursor)
        return cursor

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True


class FakeConnector(PsycopgConnector):
    """PsycopgConnector double whose _open() serves the next queued outcome.

    The base class caches the connection, so the next outcome is only used after
    a reset, a closed connection or max_age. The last outcome repeats. A
    DataSourceConnectionError outcome is raised by _open() (connection() wraps
    it); any other exception is raised by cursor.execute(). A tuple outcome is
    served by one connection, cursor by cursor.
    """

    def __init__(
        self,
        *outcomes: Outcomes,
        max_age: timedelta | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Queue the outcomes; with none, every query returns no rows."""
        super().__init__(max_age=max_age, clock=clock)
        self._outcomes: list[Outcomes] = list(outcomes) or [[]]
        self.connections: list[FakeConnection] = []
        self.reset_calls = 0

    def reset(self) -> None:
        """Count the reset, then let the base class close the connection."""
        self.reset_calls += 1
        super().reset()

    def _open(self) -> Any:
        """Return a connection double for the next outcome."""
        outcome = (
            self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        )
        if isinstance(outcome, DataSourceConnectionError):
            raise outcome
        connection = FakeConnection(outcome)
        self.connections.append(connection)
        return connection


class FakeClock:
    """Monotonic clock double that only moves when told to."""

    def __init__(self, start: float = 1000.0) -> None:
        """Start at ``start`` seconds."""
        self.now = start

    def __call__(self) -> float:
        """Return the current time in seconds."""
        return self.now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``."""
        self.now += delta.total_seconds()


class FakeDsqlTokenClient:
    """boto3 DSQL client double; returns token-1, token-2, ... and records calls."""

    def __init__(self, error: Exception | None = None) -> None:
        """Raise ``error`` from every token method if given."""
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def generate_db_connect_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return the next token for a custom database role."""
        return self._token("generate_db_connect_auth_token", Hostname, Region)

    def generate_db_connect_admin_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return the next token for the admin role."""
        return self._token("generate_db_connect_admin_auth_token", Hostname, Region)

    def _token(self, method: str, hostname: str, region: str) -> str:
        """Record the call, then raise the configured error or return a token."""
        self.calls.append((method, hostname, region))
        if self.error is not None:
            raise self.error
        return f"token-{len(self.calls)}"
```

- [ ] **Step 3: Adapt the copied settings test to the write role**

In `tests/unit/block_credit_card/test_settings.py`:

(a) Replace `test_database_settings_default_to_aurora_dsql_and_25_rows`, `test_max_rows_can_be_overridden` and `test_invalid_max_rows_is_rejected` (all three whole functions, with the `parametrize` decorator of the last one) with:

```python
def test_database_settings_default_to_aurora_dsql() -> None:
    assert DatabaseSettings.from_env({}) == DatabaseSettings(
        engine=DatabaseEngine.AURORA_DSQL
    )


def test_max_rows_is_not_a_write_tool_setting() -> None:
    # No write tool returns a list (spec section 6.4).
    settings = DatabaseSettings.from_env({"MAX_ROWS": "10"})

    assert not hasattr(settings, "max_rows")
```

(b) In `test_dsql_settings_read_endpoint_and_region_and_default_the_user`, change `db_user="ll_read"` to `db_user="ll_write"`.

(c) Replace `test_a_blank_db_user_falls_back_to_the_read_only_role` with:

```python
def test_a_blank_db_user_falls_back_to_the_write_role() -> None:
    settings = DsqlSettings.from_env({**DSQL_ENV, "DSQL_DB_USER": "   "})

    assert settings.db_user == "ll_write"
```

- [ ] **Step 4: Add the write-rule tests to the copied repository test**

In `tests/unit/block_credit_card/test_dsql_repository.py`, change the errors import to:

```python
from block_credit_card_lambda.application.ports.errors import (
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    QueryLimitExceededError,
    WriteConflictError,
)
```

Then append:

```python
def test_a_write_conflict_is_retried_on_the_same_connection_then_succeeds() -> None:
    conflict = psycopg.errors.SerializationFailure("change conflicts (OC000)")
    assert isinstance(conflict, psycopg.OperationalError)
    connector = FakeConnector((conflict, conflict, [make_row()]))
    sleeps: list[float] = []

    rows = DsqlRepository(connector, sleep=sleeps.append).execute_query(QUERY, PARAMS)

    assert rows == [make_row()]
    assert connector.reset_calls == 0
    assert len(connector.connections) == 1
    assert len(connector.connections[0].cursors) == 3
    assert len(sleeps) == 2
    assert 0.05 <= sleeps[0] <= 0.15
    assert 0.10 <= sleeps[1] <= 0.30


def test_a_write_conflict_on_every_attempt_raises_write_conflict_error() -> None:
    conflict = psycopg.errors.SerializationFailure("change conflicts (OC000)")
    connector = FakeConnector(conflict)

    with pytest.raises(WriteConflictError) as caught:
        DsqlRepository(connector, sleep=lambda _seconds: None).execute_query(
            QUERY, PARAMS
        )

    assert caught.value.__cause__ is conflict
    assert len(connector.connections[0].cursors) == 3
    assert connector.reset_calls == 0


def test_a_unique_violation_raises_duplicate_key_error_without_retry() -> None:
    duplicate = psycopg.errors.UniqueViolation(
        'duplicate key value violates unique constraint "complaints_pkey"'
    )
    connector = FakeConnector(duplicate)

    with pytest.raises(DuplicateKeyError) as caught:
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is duplicate
    assert len(connector.connections[0].cursors) == 1
    assert connector.reset_calls == 0


def test_a_retry_after_a_lost_commit_reports_the_duplicate() -> None:
    # The first INSERT committed but its reply was lost; the retry hits the key.
    connector = FakeConnector(
        psycopg.OperationalError("server closed the connection"),
        psycopg.errors.UniqueViolation("duplicate key value"),
    )

    with pytest.raises(DuplicateKeyError):
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert connector.reset_calls == 1
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `PYTEST tests/unit/block_credit_card`
Expected: FAIL. Collection errors with `ModuleNotFoundError: No module named 'block_credit_card_lambda'`.

- [ ] **Step 6: Copy the production files**

```bash
SRC=gateway/tools/list_credit_cards
DST=gateway/tools/block_credit_card
P=list_credit_cards_lambda
for f in requirements.txt \
  $P/__init__.py \
  $P/application/__init__.py \
  $P/application/ports/__init__.py \
  $P/application/ports/database_repository.py \
  $P/application/ports/query_provider.py \
  $P/application/ports/errors.py \
  $P/application/use_cases/__init__.py \
  $P/delivery/__init__.py \
  $P/delivery/settings.py \
  $P/delivery/dependencies/__init__.py \
  $P/delivery/presenters/__init__.py \
  $P/domain/__init__.py \
  $P/domain/entities/__init__.py \
  $P/infrastructure/__init__.py \
  $P/infrastructure/queries/__init__.py \
  $P/infrastructure/queries/file_query_provider.py \
  $P/infrastructure/repositories/__init__.py \
  $P/utils/__init__.py \
  $P/utils/connectors/__init__.py \
  $P/utils/connectors/base.py \
  $P/utils/connectors/dsql.py; do
  out="$DST/${f//list_credit_cards/block_credit_card}"
  mkdir -p "$(dirname "$out")"
  sed 's/list_credit_cards/block_credit_card/g' "$SRC/$f" > "$out"
done
grep -rn "list_credit_cards" "$DST" && echo "UNEXPECTED" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 7: Add the two port errors**

Append to `block_credit_card_lambda/application/ports/errors.py`:

```python


class DuplicateKeyError(DataAccessError):
    """The statement broke a unique constraint (SQLSTATE 23505)."""


class WriteConflictError(DataAccessError):
    """DSQL kept rejecting the write with a concurrency conflict (SQLSTATE 40001)."""
```

In `block_credit_card_lambda/application/ports/database_repository.py`, extend the `Raises:` section of `execute_query`. After the `QueryExecutionError` line, add:

```python
            DuplicateKeyError: The statement broke a unique constraint.
            WriteConflictError: The write kept conflicting with other transactions.
```

- [ ] **Step 8: Point the copied settings and connector at `ll_write`**

In `block_credit_card_lambda/delivery/settings.py`:

(a) Replace these two lines:

```python
DEFAULT_MAX_ROWS: Final = 25
DEFAULT_DSQL_DB_USER: Final = "ll_read"  # SELECT-only role mapped to ledgerlens-tools
```

with:

```python
# The write tools' role (SELECT; UPDATE on products; INSERT on complaints), mapped to
# ledgerlens-write-tools. A missing DSQL_DB_USER must never fall back to ll_read.
DEFAULT_DSQL_DB_USER: Final = "ll_write"
```

(b) Replace the whole `DatabaseSettings` class with:

```python
@dataclass(frozen=True)
class DatabaseSettings:
    """Database settings that don't depend on the engine.

    Attributes:
        engine: Database engine; selects the connector, repository and SQL dialect.
    """

    engine: DatabaseEngine

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DatabaseSettings":
        """Read and validate DB_ENGINE (default aurora_dsql).

        Raises:
            ConfigurationError: The value is invalid.
        """
        return cls(engine=_engine(env))
```

(c) Delete the whole `_positive_int` function. Nothing uses it any more.

In `block_credit_card_lambda/utils/connectors/dsql.py`, replace these three docstring lines:

```
TODO(ledgerlens): R6 - the DB role is the only write guard: DSQL rejects
  default_transaction_read_only. ll_read has SELECT-only grants and is mapped to
  the ledgerlens-tools IAM role by the data pipeline's load stage.
```

with:

```
The tool connects as ll_write (delivery/settings.py), which the data pipeline's
load and access stages map to the ledgerlens-write-tools IAM role.
```

- [ ] **Step 9: Write `block_credit_card_lambda/infrastructure/repositories/dsql_repository.py`**

```python
"""DatabaseRepository adapter for Aurora DSQL through psycopg 3, for a write tool.

Every statement runs in autocommit, so each one is its own transaction. Compared
with the read tools' copy, two rules are added:

- SQLSTATE 40001 (DSQL's optimistic-concurrency conflict) is retried on the same
  connection after a short jittered sleep, at most _MAX_CONFLICT_ATTEMPTS times
  in all, then raised as WriteConflictError.
- SQLSTATE 23505 (unique violation) becomes DuplicateKeyError and is never
  retried.

The reset-and-retry-once after a lost connection is kept. For writes it is safe
only because every write this tool runs is idempotent: a guarded UPDATE, or an
INSERT whose key is derived from its content (write tools spec section 6.3). A
retry after a commit whose reply was lost then changes nothing, or hits 23505.
Keep every new write idempotent.

ll_write's grants are the only limit on what this tool can change: DSQL rejects
default_transaction_read_only.

TODO(ledgerlens): R10 - no per-query timeout: DSQL rejects statement_timeout. A
  slow query runs until the Lambda times out (DSQL caps a transaction at 300 s).
  Keep the Lambda timeout well under the agent's tool timeout.
TODO(ledgerlens): R12 - server-side cancel on DSQL is unverified, so the
  QueryCanceled mapping may never fire. Harmless either way.
"""

import logging
import random
import time
from collections.abc import Callable, Mapping
from typing import Any, Final

import psycopg

from block_credit_card_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from block_credit_card_lambda.application.ports.errors import (
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    QueryLimitExceededError,
    WriteConflictError,
)
from block_credit_card_lambda.utils.connectors.base import PsycopgConnector

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS: Final = 2
# DSQL fails a conflicting commit with 40001; the statement, its own transaction
# in autocommit, is simply run again.
_MAX_CONFLICT_ATTEMPTS: Final = 3
_CONFLICT_SQLSTATE: Final = "40001"
_UNIQUE_VIOLATION_SQLSTATE: Final = "23505"
# Query limits: SQLSTATE classes 53 (insufficient resources, such as 53200 for
# DSQL's 128 MiB per query) and 54 (program limit exceeded, such as 54000 for
# its 300 s per transaction), plus 57014 (cancelled). psycopg makes them all
# OperationalError subclasses, so they are told apart by SQLSTATE.
_LIMIT_SQLSTATE_CLASSES: Final = ("53", "54")
_CANCELED_SQLSTATE: Final = "57014"
# Too many connections and connection rate exceeded: the connection may recover.
_CONNECTION_LIMIT_SQLSTATES: Final = frozenset({"53300", "53400"})


class DsqlRepository(DatabaseRepository):
    """Run parameterised SQL on Aurora DSQL and translate psycopg errors.

    A lost connection (``OperationalError``) is reset and the statement retried
    once. A write conflict (40001) is retried on the same connection. A statement
    that breaks a DSQL limit or a unique constraint is never retried: it would
    fail the same way.
    """

    def __init__(
        self,
        connector: PsycopgConnector,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Use ``connector`` for the connection; ``sleep`` is replaced in tests."""
        self._connector: PsycopgConnector = connector
        self._sleep: Callable[[float], None] = sleep

    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Execute the statement and return all rows as dictionaries.

        Raises:
            DataSourceConnectionError: The connection failed twice, or couldn't be
                opened.
            WriteConflictError: DSQL reported a write conflict on every attempt.
            DuplicateKeyError: The statement broke a unique constraint.
            QueryLimitExceededError: The query exceeded a database resource or
                program limit (SQLSTATE class 53 or 54, except the connection
                limits), or the server cancelled it.
            QueryExecutionError: Any other database error.
        """
        connection_failures = 0
        conflicts = 0
        while True:
            try:
                return self._run(query, params)
            except psycopg.OperationalError as exc:
                if exc.sqlstate == _CONFLICT_SQLSTATE:
                    conflicts += 1
                    if conflicts == _MAX_CONFLICT_ATTEMPTS:
                        raise WriteConflictError(
                            "The write kept conflicting with other transactions"
                        ) from exc
                    logger.warning(
                        "Write conflict (40001); retrying, attempt %d of %d",
                        conflicts + 1,
                        _MAX_CONFLICT_ATTEMPTS,
                    )
                    self._sleep(random.uniform(0.05, 0.15) * conflicts)
                    continue
                if _is_query_limit(exc):
                    # Never retried: the same query would fail the same way.
                    raise QueryLimitExceededError(
                        "The query exceeded a database limit"
                    ) from exc
                self._connector.reset()
                connection_failures += 1
                if connection_failures == _MAX_ATTEMPTS:
                    raise DataSourceConnectionError(
                        "Database connection failed after a retry"
                    ) from exc
                logger.warning(
                    "Database connection failed; reconnecting and retrying once",
                    exc_info=True,
                )
            except psycopg.Error as exc:
                if exc.sqlstate == _UNIQUE_VIOLATION_SQLSTATE:
                    raise DuplicateKeyError(
                        "The statement broke a unique constraint"
                    ) from exc
                raise QueryExecutionError(
                    "The database failed to run the query"
                ) from exc

    def _run(self, query: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Run the statement once on the connector's current connection."""
        connection = self._connector.connection()
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


def _is_query_limit(exc: psycopg.Error) -> bool:
    """Return True when ``exc`` is a query limit rather than a connection fault."""
    sqlstate = exc.sqlstate or ""
    if sqlstate in _CONNECTION_LIMIT_SQLSTATES:
        return False
    return sqlstate == _CANCELED_SQLSTATE or sqlstate[:2] in _LIMIT_SQLSTATE_CLASSES
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `PYTEST tests/unit/block_credit_card`
Expected: PASS: the copied tests plus the four new repository tests and the settings changes.

- [ ] **Step 11: Lint and commit**

```bash
uvx ruff@0.14.1 check --fix gateway/tools/block_credit_card tests/unit/block_credit_card
uvx ruff@0.14.1 format gateway/tools/block_credit_card tests/unit/block_credit_card
git add gateway/tools/block_credit_card tests/unit/block_credit_card
git commit -m "feat(block_credit_card): write-tool infrastructure: ll_write settings, 40001 retry and 23505 mapping"
```

---

### Task 3: `block_credit_card`, the domain, use case and SQL

**Files:**
- Create: `block_credit_card_lambda/domain/entities/card_block.py`, `block_credit_card_lambda/domain/errors.py`, `block_credit_card_lambda/application/use_cases/block_credit_card.py`, `block_credit_card_lambda/queries/postgresql/{find_credit_card,block_credit_card}.sql`
- Test: `tests/unit/block_credit_card/test_errors.py`, `test_block_credit_card_use_case.py`, `test_query_contracts.py`

(All `block_credit_card_lambda/...` paths are under `gateway/tools/block_credit_card/`.)

**Interfaces:**
- Consumes: Task 2's ports, port errors and fakes.
- Produces:
  - `CardBlock(card_last4: str, status: str, already_blocked: bool)`
  - `BlockCreditCardUseCase(database_repository, query_provider)`, with `FIND_QUERY = "find_credit_card"` and `BLOCK_QUERY = "block_credit_card"`
  - `.execute(customer_id, card_last4, reason, customer_confirmed, now: datetime) -> CardBlock`
  - Module constant `REASONS = ("customer_request", "lost", "stolen", "suspected_fraud")`
  - Domain errors:
    - `DomainError(.message)`, `InvalidInputError(field, reason)`
    - `CardNotFoundError(card_last4)`, `AmbiguousCardError(card_last4)`, `CardClosedError(card_last4)`, each with `.card_last4`
    - `DataSourceUnavailableError`, `CardUpdateError`, `CardDataIntegrityError` (each with `.MESSAGE`)

- [ ] **Step 1: Write the failing error tests**

`tests/unit/block_credit_card/test_errors.py`:

```python
"""Tests for domain and port error definitions."""

import pytest
from block_credit_card_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
    WriteConflictError,
)
from block_credit_card_lambda.domain.errors import (
    AmbiguousCardError,
    CardClosedError,
    CardDataIntegrityError,
    CardNotFoundError,
    CardUpdateError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError("card_last4", "must be exactly 4 digits")

    assert error.field == "card_last4"
    assert error.reason == "must be exactly 4 digits"
    assert error.message == (
        "Invalid value for 'card_last4': must be exactly 4 digits. "
        "Ask the customer to confirm and retry."
    )
    assert str(error) == error.message


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (
            DataSourceUnavailableError,
            "The card service is temporarily unavailable. Tell the customer and "
            "offer to retry in a moment or hand off to a human agent.",
        ),
        (
            CardUpdateError,
            "The card couldn't be blocked due to an internal error. Don't retry; "
            "offer an urgent hand-off to a human agent.",
        ),
        (
            CardDataIntegrityError,
            "Card data came back in an unexpected format. Don't retry; offer an "
            "urgent hand-off to a human agent.",
        ),
    ],
)
def test_fixed_domain_errors_carry_agent_facing_messages(
    error_type: type[DomainError], expected: str
) -> None:
    error = error_type()

    assert isinstance(error, DomainError)
    assert error.message == expected
    assert error_type.MESSAGE == expected  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (
            CardNotFoundError,
            "No credit card ending in 4821 was found for this customer. Check the "
            "card with list_credit_cards and confirm it with the customer.",
        ),
        (
            AmbiguousCardError,
            "More than one of the customer's credit cards ends in 4821, so it "
            "can't be blocked here. Don't retry; offer an urgent hand-off to a "
            "human agent.",
        ),
        (
            CardClosedError,
            "The card ending in 4821 is closed, so it can't be charged and needs "
            "no block. Tell the customer.",
        ),
    ],
)
def test_card_errors_name_the_cards_last_4_digits(
    error_type: type[DomainError], expected: str
) -> None:
    error = error_type("4821")  # type: ignore[call-arg]

    assert isinstance(error, DomainError)
    assert error.card_last4 == "4821"  # type: ignore[attr-defined]
    assert error.message == expected


@pytest.mark.parametrize(
    "error_type",
    [
        DataSourceConnectionError,
        QueryLimitExceededError,
        QueryExecutionError,
        QueryNotFoundError,
        DuplicateKeyError,
        WriteConflictError,
    ],
)
def test_port_errors_share_a_base_class(error_type: type[DataAccessError]) -> None:
    assert issubclass(error_type, DataAccessError)
    assert not issubclass(error_type, DomainError)
```

- [ ] **Step 2: Write the failing use case tests**

`tests/unit/block_credit_card/test_block_credit_card_use_case.py`:

```python
"""Tests for BlockCreditCardUseCase."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from block_credit_card_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    QueryLimitExceededError,
    WriteConflictError,
)
from block_credit_card_lambda.application.use_cases.block_credit_card import (
    BlockCreditCardUseCase,
)
from block_credit_card_lambda.domain.entities.card_block import CardBlock
from block_credit_card_lambda.domain.errors import (
    AmbiguousCardError,
    CardClosedError,
    CardDataIntegrityError,
    CardNotFoundError,
    CardUpdateError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
)

from .fakes import (
    CUSTOMER_ID,
    FakeDatabaseRepository,
    FakeQueryProvider,
    Outcomes,
    make_row,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
NAIVE_NOW = datetime(2026, 6, 17, 23, 59, 59)
FIND = "find_credit_card"
BLOCK = "block_credit_card"
BLOCKED_ROW = [{"product_id": "PRD-1"}]
ARGS: dict[str, Any] = {
    "customer_id": CUSTOMER_ID,
    "card_last4": "4821",
    "reason": "suspected_fraud",
    "customer_confirmed": True,
}


def make_use_case(
    results: dict[str, Outcomes] | None = None,
    query_provider: FakeQueryProvider | None = None,
) -> tuple[BlockCreditCardUseCase, FakeDatabaseRepository]:
    """Build the use case over fakes; return it with its repository."""
    repository = FakeDatabaseRepository(results)
    use_case = BlockCreditCardUseCase(
        database_repository=repository,
        query_provider=query_provider or FakeQueryProvider(),
    )
    return use_case, repository


def block(use_case: BlockCreditCardUseCase, **overrides: Any) -> CardBlock:
    """Run the use case with ARGS, overridden by ``overrides``."""
    return use_case.execute(**{**ARGS, **overrides, "now": overrides.get("now", NOW)})


def test_an_active_card_is_blocked() -> None:
    use_case, repository = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})

    assert block(use_case) == CardBlock(
        card_last4="4821", status="Blocked", already_blocked=False
    )
    assert repository.calls == [
        (FIND, {"customer_id": CUSTOMER_ID, "card_last4": "4821"}),
        (
            BLOCK,
            {
                "customer_id": CUSTOMER_ID,
                "product_id": "PRD-1",
                "last_updated": NAIVE_NOW,
            },
        ),
    ]


def test_a_suspended_card_is_blocked_too() -> None:
    use_case, _ = make_use_case(
        {FIND: [make_row(product_status="Suspended")], BLOCK: BLOCKED_ROW}
    )

    assert block(use_case).already_blocked is False


def test_an_already_blocked_card_is_a_success_without_a_write() -> None:
    use_case, repository = make_use_case({FIND: [make_row(product_status="Blocked")]})

    assert block(use_case) == CardBlock(
        card_last4="4821", status="Blocked", already_blocked=True
    )
    assert [name for name, _ in repository.calls] == [FIND]


def test_a_closed_card_is_refused_without_a_write() -> None:
    use_case, repository = make_use_case({FIND: [make_row(product_status="Closed")]})

    with pytest.raises(CardClosedError) as caught:
        block(use_case)

    assert caught.value.card_last4 == "4821"
    assert [name for name, _ in repository.calls] == [FIND]


def test_no_matching_card_raises_card_not_found() -> None:
    use_case, _ = make_use_case({FIND: []})

    with pytest.raises(CardNotFoundError) as caught:
        block(use_case)

    assert "No credit card ending in 4821" in caught.value.message


def test_two_matching_cards_raise_ambiguous_card() -> None:
    use_case, repository = make_use_case(
        {FIND: [make_row(), make_row(product_id="PRD-2")]}
    )

    with pytest.raises(AmbiguousCardError):
        block(use_case)

    assert [name for name, _ in repository.calls] == [FIND]


def test_an_update_that_changes_nothing_rereads_the_card() -> None:
    # A retry after a lost reply, or a block that landed between the statements.
    use_case, repository = make_use_case(
        {FIND: ([make_row()], [make_row(product_status="Blocked")]), BLOCK: []}
    )

    assert block(use_case).already_blocked is True
    assert [name for name, _ in repository.calls] == [FIND, BLOCK, FIND]


def test_a_card_closed_between_the_statements_raises_card_closed() -> None:
    use_case, _ = make_use_case(
        {FIND: ([make_row()], [make_row(product_status="Closed")]), BLOCK: []}
    )

    with pytest.raises(CardClosedError):
        block(use_case)


def test_an_update_that_changes_nothing_on_a_still_active_card_fails() -> None:
    use_case, _ = make_use_case({FIND: [make_row()], BLOCK: []})

    with pytest.raises(CardUpdateError):
        block(use_case)


def test_now_is_written_as_naive_utc() -> None:
    use_case, repository = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})
    bogota = timezone(timedelta(hours=-5))

    block(use_case, now=datetime(2026, 6, 17, 18, 59, 59, tzinfo=bogota))

    assert repository.params_of(BLOCK)[0]["last_updated"] == NAIVE_NOW


def test_the_inputs_are_cleaned_before_the_query() -> None:
    use_case, repository = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})

    block(use_case, customer_id=" cli-itiecue8prh9 ", card_last4=" 4821 ", reason=" Lost ")

    assert repository.params_of(FIND) == [
        {"customer_id": CUSTOMER_ID, "card_last4": "4821"}
    ]


def assert_rejected(field: str, **overrides: Any) -> InvalidInputError:
    """Run with ``overrides``; it must fail on ``field`` before any query."""
    use_case, repository = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})
    with pytest.raises(InvalidInputError) as caught:
        block(use_case, **overrides)
    assert caught.value.field == field
    assert repository.calls == []
    return caught.value


@pytest.mark.parametrize("customer_id", [None, "", "   ", 42, True])
def test_a_bad_customer_id_is_rejected(customer_id: object) -> None:
    error = assert_rejected("customer_id", customer_id=customer_id)

    assert error.reason == "is required and must be a non-empty string"


@pytest.mark.parametrize(
    "card_last4",
    [None, 4821, "", "482", "48210", "04821", "48 21", "\uff14\uff18\uff12\uff11", "abcd"],
)
def test_card_last4_must_be_exactly_4_ascii_digits(card_last4: object) -> None:
    error = assert_rejected("card_last4", card_last4=card_last4)

    assert error.reason == "must be exactly 4 digits"


@pytest.mark.parametrize("reason", [None, "", "fraud", "theft", 1])
def test_reason_must_be_one_of_the_four(reason: object) -> None:
    error = assert_rejected("reason", reason=reason)

    assert error.reason == (
        "must be one of: customer_request, lost, stolen, suspected_fraud"
    )


@pytest.mark.parametrize("confirmed", [False, None, "true", "yes", 1])
def test_only_the_boolean_true_confirms_the_block(confirmed: object) -> None:
    error = assert_rejected("customer_confirmed", customer_confirmed=confirmed)

    assert error.message == (
        "Invalid value for 'customer_confirmed': must be true, after the customer "
        "explicitly confirmed the block. Ask the customer to confirm and retry."
    )


@pytest.mark.parametrize(
    ("port_error", "domain_error"),
    [
        (DataSourceConnectionError("down"), DataSourceUnavailableError),
        (WriteConflictError("40001"), DataSourceUnavailableError),
        (QueryExecutionError("boom"), CardUpdateError),
        (QueryLimitExceededError("limit"), CardUpdateError),
        (DuplicateKeyError("23505"), CardUpdateError),
    ],
)
@pytest.mark.parametrize("failing_query", [FIND, BLOCK])
def test_port_errors_become_domain_errors(
    port_error: DataAccessError,
    domain_error: type[DomainError],
    failing_query: str,
) -> None:
    results: dict[str, Outcomes] = {FIND: [make_row()], BLOCK: BLOCKED_ROW}
    results[failing_query] = port_error
    use_case, _ = make_use_case(results)

    with pytest.raises(domain_error) as caught:
        block(use_case)

    assert caught.value.__cause__ is port_error


def test_a_missing_sql_file_raises_card_update_error() -> None:
    use_case, _ = make_use_case(query_provider=FakeQueryProvider(names=()))

    with pytest.raises(CardUpdateError):
        block(use_case)


@pytest.mark.parametrize(
    "row",
    [
        {"product_status": "Active"},
        make_row(product_id=None),
        make_row(product_id=""),
        make_row(product_status=5),
    ],
)
def test_an_unreadable_card_row_raises_card_data_integrity_error(
    row: dict[str, Any],
) -> None:
    use_case, _ = make_use_case({FIND: [row]})

    with pytest.raises(CardDataIntegrityError):
        block(use_case)


def test_every_block_writes_an_audit_line(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    use_case, _ = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})

    block(use_case)

    assert (
        f"block_credit_card audit: customer_id={CUSTOMER_ID} card_last4=4821 "
        "reason=suspected_fraud already_blocked=False"
    ) in caplog.text
```

- [ ] **Step 3: Write the failing query contract tests**

`tests/unit/block_credit_card/test_query_contracts.py`:

```python
"""Drift tests: the SQL files must match the Python contracts and the schema."""

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pytest
from block_credit_card_lambda.application.use_cases.block_credit_card import (
    BlockCreditCardUseCase,
)
from block_credit_card_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)
from data_load.ddl import load_plan

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    FakeDatabaseRepository,
    FakeQueryProvider,
    make_row,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/block_credit_card"
QUERIES_DIR = TOOL_ROOT / "block_credit_card_lambda/queries/postgresql"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
# Escaped so this test file's own encoding can't change the expected value.
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Cr\u00e9dito'"


def sql(name: str) -> str:
    """Load one of the tool's real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def flat_sql(name: str) -> str:
    """Return the query with every run of whitespace collapsed to one space."""
    return " ".join(sql(name).split())


def statements(text: str) -> list[str]:
    """Split SQL text into statements, ignoring -- comments."""
    without_comments = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def sent_params() -> dict[str, set[str]]:
    """Return the param names the use case sends, per query, on the blocking path."""
    repository = FakeDatabaseRepository(
        {"find_credit_card": [make_row()], "block_credit_card": [{"product_id": "P"}]}
    )
    BlockCreditCardUseCase(
        database_repository=repository, query_provider=FakeQueryProvider()
    ).execute(
        customer_id=CUSTOMER_ID,
        card_last4="4821",
        reason="lost",
        customer_confirmed=True,
        now=datetime(2026, 6, 17, tzinfo=timezone.utc),
    )
    return {name: set(params) for name, params in repository.calls}


def test_the_use_case_runs_exactly_the_tools_queries() -> None:
    assert set(sent_params()) == set(QUERY_NAMES)
    assert {path.stem for path in QUERIES_DIR.glob("*.sql")} == set(QUERY_NAMES)


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_placeholders_match_the_use_case_params_exactly(name: str) -> None:
    assert set(PLACEHOLDER.findall(sql(name))) == sent_params()[name]


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_has_no_stray_percent_signs(name: str) -> None:
    # psycopg treats every '%' as a placeholder marker, including inside comments.
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_each_file_is_one_statement_that_sets_no_session_parameter(name: str) -> None:
    found = statements(sql(name))

    assert len(found) == 1
    assert not found[0].upper().startswith("SET ")
    assert "statement_timeout" not in sql(name).lower()


def test_find_filters_on_the_exact_credit_card_literal_in_nfc_utf8() -> None:
    raw = (QUERIES_DIR / "find_credit_card.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert CREDIT_CARD_FILTER.encode("utf-8") in raw
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


def test_find_reads_only_the_customers_matching_cards_and_at_most_two() -> None:
    text = flat_sql("find_credit_card")

    assert (
        "FROM products AS p WHERE p.customer_id = %(customer_id)s "
        f"AND {CREDIT_CARD_FILTER} "
        "AND RIGHT(p.product_number, 4) = %(card_last4)s"
    ) in text
    assert text.endswith("ORDER BY p.product_id LIMIT 2")


def test_block_only_changes_a_card_that_is_neither_blocked_nor_closed() -> None:
    assert (
        "UPDATE products SET product_status = 'Blocked', "
        "last_updated = %(last_updated)s "
        "WHERE product_id = %(product_id)s AND customer_id = %(customer_id)s "
        "AND product_status NOT IN ('Blocked', 'Closed') RETURNING product_id"
    ) in flat_sql("block_credit_card")


def test_the_statuses_used_pass_the_products_check_constraint() -> None:
    products = load_plan().data_tables["products"]

    for status in ("'Blocked'", "'Closed'", "'Active'", "'Suspended'"):
        assert status in products
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `PYTEST tests/unit/block_credit_card`
Expected: FAIL. `ModuleNotFoundError` for `block_credit_card_lambda.domain.errors`, `...domain.entities.card_block` and `...application.use_cases.block_credit_card`.

- [ ] **Step 5: Write the entity**

`block_credit_card_lambda/domain/entities/card_block.py`:

```python
"""Result entity of the block_credit_card use case."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CardBlock:
    """The card the customer asked to block, after the call.

    ``already_blocked`` is True when the card was blocked before this call (by an
    earlier call or a retry), so nothing was written. It is a success, not an
    error. The internal ``product_id`` is never exposed.
    """

    card_last4: str
    status: str
    already_blocked: bool
```

- [ ] **Step 6: Write the domain errors**

`block_credit_card_lambda/domain/errors.py`:

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output or other internal details; the
card-named ones carry only the 4 digits the agent sent, after validation.
"""

from typing import ClassVar


class DomainError(Exception):
    """Base class for agent-facing errors raised by the use case.

    Attributes:
        message: Agent-facing text describing the failure and the next step.
    """

    def __init__(self, message: str) -> None:
        """Store the agent-facing message."""
        super().__init__(message)
        self.message: str = message


class InvalidInputError(DomainError):
    """A tool argument failed validation.

    Attributes:
        field: Name of the offending tool argument.
        reason: Short human-readable rule that was broken.
    """

    def __init__(self, field: str, reason: str) -> None:
        """Build the message from the field name and the broken rule."""
        self.field: str = field
        self.reason: str = reason
        super().__init__(
            f"Invalid value for '{field}': {reason}. "
            "Ask the customer to confirm and retry."
        )


class _FixedMessageError(DomainError):
    """Base for domain errors whose message never varies."""

    MESSAGE: ClassVar[str] = ""

    def __init__(self) -> None:
        """Use the class-level MESSAGE as the agent-facing message."""
        super().__init__(self.MESSAGE)


class _CardMessageError(DomainError):
    """Base for errors whose message names the card's last 4 digits."""

    TEMPLATE: ClassVar[str] = ""

    def __init__(self, card_last4: str) -> None:
        """Fill the class-level TEMPLATE with the validated last 4 digits."""
        self.card_last4: str = card_last4
        super().__init__(self.TEMPLATE.format(last4=card_last4))


class CardNotFoundError(_CardMessageError):
    """No credit card of this customer ends in these digits."""

    TEMPLATE: ClassVar[str] = (
        "No credit card ending in {last4} was found for this customer. Check the "
        "card with list_credit_cards and confirm it with the customer."
    )


class AmbiguousCardError(_CardMessageError):
    """More than one of the customer's credit cards ends in these digits."""

    TEMPLATE: ClassVar[str] = (
        "More than one of the customer's credit cards ends in {last4}, so it "
        "can't be blocked here. Don't retry; offer an urgent hand-off to a "
        "human agent."
    )


class CardClosedError(_CardMessageError):
    """The card is closed: it can't be charged, so there is nothing to block."""

    TEMPLATE: ClassVar[str] = (
        "The card ending in {last4} is closed, so it can't be charged and needs "
        "no block. Tell the customer."
    )


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "The card service is temporarily unavailable. Tell the customer and "
        "offer to retry in a moment or hand off to a human agent."
    )


class CardUpdateError(_FixedMessageError):
    """A query failed, or the card couldn't be blocked; retrying won't help."""

    MESSAGE: ClassVar[str] = (
        "The card couldn't be blocked due to an internal error. Don't retry; "
        "offer an urgent hand-off to a human agent."
    )


class CardDataIntegrityError(_FixedMessageError):
    """A returned row couldn't be read."""

    MESSAGE: ClassVar[str] = (
        "Card data came back in an unexpected format. Don't retry; offer an "
        "urgent hand-off to a human agent."
    )
```

- [ ] **Step 7: Write the use case**

`block_credit_card_lambda/application/use_cases/block_credit_card.py`:

```python
"""Use case: block one of a customer's credit cards."""

import logging
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Final

from block_credit_card_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from block_credit_card_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    WriteConflictError,
)
from block_credit_card_lambda.application.ports.query_provider import QueryProvider
from block_credit_card_lambda.domain.entities.card_block import CardBlock
from block_credit_card_lambda.domain.errors import (
    AmbiguousCardError,
    CardClosedError,
    CardDataIntegrityError,
    CardNotFoundError,
    CardUpdateError,
    DataSourceUnavailableError,
    InvalidInputError,
)

logger = logging.getLogger(__name__)

BLOCKED: Final = "Blocked"
CLOSED: Final = "Closed"
REASONS: Final = ("customer_request", "lost", "stolen", "suspected_fraud")
_LAST4: Final = re.compile(r"[0-9]{4}")


class BlockCreditCardUseCase:
    """Block one of the customer's credit cards through a database-agnostic repository.

    The card is found by its last 4 digits, then blocked with a guarded UPDATE
    that only changes a card that is neither blocked nor closed. Both statements
    are safe to run twice. Port errors become domain errors whose messages tell
    the agent what to do next.
    """

    FIND_QUERY: Final = "find_credit_card"
    BLOCK_QUERY: Final = "block_credit_card"

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
    ) -> None:
        """Store the ports."""
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider

    def execute(
        self,
        customer_id: object,
        card_last4: object,
        reason: object,
        customer_confirmed: object,
        now: datetime,
    ) -> CardBlock:
        """Validate every input, then block the card unless it already is.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            card_last4: The card's last 4 digits, as they came.
            reason: suspected_fraud, lost, stolen or customer_request, as it came.
            customer_confirmed: Must be the boolean True.
            now: The tool's "now" (AS_OF in demos), written as last_updated.

        Raises:
            InvalidInputError: An input is invalid, or customer_confirmed isn't
                true. Raised before the database is touched.
            CardNotFoundError: No credit card of the customer ends in the digits.
            AmbiguousCardError: More than one does.
            CardClosedError: The card is closed.
            DataSourceUnavailableError: The database can't be reached, or kept
                reporting write conflicts.
            CardUpdateError: A query failed, or the card couldn't be blocked.
            CardDataIntegrityError: A returned row couldn't be read.
        """
        customer = _clean_customer_id(customer_id)
        last4 = _clean_card_last4(card_last4)
        clean_reason = _clean_reason(reason)
        _require_confirmation(customer_confirmed)
        try:
            already_blocked = self._block(customer, last4, _naive_utc(now))
        except (DataSourceConnectionError, WriteConflictError) as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise CardUpdateError() from exc
        # products has no column for the reason: this line is its only record.
        logger.info(
            "block_credit_card audit: customer_id=%s card_last4=%s reason=%s "
            "already_blocked=%s",
            customer,
            last4,
            clean_reason,
            already_blocked,
        )
        return CardBlock(
            card_last4=last4, status=BLOCKED, already_blocked=already_blocked
        )

    def _block(self, customer_id: str, card_last4: str, last_updated: datetime) -> bool:
        """Block the card; return True when it was already blocked."""
        product_id = self._card_to_block(customer_id, card_last4)
        if product_id is None:
            return True
        updated = self._run(
            self.BLOCK_QUERY,
            {
                "customer_id": customer_id,
                "product_id": product_id,
                "last_updated": last_updated,
            },
        )
        if updated:
            return False
        # The card changed between the two statements, or a retry after a lost
        # reply found its own committed UPDATE: decide from the card as it is now.
        if self._card_to_block(customer_id, card_last4) is None:
            return True
        raise CardUpdateError()

    def _card_to_block(self, customer_id: str, card_last4: str) -> str | None:
        """Return the product_id to block, or None when the card is already blocked.

        Raises:
            CardNotFoundError, AmbiguousCardError, CardClosedError: The card
                can't be blocked here.
            CardDataIntegrityError: The row couldn't be read.
        """
        rows = self._run(
            self.FIND_QUERY, {"customer_id": customer_id, "card_last4": card_last4}
        )
        if not rows:
            raise CardNotFoundError(card_last4)
        if len(rows) > 1:
            raise AmbiguousCardError(card_last4)
        try:
            product_id = _text(rows[0], "product_id")
            status = _text(rows[0], "product_status")
        except (KeyError, TypeError) as exc:
            raise CardDataIntegrityError() from exc
        if status == BLOCKED:
            return None
        if status == CLOSED:
            raise CardClosedError(card_last4)
        return product_id

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it."""
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return raw.strip().upper()


def _clean_card_last4(raw: object) -> str:
    """Strip the digits; they must be exactly 4 ASCII digits.

    Raises:
        InvalidInputError: Not a string, or not 4 ASCII digits after stripping.
    """
    if isinstance(raw, str) and _LAST4.fullmatch(raw.strip()):
        return raw.strip()
    raise InvalidInputError("card_last4", "must be exactly 4 digits")


def _clean_reason(raw: object) -> str:
    """Strip and lowercase the reason; it must be one of REASONS.

    Raises:
        InvalidInputError: Not one of REASONS.
    """
    if isinstance(raw, str) and raw.strip().lower() in REASONS:
        return raw.strip().lower()
    raise InvalidInputError("reason", f"must be one of: {', '.join(REASONS)}")


def _require_confirmation(raw: object) -> None:
    """Only the boolean True confirms; "true", 1 or a missing value don't.

    The Gateway's Cedar statement 3 will check it too (spec section 10).

    Raises:
        InvalidInputError: The value isn't True.
    """
    if raw is not True:
        raise InvalidInputError(
            "customer_confirmed",
            "must be true, after the customer explicitly confirmed the block",
        )


def _naive_utc(now: datetime) -> datetime:
    """Return ``now`` as naive UTC: products.last_updated has no time zone."""
    if now.tzinfo is None:
        return now
    return now.astimezone(timezone.utc).replace(tzinfo=None)


def _text(row: Mapping[str, Any], column: str) -> str:
    """Return a non-empty text column.

    Raises:
        KeyError: The column is missing.
        TypeError: The value isn't a non-empty string.
    """
    value = row[column]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{column} is {type(value).__name__}, expected text")
    return value
```

- [ ] **Step 8: Write the SQL files**

`block_credit_card_lambda/queries/postgresql/find_credit_card.sql` (UTF-8, no BOM):

```sql
-- find_credit_card (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The customer's credit cards whose number ends in the given 4 digits, with their
-- status. Used by BlockCreditCardUseCase before the UPDATE: no row means no such
-- card, and two rows mean the digits are ambiguous (LIMIT 2 is enough to tell).
--
-- Parameters (psycopg named placeholders):
--   customer_id  text  required (the use case strips and uppercases it)
--   card_last4   text  required, exactly 4 digits
--
-- product_id is the primary key, so there are no duplicate rows to remove. The
-- literal 'Tarjeta Crédito' is UTF-8; the connection uses client_encoding=utf8.
--
-- TODO(ledgerlens): W1 - not yet run against a real Aurora DSQL cluster.
SELECT p.product_id,
       p.product_status
FROM products AS p
WHERE p.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND RIGHT(p.product_number, 4) = %(card_last4)s
ORDER BY p.product_id
LIMIT 2
```

`block_credit_card_lambda/queries/postgresql/block_credit_card.sql`:

```sql
-- block_credit_card (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Blocks the one card find_credit_card returned. Used by BlockCreditCardUseCase.
--
-- Parameters (psycopg named placeholders):
--   product_id    text       required, from find_credit_card
--   customer_id   text       required, a second guard on the card's owner
--   last_updated  timestamp  required, the tool's "now" (AS_OF in demos), naive UTC
--
-- The status guard makes the statement safe to run twice: a card that is
-- already blocked, or closed, isn't touched and no row comes back. RETURNING
-- lets the repository read the result of an UPDATE with fetchall().
--
-- TODO(ledgerlens): W1 - UPDATE ... RETURNING not yet run on a real Aurora DSQL cluster.
UPDATE products
SET product_status = 'Blocked',
    last_updated   = %(last_updated)s
WHERE product_id = %(product_id)s
  AND customer_id = %(customer_id)s
  AND product_status NOT IN ('Blocked', 'Closed')
RETURNING product_id
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `PYTEST tests/unit/block_credit_card`
Expected: PASS.

- [ ] **Step 10: Lint and commit**

```bash
uvx ruff@0.14.1 check --fix gateway/tools/block_credit_card tests/unit/block_credit_card
uvx ruff@0.14.1 format gateway/tools/block_credit_card tests/unit/block_credit_card
git add gateway/tools/block_credit_card tests/unit/block_credit_card
git commit -m "feat(block_credit_card): use case, card errors and the find and guarded block queries"
```

---

### Task 4: `block_credit_card` delivery

**Files:**
- Create: `block_credit_card_lambda/delivery/presenters/card_block.py`, `block_credit_card_lambda/delivery/handler.py`, `gateway/tools/block_credit_card/tool_spec.json`
- Create (copied, then edited): `block_credit_card_lambda/delivery/dependencies/dependencies_builder.py`
- Test: `tests/unit/block_credit_card/test_card_block_presenter.py`, `test_delivery_wiring.py`, `test_block_credit_card_handler.py`; append to `test_query_contracts.py`

**Interfaces:**
- Consumes: `BlockCreditCardUseCase`, `CardBlock`, the domain errors (Task 3); `ClockSettings`, `DatabaseSettings` and `DsqlRepository` (Task 2).
- Produces:
  - `present_card_block(block: CardBlock) -> dict`
  - `build_block_credit_card_use_case(env) -> BlockCreditCardUseCase | None`
  - `build_clock(env)` and the other builder functions, as in `list_credit_cards`
  - `handler.handler(event, context)`, with `handler.TOOL_NAME = "block_credit_card"`, `handler.UNEXPECTED_ERROR_MESSAGE`, `handler.USE_CASE` and `handler.CLOCK`

- [ ] **Step 1: Write the failing presenter test**

`tests/unit/block_credit_card/test_card_block_presenter.py`:

```python
"""Tests for the block_credit_card presenter."""

import pytest
from block_credit_card_lambda.delivery.presenters.card_block import (
    present_card_block,
)
from block_credit_card_lambda.domain.entities.card_block import CardBlock

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("already_blocked", [False, True])
def test_presenter_returns_the_card_status_and_the_already_blocked_flag(
    already_blocked: bool,
) -> None:
    block = CardBlock(card_last4="4821", status="Blocked", already_blocked=already_blocked)

    assert present_card_block(block) == {
        "card_last4": "4821",
        "status": "Blocked",
        "already_blocked": already_blocked,
    }
```

- [ ] **Step 2: Write the failing wiring tests**

`tests/unit/block_credit_card/test_delivery_wiring.py`:

```python
"""Tests for the dependency wiring of the block_credit_card tool."""

from datetime import datetime, timezone

import block_credit_card_lambda.utils.connectors.dsql as dsql_module
import pytest
from block_credit_card_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from block_credit_card_lambda.application.use_cases.block_credit_card import (
    BlockCreditCardUseCase,
)
from block_credit_card_lambda.delivery.dependencies import dependencies_builder
from block_credit_card_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_block_credit_card_use_case,
    build_clock,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_query_provider,
    build_settings,
)
from block_credit_card_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from block_credit_card_lambda.domain.entities.card_block import CardBlock
from block_credit_card_lambda.infrastructure.repositories.dsql_repository import (
    DsqlRepository,
)
from block_credit_card_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import CUSTOMER_ID, QUERY_NAMES, FakeConnector, make_row

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
SETTINGS = DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL)
NOW = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
ARGS = {
    "customer_id": CUSTOMER_ID,
    "card_last4": "4821",
    "reason": "lost",
    "customer_confirmed": True,
}


def test_build_settings_reads_the_environment() -> None:
    assert build_settings(ENV) == SETTINGS


def test_build_dsql_settings_connects_as_the_write_role_by_default() -> None:
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ll_write"
    )


def test_build_connector_returns_a_dsql_connector_without_touching_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_boto3(*args: object, **kwargs: object) -> object:
        raise AssertionError("boto3 client created while building the connector")

    monkeypatch.setattr(dsql_module.boto3, "client", no_boto3)

    assert isinstance(build_connector(SETTINGS, ENV), DsqlConnector)


def test_aurora_dsql_runs_the_postgresql_sql_dialect() -> None:
    assert SQL_DIALECTS == {DatabaseEngine.AURORA_DSQL: "postgresql"}
    provider = build_query_provider(DatabaseEngine.AURORA_DSQL)

    assert provider is build_query_provider(DatabaseEngine.AURORA_DSQL)
    assert "UPDATE products" in provider.get("block_credit_card")


def test_every_engine_has_a_dialect_folder_with_every_query() -> None:
    for engine in DatabaseEngine:
        for name in QUERY_NAMES:
            assert (QUERIES_ROOT / SQL_DIALECTS[engine] / f"{name}.sql").is_file()


def test_queries_root_is_this_tools_own_folder() -> None:
    assert QUERIES_ROOT.parent.name == "block_credit_card_lambda"


def test_build_database_repository_wraps_the_connector_for_the_engine() -> None:
    repository = build_database_repository(DatabaseEngine.AURORA_DSQL, FakeConnector())

    assert isinstance(repository, DsqlRepository)


def test_build_database_repository_rejects_an_unknown_engine() -> None:
    with pytest.raises(ConfigurationError):
        build_database_repository("oracle", FakeConnector())  # type: ignore[arg-type]


def use_fake_connector(
    monkeypatch: pytest.MonkeyPatch, connector: FakeConnector
) -> None:
    """Make the builder hand out ``connector`` instead of a real DSQL one."""
    monkeypatch.setattr(
        dependencies_builder, "build_connector", lambda _settings, _env: connector
    )


def test_use_case_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(([make_row()], [{"product_id": "PRD-1"}]))
    use_fake_connector(monkeypatch, connector)

    use_case = build_block_credit_card_use_case(ENV)
    assert isinstance(use_case, BlockCreditCardUseCase)

    assert use_case.execute(**ARGS, now=NOW) == CardBlock(
        card_last4="4821", status="Blocked", already_blocked=False
    )
    find, update = connector.connections[-1].cursors
    assert "FROM products" in find.executed[0][0]
    assert "UPDATE products" in update.executed[0][0]


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_block_credit_card_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(
        DataSourceConnectionError("no route to host"),
        [make_row(product_status="Blocked")],
    )
    use_fake_connector(monkeypatch, connector)

    use_case = build_block_credit_card_use_case(ENV)

    assert use_case is not None
    assert use_case.execute(**ARGS, now=NOW).already_blocked is True


@pytest.mark.parametrize(
    "env",
    [
        {},
        {**ENV, "DB_ENGINE": "oracle"},
        {"AWS_REGION": "us-east-1"},
        {"DSQL_CLUSTER_ENDPOINT": ENDPOINT},
        {**ENV, "DSQL_CLUSTER_ENDPOINT": f"https://{ENDPOINT}"},
    ],
)
def test_use_case_build_with_bad_configuration_returns_none(
    env: dict[str, str],
) -> None:
    assert build_block_credit_card_use_case(env) is None


def test_build_clock_reads_as_of() -> None:
    assert build_clock({"AS_OF": "2026-03-14"}) == ClockSettings(
        as_of=datetime(2026, 3, 14, tzinfo=timezone.utc)
    )


def test_build_clock_with_a_bad_as_of_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert build_clock({"AS_OF": "yesterday"}) is None
    assert "Invalid AS_OF for block_credit_card" in caplog.text
```

- [ ] **Step 3: Write the failing handler tests**

`tests/unit/block_credit_card/test_block_credit_card_handler.py`:

```python
"""Tests for the block_credit_card Lambda handler."""

import importlib
import json
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from block_credit_card_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from block_credit_card_lambda.application.use_cases.block_credit_card import (
    BlockCreditCardUseCase,
)
from block_credit_card_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from block_credit_card_lambda.delivery.settings import ClockSettings, DatabaseEngine
from block_credit_card_lambda.domain.errors import (
    CardNotFoundError,
    CardUpdateError,
    DataSourceUnavailableError,
)

from .fakes import CUSTOMER_ID, FakeConnector, make_row

pytestmark = pytest.mark.unit

EVENT = {
    "customer_id": CUSTOMER_ID,
    "card_last4": "4821",
    "reason": "suspected_fraud",
    "customer_confirmed": True,
}
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
BLOCKED = [{"product_id": "PRD-1"}]
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
NOT_CONFIRMED = (
    "Invalid value for 'customer_confirmed': must be true, after the customer "
    "explicitly confirmed the block. Ask the customer to confirm and retry."
)


def make_context(
    tool_name: str = "block-credit-card-target___block_credit_card",
) -> SimpleNamespace:
    """Build a Lambda context carrying the Gateway tool name."""
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name})
    )


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the handler module fresh, with no DB env vars (no AWS calls)."""
    for name in (
        "DB_ENGINE",
        "DSQL_CLUSTER_ENDPOINT",
        "DSQL_DB_USER",
        "AWS_REGION",
        "AS_OF",
    ):
        monkeypatch.delenv(name, raising=False)
    import block_credit_card_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any) -> None:
    """Point the handler at real adapters over a fake connector, with AS_OF set."""
    use_case = BlockCreditCardUseCase(
        database_repository=build_database_repository(
            DatabaseEngine.AURORA_DSQL, connector
        ),
        query_provider=build_query_provider(DatabaseEngine.AURORA_DSQL),
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def executed(connector: FakeConnector) -> list[tuple[str, Any]]:
    """Return (sql, params) of every statement on the last connection."""
    return [cursor.executed[0] for cursor in connector.connections[-1].cursors]


def test_success_blocks_the_card_with_the_clocks_now(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector(([make_row()], BLOCKED))
    wire(module, monkeypatch, connector)

    payload = body(module.handler(EVENT, make_context()))

    assert payload == {"card_last4": "4821", "status": "Blocked", "already_blocked": False}
    (_, find_params), (block_sql, block_params) = executed(connector)
    assert find_params == {"customer_id": CUSTOMER_ID, "card_last4": "4821"}
    assert "UPDATE products" in block_sql
    assert block_params == {
        "customer_id": CUSTOMER_ID,
        "product_id": "PRD-1",
        "last_updated": datetime(2026, 6, 17, 23, 59, 59),
    }


def test_an_already_blocked_card_is_reported_without_an_update(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row(product_status="Blocked")])
    wire(module, monkeypatch, connector)

    assert body(module.handler(EVENT, make_context()))["already_blocked"] is True
    assert len(executed(connector)) == 1


@pytest.mark.parametrize("confirmed", [False, None, "true", 1])
def test_an_unconfirmed_block_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, confirmed: object
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler({**EVENT, "customer_confirmed": confirmed}, make_context())

    assert response == {"error": NOT_CONFIRMED}
    assert connector.connections == []


def test_a_missing_confirmation_returns_the_input_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)
    event = {k: v for k, v in EVENT.items() if k != "customer_confirmed"}

    assert module.handler(event, make_context()) == {"error": NOT_CONFIRMED}
    assert connector.connections == []


@pytest.mark.parametrize("event", [None, [], "block 4821"])
def test_a_non_object_event_returns_the_customer_id_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    assert module.handler(event, make_context()) == {"error": INVALID_CUSTOMER_ID}
    assert connector.connections == []


def test_an_unknown_card_returns_the_not_found_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    response = module.handler(EVENT, make_context())

    assert response == {"error": CardNotFoundError("4821").message}


def test_a_query_failure_returns_the_card_update_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "products" does not exist')
    wire(module, monkeypatch, FakeConnector(error))

    assert module.handler(EVENT, make_context()) == {"error": CardUpdateError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("list-credit-cards-target___list_credit_cards"),
        None,
        SimpleNamespace(client_context=None),
        SimpleNamespace(client_context=SimpleNamespace(custom={})),
    ],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    connector = FakeConnector()
    wire(module, monkeypatch, connector)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "block_credit_card" in response["error"]
    assert connector.connections == []


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(**_kwargs: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error blocking the card. "
        "Offer an urgent hand-off to a human agent."
    )


def test_missing_configuration_returns_data_source_unavailable(
    module: ModuleType,
) -> None:
    assert module.USE_CASE is None

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_cold_start_failure_then_failed_retry_returns_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector(DataSourceConnectionError("down")))

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_missing_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)
    monkeypatch.setattr(module, "CLOCK", None)

    assert module.handler(EVENT, make_context()) == {
        "error": DataSourceUnavailableError.MESSAGE
    }
    assert connector.connections == []
```

- [ ] **Step 4: Write the failing tool spec tests**

Append to `tests/unit/block_credit_card/test_query_contracts.py`:

```python
def tool_spec() -> dict:
    """Load the single tool definition from tool_spec.json."""
    import json

    specs = json.loads((TOOL_ROOT / "tool_spec.json").read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_tool_spec_name_inputs_and_required_fields() -> None:
    from block_credit_card_lambda.application.use_cases.block_credit_card import (
        REASONS,
    )

    spec = tool_spec()
    properties = spec["inputSchema"]["properties"]

    assert spec["name"] == "block_credit_card"
    assert spec["inputSchema"]["required"] == [
        "customer_id",
        "card_last4",
        "reason",
        "customer_confirmed",
    ]
    assert set(properties) == {"customer_id", "card_last4", "reason", "customer_confirmed"}
    assert set(properties["reason"]["enum"]) == set(REASONS)
    assert properties["customer_confirmed"]["type"] == "boolean"


def test_tool_spec_description_demands_an_explicit_yes() -> None:
    description = tool_spec()["description"]

    assert "Only call after the customer explicitly said yes" in description
    assert "'already_blocked'" in description
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `PYTEST tests/unit/block_credit_card`
Expected: FAIL. `ModuleNotFoundError` for `...delivery.presenters.card_block`, `...delivery.dependencies.dependencies_builder` and `...delivery.handler`, and a `FileNotFoundError` for `tool_spec.json`.

- [ ] **Step 6: Write the presenter**

`block_credit_card_lambda/delivery/presenters/card_block.py`:

```python
"""Present the block_credit_card result as the JSON returned to the agent."""

from typing import Any

from block_credit_card_lambda.domain.entities.card_block import CardBlock


def present_card_block(block: CardBlock) -> dict[str, Any]:
    """Return ``{"card_last4", "status", "already_blocked"}``.

    ``already_blocked`` true means the card was blocked before this call; the
    agent tells the customer the card is blocked, not that anything failed.
    """
    return {
        "card_last4": block.card_last4,
        "status": block.status,
        "already_blocked": block.already_blocked,
    }
```

- [ ] **Step 7: Copy the builder and drop `max_rows`**

```bash
sed -e 's/list_credit_cards/block_credit_card/g' -e 's/ListCreditCardsUseCase/BlockCreditCardUseCase/g' \
  gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py \
  > gateway/tools/block_credit_card/block_credit_card_lambda/delivery/dependencies/dependencies_builder.py
```

Then, in the new file, delete the line `            max_rows=settings.max_rows,` inside `build_block_credit_card_use_case`.

Check: `grep -n "max_rows\|list_credit\|ListCredit" gateway/tools/block_credit_card/block_credit_card_lambda/delivery/dependencies/dependencies_builder.py`
Expected: no output.

- [ ] **Step 8: Write the handler**

`block_credit_card_lambda/delivery/handler.py`:

```python
"""Lambda handler for the ``block_credit_card`` Gateway tool.

Handler string: ``block_credit_card_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/block_credit_card/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix. Every argument is passed to the use case bare, exactly
as it came; the use case validates and cleans them.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Raw exception text is never returned: it
could leak SQL, hosts or driver details to the model.

The use case and its whole graph are built once, when the module loads, by
dependencies_builder; a warm container reuses them. AS_OF (optional) is read
once into CLOCK, and CLOCK.now() becomes the card's last_updated on every call.
An invalid AS_OF answers every request with DataSourceUnavailableError's message.

TODO(ledgerlens): R1 - deployed by the data stack (ledgerlens-block-credit-card,
  role ledgerlens-write-tools); no Gateway target or Cedar statement 3 yet (write
  tools spec section 10), so the agent can't call it.
TODO(ledgerlens): R5 - customer_id is trusted from the tool input until Cedar
  statement 2 covers this tool (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from block_credit_card_lambda.delivery.dependencies.dependencies_builder import (
    build_block_credit_card_use_case,
    build_clock,
)
from block_credit_card_lambda.delivery.presenters.card_block import (
    present_card_block,
)
from block_credit_card_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "block_credit_card"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error blocking the card. "
    "Offer an urgent hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_block_credit_card_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Block one of the customer's credit cards for the agent.

    Args:
        event: Tool arguments passed directly by the AgentCore Gateway.
        context: Lambda context with the tool name in client_context.custom.

    Returns:
        A Gateway ``content`` response, or ``{"error": message}``.
    """
    tool_name = _tool_name(context)
    if tool_name != TOOL_NAME:
        logger.error("Unexpected tool name %r for %s", tool_name, TOOL_NAME)
        return {"error": _WRONG_TOOL_MESSAGE}

    args = event if isinstance(event, Mapping) else {}
    try:
        if USE_CASE is None or CLOCK is None:
            raise DataSourceUnavailableError()
        body = present_card_block(
            USE_CASE.execute(
                customer_id=args.get("customer_id"),
                card_last4=args.get("card_last4"),
                reason=args.get("reason"),
                customer_confirmed=args.get("customer_confirmed"),
                now=CLOCK.now(),
            )
        )
    except DomainError as err:
        logger.warning(
            "%s returned an error: %s", TOOL_NAME, err.message, exc_info=True
        )
        return {"error": err.message}
    except Exception:
        logger.exception("Unexpected error in %s", TOOL_NAME)
        return {"error": UNEXPECTED_ERROR_MESSAGE}

    logger.info(
        "%s: card %s blocked (already_blocked=%s)",
        TOOL_NAME,
        body["card_last4"],
        body["already_blocked"],
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _tool_name(context: object) -> str | None:
    """Return the tool name without its ``<target>___`` prefix, or None if absent."""
    try:
        full_name = context.client_context.custom["bedrockAgentCoreToolName"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return None
    if not isinstance(full_name, str):
        return None
    return full_name.rpartition(_TOOL_NAME_DELIMITER)[2]
```

- [ ] **Step 9: Write `gateway/tools/block_credit_card/tool_spec.json`**

```json
[
  {
    "name": "block_credit_card",
    "description": "Blocks one of the customer's credit cards immediately so it can't be charged again. Only call after the customer explicitly said yes, in this conversation, to blocking the card with these last 4 digits. Can't be undone through this assistant. Returns JSON with 'card_last4', 'status' and 'already_blocked' (true when the card was already blocked; that is not an error).",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": {
          "type": "string",
          "description": "The authenticated customer's id from get_session_context."
        },
        "card_last4": {
          "type": "string",
          "description": "Last 4 digits of the card, from list_credit_cards."
        },
        "reason": {
          "type": "string",
          "enum": ["suspected_fraud", "lost", "stolen", "customer_request"]
        },
        "customer_confirmed": {
          "type": "boolean",
          "description": "Must be true: the customer explicitly said yes to blocking this card."
        }
      },
      "required": ["customer_id", "card_last4", "reason", "customer_confirmed"]
    }
  }
]
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `PYTEST tests/unit/block_credit_card`
Expected: PASS.

- [ ] **Step 11: Lint and commit**

```bash
uvx ruff@0.14.1 check --fix gateway/tools/block_credit_card tests/unit/block_credit_card
uvx ruff@0.14.1 format gateway/tools/block_credit_card tests/unit/block_credit_card
git add gateway/tools/block_credit_card tests/unit/block_credit_card
git commit -m "feat(block_credit_card): handler, presenter, builder and tool spec"
```

---

### Task 5: `open_claim`, the write infrastructure (copied from `block_credit_card`)

**Files:**
- Create (copied from `gateway/tools/block_credit_card/`): `requirements.txt`, every `__init__.py`, the ports, `file_query_provider.py`, `dsql_repository.py`, the connectors and `delivery/settings.py`
- Create (copied, then edited): `tests/unit/open_claim/{__init__,conftest,fakes}.py`
- Test (copied): `tests/unit/open_claim/test_{file_query_provider,dsql_repository,psycopg_connector,dsql_connector,settings}.py`

**Interfaces:**
- Consumes: Task 2's write infrastructure, copied.
- Produces:
  - The same ports, port errors, `DsqlRepository` and settings, all under `open_claim_lambda`.
  - Test fakes: as in Task 2, but `QUERY_NAMES = ("claim_transactions", "insert_claim", "resolution_estimate")`, and `make_row(**overrides)` builds a `claim_transactions` row with the keys `transaction_id`, `product_id`, `card_last4`, `amount`, `currency` and `amount_usd`.

- [ ] **Step 1: Copy the tests and fakes**

```bash
SRC_T=tests/unit/block_credit_card
DST_T=tests/unit/open_claim
mkdir -p "$DST_T"
: > "$DST_T/__init__.py"
for f in conftest.py fakes.py test_file_query_provider.py test_dsql_repository.py \
         test_psycopg_connector.py test_dsql_connector.py test_settings.py; do
  sed 's/block_credit_card/open_claim/g' "$SRC_T/$f" > "$DST_T/$f"
done
```

- [ ] **Step 2: Adapt `tests/unit/open_claim/fakes.py` to transaction rows**

(a) Change the line `from datetime import timedelta` to:

```python
from datetime import timedelta
from decimal import Decimal
```

(b) Replace the `QUERY_NAMES` line (after the sed it reads `QUERY_NAMES: Final = ("find_credit_card", "open_claim")`) with:

```python
QUERY_NAMES: Final = ("claim_transactions", "insert_claim", "resolution_estimate")
```

(c) Replace the whole `make_row` function with:

```python
def make_row(**overrides: Any) -> dict[str, Any]:
    """Build a claim_transactions row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "transaction_id": "TRX-1",
        "product_id": "PRD-1",
        "card_last4": "4821",
        "amount": Decimal("740.00"),
        "currency": "USD",
        "amount_usd": Decimal("740.00"),
    }
    row.update(overrides)
    return row
```

Check: `grep -n "block_credit_card\|find_credit_card\|product_status" tests/unit/open_claim/*.py`
Expected: no output.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTEST tests/unit/open_claim`
Expected: FAIL. Collection errors with `ModuleNotFoundError: No module named 'open_claim_lambda'`.

- [ ] **Step 4: Copy the production files**

```bash
SRC=gateway/tools/block_credit_card
DST=gateway/tools/open_claim
P=block_credit_card_lambda
for f in requirements.txt \
  $P/__init__.py \
  $P/application/__init__.py \
  $P/application/ports/__init__.py \
  $P/application/ports/database_repository.py \
  $P/application/ports/query_provider.py \
  $P/application/ports/errors.py \
  $P/application/use_cases/__init__.py \
  $P/delivery/__init__.py \
  $P/delivery/settings.py \
  $P/delivery/dependencies/__init__.py \
  $P/delivery/presenters/__init__.py \
  $P/domain/__init__.py \
  $P/domain/entities/__init__.py \
  $P/infrastructure/__init__.py \
  $P/infrastructure/queries/__init__.py \
  $P/infrastructure/queries/file_query_provider.py \
  $P/infrastructure/repositories/__init__.py \
  $P/infrastructure/repositories/dsql_repository.py \
  $P/utils/__init__.py \
  $P/utils/connectors/__init__.py \
  $P/utils/connectors/base.py \
  $P/utils/connectors/dsql.py; do
  out="$DST/${f//block_credit_card/open_claim}"
  mkdir -p "$(dirname "$out")"
  sed 's/block_credit_card/open_claim/g' "$SRC/$f" > "$out"
done
grep -rn "block_credit_card\|list_credit_cards" "$DST" && echo "UNEXPECTED" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTEST tests/unit/open_claim`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
uvx ruff@0.14.1 check --fix gateway/tools/open_claim tests/unit/open_claim
uvx ruff@0.14.1 format gateway/tools/open_claim tests/unit/open_claim
git add gateway/tools/open_claim tests/unit/open_claim
git commit -m "feat(open_claim): write-tool infrastructure copied from block_credit_card"
```

---

### Task 6: `open_claim`, the domain, use case and SQL

**Files:**
- Create: `open_claim_lambda/domain/entities/claim.py`, `open_claim_lambda/domain/errors.py`, `open_claim_lambda/application/use_cases/open_claim.py`, `open_claim_lambda/queries/postgresql/{claim_transactions,insert_claim,resolution_estimate}.sql`
- Test: `tests/unit/open_claim/test_errors.py`, `test_open_claim_use_case.py`, `test_query_contracts.py`

(All `open_claim_lambda/...` paths are under `gateway/tools/open_claim/`.)

**Interfaces:**
- Consumes: Task 5's ports, port errors and fakes.
- Produces:
  - Entities:
    - `Claim(claim_id: str, card_last4: str, transaction_ids: tuple[str, ...], claimed_amount: Decimal, currency: str, priority: str, status: str, already_existed: bool)`
    - `ResolutionEstimate(median_days: int, p90_days: int)`
    - `ClaimsResult(claims: tuple[Claim, ...], resolution_estimate: ResolutionEstimate | None)`
  - `OpenClaimUseCase(database_repository, query_provider)`, with `TRANSACTIONS_QUERY`, `INSERT_QUERY` and `ESTIMATE_QUERY`
    - `.execute(customer_id, transaction_ids, claim_type, customer_statement, customer_confirmed, now: datetime) -> ClaimsResult`
  - Module-level: `claim_id_for(customer_id, claim_type, product_id, currency, transaction_ids) -> str` and `SUBCATEGORIES`
  - Domain errors: `DomainError`, `InvalidInputError`, `TransactionsNotFoundError(transaction_ids)` (with `.transaction_ids`), `DataSourceUnavailableError`, `ClaimError`, `ClaimDataIntegrityError`

- [ ] **Step 1: Write the failing error tests**

`tests/unit/open_claim/test_errors.py`:

```python
"""Tests for domain and port error definitions."""

import pytest
from open_claim_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
    WriteConflictError,
)
from open_claim_lambda.domain.errors import (
    ClaimDataIntegrityError,
    ClaimError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    TransactionsNotFoundError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError("claim_type", "must be fraud or dispute")

    assert error.message == (
        "Invalid value for 'claim_type': must be fraud or dispute. "
        "Ask the customer to confirm and retry."
    )


def test_transactions_not_found_names_the_missing_ids() -> None:
    error = TransactionsNotFoundError(["TRX-9", "TRX-10"])

    assert isinstance(error, DomainError)
    assert error.transaction_ids == ("TRX-9", "TRX-10")
    assert error.message == (
        "These transactions weren't found among the customer's credit card "
        "transactions: TRX-9, TRX-10. Check them with list_card_transactions "
        "and retry."
    )


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (
            DataSourceUnavailableError,
            "The claim service is temporarily unavailable. Tell the customer and "
            "offer to retry in a moment or hand off to a human agent.",
        ),
        (
            ClaimError,
            "The claim couldn't be opened due to an internal error. Don't retry; "
            "offer a hand-off to a human agent.",
        ),
        (
            ClaimDataIntegrityError,
            "Transaction data came back in an unexpected format. Don't retry; "
            "offer a hand-off to a human agent.",
        ),
    ],
)
def test_fixed_domain_errors_carry_agent_facing_messages(
    error_type: type[DomainError], expected: str
) -> None:
    error = error_type()

    assert isinstance(error, DomainError)
    assert error.message == expected
    assert error_type.MESSAGE == expected  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "error_type",
    [
        DataSourceConnectionError,
        QueryLimitExceededError,
        QueryExecutionError,
        QueryNotFoundError,
        DuplicateKeyError,
        WriteConflictError,
    ],
)
def test_port_errors_share_a_base_class(error_type: type[DataAccessError]) -> None:
    assert issubclass(error_type, DataAccessError)
    assert not issubclass(error_type, DomainError)
```

- [ ] **Step 2: Write the failing use case tests**

`tests/unit/open_claim/test_open_claim_use_case.py`:

```python
"""Tests for OpenClaimUseCase."""

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from open_claim_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    WriteConflictError,
)
from open_claim_lambda.application.use_cases.open_claim import (
    OpenClaimUseCase,
    claim_id_for,
)
from open_claim_lambda.domain.entities.claim import (
    Claim,
    ClaimsResult,
    ResolutionEstimate,
)
from open_claim_lambda.domain.errors import (
    ClaimDataIntegrityError,
    ClaimError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    TransactionsNotFoundError,
)

from .fakes import (
    CUSTOMER_ID,
    FakeDatabaseRepository,
    FakeQueryProvider,
    Outcomes,
    make_row,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
NAIVE_NOW = datetime(2026, 6, 17, 23, 59, 59)
TXS = "claim_transactions"
INSERT = "insert_claim"
ESTIMATE = "resolution_estimate"
STATEMENT = "No reconozco este cargo"
INSERTED = [{"complaint_id": "CMP-X"}]
ESTIMATE_ROW = [{"median_days": 4.2, "p90_days": Decimal("11.5")}]
ARGS: dict[str, Any] = {
    "customer_id": CUSTOMER_ID,
    "transaction_ids": ["TRX-1"],
    "claim_type": "fraud",
    "customer_statement": STATEMENT,
    "customer_confirmed": True,
}


def make_use_case(
    results: dict[str, Outcomes] | None = None,
    query_provider: FakeQueryProvider | None = None,
) -> tuple[OpenClaimUseCase, FakeDatabaseRepository]:
    """Build the use case over fakes; return it with its repository."""
    repository = FakeDatabaseRepository(results)
    use_case = OpenClaimUseCase(
        database_repository=repository,
        query_provider=query_provider or FakeQueryProvider(),
    )
    return use_case, repository


def open_claim(use_case: OpenClaimUseCase, **overrides: Any) -> ClaimsResult:
    """Run the use case with ARGS, overridden by ``overrides``."""
    return use_case.execute(**{**ARGS, **overrides}, now=NOW)


def default_results(rows: list[dict[str, Any]] | None = None) -> dict[str, Outcomes]:
    """One fraud transaction, a successful insert and an estimate."""
    return {TXS: rows or [make_row()], INSERT: INSERTED, ESTIMATE: ESTIMATE_ROW}


def test_a_fraud_claim_is_opened_with_the_estimate() -> None:
    use_case, repository = make_use_case(default_results())

    result = open_claim(use_case)

    claim_id = claim_id_for(CUSTOMER_ID, "fraud", "PRD-1", "USD", ["TRX-1"])
    assert result == ClaimsResult(
        claims=(
            Claim(
                claim_id=claim_id,
                card_last4="4821",
                transaction_ids=("TRX-1",),
                claimed_amount=Decimal("740.00"),
                currency="USD",
                priority="High",
                status="Open",
                already_existed=False,
            ),
        ),
        resolution_estimate=ResolutionEstimate(median_days=5, p90_days=12),
    )
    assert repository.params_of(TXS) == [
        {"customer_id": CUSTOMER_ID, "transaction_ids": ["TRX-1"]}
    ]
    assert repository.params_of(INSERT) == [
        {
            "complaint_id": claim_id,
            "creation_date": NAIVE_NOW,
            "process_date": NAIVE_NOW.date(),
            "customer_id": CUSTOMER_ID,
            "subcategory": "Cargo no reconocido",
            "product_id": "PRD-1",
            "description": f"{STATEMENT} | tx: TRX-1",
            "claimed_amount": Decimal("740.00"),
            "currency": "USD",
            "priority": "High",
        }
    ]
    assert repository.params_of(ESTIMATE) == [
        {"subcategory": "Cargo no reconocido", "since": datetime(2025, 6, 17, 23, 59, 59)}
    ]


def test_a_dispute_uses_its_own_subcategory() -> None:
    use_case, repository = make_use_case(default_results())

    open_claim(use_case, claim_type=" Dispute ")

    assert repository.params_of(INSERT)[0]["subcategory"] == "Cobro indebido"
    assert repository.params_of(ESTIMATE)[0]["subcategory"] == "Cobro indebido"


@pytest.mark.parametrize(
    ("amounts_usd", "priority"),
    [
        ([Decimal("95.00")], "Medium"),
        ([Decimal("500.00")], "Medium"),
        ([Decimal("500.01")], "High"),
        ([Decimal("300.00"), Decimal("200.01")], "High"),
        ([None], "High"),
        ([Decimal("10.00"), None], "High"),
    ],
)
def test_priority_is_high_above_500_usd_or_when_unknown(
    amounts_usd: list[Decimal | None], priority: str
) -> None:
    rows = [
        make_row(transaction_id=f"TRX-{i}", amount_usd=usd)
        for i, usd in enumerate(amounts_usd, start=1)
    ]
    ids = [row["transaction_id"] for row in rows]
    use_case, _ = make_use_case(default_results(rows))

    result = open_claim(use_case, transaction_ids=ids)

    assert result.claims[0].priority == priority


def test_transaction_ids_are_cleaned_and_deduplicated_in_order() -> None:
    rows = [make_row(transaction_id="TRX-2"), make_row(transaction_id="TRX-1")]
    use_case, repository = make_use_case(default_results(rows))

    result = open_claim(use_case, transaction_ids=[" trx-2", "TRX-1", "trx-2 "])

    assert repository.params_of(TXS)[0]["transaction_ids"] == ["TRX-2", "TRX-1"]
    assert result.claims[0].transaction_ids == ("TRX-2", "TRX-1")
    assert result.claims[0].claimed_amount == Decimal("1480.00")
    assert repository.params_of(INSERT)[0]["description"] == (
        f"{STATEMENT} | tx: TRX-2,TRX-1"
    )


def test_one_claim_per_card_and_currency_ordered_by_card_then_currency() -> None:
    rows = [
        make_row(transaction_id="TRX-1", product_id="PRD-B", card_last4="9999"),
        make_row(transaction_id="TRX-2", product_id="PRD-A", card_last4="1111"),
        make_row(
            transaction_id="TRX-3",
            product_id="PRD-A",
            card_last4="1111",
            currency="COP",
            amount=Decimal("350000.00"),
            amount_usd=Decimal("87.50"),
        ),
        make_row(transaction_id="TRX-4", product_id="PRD-A", card_last4="1111"),
    ]
    use_case, repository = make_use_case(default_results(rows))

    result = open_claim(
        use_case, transaction_ids=["TRX-1", "TRX-2", "TRX-3", "TRX-4"]
    )

    assert [(c.card_last4, c.currency, c.transaction_ids) for c in result.claims] == [
        ("1111", "COP", ("TRX-3",)),
        ("1111", "USD", ("TRX-2", "TRX-4")),
        ("9999", "USD", ("TRX-1",)),
    ]
    assert [c.claimed_amount for c in result.claims] == [
        Decimal("350000.00"),
        Decimal("1480.00"),
        Decimal("740.00"),
    ]
    assert len({c.claim_id for c in result.claims}) == 3
    assert len(repository.params_of(INSERT)) == 3


def test_the_same_transactions_in_another_order_give_the_same_claim_id() -> None:
    rows = [make_row(transaction_id="TRX-1"), make_row(transaction_id="TRX-2")]
    first, _ = make_use_case(default_results(rows))
    second, _ = make_use_case(default_results(rows))

    a = open_claim(first, transaction_ids=["TRX-1", "TRX-2"]).claims[0].claim_id
    b = open_claim(second, transaction_ids=["trx-2", "TRX-1"]).claims[0].claim_id

    assert a == b
    assert re.fullmatch(r"CMP-[A-Z2-7]{20}", a)


def test_the_claim_id_depends_on_every_part_of_the_claim() -> None:
    base = ("CLI-1", "fraud", "PRD-1", "USD", ["TRX-1"])
    variants = [
        ("CLI-2", "fraud", "PRD-1", "USD", ["TRX-1"]),
        ("CLI-1", "dispute", "PRD-1", "USD", ["TRX-1"]),
        ("CLI-1", "fraud", "PRD-2", "USD", ["TRX-1"]),
        ("CLI-1", "fraud", "PRD-1", "COP", ["TRX-1"]),
        ("CLI-1", "fraud", "PRD-1", "USD", ["TRX-1", "TRX-2"]),
    ]

    assert len({claim_id_for(*v) for v in [base, *variants]}) == 6


def test_an_existing_claim_is_returned_as_already_existed() -> None:
    results = default_results()
    results[INSERT] = DuplicateKeyError("23505")
    use_case, repository = make_use_case(results)

    result = open_claim(use_case)

    assert result.claims[0].already_existed is True
    assert result.claims[0].status == "Open"
    assert result.resolution_estimate == ResolutionEstimate(median_days=5, p90_days=12)
    assert len(repository.params_of(INSERT)) == 1


def test_missing_transactions_raise_not_found_before_any_insert() -> None:
    use_case, repository = make_use_case(default_results([make_row()]))

    with pytest.raises(TransactionsNotFoundError) as caught:
        open_claim(use_case, transaction_ids=["TRX-1", "TRX-9", "TRX-8"])

    assert caught.value.transaction_ids == ("TRX-9", "TRX-8")
    assert repository.params_of(INSERT) == []


def test_no_estimate_when_history_is_too_short() -> None:
    results = default_results()
    results[ESTIMATE] = []
    use_case, _ = make_use_case(results)

    assert open_claim(use_case).resolution_estimate is None


@pytest.mark.parametrize(
    "estimate",
    [
        QueryExecutionError("function percentile_cont does not exist"),
        DataSourceConnectionError("down"),
        [{"median_days": None, "p90_days": 3}],
        [{"median_days": float("nan"), "p90_days": 3}],
        [{"p90_days": 3}],
    ],
)
def test_a_failed_estimate_never_fails_the_written_claims(
    estimate: Outcomes, caplog: pytest.LogCaptureFixture
) -> None:
    results = default_results()
    results[ESTIMATE] = estimate
    use_case, _ = make_use_case(results)
    caplog.set_level(logging.WARNING)

    result = open_claim(use_case)

    assert result.resolution_estimate is None
    assert len(result.claims) == 1
    assert "Resolution estimate failed" in caplog.text


def test_a_missing_estimate_sql_file_gives_no_estimate() -> None:
    provider = FakeQueryProvider(names=(TXS, INSERT))
    use_case, _ = make_use_case(default_results(), query_provider=provider)

    assert open_claim(use_case).resolution_estimate is None


def assert_rejected(field: str, **overrides: Any) -> InvalidInputError:
    """Run with ``overrides``; it must fail on ``field`` before any query."""
    use_case, repository = make_use_case(default_results())
    with pytest.raises(InvalidInputError) as caught:
        open_claim(use_case, **overrides)
    assert caught.value.field == field
    assert repository.calls == []
    return caught.value


@pytest.mark.parametrize(
    "transaction_ids",
    [
        None,
        "TRX-1",
        [],
        [""],
        ["   "],
        [1],
        ["X" * 31],
        [f"TRX-{i}" for i in range(11)],
    ],
)
def test_transaction_ids_must_be_1_to_10_ids(transaction_ids: object) -> None:
    error = assert_rejected("transaction_ids", transaction_ids=transaction_ids)

    assert error.reason == (
        "must be a list of 1 to 10 transaction ids from list_card_transactions"
    )


def test_ten_distinct_ids_with_repeats_are_accepted() -> None:
    ids = [f"TRX-{i}" for i in range(10)] * 2
    rows = [make_row(transaction_id=f"TRX-{i}") for i in range(10)]
    use_case, repository = make_use_case(default_results(rows))

    open_claim(use_case, transaction_ids=ids)

    assert len(repository.params_of(TXS)[0]["transaction_ids"]) == 10


@pytest.mark.parametrize("claim_type", [None, "", "chargeback", 1])
def test_claim_type_must_be_fraud_or_dispute(claim_type: object) -> None:
    error = assert_rejected("claim_type", claim_type=claim_type)

    assert error.reason == "must be fraud or dispute"


@pytest.mark.parametrize("statement", [None, "", "   ", "x" * 501, 42])
def test_the_statement_must_be_1_to_500_characters(statement: object) -> None:
    error = assert_rejected("customer_statement", customer_statement=statement)

    assert error.reason == "must be the customer's own words, 1 to 500 characters"


def test_a_statement_of_500_characters_is_accepted() -> None:
    use_case, repository = make_use_case(default_results())

    open_claim(use_case, customer_statement="x" * 500)

    assert repository.params_of(INSERT)[0]["description"].startswith("x" * 500)


@pytest.mark.parametrize("confirmed", [False, None, "true", 1])
def test_only_the_boolean_true_confirms_the_claim(confirmed: object) -> None:
    error = assert_rejected("customer_confirmed", customer_confirmed=confirmed)

    assert error.reason == (
        "must be true, after the customer explicitly confirmed these transactions"
    )


@pytest.mark.parametrize("customer_id", [None, "", "   ", 42])
def test_a_bad_customer_id_is_rejected(customer_id: object) -> None:
    assert_rejected("customer_id", customer_id=customer_id)


@pytest.mark.parametrize(
    ("failing_query", "port_error", "domain_error"),
    [
        (TXS, DataSourceConnectionError("down"), DataSourceUnavailableError),
        (TXS, QueryExecutionError("boom"), ClaimError),
        (INSERT, WriteConflictError("40001"), DataSourceUnavailableError),
        (INSERT, QueryExecutionError("boom"), ClaimError),
    ],
)
def test_port_errors_become_domain_errors(
    failing_query: str,
    port_error: DataAccessError,
    domain_error: type[DomainError],
) -> None:
    results = default_results()
    results[failing_query] = port_error
    use_case, _ = make_use_case(results)

    with pytest.raises(domain_error) as caught:
        open_claim(use_case)

    assert caught.value.__cause__ is port_error


def test_a_missing_transactions_sql_file_raises_claim_error() -> None:
    use_case, _ = make_use_case(query_provider=FakeQueryProvider(names=()))

    with pytest.raises(ClaimError):
        open_claim(use_case)


def test_a_later_group_failing_leaves_the_earlier_claim_written() -> None:
    rows = [
        make_row(transaction_id="TRX-1"),
        make_row(transaction_id="TRX-2", currency="COP"),
    ]
    results = default_results(rows)
    results[INSERT] = (INSERTED, QueryExecutionError("boom"))
    use_case, repository = make_use_case(results)

    with pytest.raises(ClaimError):
        open_claim(use_case, transaction_ids=["TRX-1", "TRX-2"])

    assert len(repository.params_of(INSERT)) == 2


@pytest.mark.parametrize(
    "row",
    [
        make_row(amount=None),
        make_row(amount=True),
        make_row(amount=Decimal("NaN")),
        make_row(currency=3),
        make_row(amount_usd="740"),
        {k: v for k, v in make_row().items() if k != "card_last4"},
    ],
)
def test_an_unreadable_transaction_row_raises_claim_data_integrity_error(
    row: dict[str, Any],
) -> None:
    use_case, repository = make_use_case(default_results([row]))

    with pytest.raises(ClaimDataIntegrityError):
        open_claim(use_case)

    assert repository.params_of(INSERT) == []
```

- [ ] **Step 3: Write the failing query contract tests**

`tests/unit/open_claim/test_query_contracts.py`:

```python
"""Drift tests: the SQL files must match the Python contracts and the schema."""

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pytest
from data_load.ddl import load_plan
from open_claim_lambda.application.use_cases.open_claim import (
    SUBCATEGORIES,
    OpenClaimUseCase,
)
from open_claim_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    FakeDatabaseRepository,
    FakeQueryProvider,
    make_row,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/open_claim"
QUERIES_DIR = TOOL_ROOT / "open_claim_lambda/queries/postgresql"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
# Escaped so this test file's own encoding can't change the expected value.
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Cr\u00e9dito'"


def sql(name: str) -> str:
    """Load one of the tool's real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def flat_sql(name: str) -> str:
    """Return the query with every run of whitespace collapsed to one space."""
    return " ".join(sql(name).split())


def statements(text: str) -> list[str]:
    """Split SQL text into statements, ignoring -- comments."""
    without_comments = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def sent_params() -> dict[str, set[str]]:
    """Return the param names the use case sends, per query, on the full path."""
    repository = FakeDatabaseRepository(
        {
            "claim_transactions": [make_row()],
            "insert_claim": [{"complaint_id": "CMP-X"}],
            "resolution_estimate": [{"median_days": 5, "p90_days": 9}],
        }
    )
    OpenClaimUseCase(
        database_repository=repository, query_provider=FakeQueryProvider()
    ).execute(
        customer_id=CUSTOMER_ID,
        transaction_ids=["TRX-1"],
        claim_type="fraud",
        customer_statement="No lo reconozco",
        customer_confirmed=True,
        now=datetime(2026, 6, 17, tzinfo=timezone.utc),
    )
    return {name: set(params) for name, params in repository.calls}


def test_the_use_case_runs_exactly_the_tools_queries() -> None:
    assert set(sent_params()) == set(QUERY_NAMES)
    assert {path.stem for path in QUERIES_DIR.glob("*.sql")} == set(QUERY_NAMES)


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_placeholders_match_the_use_case_params_exactly(name: str) -> None:
    assert set(PLACEHOLDER.findall(sql(name))) == sent_params()[name]


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_has_no_stray_percent_signs(name: str) -> None:
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_each_file_is_one_statement_that_sets_no_session_parameter(name: str) -> None:
    found = statements(sql(name))

    assert len(found) == 1
    assert not found[0].upper().startswith("SET ")
    assert "statement_timeout" not in sql(name).lower()


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_files_are_nfc_utf8_without_bom(name: str) -> None:
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


def test_transactions_are_the_customers_and_on_a_credit_card() -> None:
    text = flat_sql("claim_transactions")

    assert "WHERE t.customer_id = %(customer_id)s" in text
    assert "AND t.transaction_id = ANY(%(transaction_ids)s)" in text
    assert f"AND {CREDIT_CARD_FILTER}" in text


def test_the_insert_writes_a_claim_with_values_the_schema_accepts() -> None:
    text = flat_sql("insert_claim")
    complaints = load_plan().data_tables["complaints"]

    assert "'Claim', 'Transactions'" in text
    assert "'Web'" in text
    assert "'Open', false, false" in text
    assert "RETURNING complaint_id" in text
    # category and reception_channel have CHECK constraints in schema.sql.
    assert "'Transactions'" in complaints
    assert "'Web'" in complaints
    assert "'Cards'" not in text
    assert "AI Assistant" not in text


def test_the_subcategories_are_the_datasets_values() -> None:
    assert SUBCATEGORIES == {
        "fraud": "Cargo no reconocido",
        "dispute": "Cobro indebido",
    }


def test_the_estimate_uses_similar_claims_from_enough_history() -> None:
    text = flat_sql("resolution_estimate")

    assert "percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_days)" in text
    assert "percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_days)" in text
    assert (
        "WHERE case_type = 'Claim' AND category = 'Transactions' "
        "AND subcategory = %(subcategory)s AND resolution_days IS NOT NULL "
        "AND creation_date >= %(since)s HAVING COUNT(*) >= 20"
    ) in text
    # The header comment names the column on purpose; the statement never reads it.
    assert "compensation_granted" not in statements(sql("resolution_estimate"))[0]
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `PYTEST tests/unit/open_claim`
Expected: FAIL. `ModuleNotFoundError` for `open_claim_lambda.domain.errors`, `...domain.entities.claim` and `...application.use_cases.open_claim`.

- [ ] **Step 5: Write the entities**

`open_claim_lambda/domain/entities/claim.py`:

```python
"""Entities returned by the open_claim use case."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Claim:
    """One opened claim: one card and one currency.

    ``already_existed`` is True when the same claim was opened before (a retry,
    or the agent calling again), so nothing was written. It is a success, not an
    error. ``status`` is "Open" as written; a later change isn't re-read.
    """

    claim_id: str
    card_last4: str
    transaction_ids: tuple[str, ...]
    claimed_amount: Decimal
    currency: str
    priority: str
    status: str
    already_existed: bool


@dataclass(frozen=True)
class ResolutionEstimate:
    """Median and 90th-percentile resolution time of similar past claims, in days."""

    median_days: int
    p90_days: int


@dataclass(frozen=True)
class ClaimsResult:
    """The claims of one call; the estimate is None when it isn't known."""

    claims: tuple[Claim, ...]
    resolution_estimate: ResolutionEstimate | None
```

- [ ] **Step 6: Write the domain errors**

`open_claim_lambda/domain/errors.py`:

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output or other internal details; the only
variable text is transaction ids the agent sent, after validation.
"""

from collections.abc import Sequence
from typing import ClassVar


class DomainError(Exception):
    """Base class for agent-facing errors raised by the use case.

    Attributes:
        message: Agent-facing text describing the failure and the next step.
    """

    def __init__(self, message: str) -> None:
        """Store the agent-facing message."""
        super().__init__(message)
        self.message: str = message


class InvalidInputError(DomainError):
    """A tool argument failed validation.

    Attributes:
        field: Name of the offending tool argument.
        reason: Short human-readable rule that was broken.
    """

    def __init__(self, field: str, reason: str) -> None:
        """Build the message from the field name and the broken rule."""
        self.field: str = field
        self.reason: str = reason
        super().__init__(
            f"Invalid value for '{field}': {reason}. "
            "Ask the customer to confirm and retry."
        )


class _FixedMessageError(DomainError):
    """Base for domain errors whose message never varies."""

    MESSAGE: ClassVar[str] = ""

    def __init__(self) -> None:
        """Use the class-level MESSAGE as the agent-facing message."""
        super().__init__(self.MESSAGE)


class TransactionsNotFoundError(DomainError):
    """Some requested ids aren't among the customer's credit card transactions.

    Attributes:
        transaction_ids: The missing ids, as the agent sent them (cleaned).
    """

    def __init__(self, transaction_ids: Sequence[str]) -> None:
        """Name the missing ids in the message."""
        self.transaction_ids: tuple[str, ...] = tuple(transaction_ids)
        super().__init__(
            "These transactions weren't found among the customer's credit card "
            f"transactions: {', '.join(self.transaction_ids)}. Check them with "
            "list_card_transactions and retry."
        )


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "The claim service is temporarily unavailable. Tell the customer and "
        "offer to retry in a moment or hand off to a human agent."
    )


class ClaimError(_FixedMessageError):
    """A query failed; retrying won't help."""

    MESSAGE: ClassVar[str] = (
        "The claim couldn't be opened due to an internal error. Don't retry; "
        "offer a hand-off to a human agent."
    )


class ClaimDataIntegrityError(_FixedMessageError):
    """A returned transaction row couldn't be read."""

    MESSAGE: ClassVar[str] = (
        "Transaction data came back in an unexpected format. Don't retry; "
        "offer a hand-off to a human agent."
    )
```

- [ ] **Step 7: Write the use case**

`open_claim_lambda/application/use_cases/open_claim.py`:

```python
"""Use case: open fraud or dispute claims for some of a customer's card transactions."""

import base64
import hashlib
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from open_claim_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from open_claim_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    WriteConflictError,
)
from open_claim_lambda.application.ports.query_provider import QueryProvider
from open_claim_lambda.domain.entities.claim import (
    Claim,
    ClaimsResult,
    ResolutionEstimate,
)
from open_claim_lambda.domain.errors import (
    ClaimDataIntegrityError,
    ClaimError,
    DataSourceUnavailableError,
    InvalidInputError,
    TransactionsNotFoundError,
)

logger = logging.getLogger(__name__)

# complaints.subcategory values in the dataset, by claim type.
SUBCATEGORIES: Final[Mapping[str, str]] = {
    "fraud": "Cargo no reconocido",
    "dispute": "Cobro indebido",
}
OPEN: Final = "Open"
MAX_TRANSACTIONS: Final = 10
MAX_TRANSACTION_ID_LENGTH: Final = 30  # transactions.transaction_id is varchar(30)
MAX_STATEMENT_LENGTH: Final = 500
# Above this total in USD a claim is High priority: the fraud protocol's hand-off line.
HIGH_PRIORITY_USD: Final = Decimal("500")
ESTIMATE_WINDOW: Final = timedelta(days=365)


@dataclass(frozen=True)
class _Charge:
    """One disputed transaction, as claim_transactions returns it."""

    transaction_id: str
    product_id: str
    card_last4: str
    amount: Decimal
    currency: str
    amount_usd: Decimal | None


class OpenClaimUseCase:
    """Open one claim per card and currency through a database-agnostic repository.

    Each claim's id is derived from its content, so the same request run twice (a
    retry, or the model calling again) finds the existing claim instead of
    opening a second one. The resolution estimate is best effort: once a claim
    is written, nothing after it may turn the call into an error.
    """

    TRANSACTIONS_QUERY: Final = "claim_transactions"
    INSERT_QUERY: Final = "insert_claim"
    ESTIMATE_QUERY: Final = "resolution_estimate"

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
    ) -> None:
        """Store the ports."""
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider

    def execute(
        self,
        customer_id: object,
        transaction_ids: object,
        claim_type: object,
        customer_statement: object,
        customer_confirmed: object,
        now: datetime,
    ) -> ClaimsResult:
        """Validate every input, then open the claims and estimate their duration.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            transaction_ids: 1 to 10 transaction ids, as they came.
            claim_type: fraud or dispute, as it came.
            customer_statement: The customer's words, as they came.
            customer_confirmed: Must be the boolean True.
            now: The tool's "now" (AS_OF in demos), the claims' creation date.

        Raises:
            InvalidInputError: An input is invalid, or customer_confirmed isn't
                true. Raised before the database is touched.
            TransactionsNotFoundError: Some ids aren't the customer's credit card
                transactions. Raised before any claim is written.
            DataSourceUnavailableError: The database can't be reached, or kept
                reporting write conflicts.
            ClaimError: A query failed.
            ClaimDataIntegrityError: A returned row couldn't be read.
        """
        customer = _clean_customer_id(customer_id)
        ids = _clean_transaction_ids(transaction_ids)
        kind = _clean_claim_type(claim_type)
        statement = _clean_statement(customer_statement)
        _require_confirmation(customer_confirmed)
        created = _naive_utc(now)
        try:
            rows = self._run(
                self.TRANSACTIONS_QUERY,
                {"customer_id": customer, "transaction_ids": list(ids)},
            )
            claims = tuple(
                self._open(customer, kind, statement, created, group)
                for group in _groups(_charges(rows, ids))
            )
        except (DataSourceConnectionError, WriteConflictError) as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise ClaimError() from exc
        return ClaimsResult(
            claims=claims,
            resolution_estimate=self._estimate(SUBCATEGORIES[kind], created),
        )

    def _open(
        self,
        customer_id: str,
        claim_type: str,
        statement: str,
        created: datetime,
        group: Sequence[_Charge],
    ) -> Claim:
        """Insert one claim, or find that the same claim already exists."""
        first = group[0]
        ids = tuple(charge.transaction_id for charge in group)
        claim_id = claim_id_for(
            customer_id, claim_type, first.product_id, first.currency, ids
        )
        amount = sum((charge.amount for charge in group), Decimal(0))
        priority = _priority(group)
        try:
            self._run(
                self.INSERT_QUERY,
                {
                    "complaint_id": claim_id,
                    "creation_date": created,
                    "process_date": created.date(),
                    "customer_id": customer_id,
                    "subcategory": SUBCATEGORIES[claim_type],
                    "product_id": first.product_id,
                    "description": f"{statement} | tx: {','.join(ids)}",
                    "claimed_amount": amount,
                    "currency": first.currency,
                    "priority": priority,
                },
            )
            already_existed = False
        except DuplicateKeyError:
            # The same request ran before: a retry, or the model calling again.
            already_existed = True
        return Claim(
            claim_id=claim_id,
            card_last4=first.card_last4,
            transaction_ids=ids,
            claimed_amount=amount,
            currency=first.currency,
            priority=priority,
            status=OPEN,
            already_existed=already_existed,
        )

    def _estimate(
        self, subcategory: str, created: datetime
    ) -> ResolutionEstimate | None:
        """Median and p90 resolution days of similar past claims; None when unknown.

        The claims are already written, so any failure here is logged, never
        raised.
        """
        try:
            rows = self._run(
                self.ESTIMATE_QUERY,
                {"subcategory": subcategory, "since": created - ESTIMATE_WINDOW},
            )
            if not rows:
                return None
            return ResolutionEstimate(
                median_days=_days(rows[0], "median_days"),
                p90_days=_days(rows[0], "p90_days"),
            )
        except (DataAccessError, KeyError, TypeError, ValueError):
            logger.warning(
                "Resolution estimate failed; the claims stay open without it",
                exc_info=True,
            )
            return None

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it."""
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)


def claim_id_for(
    customer_id: str,
    claim_type: str,
    product_id: str,
    currency: str,
    transaction_ids: Sequence[str],
) -> str:
    """Return the claim's id: ``CMP-`` and 20 base32 characters of a content hash.

    The same customer, type, card, currency and transactions (in any order)
    always give the same id, so the primary key refuses a second claim for them.
    """
    key = "|".join(
        (customer_id, claim_type, product_id, currency, ",".join(sorted(transaction_ids)))
    )
    digest = base64.b32encode(hashlib.sha256(key.encode("utf-8")).digest())
    return f"CMP-{digest.decode('ascii')[:20]}"


def _charges(rows: Sequence[Mapping[str, Any]], ids: Sequence[str]) -> list[_Charge]:
    """Map the rows, check every requested id came back, order them as requested.

    Raises:
        ClaimDataIntegrityError: A row couldn't be read.
        TransactionsNotFoundError: Some ids aren't the customer's credit card
            transactions.
    """
    try:
        found = {charge.transaction_id: charge for charge in map(_to_charge, rows)}
    except (KeyError, TypeError, ValueError) as exc:
        raise ClaimDataIntegrityError() from exc
    missing = [i for i in ids if i not in found]
    if missing:
        raise TransactionsNotFoundError(missing)
    return [found[i] for i in ids]


def _groups(charges: Sequence[_Charge]) -> list[list[_Charge]]:
    """Group by card and currency, one claim each, ordered by card then currency."""
    groups: dict[tuple[str, str], list[_Charge]] = {}
    for charge in charges:
        groups.setdefault((charge.product_id, charge.currency), []).append(charge)
    return sorted(
        groups.values(), key=lambda g: (g[0].card_last4, g[0].currency, g[0].product_id)
    )


def _priority(group: Sequence[_Charge]) -> str:
    """High when the total in USD is unknown or above HIGH_PRIORITY_USD."""
    known = [c.amount_usd for c in group if c.amount_usd is not None]
    if len(known) < len(group) or sum(known, Decimal(0)) > HIGH_PRIORITY_USD:
        return "High"
    return "Medium"


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return raw.strip().upper()


def _clean_transaction_ids(raw: object) -> tuple[str, ...]:
    """Strip, uppercase and de-duplicate 1 to MAX_TRANSACTIONS ids, keeping order.

    Raises:
        InvalidInputError: Not a list, empty, an item isn't a non-empty string of
            at most 30 characters, or more than 10 distinct ids.
    """
    reason = (
        f"must be a list of 1 to {MAX_TRANSACTIONS} transaction ids "
        "from list_card_transactions"
    )
    if not isinstance(raw, list) or not raw:
        raise InvalidInputError("transaction_ids", reason)
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise InvalidInputError("transaction_ids", reason)
        clean = item.strip().upper()
        if not clean or len(clean) > MAX_TRANSACTION_ID_LENGTH:
            raise InvalidInputError("transaction_ids", reason)
        if clean not in ids:
            ids.append(clean)
    if len(ids) > MAX_TRANSACTIONS:
        raise InvalidInputError("transaction_ids", reason)
    return tuple(ids)


def _clean_claim_type(raw: object) -> str:
    """Strip and lowercase the type; it must be fraud or dispute.

    Raises:
        InvalidInputError: Anything else.
    """
    if isinstance(raw, str) and raw.strip().lower() in SUBCATEGORIES:
        return raw.strip().lower()
    raise InvalidInputError("claim_type", "must be fraud or dispute")


def _clean_statement(raw: object) -> str:
    """Strip the customer's words; 1 to MAX_STATEMENT_LENGTH characters.

    Raises:
        InvalidInputError: Not a string, blank or too long.
    """
    reason = f"must be the customer's own words, 1 to {MAX_STATEMENT_LENGTH} characters"
    if not isinstance(raw, str):
        raise InvalidInputError("customer_statement", reason)
    statement = raw.strip()
    if not statement or len(statement) > MAX_STATEMENT_LENGTH:
        raise InvalidInputError("customer_statement", reason)
    return statement


def _require_confirmation(raw: object) -> None:
    """Only the boolean True confirms; "true", 1 or a missing value don't.

    The Gateway's Cedar statement 3 will check it too (spec section 10).

    Raises:
        InvalidInputError: The value isn't True.
    """
    if raw is not True:
        raise InvalidInputError(
            "customer_confirmed",
            "must be true, after the customer explicitly confirmed these transactions",
        )


def _naive_utc(now: datetime) -> datetime:
    """Return ``now`` as naive UTC: complaints.creation_date has no time zone."""
    if now.tzinfo is None:
        return now
    return now.astimezone(timezone.utc).replace(tzinfo=None)


def _to_charge(row: Mapping[str, Any]) -> _Charge:
    """Map one claim_transactions row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type.
        ValueError: An amount isn't finite.
    """
    return _Charge(
        transaction_id=_text(row, "transaction_id"),
        product_id=_text(row, "product_id"),
        card_last4=_text(row, "card_last4"),
        amount=_amount(row, "amount"),
        currency=_text(row, "currency"),
        amount_usd=None if row["amount_usd"] is None else _amount(row, "amount_usd"),
    )


def _text(row: Mapping[str, Any], column: str) -> str:
    """Return a non-empty text column."""
    value = row[column]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{column} is {type(value).__name__}, expected text")
    return value


def _amount(row: Mapping[str, Any], column: str) -> Decimal:
    """Return a finite numeric column as an exact Decimal; bool is rejected."""
    value = row[column]
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float):
        raise TypeError(f"{column} is {type(value).__name__}, expected a number")
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise ValueError(f"{column} is not finite")
    return amount


def _days(row: Mapping[str, Any], column: str) -> int:
    """Round a finite day count up to whole days."""
    value = row[column]
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float):
        raise TypeError(f"{column} is {type(value).__name__}, expected a number")
    if not math.isfinite(value):
        raise ValueError(f"{column} is not finite")
    return math.ceil(value)
```

- [ ] **Step 8: Write the SQL files**

`open_claim_lambda/queries/postgresql/claim_transactions.sql` (UTF-8, no BOM):

```sql
-- claim_transactions (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The requested transactions that belong to the customer and were made with one
-- of their credit cards, with what OpenClaimUseCase needs to group and price the
-- claims. A requested id missing from the result isn't the customer's.
--
-- Parameters (psycopg named placeholders):
--   customer_id      text    required (the use case strips and uppercases it)
--   transaction_ids  text[]  required, 1 to 10 ids; psycopg sends the list as an array
--
-- transaction_id is the primary key, so there are no duplicate rows to remove.
-- The literal 'Tarjeta Crédito' is UTF-8; the connection uses client_encoding=utf8.
--
-- TODO(ledgerlens): W1 - = ANY(array) not yet run on a real Aurora DSQL cluster.
SELECT t.transaction_id,
       t.product_id,
       RIGHT(p.product_number, 4) AS card_last4,
       t.amount,
       t.currency,
       t.amount_usd
FROM transactions AS t
JOIN products AS p ON p.product_id = t.product_id
WHERE t.customer_id = %(customer_id)s
  AND t.transaction_id = ANY(%(transaction_ids)s)
  AND p.product_type = 'Tarjeta Crédito'
```

`open_claim_lambda/queries/postgresql/insert_claim.sql`:

```sql
-- insert_claim (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Writes one claim: one card and one currency. Used by OpenClaimUseCase.
--
-- Parameters (psycopg named placeholders):
--   complaint_id    text       required, CMP- and a hash of the claim's content
--   creation_date   timestamp  required, the tool's "now" (AS_OF in demos), naive UTC
--   process_date    date       required, creation_date's date
--   customer_id     text       required
--   subcategory     text       required, Cargo no reconocido (fraud) or Cobro indebido (dispute)
--   product_id      text       required, the card
--   description     text       required, the customer's words and the transaction ids
--   claimed_amount  numeric    required, the transactions' total in the claim currency
--   currency        text       required
--   priority        text       required, High or Medium
--
-- The values pass the schema's CHECK constraints: category 'Transactions' and
-- reception_channel 'Web' (the chat runs in the web frontend). The id comes from
-- the claim's content, so a second run of the same claim fails with 23505 and
-- the use case reports the existing claim. RETURNING lets the repository read
-- the result with fetchall().
--
-- TODO(ledgerlens): W1 - INSERT ... RETURNING not yet run on a real Aurora DSQL cluster.
INSERT INTO complaints (
    complaint_id, creation_date, process_date, customer_id, case_type, category,
    subcategory, reception_channel, affected_product_id, description,
    claimed_amount, currency, priority, status, sla_breached, is_repeat_complainer
) VALUES (
    %(complaint_id)s, %(creation_date)s, %(process_date)s, %(customer_id)s, 'Claim', 'Transactions',
    %(subcategory)s, 'Web', %(product_id)s, %(description)s,
    %(claimed_amount)s, %(currency)s, %(priority)s, 'Open', false, false
)
RETURNING complaint_id
```

`open_claim_lambda/queries/postgresql/resolution_estimate.sql`:

```sql
-- resolution_estimate (PostgreSQL dialect, runs on Aurora DSQL)
--
-- How long similar claims took to resolve over the last year: the median and the
-- 90th percentile of resolution_days. Used by OpenClaimUseCase after the claims
-- are written; any failure here is logged and gives no estimate.
--
-- Parameters (psycopg named placeholders):
--   subcategory  text       required, the claim's subcategory
--   since        timestamp  required, the claim's creation date minus 365 days
--
-- With fewer than 20 cases no row comes back: no estimate from too few cases.
-- compensation_granted is never read: quoting it would sound like a promise.
--
-- TODO(ledgerlens): W1 - percentile_cont not yet run on a real Aurora DSQL cluster.
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_days) AS median_days,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_days) AS p90_days
FROM complaints
WHERE case_type = 'Claim'
  AND category = 'Transactions'
  AND subcategory = %(subcategory)s
  AND resolution_days IS NOT NULL
  AND creation_date >= %(since)s
HAVING COUNT(*) >= 20
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `PYTEST tests/unit/open_claim`
Expected: PASS.

- [ ] **Step 10: Lint and commit**

```bash
uvx ruff@0.14.1 check --fix gateway/tools/open_claim tests/unit/open_claim
uvx ruff@0.14.1 format gateway/tools/open_claim tests/unit/open_claim
git add gateway/tools/open_claim tests/unit/open_claim
git commit -m "feat(open_claim): use case with content-derived claim ids, the claim queries and a best-effort estimate"
```

---

### Task 7: `open_claim` delivery

**Files:**
- Create: `open_claim_lambda/delivery/presenters/claims.py`, `open_claim_lambda/delivery/handler.py`, `gateway/tools/open_claim/tool_spec.json`
- Create (copied, then edited): `open_claim_lambda/delivery/dependencies/dependencies_builder.py`
- Test: `tests/unit/open_claim/test_claims_presenter.py`, `test_delivery_wiring.py`, `test_open_claim_handler.py`; append to `test_query_contracts.py`

**Interfaces:**
- Consumes: `OpenClaimUseCase`, `Claim`, `ClaimsResult`, `ResolutionEstimate` and the domain errors (Task 6); `ClockSettings` and `DatabaseSettings` (Task 5).
- Produces:
  - `present_claims(result: ClaimsResult) -> dict`
  - `build_open_claim_use_case(env) -> OpenClaimUseCase | None`, plus `build_clock(env)`
  - `handler.handler`, with `handler.TOOL_NAME = "open_claim"`, `handler.UNEXPECTED_ERROR_MESSAGE`, `handler.USE_CASE` and `handler.CLOCK`

- [ ] **Step 1: Write the failing presenter test**

`tests/unit/open_claim/test_claims_presenter.py`:

```python
"""Tests for the open_claim presenter."""

from decimal import Decimal

import pytest
from open_claim_lambda.delivery.presenters.claims import present_claims
from open_claim_lambda.domain.entities.claim import (
    Claim,
    ClaimsResult,
    ResolutionEstimate,
)

pytestmark = pytest.mark.unit

CLAIM = Claim(
    claim_id="CMP-4KQ2ZJ7M3XH5TB6RWN2Y",
    card_last4="4821",
    transaction_ids=("TRX-88", "TRX-89"),
    claimed_amount=Decimal("835.005"),
    currency="USD",
    priority="High",
    status="Open",
    already_existed=False,
)


def test_presenter_returns_claims_with_2_decimal_amounts_and_the_estimate() -> None:
    result = ClaimsResult(
        claims=(CLAIM,), resolution_estimate=ResolutionEstimate(5, 12)
    )

    assert present_claims(result) == {
        "claims": [
            {
                "claim_id": "CMP-4KQ2ZJ7M3XH5TB6RWN2Y",
                "card_last4": "4821",
                "transaction_ids": ["TRX-88", "TRX-89"],
                "claimed_amount": "835.01",
                "currency": "USD",
                "priority": "High",
                "status": "Open",
                "already_existed": False,
            }
        ],
        "resolution_estimate": {"median_days": 5, "p90_days": 12},
    }


def test_presenter_returns_a_null_estimate_when_unknown() -> None:
    result = ClaimsResult(claims=(CLAIM,), resolution_estimate=None)

    assert present_claims(result)["resolution_estimate"] is None
```

- [ ] **Step 2: Write the failing wiring tests**

`tests/unit/open_claim/test_delivery_wiring.py`:

```python
"""Tests for the dependency wiring of the open_claim tool."""

from datetime import datetime, timezone

import pytest
from open_claim_lambda.application.use_cases.open_claim import OpenClaimUseCase
from open_claim_lambda.delivery.dependencies import dependencies_builder
from open_claim_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_clock,
    build_dsql_settings,
    build_open_claim_use_case,
    build_query_provider,
    build_settings,
)
from open_claim_lambda.delivery.settings import (
    ClockSettings,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from open_claim_lambda.domain.entities.claim import ResolutionEstimate

from .fakes import CUSTOMER_ID, QUERY_NAMES, FakeConnector, make_row

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
NOW = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
ARGS = {
    "customer_id": CUSTOMER_ID,
    "transaction_ids": ["TRX-1"],
    "claim_type": "fraud",
    "customer_statement": "No lo reconozco",
    "customer_confirmed": True,
}


def test_build_settings_and_the_write_role_default() -> None:
    assert build_settings(ENV) == DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL)
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ll_write"
    )


def test_every_engine_has_a_dialect_folder_with_every_query() -> None:
    assert QUERIES_ROOT.parent.name == "open_claim_lambda"
    for engine in DatabaseEngine:
        for name in QUERY_NAMES:
            assert (QUERIES_ROOT / SQL_DIALECTS[engine] / f"{name}.sql").is_file()
    assert "INSERT INTO complaints" in build_query_provider(
        DatabaseEngine.AURORA_DSQL
    ).get("insert_claim")


def use_fake_connector(
    monkeypatch: pytest.MonkeyPatch, connector: FakeConnector
) -> None:
    """Make the builder hand out ``connector`` instead of a real DSQL one."""
    monkeypatch.setattr(
        dependencies_builder, "build_connector", lambda _settings, _env: connector
    )


def test_use_case_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(
        (
            [make_row()],
            [{"complaint_id": "CMP-X"}],
            [{"median_days": 4.2, "p90_days": 11.5}],
        )
    )
    use_fake_connector(monkeypatch, connector)

    use_case = build_open_claim_use_case(ENV)
    assert isinstance(use_case, OpenClaimUseCase)
    result = use_case.execute(**ARGS, now=NOW)

    assert result.claims[0].card_last4 == "4821"
    assert result.resolution_estimate == ResolutionEstimate(median_days=5, p90_days=12)
    sqls = [c.executed[0][0] for c in connector.connections[-1].cursors]
    assert "FROM transactions" in sqls[0]
    assert "INSERT INTO complaints" in sqls[1]
    assert "percentile_cont" in sqls[2]


@pytest.mark.parametrize(
    "env",
    [{}, {**ENV, "DB_ENGINE": "oracle"}, {"AWS_REGION": "us-east-1"}],
)
def test_use_case_build_with_bad_configuration_returns_none(
    env: dict[str, str],
) -> None:
    assert build_open_claim_use_case(env) is None


def test_build_clock_reads_as_of_and_rejects_a_bad_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert build_clock({"AS_OF": "2026-03-14"}) == ClockSettings(
        as_of=datetime(2026, 3, 14, tzinfo=timezone.utc)
    )
    assert build_clock({"AS_OF": "yesterday"}) is None
    assert "Invalid AS_OF for open_claim" in caplog.text
```

- [ ] **Step 3: Write the failing handler tests**

`tests/unit/open_claim/test_open_claim_handler.py`:

```python
"""Tests for the open_claim Lambda handler."""

import importlib
import json
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from open_claim_lambda.application.use_cases.open_claim import OpenClaimUseCase
from open_claim_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from open_claim_lambda.delivery.settings import ClockSettings, DatabaseEngine
from open_claim_lambda.domain.errors import (
    ClaimError,
    DataSourceUnavailableError,
    TransactionsNotFoundError,
)

from .fakes import CUSTOMER_ID, FakeConnector, make_row

pytestmark = pytest.mark.unit

EVENT = {
    "customer_id": CUSTOMER_ID,
    "transaction_ids": ["TRX-1"],
    "claim_type": "fraud",
    "customer_statement": "No reconozco este cargo",
    "customer_confirmed": True,
}
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
INSERTED = [{"complaint_id": "CMP-X"}]
ESTIMATE = [{"median_days": 4.2, "p90_days": 11.5}]
NOT_CONFIRMED = (
    "Invalid value for 'customer_confirmed': must be true, after the customer "
    "explicitly confirmed these transactions. Ask the customer to confirm and retry."
)


def make_context(tool_name: str = "open-claim-target___open_claim") -> SimpleNamespace:
    """Build a Lambda context carrying the Gateway tool name."""
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name})
    )


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the handler module fresh, with no DB env vars (no AWS calls)."""
    for name in (
        "DB_ENGINE",
        "DSQL_CLUSTER_ENDPOINT",
        "DSQL_DB_USER",
        "AWS_REGION",
        "AS_OF",
    ):
        monkeypatch.delenv(name, raising=False)
    import open_claim_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any) -> None:
    """Point the handler at real adapters over a fake connector, with AS_OF set."""
    use_case = OpenClaimUseCase(
        database_repository=build_database_repository(
            DatabaseEngine.AURORA_DSQL, connector
        ),
        query_provider=build_query_provider(DatabaseEngine.AURORA_DSQL),
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def test_success_opens_the_claim_and_returns_the_estimate(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector(([make_row()], INSERTED, ESTIMATE))
    wire(module, monkeypatch, connector)

    payload = body(module.handler(EVENT, make_context()))

    claim = payload["claims"][0]
    assert claim["card_last4"] == "4821"
    assert claim["transaction_ids"] == ["TRX-1"]
    assert claim["claimed_amount"] == "740.00"
    assert claim["priority"] == "High"
    assert claim["already_existed"] is False
    assert claim["claim_id"].startswith("CMP-")
    assert payload["resolution_estimate"] == {"median_days": 5, "p90_days": 12}
    insert_params = connector.connections[-1].cursors[1].executed[0][1]
    assert insert_params["creation_date"] == datetime(2026, 6, 17, 23, 59, 59)


def test_a_duplicate_insert_reports_the_existing_claim(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    duplicate = psycopg.errors.UniqueViolation("duplicate key value")
    wire(module, monkeypatch, FakeConnector(([make_row()], duplicate, ESTIMATE)))

    payload = body(module.handler(EVENT, make_context()))

    assert payload["claims"][0]["already_existed"] is True


def test_a_failing_estimate_still_returns_the_open_claims(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsupported = psycopg.errors.UndefinedFunction(
        "function percentile_cont does not exist"
    )
    wire(module, monkeypatch, FakeConnector(([make_row()], INSERTED, unsupported)))

    payload = body(module.handler(EVENT, make_context()))

    assert len(payload["claims"]) == 1
    assert payload["resolution_estimate"] is None


@pytest.mark.parametrize("confirmed", [False, None, "true"])
def test_an_unconfirmed_claim_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, confirmed: object
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler({**EVENT, "customer_confirmed": confirmed}, make_context())

    assert response == {"error": NOT_CONFIRMED}
    assert connector.connections == []


def test_unknown_transactions_return_the_not_found_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    response = module.handler(EVENT, make_context())

    assert response == {"error": TransactionsNotFoundError(["TRX-1"]).message}


def test_a_failing_insert_returns_the_claim_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.InsufficientPrivilege("permission denied for complaints")
    wire(module, monkeypatch, FakeConnector(([make_row()], error)))

    assert module.handler(EVENT, make_context()) == {"error": ClaimError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [make_context("block-credit-card-target___block_credit_card"), None],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    connector = FakeConnector()
    wire(module, monkeypatch, connector)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "open_claim" in response["error"]
    assert connector.connections == []


def test_unexpected_exception_returns_a_generic_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(**_kwargs: object) -> None:
        raise RuntimeError("password=hunter2")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error opening the claim. "
        "Offer a hand-off to a human agent."
    )


def test_missing_configuration_or_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert module.USE_CASE is None
    assert module.handler(EVENT, make_context()) == {
        "error": DataSourceUnavailableError.MESSAGE
    }

    wire(module, monkeypatch, FakeConnector([make_row()]))
    monkeypatch.setattr(module, "CLOCK", None)
    assert module.handler(EVENT, make_context()) == {
        "error": DataSourceUnavailableError.MESSAGE
    }
```

- [ ] **Step 4: Write the failing tool spec tests**

Append to `tests/unit/open_claim/test_query_contracts.py`:

```python
def tool_spec() -> dict:
    """Load the single tool definition from tool_spec.json."""
    import json

    specs = json.loads((TOOL_ROOT / "tool_spec.json").read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_tool_spec_name_inputs_and_required_fields() -> None:
    spec = tool_spec()
    properties = spec["inputSchema"]["properties"]

    assert spec["name"] == "open_claim"
    assert spec["inputSchema"]["required"] == [
        "customer_id",
        "transaction_ids",
        "claim_type",
        "customer_statement",
        "customer_confirmed",
    ]
    assert properties["transaction_ids"]["maxItems"] == 10
    assert set(properties["claim_type"]["enum"]) == set(SUBCATEGORIES)
    assert properties["customer_confirmed"]["type"] == "boolean"


def test_tool_spec_description_forbids_promising_an_outcome() -> None:
    description = tool_spec()["description"]

    assert "Only call after the customer confirmed" in description
    assert "one claim per card and currency" in description
    assert "Never promise a refund or an outcome." in description
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `PYTEST tests/unit/open_claim`
Expected: FAIL. `ModuleNotFoundError` for the presenter, the builder and the handler, and a `FileNotFoundError` for `tool_spec.json`.

- [ ] **Step 6: Write the presenter**

`open_claim_lambda/delivery/presenters/claims.py`:

```python
"""Present open_claim results as the JSON returned to the agent."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from open_claim_lambda.domain.entities.claim import Claim, ClaimsResult

_CENTS: Final = Decimal("0.01")


def present_claims(result: ClaimsResult) -> dict[str, Any]:
    """Return ``{"claims": [...], "resolution_estimate": {...} | None}``.

    Amounts are 2-decimal strings in the claim's currency, so no float rounding
    reaches the agent. ``resolution_estimate`` is null when there isn't enough
    history; the agent then gives no time.
    """
    estimate = result.resolution_estimate
    return {
        "claims": [_present(claim) for claim in result.claims],
        "resolution_estimate": (
            None
            if estimate is None
            else {"median_days": estimate.median_days, "p90_days": estimate.p90_days}
        ),
    }


def _present(claim: Claim) -> dict[str, Any]:
    """Convert one claim to JSON-safe values."""
    return {
        "claim_id": claim.claim_id,
        "card_last4": claim.card_last4,
        "transaction_ids": list(claim.transaction_ids),
        "claimed_amount": str(
            claim.claimed_amount.quantize(_CENTS, rounding=ROUND_HALF_UP)
        ),
        "currency": claim.currency,
        "priority": claim.priority,
        "status": claim.status,
        "already_existed": claim.already_existed,
    }
```

- [ ] **Step 7: Copy the builder from `block_credit_card`**

```bash
sed -e 's/block_credit_card/open_claim/g' -e 's/BlockCreditCardUseCase/OpenClaimUseCase/g' \
  gateway/tools/block_credit_card/block_credit_card_lambda/delivery/dependencies/dependencies_builder.py \
  > gateway/tools/open_claim/open_claim_lambda/delivery/dependencies/dependencies_builder.py
grep -n "block\|Block\|max_rows" gateway/tools/open_claim/open_claim_lambda/delivery/dependencies/dependencies_builder.py
```

Expected: no output from the grep.

- [ ] **Step 8: Write the handler**

`open_claim_lambda/delivery/handler.py`:

```python
"""Lambda handler for the ``open_claim`` Gateway tool.

Handler string: ``open_claim_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/open_claim/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix. Every argument is passed to the use case bare, exactly
as it came; the use case validates and cleans them.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Raw exception text is never returned: it
could leak SQL, hosts or driver details to the model.

The use case and its whole graph are built once, when the module loads, by
dependencies_builder; a warm container reuses them. AS_OF (optional) is read
once into CLOCK, and CLOCK.now() is the claims' creation date on every call. An
invalid AS_OF answers every request with DataSourceUnavailableError's message.

TODO(ledgerlens): R1 - deployed by the data stack (ledgerlens-open-claim, role
  ledgerlens-write-tools); no Gateway target or Cedar statement 3 yet (write
  tools spec section 10), so the agent can't call it.
TODO(ledgerlens): R5 - customer_id is trusted from the tool input until Cedar
  statement 2 covers this tool (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from open_claim_lambda.delivery.dependencies.dependencies_builder import (
    build_clock,
    build_open_claim_use_case,
)
from open_claim_lambda.delivery.presenters.claims import present_claims
from open_claim_lambda.domain.errors import DataSourceUnavailableError, DomainError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "open_claim"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error opening the claim. "
    "Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_open_claim_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Open fraud or dispute claims for the agent.

    Args:
        event: Tool arguments passed directly by the AgentCore Gateway.
        context: Lambda context with the tool name in client_context.custom.

    Returns:
        A Gateway ``content`` response, or ``{"error": message}``.
    """
    tool_name = _tool_name(context)
    if tool_name != TOOL_NAME:
        logger.error("Unexpected tool name %r for %s", tool_name, TOOL_NAME)
        return {"error": _WRONG_TOOL_MESSAGE}

    args = event if isinstance(event, Mapping) else {}
    try:
        if USE_CASE is None or CLOCK is None:
            raise DataSourceUnavailableError()
        body = present_claims(
            USE_CASE.execute(
                customer_id=args.get("customer_id"),
                transaction_ids=args.get("transaction_ids"),
                claim_type=args.get("claim_type"),
                customer_statement=args.get("customer_statement"),
                customer_confirmed=args.get("customer_confirmed"),
                now=CLOCK.now(),
            )
        )
    except DomainError as err:
        logger.warning(
            "%s returned an error: %s", TOOL_NAME, err.message, exc_info=True
        )
        return {"error": err.message}
    except Exception:
        logger.exception("Unexpected error in %s", TOOL_NAME)
        return {"error": UNEXPECTED_ERROR_MESSAGE}

    logger.info(
        "%s: %d claims (%d already existed): %s",
        TOOL_NAME,
        len(body["claims"]),
        sum(claim["already_existed"] for claim in body["claims"]),
        ", ".join(claim["claim_id"] for claim in body["claims"]),
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _tool_name(context: object) -> str | None:
    """Return the tool name without its ``<target>___`` prefix, or None if absent."""
    try:
        full_name = context.client_context.custom["bedrockAgentCoreToolName"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return None
    if not isinstance(full_name, str):
        return None
    return full_name.rpartition(_TOOL_NAME_DELIMITER)[2]
```

- [ ] **Step 9: Write `gateway/tools/open_claim/tool_spec.json`**

```json
[
  {
    "name": "open_claim",
    "description": "Opens a fraud or dispute claim for one or more of the customer's credit card transactions. Only call after the customer confirmed, in this conversation, exactly which transactions they don't recognise or dispute. Opens one claim per card and currency. Returns JSON with 'claims' (claim_id, card_last4, transaction_ids, claimed_amount, currency, priority, status, already_existed) and 'resolution_estimate' (median_days and p90_days from similar past claims, or null when there is not enough history). Never promise a refund or an outcome.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": {
          "type": "string",
          "description": "The authenticated customer's id from get_session_context."
        },
        "transaction_ids": {
          "type": "array",
          "items": { "type": "string" },
          "minItems": 1,
          "maxItems": 10,
          "description": "Transaction ids from list_card_transactions."
        },
        "claim_type": {
          "type": "string",
          "enum": ["fraud", "dispute"],
          "description": "fraud: the customer doesn't recognise the charges. dispute: they recognise them but contest them."
        },
        "customer_statement": {
          "type": "string",
          "description": "What the customer said happened, in their words, at most 500 characters."
        },
        "customer_confirmed": {
          "type": "boolean",
          "description": "Must be true: the customer explicitly confirmed these transactions."
        }
      },
      "required": ["customer_id", "transaction_ids", "claim_type", "customer_statement", "customer_confirmed"]
    }
  }
]
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `PYTEST tests/unit/open_claim`
Expected: PASS.

- [ ] **Step 11: Lint and commit**

```bash
uvx ruff@0.14.1 check --fix gateway/tools/open_claim tests/unit/open_claim
uvx ruff@0.14.1 format gateway/tools/open_claim tests/unit/open_claim
git add gateway/tools/open_claim tests/unit/open_claim
git commit -m "feat(open_claim): handler, presenter, builder and tool spec"
```

---

### Task 8: `human_agent_hand_off`, the domain, use case and SNS publisher

**Files:**
- Create under `gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/`:
  - `__init__.py`
  - `domain/__init__.py`, `domain/entities/__init__.py`, `domain/entities/hand_off.py`, `domain/errors.py`
  - `application/__init__.py`, `application/ports/__init__.py`, `application/ports/errors.py`, `application/ports/hand_off_publisher.py`
  - `application/use_cases/__init__.py`, `application/use_cases/hand_off.py`
  - `infrastructure/__init__.py`, `infrastructure/publishers/__init__.py`, `infrastructure/publishers/sns_publisher.py`
- Create: `tests/unit/human_agent_hand_off/{__init__,conftest,fakes}.py`
- Test: `tests/unit/human_agent_hand_off/test_errors.py`, `test_hand_off_use_case.py`, `test_sns_publisher.py`

**Interfaces:**
- Produces:
  - Entities: `HandOff(customer_id, priority, reason, summary, related_ids: tuple[str, ...])` and `HandOffResult(hand_off_id, priority)`
  - Port: `HandOffPublisher.publish(hand_off) -> str`; port error `PublishError`
  - `HandOffUseCase(publisher).execute(customer_id, priority, reason, summary, related_ids) -> HandOffResult`
  - Module constants: `PRIORITIES`, `REASONS`, `MAX_SUMMARY_LENGTH = 2000`, `MAX_RELATED_IDS = 20`
  - `SnsHandOffPublisher(topic_arn, region, sns_client=None)`; module functions `subject(hand_off)` and `payload(hand_off)`
  - Domain errors: `DomainError`, `InvalidInputError`, `HandOffUnavailableError` (with `.MESSAGE`)
  - Test fakes: `CUSTOMER_ID`, `FakePublisher(reference="msg-1", error=None)` (with `.published`), `FakeSnsClient(response=None, error=None)` (with `.calls`)

- [ ] **Step 1: Create the test package**

```bash
mkdir -p tests/unit/human_agent_hand_off
: > tests/unit/human_agent_hand_off/__init__.py
sed 's/list_credit_cards/human_agent_hand_off/g' tests/unit/list_credit_cards/conftest.py \
  > tests/unit/human_agent_hand_off/conftest.py
```

`tests/unit/human_agent_hand_off/fakes.py`:

```python
"""Test doubles for the human_agent_hand_off tests."""

from typing import Any, Final

from human_agent_hand_off_lambda.application.ports.hand_off_publisher import (
    HandOffPublisher,
)
from human_agent_hand_off_lambda.domain.entities.hand_off import HandOff

# A customer id in the format the customer system issues.
CUSTOMER_ID: Final = "CLI-ITIECUE8PRH9"


class FakePublisher(HandOffPublisher):
    """HandOffPublisher double that records hand-offs and returns a reference."""

    def __init__(self, reference: str = "msg-1", error: Exception | None = None) -> None:
        """Return ``reference`` from every publish, or raise ``error``."""
        self.reference = reference
        self.error = error
        self.published: list[HandOff] = []

    def publish(self, hand_off: HandOff) -> str:
        """Record the hand-off, then raise or return the reference."""
        self.published.append(hand_off)
        if self.error is not None:
            raise self.error
        return self.reference


class FakeSnsClient:
    """boto3 SNS client double: records publish() calls."""

    def __init__(
        self, response: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        """Return ``response`` (default a MessageId) or raise ``error``."""
        self.response = response if response is not None else {"MessageId": "msg-1"}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def publish(self, **kwargs: Any) -> dict[str, Any]:
        """Record the keyword arguments, then raise or return the response."""
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response
```

- [ ] **Step 2: Write the failing error and use case tests**

`tests/unit/human_agent_hand_off/test_errors.py`:

```python
"""Tests for the hand-off domain errors."""

import pytest
from human_agent_hand_off_lambda.domain.errors import (
    DomainError,
    HandOffUnavailableError,
    InvalidInputError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError("priority", "must be high or normal")

    assert error.message == (
        "Invalid value for 'priority': must be high or normal. "
        "Ask the customer to confirm and retry."
    )


def test_hand_off_unavailable_tells_the_agent_what_to_say() -> None:
    error = HandOffUnavailableError()

    assert isinstance(error, DomainError)
    assert error.message == HandOffUnavailableError.MESSAGE == (
        "The hand-off to a human agent couldn't be sent right now. Tell the "
        "customer you couldn't reach a person and that they can contact the "
        "bank through its usual channels."
    )
```

`tests/unit/human_agent_hand_off/test_hand_off_use_case.py`:

```python
"""Tests for HandOffUseCase."""

from typing import Any

import pytest
from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.application.use_cases.hand_off import HandOffUseCase
from human_agent_hand_off_lambda.domain.entities.hand_off import (
    HandOff,
    HandOffResult,
)
from human_agent_hand_off_lambda.domain.errors import (
    HandOffUnavailableError,
    InvalidInputError,
)

from .fakes import CUSTOMER_ID, FakePublisher

pytestmark = pytest.mark.unit

SUMMARY = (
    "Customer did not recognise 2 charges (USD 740.00 BESTBUY Miami). Card 4821 "
    "blocked. Claim CMP-4KQ2ZJ7M3XH5TB6RWN2Y opened."
)
ARGS: dict[str, Any] = {
    "customer_id": CUSTOMER_ID,
    "priority": "high",
    "reason": "FRAUD_CONFIRMED",
    "summary": SUMMARY,
    "related_ids": ["TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
}
RELATED_IDS_REASON = (
    "must be a list of at most 20 ids made of letters, digits and dashes"
)


def hand_off(publisher: FakePublisher, **overrides: Any) -> HandOffResult:
    """Run the use case with ARGS, overridden by ``overrides``."""
    return HandOffUseCase(publisher=publisher).execute(**{**ARGS, **overrides})


def test_a_valid_hand_off_is_published_and_its_reference_returned() -> None:
    publisher = FakePublisher(reference="msg-1")

    assert hand_off(publisher) == HandOffResult(hand_off_id="msg-1", priority="high")
    assert publisher.published == [
        HandOff(
            customer_id=CUSTOMER_ID,
            priority="high",
            reason="FRAUD_CONFIRMED",
            summary=SUMMARY,
            related_ids=("TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"),
        )
    ]


def test_inputs_are_cleaned_before_publishing() -> None:
    publisher = FakePublisher()

    hand_off(
        publisher,
        customer_id=" cli-itiecue8prh9 ",
        priority=" Normal ",
        reason=" customer_request ",
        summary=f"  {SUMMARY}\n",
        related_ids=[" trx-88 "],
    )

    assert publisher.published[0] == HandOff(
        customer_id=CUSTOMER_ID,
        priority="normal",
        reason="CUSTOMER_REQUEST",
        summary=SUMMARY,
        related_ids=("TRX-88",),
    )


@pytest.mark.parametrize("related_ids", [None, []])
def test_related_ids_are_optional(related_ids: object) -> None:
    publisher = FakePublisher()

    hand_off(publisher, related_ids=related_ids)

    assert publisher.published[0].related_ids == ()


def test_a_summary_of_2000_characters_and_20_related_ids_are_accepted() -> None:
    publisher = FakePublisher()

    hand_off(
        publisher,
        summary="á" * 2000,
        related_ids=[f"TRX-{i}" for i in range(20)],
    )

    assert len(publisher.published[0].summary) == 2000
    assert len(publisher.published[0].related_ids) == 20


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("customer_id", None, "is required and must be a non-empty string"),
        ("customer_id", "   ", "is required and must be a non-empty string"),
        ("priority", "urgent", "must be high or normal"),
        ("priority", None, "must be high or normal"),
        (
            "reason",
            "ANGRY",
            "must be one of: FRAUD_CONFIRMED, CUSTOMER_REQUEST, UNRESOLVED, "
            "OUT_OF_SCOPE",
        ),
        ("summary", "", "must be a summary of 1 to 2000 characters"),
        ("summary", "   ", "must be a summary of 1 to 2000 characters"),
        ("summary", "x" * 2001, "must be a summary of 1 to 2000 characters"),
        ("summary", 42, "must be a summary of 1 to 2000 characters"),
        ("related_ids", "TRX-88", RELATED_IDS_REASON),
        ("related_ids", ["TRX 88"], RELATED_IDS_REASON),
        ("related_ids", ["TRX-88;DROP"], RELATED_IDS_REASON),
        ("related_ids", ["SEÑOR-1"], RELATED_IDS_REASON),
        ("related_ids", [42], RELATED_IDS_REASON),
        ("related_ids", [""], RELATED_IDS_REASON),
        ("related_ids", ["X" * 41], RELATED_IDS_REASON),
        ("related_ids", [f"TRX-{i}" for i in range(21)], RELATED_IDS_REASON),
    ],
)
def test_invalid_input_is_rejected_before_publishing(
    field: str, value: object, reason: str
) -> None:
    publisher = FakePublisher()

    with pytest.raises(InvalidInputError) as caught:
        hand_off(publisher, **{field: value})

    assert caught.value.field == field
    assert caught.value.reason == reason
    assert publisher.published == []


def test_a_failed_publish_raises_hand_off_unavailable() -> None:
    failure = PublishError("SNS publish failed")

    with pytest.raises(HandOffUnavailableError) as caught:
        hand_off(FakePublisher(error=failure))

    assert caught.value.__cause__ is failure
```

- [ ] **Step 3: Write the failing publisher tests**

`tests/unit/human_agent_hand_off/test_sns_publisher.py`:

```python
"""Tests for SnsHandOffPublisher."""

import json

import human_agent_hand_off_lambda.infrastructure.publishers.sns_publisher as sns_module
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoRegionError
from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.domain.entities.hand_off import HandOff
from human_agent_hand_off_lambda.infrastructure.publishers.sns_publisher import (
    SnsHandOffPublisher,
)

from .fakes import CUSTOMER_ID, FakeSnsClient

pytestmark = pytest.mark.unit

TOPIC = "arn:aws:sns:us-east-1:111111111111:ledgerlens-human-handoff"
HAND_OFF = HandOff(
    customer_id=CUSTOMER_ID,
    priority="high",
    reason="FRAUD_CONFIRMED",
    summary="El cliente no reconoce 2 cargos. Tarjeta 4821 bloqueada.",
    related_ids=("TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"),
)


def test_publishes_json_with_an_ascii_subject_and_filterable_attributes() -> None:
    client = FakeSnsClient()

    reference = SnsHandOffPublisher(TOPIC, "us-east-1", client).publish(HAND_OFF)

    assert reference == "msg-1"
    (call,) = client.calls
    assert call["TopicArn"] == TOPIC
    assert call["Subject"] == "[HIGH] LedgerLens hand-off: FRAUD_CONFIRMED"
    assert call["Subject"].isascii() and len(call["Subject"]) <= 100
    assert call["MessageAttributes"] == {
        "priority": {"DataType": "String", "StringValue": "high"},
        "reason": {"DataType": "String", "StringValue": "FRAUD_CONFIRMED"},
    }
    assert json.loads(call["Message"]) == {
        "source": "ledgerlens",
        "customer_id": CUSTOMER_ID,
        "priority": "high",
        "reason": "FRAUD_CONFIRMED",
        "summary": HAND_OFF.summary,
        "related_ids": ["TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
    }
    assert "El cliente" in call["Message"]  # ensure_ascii=False keeps the text readable


@pytest.mark.parametrize(
    "error",
    [
        ClientError({"Error": {"Code": "AuthorizationError", "Message": "no"}}, "Publish"),
        EndpointConnectionError(endpoint_url="https://sns.us-east-1.amazonaws.com"),
    ],
)
def test_sdk_errors_become_publish_error(error: Exception) -> None:
    with pytest.raises(PublishError) as caught:
        SnsHandOffPublisher(TOPIC, "us-east-1", FakeSnsClient(error=error)).publish(
            HAND_OFF
        )

    assert caught.value.__cause__ is error


def test_a_response_without_a_message_id_is_a_publish_error() -> None:
    client = FakeSnsClient(response={"ResponseMetadata": {}})

    with pytest.raises(PublishError):
        SnsHandOffPublisher(TOPIC, "us-east-1", client).publish(HAND_OFF)


def test_the_client_is_created_lazily_for_the_region_and_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str, str]] = []
    client = FakeSnsClient()

    def fake_client(service: str, region_name: str) -> FakeSnsClient:
        created.append((service, region_name))
        return client

    monkeypatch.setattr(sns_module.boto3, "client", fake_client)
    publisher = SnsHandOffPublisher(TOPIC, "us-east-1")
    assert created == []

    publisher.publish(HAND_OFF)
    publisher.publish(HAND_OFF)

    assert created == [("sns", "us-east-1")]
    assert len(client.calls) == 2


def test_a_failed_client_creation_is_a_publish_error_and_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def failing_client(service: str, region_name: str) -> FakeSnsClient:
        attempts.append(service)
        raise NoRegionError()

    monkeypatch.setattr(sns_module.boto3, "client", failing_client)
    publisher = SnsHandOffPublisher(TOPIC, "us-east-1")

    for _ in range(2):
        with pytest.raises(PublishError):
            publisher.publish(HAND_OFF)

    assert attempts == ["sns", "sns"]
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `PYTEST tests/unit/human_agent_hand_off`
Expected: FAIL. Collection errors with `ModuleNotFoundError: No module named 'human_agent_hand_off_lambda'`.

- [ ] **Step 5: Write the package files, entities and errors**

```bash
R=gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda
mkdir -p $R/domain/entities $R/application/ports $R/application/use_cases $R/infrastructure/publishers
printf '"""The human_agent_hand_off Gateway tool Lambda, in hexagonal layers."""\n' > $R/__init__.py
printf '"""Domain layer: entities and agent-facing errors. No I/O."""\n' > $R/domain/__init__.py
printf '"""Domain entities used by the use case."""\n' > $R/domain/entities/__init__.py
printf '"""Application layer: use cases and the ports they depend on."""\n' > $R/application/__init__.py
printf '"""Ports (interfaces) implemented by infrastructure adapters."""\n' > $R/application/ports/__init__.py
printf '"""Use case of the human_agent_hand_off tool."""\n' > $R/application/use_cases/__init__.py
printf '"""Infrastructure layer: adapters that implement the application ports."""\n' > $R/infrastructure/__init__.py
printf '"""HandOffPublisher adapters."""\n' > $R/infrastructure/publishers/__init__.py
```

`$R/domain/entities/hand_off.py`:

```python
"""Entities of the human_agent_hand_off use case."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HandOff:
    """A validated hand-off to a human agent, as it is published."""

    customer_id: str
    priority: str
    reason: str
    summary: str
    related_ids: tuple[str, ...]


@dataclass(frozen=True)
class HandOffResult:
    """The published hand-off: its reference and priority."""

    hand_off_id: str
    priority: str
```

`$R/domain/errors.py`:

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SDK output, topic ARNs or other internal details.
"""

from typing import ClassVar


class DomainError(Exception):
    """Base class for agent-facing errors raised by the use case.

    Attributes:
        message: Agent-facing text describing the failure and the next step.
    """

    def __init__(self, message: str) -> None:
        """Store the agent-facing message."""
        super().__init__(message)
        self.message: str = message


class InvalidInputError(DomainError):
    """A tool argument failed validation.

    Attributes:
        field: Name of the offending tool argument.
        reason: Short human-readable rule that was broken.
    """

    def __init__(self, field: str, reason: str) -> None:
        """Build the message from the field name and the broken rule."""
        self.field: str = field
        self.reason: str = reason
        super().__init__(
            f"Invalid value for '{field}': {reason}. "
            "Ask the customer to confirm and retry."
        )


class _FixedMessageError(DomainError):
    """Base for domain errors whose message never varies."""

    MESSAGE: ClassVar[str] = ""

    def __init__(self) -> None:
        """Use the class-level MESSAGE as the agent-facing message."""
        super().__init__(self.MESSAGE)


class HandOffUnavailableError(_FixedMessageError):
    """The hand-off couldn't be delivered, or the tool isn't configured."""

    MESSAGE: ClassVar[str] = (
        "The hand-off to a human agent couldn't be sent right now. Tell the "
        "customer you couldn't reach a person and that they can contact the "
        "bank through its usual channels."
    )
```

- [ ] **Step 6: Write the port**

`$R/application/ports/errors.py`:

```python
"""Errors that publisher adapters raise; part of the port contract.

Adapters wrap SDK exceptions in these (``raise ... from exc``) so the use case
can react to failures without importing any infrastructure code. Their
messages are for logs only and are never shown to the agent.
"""


class PublishError(Exception):
    """The hand-off couldn't be published."""
```

`$R/application/ports/hand_off_publisher.py`:

```python
"""Port for delivering a hand-off to wherever human agents pick it up."""

from abc import ABC, abstractmethod

from human_agent_hand_off_lambda.domain.entities.hand_off import HandOff


class HandOffPublisher(ABC):
    """Port for publishing a validated hand-off."""

    @abstractmethod
    def publish(self, hand_off: HandOff) -> str:
        """Publish the hand-off and return its reference.

        Raises:
            PublishError: The hand-off couldn't be delivered.
        """
```

- [ ] **Step 7: Write the use case**

`$R/application/use_cases/hand_off.py`:

```python
"""Use case: send the conversation to a human agent."""

import re
from typing import Final

from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.application.ports.hand_off_publisher import (
    HandOffPublisher,
)
from human_agent_hand_off_lambda.domain.entities.hand_off import (
    HandOff,
    HandOffResult,
)
from human_agent_hand_off_lambda.domain.errors import (
    HandOffUnavailableError,
    InvalidInputError,
)

PRIORITIES: Final = ("high", "normal")
REASONS: Final = ("FRAUD_CONFIRMED", "CUSTOMER_REQUEST", "UNRESOLVED", "OUT_OF_SCOPE")
MAX_SUMMARY_LENGTH: Final = 2000
MAX_RELATED_IDS: Final = 20
_RELATED_ID: Final = re.compile(r"[A-Z0-9-]{1,40}")
_RELATED_IDS_REASON: Final = (
    f"must be a list of at most {MAX_RELATED_IDS} ids made of letters, "
    "digits and dashes"
)


class HandOffUseCase:
    """Validate a hand-off and publish it through the HandOffPublisher port.

    Every field but the summary is a closed set or an id, so only the summary
    carries free text written by the model.
    """

    def __init__(self, publisher: HandOffPublisher) -> None:
        """Store the publisher port."""
        self._publisher: HandOffPublisher = publisher

    def execute(
        self,
        customer_id: object,
        priority: object,
        reason: object,
        summary: object,
        related_ids: object,
    ) -> HandOffResult:
        """Validate every input, then publish the hand-off.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            priority: high or normal, as it came.
            reason: One of REASONS, as it came.
            summary: The summary for the human agent, as it came.
            related_ids: Optional list of related record ids, as it came.

        Raises:
            InvalidInputError: An input is invalid. Raised before publishing.
            HandOffUnavailableError: The publisher failed.
        """
        hand_off = HandOff(
            customer_id=_clean_customer_id(customer_id),
            priority=_clean_priority(priority),
            reason=_clean_reason(reason),
            summary=_clean_summary(summary),
            related_ids=_clean_related_ids(related_ids),
        )
        try:
            reference = self._publisher.publish(hand_off)
        except PublishError as exc:
            raise HandOffUnavailableError() from exc
        return HandOffResult(hand_off_id=reference, priority=hand_off.priority)


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``."""
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return raw.strip().upper()


def _clean_priority(raw: object) -> str:
    """Strip and lowercase; high or normal."""
    if isinstance(raw, str) and raw.strip().lower() in PRIORITIES:
        return raw.strip().lower()
    raise InvalidInputError("priority", "must be high or normal")


def _clean_reason(raw: object) -> str:
    """Strip and uppercase; one of REASONS."""
    if isinstance(raw, str) and raw.strip().upper() in REASONS:
        return raw.strip().upper()
    raise InvalidInputError("reason", f"must be one of: {', '.join(REASONS)}")


def _clean_summary(raw: object) -> str:
    """Strip; 1 to MAX_SUMMARY_LENGTH characters."""
    reason = f"must be a summary of 1 to {MAX_SUMMARY_LENGTH} characters"
    if not isinstance(raw, str):
        raise InvalidInputError("summary", reason)
    summary = raw.strip()
    if not summary or len(summary) > MAX_SUMMARY_LENGTH:
        raise InvalidInputError("summary", reason)
    return summary


def _clean_related_ids(raw: object) -> tuple[str, ...]:
    """Missing means none; else at most MAX_RELATED_IDS ids of [A-Z0-9-], uppercased."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_RELATED_IDS:
        raise InvalidInputError("related_ids", _RELATED_IDS_REASON)
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not _RELATED_ID.fullmatch(item.strip().upper()):
            raise InvalidInputError("related_ids", _RELATED_IDS_REASON)
        ids.append(item.strip().upper())
    return tuple(ids)
```

- [ ] **Step 8: Write the SNS publisher**

`$R/infrastructure/publishers/sns_publisher.py`:

```python
"""HandOffPublisher adapter for Amazon SNS.

The topic (ledgerlens-human-handoff, data stack) fans each hand-off out to its
subscribers: an email address for the demo, a contact-center queue later
(product design Q5). The Lambda runs outside the VPC, so it reaches SNS
directly.

TODO(ledgerlens): W7 - an email subscriber gets the summary in plain text.
  Demo only.
"""

import json
from typing import Any, Final, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.application.ports.hand_off_publisher import (
    HandOffPublisher,
)
from human_agent_hand_off_lambda.domain.entities.hand_off import HandOff

SOURCE: Final = "ledgerlens"


class SnsClient(Protocol):
    """The part of the boto3 SNS client the publisher uses."""

    def publish(self, **kwargs: Any) -> dict[str, Any]:
        """Publish a message; the response carries its MessageId."""
        ...


class SnsHandOffPublisher(HandOffPublisher):
    """Publish each hand-off to one SNS topic as JSON."""

    def __init__(
        self, topic_arn: str, region: str, sns_client: SnsClient | None = None
    ) -> None:
        """Configure the topic; the boto3 client is created on the first publish."""
        self._topic_arn: str = topic_arn
        self._region: str = region
        self._sns_client: SnsClient | None = sns_client

    def publish(self, hand_off: HandOff) -> str:
        """Publish the hand-off and return SNS's MessageId.

        Raises:
            PublishError: The client couldn't be created, SNS refused the
                message, or the response had no MessageId. A failed client
                creation is retried on the next publish.
        """
        try:
            if self._sns_client is None:
                self._sns_client = boto3.client("sns", region_name=self._region)
            response = self._sns_client.publish(
                TopicArn=self._topic_arn,
                Subject=subject(hand_off),
                Message=json.dumps(payload(hand_off), ensure_ascii=False),
                MessageAttributes={
                    "priority": {"DataType": "String", "StringValue": hand_off.priority},
                    "reason": {"DataType": "String", "StringValue": hand_off.reason},
                },
            )
            return str(response["MessageId"])
        except (BotoCoreError, ClientError, KeyError, TypeError) as exc:
            raise PublishError("SNS publish failed") from exc


def subject(hand_off: HandOff) -> str:
    """ASCII and under 100 characters, as SNS requires: built only from enum values."""
    return f"[{hand_off.priority.upper()}] LedgerLens hand-off: {hand_off.reason}"


def payload(hand_off: HandOff) -> dict[str, Any]:
    """The message body. SNS adds its own timestamp to every delivery."""
    return {
        "source": SOURCE,
        "customer_id": hand_off.customer_id,
        "priority": hand_off.priority,
        "reason": hand_off.reason,
        "summary": hand_off.summary,
        "related_ids": list(hand_off.related_ids),
    }
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `PYTEST tests/unit/human_agent_hand_off`
Expected: PASS.

- [ ] **Step 10: Lint and commit**

```bash
uvx ruff@0.14.1 check --fix gateway/tools/human_agent_hand_off tests/unit/human_agent_hand_off
uvx ruff@0.14.1 format gateway/tools/human_agent_hand_off tests/unit/human_agent_hand_off
git add gateway/tools/human_agent_hand_off tests/unit/human_agent_hand_off
git commit -m "feat(human_agent_hand_off): use case, validation and the SNS publisher"
```

---

### Task 9: `human_agent_hand_off` delivery

**Files:**
- Create under `gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/delivery/`: `__init__.py`, `settings.py`, `handler.py`, `dependencies/__init__.py`, `dependencies/dependencies_builder.py`, `presenters/__init__.py`, `presenters/hand_off.py`
- Create: `gateway/tools/human_agent_hand_off/tool_spec.json`
- Test: `tests/unit/human_agent_hand_off/test_settings.py`, `test_delivery_wiring.py`, `test_hand_off_handler.py`, `test_tool_spec.py`

**Interfaces:**
- Consumes: `HandOffUseCase`, `HandOffResult`, `SnsHandOffPublisher`, `HandOffUnavailableError` and `DomainError` (Task 8).
- Produces:
  - `HandOffSettings(topic_arn, region).from_env(env)` and `ConfigurationError`
  - `build_hand_off_use_case(env) -> HandOffUseCase | None`
  - `present_hand_off(result) -> {"hand_off_id", "status": "queued", "priority"}`
  - `handler.handler`, with `handler.TOOL_NAME = "human_agent_hand_off"`, `handler.USE_CASE` and `handler.UNEXPECTED_ERROR_MESSAGE`

- [ ] **Step 1: Write the failing tests**

`tests/unit/human_agent_hand_off/test_settings.py`:

```python
"""Tests for the hand-off Lambda settings."""

import pytest
from human_agent_hand_off_lambda.delivery.settings import (
    ConfigurationError,
    HandOffSettings,
)

pytestmark = pytest.mark.unit

TOPIC = "arn:aws:sns:us-east-1:111111111111:ledgerlens-human-handoff"


def test_settings_read_the_topic_and_region() -> None:
    env = {"HANDOFF_TOPIC_ARN": f" {TOPIC} ", "AWS_REGION": " us-east-1 "}

    assert HandOffSettings.from_env(env) == HandOffSettings(
        topic_arn=TOPIC, region="us-east-1"
    )


@pytest.mark.parametrize(
    ("env", "name"),
    [
        ({"AWS_REGION": "us-east-1"}, "HANDOFF_TOPIC_ARN"),
        ({"HANDOFF_TOPIC_ARN": " ", "AWS_REGION": "us-east-1"}, "HANDOFF_TOPIC_ARN"),
        ({"HANDOFF_TOPIC_ARN": "ledgerlens-human-handoff", "AWS_REGION": "us-east-1"}, "HANDOFF_TOPIC_ARN"),
        ({"HANDOFF_TOPIC_ARN": "arn:aws:sqs:us-east-1:1:q", "AWS_REGION": "us-east-1"}, "HANDOFF_TOPIC_ARN"),
        ({"HANDOFF_TOPIC_ARN": TOPIC}, "AWS_REGION"),
    ],
)
def test_invalid_settings_are_rejected(env: dict[str, str], name: str) -> None:
    with pytest.raises(ConfigurationError, match=name):
        HandOffSettings.from_env(env)
```

`tests/unit/human_agent_hand_off/test_delivery_wiring.py`:

```python
"""Tests for the dependency wiring of the human_agent_hand_off tool."""

import human_agent_hand_off_lambda.infrastructure.publishers.sns_publisher as sns_module
import pytest
from human_agent_hand_off_lambda.application.use_cases.hand_off import HandOffUseCase
from human_agent_hand_off_lambda.delivery.dependencies.dependencies_builder import (
    build_hand_off_use_case,
)

from .fakes import CUSTOMER_ID, FakeSnsClient

pytestmark = pytest.mark.unit

TOPIC = "arn:aws:sns:us-east-1:111111111111:ledgerlens-human-handoff"
ENV = {"HANDOFF_TOPIC_ARN": TOPIC, "AWS_REGION": "us-east-1"}


def test_the_use_case_publishes_to_the_configured_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSnsClient()
    monkeypatch.setattr(sns_module.boto3, "client", lambda *_a, **_k: client)

    use_case = build_hand_off_use_case(ENV)
    assert isinstance(use_case, HandOffUseCase)
    result = use_case.execute(CUSTOMER_ID, "normal", "OUT_OF_SCOPE", "Pide un préstamo.", None)

    assert result.hand_off_id == "msg-1"
    assert client.calls[0]["TopicArn"] == TOPIC


def test_building_creates_no_boto3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_boto3(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("boto3 client created while building")

    monkeypatch.setattr(sns_module.boto3, "client", no_boto3)

    assert build_hand_off_use_case(ENV) is not None


@pytest.mark.parametrize("env", [{}, {"AWS_REGION": "us-east-1"}, {"HANDOFF_TOPIC_ARN": "x", "AWS_REGION": "us-east-1"}])
def test_bad_configuration_returns_none(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    assert build_hand_off_use_case(env) is None
    assert "Invalid configuration for human_agent_hand_off" in caplog.text
```

`tests/unit/human_agent_hand_off/test_hand_off_handler.py`:

```python
"""Tests for the human_agent_hand_off Lambda handler."""

import importlib
import json
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.application.use_cases.hand_off import HandOffUseCase
from human_agent_hand_off_lambda.domain.errors import HandOffUnavailableError

from .fakes import CUSTOMER_ID, FakePublisher

pytestmark = pytest.mark.unit

EVENT = {
    "customer_id": CUSTOMER_ID,
    "priority": "high",
    "reason": "FRAUD_CONFIRMED",
    "summary": "Card 4821 blocked; claim CMP-4KQ2ZJ7M3XH5TB6RWN2Y opened.",
    "related_ids": ["CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
}


def make_context(
    tool_name: str = "human-agent-hand-off-target___human_agent_hand_off",
) -> SimpleNamespace:
    """Build a Lambda context carrying the Gateway tool name."""
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name})
    )


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the handler module fresh, with no topic configured (no AWS calls)."""
    for name in ("HANDOFF_TOPIC_ARN", "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)
    import human_agent_hand_off_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, publisher: FakePublisher
) -> None:
    """Point the handler at a use case over ``publisher``."""
    monkeypatch.setattr(module, "USE_CASE", HandOffUseCase(publisher=publisher))


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def test_success_queues_the_hand_off(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = FakePublisher(reference="msg-42")
    wire(module, monkeypatch, publisher)

    assert body(module.handler(EVENT, make_context())) == {
        "hand_off_id": "msg-42",
        "status": "queued",
        "priority": "high",
    }
    assert publisher.published[0].reason == "FRAUD_CONFIRMED"


def test_related_ids_may_be_left_out(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = FakePublisher()
    wire(module, monkeypatch, publisher)
    event = {k: v for k, v in EVENT.items() if k != "related_ids"}

    assert "content" in module.handler(event, make_context())
    assert publisher.published[0].related_ids == ()


@pytest.mark.parametrize("event", [None, [], "hand off"])
def test_a_non_object_event_returns_the_customer_id_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    publisher = FakePublisher()
    wire(module, monkeypatch, publisher)

    response = module.handler(event, make_context())

    assert "customer_id" in response["error"]
    assert publisher.published == []


def test_a_failed_publish_returns_the_unavailable_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakePublisher(error=PublishError("down")))

    assert module.handler(EVENT, make_context()) == {
        "error": HandOffUnavailableError.MESSAGE
    }


def test_missing_configuration_returns_the_unavailable_message(
    module: ModuleType,
) -> None:
    assert module.USE_CASE is None

    assert module.handler(EVENT, make_context()) == {
        "error": HandOffUnavailableError.MESSAGE
    }


@pytest.mark.parametrize(
    "context", [make_context("open-claim-target___open_claim"), None]
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    publisher = FakePublisher()
    wire(module, monkeypatch, publisher)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "human_agent_hand_off" in response["error"]
    assert publisher.published == []


def test_unexpected_exception_returns_a_generic_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(**_kwargs: object) -> None:
        raise RuntimeError("arn:aws:sns:secret")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert "arn:aws" not in response["error"]
```

`tests/unit/human_agent_hand_off/test_tool_spec.py`:

```python
"""Drift tests: tool_spec.json must match the use case's rules."""

import json
from pathlib import Path

import pytest
from human_agent_hand_off_lambda.application.use_cases.hand_off import (
    MAX_RELATED_IDS,
    PRIORITIES,
    REASONS,
)

pytestmark = pytest.mark.unit

TOOL_SPEC = (
    Path(__file__).resolve().parents[3]
    / "gateway/tools/human_agent_hand_off/tool_spec.json"
)


def tool_spec() -> dict:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_tool_spec_matches_the_use_case() -> None:
    spec = tool_spec()
    properties = spec["inputSchema"]["properties"]

    assert spec["name"] == "human_agent_hand_off"
    assert spec["inputSchema"]["required"] == ["customer_id", "priority", "reason", "summary"]
    assert tuple(properties["priority"]["enum"]) == PRIORITIES
    assert tuple(properties["reason"]["enum"]) == REASONS
    assert properties["related_ids"]["maxItems"] == MAX_RELATED_IDS


def test_tool_spec_description_asks_for_a_complete_summary_and_no_time() -> None:
    description = tool_spec()["description"]

    assert "without asking the customer anything again" in description
    assert "Don't promise a time." in description
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/unit/human_agent_hand_off`
Expected: FAIL. `ModuleNotFoundError` for `human_agent_hand_off_lambda.delivery`, and a `FileNotFoundError` for `tool_spec.json`.

- [ ] **Step 3: Write the delivery layer**

```bash
R=gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda
mkdir -p $R/delivery/dependencies $R/delivery/presenters
printf '"""Delivery layer: Lambda handler, configuration and dependency wiring."""\n' > $R/delivery/__init__.py
printf '"""Dependency building: dependencies_builder builds every object of this tool."""\n' > $R/delivery/dependencies/__init__.py
printf '"""Turn use-case results into the JSON returned to the agent."""\n' > $R/delivery/presenters/__init__.py
```

`$R/delivery/settings.py`:

```python
"""Lambda configuration read from environment variables."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

_TOPIC_ARN_PREFIX: Final = "arn:aws:sns:"


class ConfigurationError(Exception):
    """The Lambda environment is missing a setting or has an invalid one."""


@dataclass(frozen=True)
class HandOffSettings:
    """Where hand-offs are published.

    Attributes:
        topic_arn: The SNS topic, ledgerlens-human-handoff in the data stack.
        region: Region of the SNS client; the Lambda runtime sets AWS_REGION.
    """

    topic_arn: str
    region: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "HandOffSettings":
        """Read and validate HANDOFF_TOPIC_ARN and AWS_REGION.

        Raises:
            ConfigurationError: A variable is missing, or the ARN isn't an SNS
                topic ARN.
        """
        topic_arn = _required(env, "HANDOFF_TOPIC_ARN")
        if not topic_arn.startswith(_TOPIC_ARN_PREFIX):
            raise ConfigurationError(
                "HANDOFF_TOPIC_ARN must be an SNS topic ARN (arn:aws:sns:...), "
                f"got {topic_arn!r}"
            )
        return cls(topic_arn=topic_arn, region=_required(env, "AWS_REGION"))


def _required(env: Mapping[str, str], name: str) -> str:
    """Return a required variable, trimmed.

    Raises:
        ConfigurationError: The variable is missing or blank.
    """
    value = env.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value
```

`$R/delivery/dependencies/dependencies_builder.py`:

```python
"""Dependency builder: the only place where this tool's objects get built.

The handler never builds anything itself. At cold start it calls
build_hand_off_use_case once and reuses the result on every warm invocation.
That is safe because nothing built here keeps request data; the SNS client is
created on the first publish and reused.
"""

import logging
from collections.abc import Mapping

from human_agent_hand_off_lambda.application.use_cases.hand_off import HandOffUseCase
from human_agent_hand_off_lambda.delivery.settings import (
    ConfigurationError,
    HandOffSettings,
)
from human_agent_hand_off_lambda.infrastructure.publishers.sns_publisher import (
    SnsHandOffPublisher,
)

logger = logging.getLogger(__name__)


def build_hand_off_use_case(env: Mapping[str, str]) -> HandOffUseCase | None:
    """Build the human_agent_hand_off use case and its publisher. Never raises.

    Returns:
        The ready use case, or None when the configuration is invalid. Every
        request then gets HandOffUnavailableError's message.
    """
    try:
        settings = HandOffSettings.from_env(env)
    except ConfigurationError:
        logger.exception("Invalid configuration for human_agent_hand_off")
        return None
    return HandOffUseCase(
        publisher=SnsHandOffPublisher(
            topic_arn=settings.topic_arn, region=settings.region
        )
    )
```

`$R/delivery/presenters/hand_off.py`:

```python
"""Present the hand-off result as the JSON returned to the agent."""

from typing import Any

from human_agent_hand_off_lambda.domain.entities.hand_off import HandOffResult


def present_hand_off(result: HandOffResult) -> dict[str, Any]:
    """Return ``{"hand_off_id", "status": "queued", "priority"}``.

    "queued" means a person has the case and the summary; nobody has picked it up
    yet, so the agent promises no time.
    """
    return {
        "hand_off_id": result.hand_off_id,
        "status": "queued",
        "priority": result.priority,
    }
```

`$R/delivery/handler.py`:

```python
"""Lambda handler for the ``human_agent_hand_off`` Gateway tool.

Handler string: ``human_agent_hand_off_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/human_agent_hand_off/tool_spec.json``); the tool name arrives
in ``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix. Every argument is passed to the use case bare.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Raw exception text is never returned.

The use case and its publisher are built once, when the module loads; a warm
container reuses them. The function runs outside the VPC and never touches DSQL.

TODO(ledgerlens): R1 - deployed by the data stack (ledgerlens-human-agent-hand-off);
  no Gateway target yet (write tools spec section 10), so the agent can't call it.
TODO(ledgerlens): R5 - customer_id is trusted from the tool input until Cedar
  statement 2 covers this tool (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from human_agent_hand_off_lambda.delivery.dependencies.dependencies_builder import (
    build_hand_off_use_case,
)
from human_agent_hand_off_lambda.delivery.presenters.hand_off import (
    present_hand_off,
)
from human_agent_hand_off_lambda.domain.errors import (
    DomainError,
    HandOffUnavailableError,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "human_agent_hand_off"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error sending the hand-off. Tell the customer you "
    "couldn't reach a person and that they can contact the bank through its "
    "usual channels."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. Don't retry; tell the "
    "customer they can contact the bank through its usual channels."
)


USE_CASE = build_hand_off_use_case(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Send the conversation to a human agent for the agent.

    Args:
        event: Tool arguments passed directly by the AgentCore Gateway.
        context: Lambda context with the tool name in client_context.custom.

    Returns:
        A Gateway ``content`` response, or ``{"error": message}``.
    """
    tool_name = _tool_name(context)
    if tool_name != TOOL_NAME:
        logger.error("Unexpected tool name %r for %s", tool_name, TOOL_NAME)
        return {"error": _WRONG_TOOL_MESSAGE}

    args = event if isinstance(event, Mapping) else {}
    try:
        if USE_CASE is None:
            raise HandOffUnavailableError()
        body = present_hand_off(
            USE_CASE.execute(
                customer_id=args.get("customer_id"),
                priority=args.get("priority"),
                reason=args.get("reason"),
                summary=args.get("summary"),
                related_ids=args.get("related_ids"),
            )
        )
    except DomainError as err:
        logger.warning(
            "%s returned an error: %s", TOOL_NAME, err.message, exc_info=True
        )
        return {"error": err.message}
    except Exception:
        logger.exception("Unexpected error in %s", TOOL_NAME)
        return {"error": UNEXPECTED_ERROR_MESSAGE}

    # The summary is never logged: it holds what the customer said.
    logger.info(
        "%s queued %s (priority=%s)", TOOL_NAME, body["hand_off_id"], body["priority"]
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _tool_name(context: object) -> str | None:
    """Return the tool name without its ``<target>___`` prefix, or None if absent."""
    try:
        full_name = context.client_context.custom["bedrockAgentCoreToolName"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return None
    if not isinstance(full_name, str):
        return None
    return full_name.rpartition(_TOOL_NAME_DELIMITER)[2]
```

`gateway/tools/human_agent_hand_off/tool_spec.json`:

```json
[
  {
    "name": "human_agent_hand_off",
    "description": "Sends the conversation to a human agent. Use when the customer asks for a person, after a confirmed fraud case, for anything out of scope, or when you can't resolve the request. The summary must let the agent continue without asking the customer anything again: the card's last 4 digits, the transactions, what was blocked or opened (with ids) and what the customer said. Returns JSON with 'hand_off_id', 'status' and 'priority'. Don't promise a time.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": {
          "type": "string",
          "description": "The authenticated customer's id from get_session_context."
        },
        "priority": {
          "type": "string",
          "enum": ["high", "normal"]
        },
        "reason": {
          "type": "string",
          "enum": ["FRAUD_CONFIRMED", "CUSTOMER_REQUEST", "UNRESOLVED", "OUT_OF_SCOPE"]
        },
        "summary": {
          "type": "string",
          "description": "Complete summary for the human agent, at most 2000 characters."
        },
        "related_ids": {
          "type": "array",
          "items": { "type": "string" },
          "maxItems": 20,
          "description": "Ids of the transactions, claims and other records involved."
        }
      },
      "required": ["customer_id", "priority", "reason", "summary"]
    }
  }
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/unit/human_agent_hand_off`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff@0.14.1 check --fix gateway/tools/human_agent_hand_off tests/unit/human_agent_hand_off
uvx ruff@0.14.1 format gateway/tools/human_agent_hand_off tests/unit/human_agent_hand_off
git add gateway/tools/human_agent_hand_off tests/unit/human_agent_hand_off
git commit -m "feat(human_agent_hand_off): handler, settings, builder, presenter and tool spec"
```

---

### Task 10: CDK in the data stack

**Files:**
- Modify: `infra-cdk/lib/data-construct.ts` (CRLF)
- Test: `infra-cdk/test/data-construct.test.ts`, `tests/unit/test_tool_requirements.py`

**Interfaces:**
- Consumes:
  - the tool folders (Tasks 2–9), with handler strings `<tool>_lambda.delivery.handler.handler`
  - the `access` stage and `WRITE_TOOLS_ROLE_ARN` (Task 1)
- Produces:
  - `DataConstruct.writeToolsRole` (IAM role `ledgerlens-write-tools`)
  - the functions `ledgerlens-block-credit-card`, `ledgerlens-open-claim` and `ledgerlens-human-agent-hand-off`
  - the topic `ledgerlens-human-handoff`

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_tool_requirements.py`:
- Change the `parametrize` list to `["list_credit_cards", "list_card_transactions", "get_session_context", "block_credit_card", "open_claim"]`.
- Append:

```python
def test_the_hand_off_tool_bundles_nothing() -> None:
    # It only needs boto3, which the runtime ships.
    assert not (TOOLS_DIR / "human_agent_hand_off" / "requirements.txt").exists()
```

In `infra-cdk/test/data-construct.test.ts`:

(a) Replace the `synth` function with one that takes a config:

```ts
function synth(cfg: AppConfig = config): Template {
  // skip Docker bundling of the Lambdas: these tests read the template only
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } })
  const stack = new cdk.Stack(app, "T", { env: { account: "111111111111", region: "us-east-1" } })
  new DataConstruct(stack, "Data", { config: cfg })
  return Template.fromStack(stack)
}
```

(b) In `every Lambda in the VPC runs in the endpoint's subnet`, change `expect(vpcFns).toHaveLength(4) // the read check and the three tools` to `expect(vpcFns).toHaveLength(6) // the read check and the five DSQL tools`.

(c) In the CodeBuild test, add `Match.objectLike({ Name: "WRITE_TOOLS_ROLE_ARN" }),` after the `TOOLS_ROLE_ARN` matcher.

(d) Append:

```ts
test("write tools role can connect to DSQL, never as admin", () => {
  const writeId = logicalId("AWS::IAM::Role", { RoleName: "ledgerlens-write-tools" })
  const actions = actionsOf(writeId)
  expect(actions).toContain("dsql:DbConnect")
  expect(actions).not.toContain("dsql:DbConnectAdmin")
})

test.each([
  ["block_credit_card", "ledgerlens-block-credit-card"],
  ["open_claim", "ledgerlens-open-claim"],
])("%s runs in the VPC as the write tools role, against the private host", (tool, functionName) => {
  const writeId = logicalId("AWS::IAM::Role", { RoleName: "ledgerlens-write-tools" })
  t.hasResourceProperties("AWS::Lambda::Function", {
    FunctionName: functionName,
    Handler: `${tool}_lambda.delivery.handler.handler`,
    Role: { "Fn::GetAtt": [writeId, "Arn"] },
    Timeout: 30,
    VpcConfig: Match.objectLike({ SubnetIds: Match.anyValue() }),
    Environment: { Variables: { DSQL_CLUSTER_ENDPOINT: Match.anyValue(), AS_OF: "2026-06-17T23:59:59" } },
  })
})

test("the read tools keep their construct ids, so the deployed functions are not replaced", () => {
  for (const [functionName, prefix] of [
    ["ledgerlens-list-credit-cards", "DataListCreditCardsFn"],
    ["ledgerlens-list-card-transactions", "DataListCardTransactionsFn"],
    ["ledgerlens-get-session-context", "DataGetSessionContextFn"],
  ]) {
    const ids = Object.keys(t.findResources("AWS::Lambda::Function", { Properties: { FunctionName: functionName } }))
    expect(ids).toHaveLength(1)
    expect(ids[0].startsWith(prefix)).toBe(true)
  }
})

test("the hand-off topic is encrypted; its Lambda runs outside the VPC and may only publish", () => {
  const topicId = logicalId("AWS::SNS::Topic", { TopicName: "ledgerlens-human-handoff" })
  const topic = t.findResources("AWS::SNS::Topic")[topicId]
  expect(JSON.stringify(topic.Properties.KmsMasterKeyId)).toContain("alias/aws/sns")
  const fns = Object.values(
    t.findResources("AWS::Lambda::Function", { Properties: { FunctionName: "ledgerlens-human-agent-hand-off" } })
  )
  expect(fns).toHaveLength(1)
  const fn = fns[0]
  expect(fn.Properties.VpcConfig).toBeUndefined()
  expect(fn.Properties.Handler).toBe("human_agent_hand_off_lambda.delivery.handler.handler")
  expect(fn.Properties.Timeout).toBe(10)
  expect(fn.Properties.Environment.Variables.HANDOFF_TOPIC_ARN).toEqual({ Ref: topicId })
  const roleId = fn.Properties.Role["Fn::GetAtt"][0]
  const actions = actionsOf(roleId)
  expect(actions).toContain("sns:Publish")
  expect(actions.filter((a: string) => a.startsWith("dsql:"))).toEqual([])
})

test("the admin email gets the hand-offs only when it is configured", () => {
  t.resourceCountIs("AWS::SNS::Subscription", 0)
  const withEmail = synth({ ...config, admin_user_email: "ops@example.com" } as unknown as AppConfig)
  withEmail.hasResourceProperties("AWS::SNS::Subscription", { Protocol: "email", Endpoint: "ops@example.com" })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/unit/test_tool_requirements.py`
Expected: PASS. The tool folders already exist, so this test is green as soon as Tasks 2–9 are done; it guards against regressions.

Run: `cd infra-cdk && npx jest test/data-construct.test.ts; cd ..`
Expected: FAIL in the new tests:
- no `ledgerlens-write-tools` role;
- 4 VPC functions instead of 6;
- no SNS topic;
- no `WRITE_TOOLS_ROLE_ARN`.

- [ ] **Step 3: Change `infra-cdk/lib/data-construct.ts`**

(a) Imports. After `import * as iam from "aws-cdk-lib/aws-iam"`, add `import * as kms from "aws-cdk-lib/aws-kms"`. After `import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager"`, add:

```ts
import * as sns from "aws-cdk-lib/aws-sns"
import * as subscriptions from "aws-cdk-lib/aws-sns-subscriptions"
```

(b) Class doc comment. Replace:

```ts
 * Aurora DSQL, readable only by the tools role from inside the VPC, plus the staged
 * pipeline that loads it (docs/superpowers/specs/2026-10-02-data-pipeline-design.md).
```

with:

```ts
 * Aurora DSQL, open only to the tool roles from inside the VPC, the staged pipeline that
 * loads it (docs/superpowers/specs/2026-10-02-data-pipeline-design.md), the Gateway tool
 * Lambdas and the hand-off topic (docs/superpowers/specs/2026-10-03-write-tools-design.md).
```

(c) After `  public readonly toolsRole: iam.Role`, add `  public readonly writeToolsRole: iam.Role`.

(d) After the `this.toolsRole = new iam.Role(this, "ToolsRole", { … })` block, add:

```ts
    // block_credit_card and open_claim connect as ll_write (write tools spec section 8)
    this.writeToolsRole = new iam.Role(this, "WriteToolsRole", {
      roleName: "ledgerlens-write-tools",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Write tool Lambdas: DSQL access as ll_write, from the VPC only",
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaVPCAccessExecutionRole"),
      ],
    })
```

(e) Replace:

```ts
    this.toolsRole.addToPolicy(
      new iam.PolicyStatement({ actions: ["dsql:DbConnect"], resources: [cluster.attrResourceArn] })
    )
```

with:

```ts
    for (const role of [this.toolsRole, this.writeToolsRole]) {
      role.addToPolicy(new iam.PolicyStatement({ actions: ["dsql:DbConnect"], resources: [cluster.attrResourceArn] }))
    }
```

(f) In the CodeBuild project:
- Change the description to `"Data pipeline: python -m data_load $STAGE (ingest, transform, curate, load; access on demand)"`.
- After `TOOLS_ROLE_ARN: { value: this.toolsRole.roleArn },`, add `WRITE_TOOLS_ROLE_ARN: { value: this.writeToolsRole.roleArn },`.

(g) Replace the comment and `tools` list above the loop:

```ts
    // Gateway tools deployed alone, to test them against the database. They move to the
    // agent stack with the Gateway; they read as ll_read, the role the read check proves.
    // The ids keep ListCreditCardsFn/ListCreditCardsLogs so the deployed function is not replaced.
    const tools = [
      { tool: "list_credit_cards", id: "ListCreditCards" },
      { tool: "list_card_transactions", id: "ListCardTransactions" },
      { tool: "get_session_context", id: "GetSessionContext" },
    ]
    for (const { tool, id } of tools) {
```

with:

```ts
    // Gateway tool Lambdas, imported by name by the agent stack. The read tools read as
    // ll_read, the role the read check proves. The write tools connect as ll_write (their
    // DSQL_DB_USER default) with their own IAM role, which the load and access stages map.
    // The ids keep ListCreditCardsFn/ListCreditCardsLogs so the deployed function is not replaced.
    const tools: { tool: string; id: string; role?: iam.IRole }[] = [
      { tool: "list_credit_cards", id: "ListCreditCards" },
      { tool: "list_card_transactions", id: "ListCardTransactions" },
      { tool: "get_session_context", id: "GetSessionContext" },
      { tool: "block_credit_card", id: "BlockCreditCard", role: this.writeToolsRole },
      { tool: "open_claim", id: "OpenClaim", role: this.writeToolsRole },
    ]
    for (const { tool, id, role = this.toolsRole } of tools) {
```

Inside the loop, change the 8-space-indented line `        role: this.toolsRole,` to `        role,`. Leave the read check's 6-space-indented `role: this.toolsRole,` alone.

(h) After the loop's closing `}`, before `// Stages 1-4 in order (spec 4.2)`, add:

```ts

    // The hand-off tool only publishes to SNS: it runs outside the VPC (which has no route
    // out) and never touches DSQL. The topic uses the AWS-managed key, whose key policy lets
    // SNS use it for publishers in the account, so the function needs only sns:Publish.
    const handOffTopic = new sns.Topic(this, "HumanHandOffTopic", {
      topicName: "ledgerlens-human-handoff",
      masterKey: kms.Alias.fromAliasName(this, "SnsManagedKey", "alias/aws/sns"),
    })
    if (props.config.admin_user_email) {
      // the recipient confirms the subscription once, from the email SNS sends
      handOffTopic.addSubscription(new subscriptions.EmailSubscription(props.config.admin_user_email))
    }
    const handOff = new PythonFunction(this, "HumanAgentHandOffFn", {
      functionName: "ledgerlens-human-agent-hand-off",
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      entry: path.join(__dirname, "..", "..", "gateway", "tools", "human_agent_hand_off"), // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      index: "human_agent_hand_off_lambda/delivery/handler.py",
      handler: "handler",
      bundling: { assetExcludes: ["**/__pycache__", "**/*.pyc"] },
      timeout: cdk.Duration.seconds(10),
      environment: { HANDOFF_TOPIC_ARN: handOffTopic.topicArn },
      logGroup: new logs.LogGroup(this, "HumanAgentHandOffLogs", {
        logGroupName: `/aws/lambda/${props.config.stack_name_base}-human-agent-hand-off`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })
    handOffTopic.grantPublish(handOff)
```

After editing, check that the file is still CRLF: `file infra-cdk/lib/data-construct.ts` must report `with CRLF line terminators`. If it doesn't, run `unix2dos infra-cdk/lib/data-construct.ts`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra-cdk && npx jest test/data-construct.test.ts test/data-stack.test.ts; cd ..`
Expected: PASS.

If the hand-off test fails because `grantPublish` also added `kms:*` actions to the role, keep the code: that's harmless. Only the two assertions in the test matter (`sns:Publish` is present, and there's no `dsql:` action).

Run: `cd infra-cdk && npx jest; cd ..`
Expected: PASS for the whole CDK suite (about 2 minutes).

Run: `PYTEST tests/unit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add infra-cdk/lib/data-construct.ts infra-cdk/test/data-construct.test.ts tests/unit/test_tool_requirements.py
git commit -m "feat(cdk): write tools on their own DSQL role, and the hand-off Lambda and topic in the data stack"
```

---

### Task 11: Docs

**Files:**
- Modify: `docs/LEDGERLENS_PRODUCT_DESIGN.md` (CRLF), `README.md` (CRLF)

- [ ] **Step 1: Update the product design**

In `docs/LEDGERLENS_PRODUCT_DESIGN.md`:

(a) After the heading line `### 7.7 \`block_credit_card\` (A2, **changes data**)`, insert a blank line and:

```markdown
Spec: [2026-10-03-write-tools-design.md](superpowers/specs/2026-10-03-write-tools-design.md) §3. The Lambda is deployed by the data stack; its Gateway target and Cedar statement 3 come later (spec §10).
```

(b) After the heading line `### 7.8 \`open_claim\` (A2, **changes data**)`, insert a blank line and:

```markdown
Spec: [2026-10-03-write-tools-design.md](superpowers/specs/2026-10-03-write-tools-design.md) §4. One claim per card and currency, with an id derived from its content, so the same claim can't be opened twice.
```

(c) In §7.8, make these replacements:

| Old | New |
|---|---|
| `If they aren't, the Lambda opens one claim per currency.` | `The Lambda opens one claim per card and currency.` |
| `'Claim', 'Cards', CASE WHEN :claim_type = 'fraud' THEN 'Unrecognised transaction' ELSE 'Disputed charge' END,` | `'Claim', 'Transactions', CASE WHEN :claim_type = 'fraud' THEN 'Cargo no reconocido' ELSE 'Cobro indebido' END,` |
| `'AI Assistant', MIN(t.product_id),` | `'Web', MIN(t.product_id),` |
| `WHERE category = 'Cards'` | `WHERE category = 'Transactions'` |

(d) After the heading line `### 7.9 \`human_agent_hand_off\` (A2 + fallback)`, insert a blank line and:

```markdown
Spec: [2026-10-03-write-tools-design.md](superpowers/specs/2026-10-03-write-tools-design.md) §5. SNS only; the Lambda runs outside the VPC.
```

Then replace the line `- Optionally inserts a \`call_center_interactions\` row (\`channel = 'AI Assistant'\`, \`was_escalated = true\`) so the hand-off is counted in reporting.` with:

```markdown
- No `call_center_interactions` row: that table has no column for the summary.
```

(e) In §15:
- Replace `- [ ] Create the SNS topic \`ledgerlens-human-handoff\`.` with `- [x] Create the SNS topic \`ledgerlens-human-handoff\` (data stack).`
- Replace the `- [ ] Lambda IAM: …` line with:

```markdown
- [x] Lambda IAM: `dsql:DbConnect` on the cluster ARN (`dsql:DbConnectAdmin` only if `DSQL_DB_USER=admin`). The read tools use `ledgerlens-tools` (DSQL role `ll_read`); `block_credit_card` and `open_claim` use `ledgerlens-write-tools` (`ll_write`); only the hand-off role may publish to SNS.
```

- [ ] **Step 2: Update the README**

In `README.md`:

(a) Replace the bullet starting `- **Read-only access:** only the IAM role \`ledgerlens-tools\` can read the data` with:

```markdown
- **Tool access:**
  - The read tools connect as `ll_read` (IAM role `ledgerlens-tools`, SELECT only).
  - `block_credit_card` and `open_claim` connect as `ll_write` (IAM role `ledgerlens-write-tools`): UPDATE on `products`, INSERT on `complaints`.
  - Both connect only from inside the stack's VPC, through the private host `DsqlPrivateHost`.
```

(b) After the `- **After a manual rerun,** run the read check yourself:` bullet and its code block, add:

````markdown
- **Adding a tool role to a loaded cluster:** after a data stack deploy that adds a role, run the `access` stage once. It creates the roles, maps them to their IAM roles and re-runs the grants, without touching the data:

  ```bash
  aws codebuild start-build --profile ledgerlens --project-name ledgerlens-data-load \
    --environment-variables-override name=STAGE,value=access,type=PLAINTEXT
  ```
````

- [ ] **Step 3: Check the line endings and commit**

```bash
uv run --no-project --quiet python - <<'EOF'
for path in ("docs/LEDGERLENS_PRODUCT_DESIGN.md", "README.md"):
    data = open(path, "rb").read()
    assert b"\n" not in data.replace(b"\r\n", b""), f"{path} has LF-only lines"
print("CRLF ok")
EOF
grep -c "'Cargo no reconocido' ELSE 'Cobro indebido'" docs/LEDGERLENS_PRODUCT_DESIGN.md
grep -c "write-tools-design.md" docs/LEDGERLENS_PRODUCT_DESIGN.md
git add docs/LEDGERLENS_PRODUCT_DESIGN.md README.md
git commit -m "docs: write tools in the product design and the access stage in the README"
```

Expected: `CRLF ok`, then `1`, then `3`. If the CRLF check fails, convert the file with `unix2dos <path>` and run the check again.

---

### Task 12: Deploy, map `ll_write`, smoke test and restore

**Gate:** start only after both of these are true:
1. The branch's code review has finished, and its findings are fixed.
2. The user says to deploy.

Every command below changes the team's AWS account.

- [ ] **Step 1: Ask the user which customer the write checks may change**

Recommend persona **P07** (`CLI-EX6BOAOEFZHQ`, card `4497`, transaction `TRX-23BIJAU4GL46ATPW9STY`): it is the fraud persona, and its demo needs the Gateway, which comes later. Step 7 restores the data afterwards. Use whatever customer the user picks in Steps 5–6.

- [ ] **Step 2: Deploy the data stack**

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant-data
```

Expected: the deploy succeeds and creates `ledgerlens-write-tools`, the three functions and `ledgerlens-human-handoff`. The read tools aren't replaced, so their logical ids are unchanged.

- [ ] **Step 3: Map `ll_write` with the `access` stage**

```bash
id=$(aws codebuild start-build --profile ledgerlens --project-name ledgerlens-data-load \
  --environment-variables-override name=STAGE,value=access,type=PLAINTEXT \
  --query 'build.id' --output text)
echo "$id"
aws codebuild batch-get-builds --profile ledgerlens --ids "$id" --query 'builds[0].buildStatus' --output text
```

Repeat the last command until it prints `SUCCEEDED`, about 3 minutes. In the build log (CodeBuild console, or `aws logs tail` on the project's log group), the last stage line reads:
`access: roles ll_read, ll_write mapped and granted`.

Then check that reading still works:

```bash
aws lambda invoke --profile ledgerlens --function-name ledgerlens-dsql-read-check out.json && cat out.json
```

- [ ] **Step 4: Confirm the hand-off email subscription**

This only applies if `admin_user_email` is set in `infra-cdk/config.yaml`. Open the "AWS Notification - Subscription Confirmation" email and click the link.

- [ ] **Step 5: Smoke test the write tools**

Use the customer from Step 1. Each call passes the tool name in the client context:

```bash
ctx() { printf '{"custom":{"bedrockAgentCoreToolName":"x___%s"}}' "$1" | base64 -w0; }
call() {  # call <function-suffix> <tool> <json>
  aws lambda invoke --profile ledgerlens --function-name "ledgerlens-$1" \
    --client-context "$(ctx "$2")" --cli-binary-format raw-in-base64-out \
    --payload "$3" out.json >/dev/null && cat out.json && echo
}
C=CLI-EX6BOAOEFZHQ
call block-credit-card block_credit_card "{\"customer_id\":\"$C\",\"card_last4\":\"4497\",\"reason\":\"suspected_fraud\",\"customer_confirmed\":false}"
call block-credit-card block_credit_card "{\"customer_id\":\"$C\",\"card_last4\":\"4497\",\"reason\":\"suspected_fraud\",\"customer_confirmed\":true}"
call block-credit-card block_credit_card "{\"customer_id\":\"$C\",\"card_last4\":\"4497\",\"reason\":\"suspected_fraud\",\"customer_confirmed\":true}"
T='["TRX-23BIJAU4GL46ATPW9STY"]'
call open-claim open_claim "{\"customer_id\":\"$C\",\"transaction_ids\":$T,\"claim_type\":\"fraud\",\"customer_statement\":\"Smoke test: no reconozco este cargo\",\"customer_confirmed\":true}"
call open-claim open_claim "{\"customer_id\":\"$C\",\"transaction_ids\":$T,\"claim_type\":\"fraud\",\"customer_statement\":\"Smoke test: no reconozco este cargo\",\"customer_confirmed\":true}"
call human-agent-hand-off human_agent_hand_off "{\"customer_id\":\"$C\",\"priority\":\"high\",\"reason\":\"FRAUD_CONFIRMED\",\"summary\":\"Smoke test of the hand-off tool; ignore.\"}"
```

Expected, in order:
1. The `customer_confirmed` input error.
2. `{"card_last4": "4497", "status": "Blocked", "already_blocked": false}`.
3. The same, with `"already_blocked": true`.
4. One claim with `"already_existed": false` and a `CMP-…` id.
5. The same claim id with `"already_existed": true`.
6. A `hand_off_id` and `"status": "queued"`; the email arrives if the subscription is confirmed.

For W1, check the claim's `resolution_estimate`:
- **An object** means `percentile_cont` works on DSQL.
- **`null` both times:** read `/aws/lambda/<stack_name_base>-open-claim` for `Resolution estimate failed`. If the log names an unsupported function, report it to the user (it fails safe).

Any other result is a failure to report with the output. Don't fix it on the spot.

- [ ] **Step 6: Report**

Tell the user each of the six results and the estimate outcome.

- [ ] **Step 7: Restore the data**

Ask the user before running this, because the tools see missing tables for about 2 minutes (README). Rerun the `load` stage of the latest pipeline run to drop the smoke test's block and claim:

```bash
arn=$(aws stepfunctions list-state-machines --profile ledgerlens --query "stateMachines[?name=='ledgerlens-data-pipeline'].stateMachineArn" --output text)
run=$(aws stepfunctions list-executions --profile ledgerlens --state-machine-arn "$arn" --status-filter SUCCEEDED --max-results 1 --query 'executions[0].name' --output text)
aws codebuild start-build --profile ledgerlens --project-name ledgerlens-data-load \
  --environment-variables-override name=STAGE,value=load,type=PLAINTEXT name=RUN_ID,value="$run",type=PLAINTEXT
```

When the build succeeds, run the read check from Step 3 again. Then check the card with the read tool, which changes nothing:

```bash
call list-credit-cards list_credit_cards "{\"customer_id\":\"$C\"}"
```

Expected: the card ending in `4497` shows `"product_status": "Active"` again. That shows the restore worked. Report it to the user.
