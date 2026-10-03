# Self-contained Tool Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `list_card_transactions` tool out of the shared `ledgerlens` package into its own self-contained folder, `gateway/tools/list_card_transactions/list_card_transactions_lambda/`, with no behaviour change.

**Architecture:**
- This is a pure move and rename. Every file goes over with `git mv`.
- Imports change from `ledgerlens.` to `list_card_transactions_lambda.`.
- The test folder becomes the package `tests/unit/list_card_transactions/`.
- Docstrings that described a core shared by every tool are reworded for one tool.
- The existing 248 tests are the safety net. No new tests are needed because nothing new is built.

**Tech Stack:** Python 3.10, pytest 7.1, ruff, git (Git Bash on Windows).

**Spec:** `docs/superpowers/specs/2026-10-01-self-contained-tool-folders-design.md`

## Global Constraints

- Python: `PY=/c/ProgramData/anaconda3/python`. Run every command from the repo root `C:\GITHUB REPOS\ledgerlens-bank-assistant` in Git Bash.
- **Do not commit during execution.** The user commits once, on their command, at the end. Never run `git commit`, and never `git add` anything other than what `git mv` stages.
- Never stage `infra-cdk/config.yaml`, `frontend/public/aws-exports.json` or `frontend/.env`.
- No AWS deploys, no CDK changes, no push and no merge.
- No behaviour change, and no renaming of classes, functions, test files or test functions. Only paths, imports, docstrings and comments change.
- Keep `TODO(ledgerlens): Rn` tags and the database role name `ledgerlens_readonly` exactly as they are. They are not references to the package.
- Names:
  - asset folder: `gateway/tools/list_card_transactions/`
  - package: `list_card_transactions_lambda`
  - handler: `delivery/handler.py`
  - handler string: `list_card_transactions_lambda/delivery/handler.handler`
  - test package: `tests/unit/list_card_transactions/`
  - fakes: `fakes.py`
- Lint: `$PY -m ruff format --check <paths>` and `$PY -m ruff check <paths>`.

## Review Focus

1. **Stale `__pycache__` from the old folders.** A leftover `.pyc` could let an old import keep working by accident. Expected: the old folders are gone entirely, and the suite passes from a clean tree. *Pinned by Task 1 Step 6, which deletes them, and Step 9, which runs with `-p no:cacheprovider` after a `__pycache__` purge.*
2. **The test package `list_card_transactions` shadowed by, or shadowing, another module of that name on `sys.path`.** This could happen if anything puts `gateway/tools/` on the path. Expected: production imports resolve to `list_card_transactions_lambda` only, and the test package resolves to `tests/unit/list_card_transactions`. *Pinned by Task 1 Step 9, which runs all of `tests/unit` in one session, `test_mcp_registry.py` included.*
3. **The handler test reloading the wrong module.** `importlib.reload` on a path that no longer exists fails only when that test runs. Expected: `test_list_card_transactions_handler.py` passes. *Pinned by Task 1 Step 8, which runs that file on its own.*
4. **A missed `ledgerlens.` import in code paths that tests don't import**, such as a lazily imported module. Expected: none remain. *Pinned by Task 2 Step 5's grep.*
5. **The query file path.** `FileQueryProvider` resolves `QUERIES_ROOT` from `dependencies_builder`'s `__file__`, so a broken relative layout only fails when the query loads. Expected: the wiring test that loads the real SQL passes. *Pinned by Task 1 Step 8, which runs `test_delivery_wiring.py` and `test_query_contracts.py`.*

---

### Task 1: Move the package and its tests

**Files:**
- Move: `gateway/tools/ledgerlens_tools/requirements.txt` → `gateway/tools/list_card_transactions/requirements.txt`
- Move: `gateway/tools/ledgerlens_tools/ledgerlens/` → `gateway/tools/list_card_transactions/list_card_transactions_lambda/`
- Move: `…/list_card_transactions_lambda/delivery/list_card_transactions_handler.py` → `…/list_card_transactions_lambda/delivery/handler.py`
- Move: `tests/unit/ledgerlens_tools/` → `tests/unit/list_card_transactions/`
- Move: `tests/unit/list_card_transactions/ledgerlens_fakes.py` → `tests/unit/list_card_transactions/fakes.py`
- Create: `tests/unit/list_card_transactions/__init__.py` (empty)
- Modify: every `.py` file under both new folders (imports), `tests/unit/list_card_transactions/conftest.py`, and `tests/unit/list_card_transactions/test_query_contracts.py:24`
- Delete: `gateway/tools/ledgerlens_tools/` and `tests/unit/ledgerlens_tools/` (after the moves only `__pycache__` is left)

**Interfaces:**
- Consumes: nothing.
- Produces, for Task 2: the package `list_card_transactions_lambda` at `gateway/tools/list_card_transactions/list_card_transactions_lambda/` and the green test package `tests/unit/list_card_transactions/`.

- [ ] **Step 1: Record the baseline**

Run:
```bash
PY=/c/ProgramData/anaconda3/python
$PY -m pytest tests/unit/ledgerlens_tools -q 2>&1 | tail -2
$PY -m pytest tests/unit -q 2>&1 | tail -2
git status --short
```
Expected:
- The first run ends with `248 passed`.
- Note the second run's count (248 plus `test_mcp_registry.py`'s tests). Step 9 must match it.
- `git status` shows only `docs/LEDGERLENS_PRODUCT_DESIGN.md`, `infra-cdk/config.yaml` and the two untracked docs (the 2026-10-01 spec and this plan).

- [ ] **Step 2: Move the production package**

```bash
git mv gateway/tools/ledgerlens_tools/requirements.txt gateway/tools/list_card_transactions/requirements.txt
git mv gateway/tools/ledgerlens_tools/ledgerlens gateway/tools/list_card_transactions/list_card_transactions_lambda
git mv gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/list_card_transactions_handler.py \
       gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/handler.py
```
Expected: no output. `git status --short` shows the files as `R` (renamed).

- [ ] **Step 3: Watch the old tests fail (RED)**

Run: `$PY -m pytest tests/unit/ledgerlens_tools -q 2>&1 | tail -5`
Expected: collection errors with `ModuleNotFoundError: No module named 'ledgerlens'`. This proves the tests really import from the moved package. If they still pass, a stale `__pycache__` or another copy is being imported. Stop and find it.

- [ ] **Step 4: Rewrite the production imports**

```bash
P=gateway/tools/list_card_transactions/list_card_transactions_lambda
find $P -name "*.py" -not -path "*__pycache__*" -print0 \
  | xargs -0 sed -i -E 's/^(\s*)from ledgerlens\./\1from list_card_transactions_lambda./'
grep -rn "ledgerlens\." $P --include=*.py
```
Expected: the grep prints nothing. The handler docstring's `ledgerlens/delivery/...` has a slash, not a dot, and Task 2 rewrites it. If anything is printed, fix it by hand the same way.

- [ ] **Step 5: Move the tests and make the folder a package**

```bash
git mv tests/unit/ledgerlens_tools tests/unit/list_card_transactions
git mv tests/unit/list_card_transactions/ledgerlens_fakes.py tests/unit/list_card_transactions/fakes.py
: > tests/unit/list_card_transactions/__init__.py
```
Expected: no output. `tests/unit/list_card_transactions/__init__.py` exists and is empty. If Git Bash creates it with CRLF or a BOM, it's still empty (0 bytes): check with `wc -c`.

- [ ] **Step 6: Delete the leftover folders**

```bash
ls -A gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools 2>&1
rm -rf gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools
find gateway/tools/list_card_transactions tests/unit/list_card_transactions -name __pycache__ -type d -prune -exec rm -rf {} +
```
Expected:
- The `ls` lists at most `__pycache__` in each folder; `tests/unit/ledgerlens_tools` may already be gone because `git mv` moved the whole folder. If any other file is listed, stop: it's untracked and must not be deleted blindly.
- After the `rm`, both old paths are gone.

- [ ] **Step 7: Rewrite the test imports, conftest and query path**

Imports:
```bash
T=tests/unit/list_card_transactions
find $T -name "*.py" -print0 | xargs -0 sed -i -E \
  -e 's/^(\s*)from ledgerlens\./\1from list_card_transactions_lambda./' \
  -e 's/^(\s*)import ledgerlens\./\1import list_card_transactions_lambda./' \
  -e 's/^from ledgerlens_fakes import/from .fakes import/' \
  -e 's/list_card_transactions_lambda\.delivery\.list_card_transactions_handler/list_card_transactions_lambda.delivery.handler/'
```

`test_query_contracts.py` line 24 must read exactly:
```python
QUERIES_DIR = (
    REPO_ROOT
    / "gateway/tools/list_card_transactions/list_card_transactions_lambda/queries/postgresql"
)
```
Use the Edit tool to replace:
`QUERIES_DIR = REPO_ROOT / "gateway/tools/ledgerlens_tools/ledgerlens/queries/postgresql"`
If ruff format would keep it on one line, accept ruff's layout in Step 10.

Replace the whole of `tests/unit/list_card_transactions/conftest.py` with:
```python
"""Pytest setup for list_card_transactions: make its Lambda package importable.

The ``list_card_transactions_lambda`` package lives in the Lambda asset root
``gateway/tools/list_card_transactions``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "list_card_transactions"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
```

Change line 1 of `tests/unit/list_card_transactions/fakes.py`:
- from `"""Test doubles and builders shared by the LedgerLens tool tests."""`
- to `"""Test doubles and builders for the list_card_transactions tests."""`

Then check:
```bash
grep -rn "ledgerlens\.\|ledgerlens_fakes\|ledgerlens_tools" $T --include=*.py
```
Expected: no output.

- [ ] **Step 8: Run the risky test files on their own (GREEN, part 1)**

Run:
```bash
$PY -m pytest tests/unit/list_card_transactions/test_list_card_transactions_handler.py \
  tests/unit/list_card_transactions/test_delivery_wiring.py \
  tests/unit/list_card_transactions/test_query_contracts.py -q 2>&1 | tail -3
```
Expected: all pass, no errors. If a relative import `from .fakes import` fails with `attempted relative import with no known parent package`, then `__init__.py` is missing. Recheck Step 5.

- [ ] **Step 9: Run the full suite from a clean cache (GREEN, part 2)**

Run:
```bash
find tests gateway -name __pycache__ -type d -prune -exec rm -rf {} +
$PY -m pytest tests/unit/list_card_transactions -q -p no:cacheprovider 2>&1 | tail -2
$PY -m pytest tests/unit -q -p no:cacheprovider 2>&1 | tail -2
```
Expected:
- The first run ends with `248 passed`.
- The second run matches the count recorded in Step 1.

- [ ] **Step 10: Lint**

Run:
```bash
$PY -m ruff format gateway/tools/list_card_transactions tests/unit/list_card_transactions
$PY -m ruff format --check gateway/tools/list_card_transactions tests/unit/list_card_transactions
$PY -m ruff check gateway/tools/list_card_transactions tests/unit/list_card_transactions
```
Expected:
- The first command reformats at most `test_query_contracts.py` (the `QUERIES_DIR` layout).
- The check commands print `… files already formatted` and `All checks passed!`.
- Re-run Step 9's first pytest command if anything was reformatted. Expected: `248 passed`.

No commit. The task ends with the tree green.

---

### Task 2: Reword shared-package text and close out

**Files:**
- Modify: `gateway/tools/list_card_transactions/requirements.txt:1`
- Modify: `gateway/tools/list_card_transactions/list_card_transactions_lambda/__init__.py:1`
- Modify: `…/list_card_transactions_lambda/utils/__init__.py:1`
- Modify: `…/list_card_transactions_lambda/application/use_cases/__init__.py:1`
- Modify: `…/list_card_transactions_lambda/delivery/dependencies/__init__.py:1`
- Modify: `…/list_card_transactions_lambda/delivery/settings.py:27`
- Modify: `…/list_card_transactions_lambda/delivery/handler.py:3`
- Modify: `…/list_card_transactions_lambda/delivery/dependencies/dependencies_builder.py:1-22,121`
- Modify: `docs/superpowers/specs/2026-09-29-list-card-transactions-lambda-design.md` (header)
- Modify: `docs/superpowers/specs/2026-09-30-dsql-engine-design.md` (header)

**Interfaces:**
- Consumes: the package `list_card_transactions_lambda` from Task 1.
- Produces: nothing new. Only text changes.

Below, `L` means `gateway/tools/list_card_transactions/list_card_transactions_lambda`. Use the Edit tool for every replacement; each old string is quoted exactly.

- [ ] **Step 1: Package docstrings and requirements header**

| File | Old (exact) | New |
|---|---|---|
| `gateway/tools/list_card_transactions/requirements.txt` | `# Runtime dependencies for every LedgerLens tool Lambda (shared asset).` | `# Runtime dependencies for the list_card_transactions Lambda.` |
| `L/__init__.py` | `"""LedgerLens bank assistant tools: shared hexagonal core for every tool Lambda."""` | `"""The list_card_transactions Gateway tool Lambda, in hexagonal layers."""` |
| `L/utils/__init__.py` | `"""Shared technical helpers used by infrastructure and delivery."""` | `"""Technical helpers used by infrastructure and delivery."""` |
| `L/application/use_cases/__init__.py` | `"""Use cases: one class per tool."""` | `"""Use case of the list_card_transactions tool."""` |
| `L/delivery/dependencies/__init__.py` | `"""Dependency building: dependencies_builder builds every LedgerLens object."""` | `"""Dependency building: dependencies_builder builds every object of this tool."""` |
| `L/delivery/settings.py` | `"""Settings shared by every tool Lambda, whatever the engine.` | `"""Database settings that don't depend on the engine.` |
| `L/delivery/handler.py` | ``Handler string: ``ledgerlens/delivery/list_card_transactions_handler.handler``.`` | ``Handler string: ``list_card_transactions_lambda/delivery/handler.handler``.`` |

In `settings.py`, read the lines that follow the replaced docstring line. If the rest of that docstring still says "every tool", reword it for a single tool in the same way.

- [ ] **Step 2: `dependencies_builder.py` docstrings**

Replace:
```
Handlers never build anything themselves. At cold start each handler calls its
tool's block below once and reuses the result on every warm invocation. That is
```
with:
```
The handler never builds anything itself. At cold start it calls
build_list_card_transactions_use_case once and reuses the result on every warm
invocation. That is
```
Reflow the rest of that paragraph if a line now runs past 88 characters. The words stay the same.

Replace:
```
- Use cases: one function per tool, which builds that tool's whole graph.
```
with:
```
- Use case: build_list_card_transactions_use_case, which builds the tool's whole
  graph.
```

Replace:
```
SQL_DIALECTS entry and, when the dialect is new, a ``queries/<dialect>/`` folder.
Adding a tool means adding one function to the use cases block. A tool builds
only its own graph, so it never fails on settings it doesn't use.
```
with:
```
SQL_DIALECTS entry and, when the dialect is new, a ``queries/<dialect>/`` folder.
The builder serves the list_card_transactions tool only; every other tool has
its own folder and its own builder.
```

Replace:
```
    Cached so every tool in the container shares one provider per engine.
```
with:
```
    Cached so the container builds the provider once per engine.
```

Leave "The connection inside the connector is the only shared state" unchanged. It means state shared between warm invocations, not between tools.

- [ ] **Step 3: Notes in the historical specs**

In `docs/superpowers/specs/2026-09-29-list-card-transactions-lambda-design.md`, insert this line directly after the line that starts `**Updated 2026-09-30:**`:
```
**Updated 2026-10-01:** the code now lives in `gateway/tools/list_card_transactions/list_card_transactions_lambda/`. See [2026-10-01-self-contained-tool-folders-design.md](2026-10-01-self-contained-tool-folders-design.md).
```

In `docs/superpowers/specs/2026-09-30-dsql-engine-design.md`, insert the same line directly after the line `**Parent design:** [2026-09-29-list-card-transactions-lambda-design.md](2026-09-29-list-card-transactions-lambda-design.md)`.

The plans in `docs/superpowers/plans/` stay as they are.

- [ ] **Step 4: Tests and lint**

Run:
```bash
$PY -m pytest tests/unit/list_card_transactions -q -p no:cacheprovider 2>&1 | tail -2
$PY -m ruff format --check gateway/tools/list_card_transactions tests/unit/list_card_transactions
$PY -m ruff check gateway/tools/list_card_transactions tests/unit/list_card_transactions
```
Expected: `248 passed`, `… files already formatted`, and `All checks passed!`.

- [ ] **Step 5: Leftover-reference sweep**

Run:
```bash
grep -rn "ledgerlens\." gateway tests --include=*.py
grep -rn "ledgerlens_tools\|ledgerlens_fakes\|list_card_transactions_handler\b" . \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=docs --exclude-dir=__pycache__ \
  | grep -v "test_list_card_transactions_handler"
grep -rn -i "every tool\|one class per tool\|shared asset\|shared hexagonal" gateway/tools/list_card_transactions
```
Expected: all three print nothing.
- The test file name `test_list_card_transactions_handler.py` is kept on purpose and is filtered out.
- `ledgerlens_readonly` and `TODO(ledgerlens)` don't match the first pattern, because neither has a dot after `ledgerlens`.

- [ ] **Step 6: Show the change set and hand over for the commit**

Run: `git status --short && git diff --stat -M HEAD | tail -3`
Expected:
- Renames (`R`) for every moved file.
- Modifications for the reworded files and the two historical specs.
- New, untracked: `tests/unit/list_card_transactions/__init__.py`, the 2026-10-01 spec and this plan.
- `docs/LEDGERLENS_PRODUCT_DESIGN.md` is still modified from earlier. `infra-cdk/config.yaml` is modified and must not be staged.

Stop here and ask the user for the commit command. Don't commit.
