# Self-contained tool folders: Design

**Date:** 2026-10-01
**Status:** Draft, awaiting review.
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §7
**Supersedes the layout in:** [2026-09-29-list-card-transactions-lambda-design.md](2026-09-29-list-card-transactions-lambda-design.md), §1 and §2 (one shared `ledgerlens` package for every tool)

---

## 1. Goal

Each Gateway Lambda tool becomes **one self-contained folder** that wraps every hexagonal layer it needs. Today the first tool, `list_card_transactions`, lives in a shared package (`gateway/tools/ledgerlens_tools/ledgerlens/`) that every later tool was meant to import. This change moves it into its own folder.

From now on, code is **copied** between tools, never shared. Each tool defines its own domain objects, errors, ports, use case, adapters, connectors, settings, presenters, dependency builder and handler.

### Why
- **Human readability:** one folder holds everything that one Lambda does. A reader never has to work out which shared pieces a tool uses.
- **Easy deployment understanding:** one folder is one Lambda asset. What gets packaged is exactly what is in the folder.

The cost is accepted: a fix to copied code (a connector, for example) has to be made in every tool that holds a copy.

### Success criteria
- `list_card_transactions` behaves exactly as before. All 248 existing unit tests pass from their new location with only import and path changes.
- `ruff format --check` and `ruff check` are clean.
- No `ledgerlens.` import and no `ledgerlens_tools` path remain outside the historical documents in `docs/superpowers/`.
- Nothing outside `list_card_transactions`'s folder and its tests imports from it.

### Out of scope
- `list_credit_cards`. It follows in its own spec, built as the second self-contained folder by copying from this one.
- Any behaviour change, renaming of classes or functions, or refactoring of the code itself.
- CDK. There is still no Lambda, Gateway target or packaging for these tools (R1).

---

## 2. Layout

### Before
```
gateway/tools/
├── ledgerlens_tools/                          ← shared asset root
│   ├── requirements.txt
│   └── ledgerlens/ (domain, application, infrastructure, delivery, utils, queries)
└── list_card_transactions/
    └── tool_spec.json

tests/unit/ledgerlens_tools/                   ← not a package
├── conftest.py, ledgerlens_fakes.py, test_*.py
```

### After
```
gateway/tools/list_card_transactions/          ← Lambda asset root for this tool only
├── tool_spec.json                             (unchanged)
├── requirements.txt                           (moved)
└── list_card_transactions_lambda/
    ├── __init__.py
    ├── domain/
    │   ├── entities/card_transaction.py
    │   ├── value_objects/transaction_filters.py
    │   └── errors.py
    ├── application/
    │   ├── ports/{database_repository,query_provider,errors}.py
    │   └── use_cases/list_card_transactions.py
    ├── infrastructure/
    │   ├── queries/file_query_provider.py
    │   └── repositories/dsql_repository.py
    ├── utils/connectors/{base,dsql}.py
    ├── delivery/
    │   ├── handler.py                         (was list_card_transactions_handler.py)
    │   ├── settings.py
    │   ├── dependencies/dependencies_builder.py
    │   └── presenters/card_transactions.py
    └── queries/postgresql/list_card_transactions.sql

tests/unit/list_card_transactions/             ← now a package
├── __init__.py                                (new, empty)
├── conftest.py                                (puts the asset root on sys.path)
├── fakes.py                                   (was ledgerlens_fakes.py)
└── test_*.py                                  (same files, same names)
```

**Handler string:** `list_card_transactions_lambda/delivery/handler.handler`.

Every `__init__.py` in the current package moves along with its folder.

### Naming
- **Folder:** the tool name (`list_card_transactions`). It already holds `tool_spec.json`.
- **Python package:** the tool name plus `_lambda` (`list_card_transactions_lambda`). Imports always say which tool they belong to, and two tools never share a module name, so every tool's tests run in one pytest session.
- **Handler module:** `delivery/handler.py`. The folder already names the tool, so the file name doesn't repeat it.
- **Test package:** the tool name without `_lambda` (`tests/unit/list_card_transactions/`). It must differ from the production package, or the test package would shadow it on `sys.path`.

---

## 3. Changes, file by file

### 3.1 Moves
Every file moves with `git mv`, so `git log --follow` keeps its history.

| From | To |
|---|---|
| `gateway/tools/ledgerlens_tools/requirements.txt` | `gateway/tools/list_card_transactions/requirements.txt` |
| `gateway/tools/ledgerlens_tools/ledgerlens/**` | `gateway/tools/list_card_transactions/list_card_transactions_lambda/**` |
| `…/delivery/list_card_transactions_handler.py` | `…/delivery/handler.py` |
| `tests/unit/ledgerlens_tools/*.py` | `tests/unit/list_card_transactions/*.py` |
| `tests/unit/ledgerlens_tools/ledgerlens_fakes.py` | `tests/unit/list_card_transactions/fakes.py` |

`gateway/tools/ledgerlens_tools/` and `tests/unit/ledgerlens_tools/` are then removed, including any leftover `__pycache__`.

### 3.2 Imports
- **Production code:** `from ledgerlens.` becomes `from list_card_transactions_lambda.` everywhere.
- **Tests:**
  - Production imports change the same way.
  - Fakes come in through a relative import: `from .fakes import …`.
  - The handler test reloads `list_card_transactions_lambda.delivery.handler`.
- **`conftest.py`:** `_ASSET_ROOT` points to `gateway/tools/list_card_transactions`. Its docstring names the new package.
- **`test_query_contracts.py`:** `QUERIES_DIR` points to `gateway/tools/list_card_transactions/list_card_transactions_lambda/queries/postgresql`.

### 3.3 Text that assumed a shared package
Only docstrings, comments and TODO text change. The code stays the same, and `TODO(ledgerlens): Rn` tags keep their IDs.

| File | Change |
|---|---|
| `delivery/handler.py` | Module docstring: new handler string; the `tool_spec.json` path is `gateway/tools/list_card_transactions/tool_spec.json`. |
| `delivery/dependencies/dependencies_builder.py` | Module docstring: drop "Adding a tool means adding one function to the use cases block. A tool builds only its own graph…". Say the builder serves this tool only. `build_query_provider`'s docstring drops "so every tool in the container shares one provider per engine"; the `@cache` stays (the provider is built once per container). |
| `requirements.txt` | Header: "Runtime dependencies for the list_card_transactions Lambda." in place of "for every LedgerLens tool Lambda (shared asset)". |
| `list_card_transactions_lambda/__init__.py` | "LedgerLens bank assistant tools: shared hexagonal core for every tool Lambda." becomes "The list_card_transactions Gateway tool Lambda, in hexagonal layers." |
| `utils/__init__.py` | "Shared technical helpers…" becomes "Technical helpers used by infrastructure and delivery." |
| `application/use_cases/__init__.py` | "Use cases: one class per tool." becomes "Use case of the list_card_transactions tool." |
| `delivery/dependencies/__init__.py` | "…builds every LedgerLens object." becomes "…builds every object of this tool." |
| `delivery/settings.py` | `DatabaseSettings` docstring: "Settings shared by every tool Lambda, whatever the engine." becomes "Database settings that don't depend on the engine." |

These are left alone, because they don't refer to sharing between tools: "the only shared state" in `dependencies_builder` (state shared between warm invocations) and "Connection lifecycle shared by psycopg-based connectors" in `connectors/base.py`.

### 3.4 Historical documents
- `docs/superpowers/specs/2026-09-29-list-card-transactions-lambda-design.md` and `2026-09-30-dsql-engine-design.md` each get one line under their header: "**Updated 2026-10-01:** the code now lives in `gateway/tools/list_card_transactions/list_card_transactions_lambda/`. See [2026-10-01-self-contained-tool-folders-design.md](2026-10-01-self-contained-tool-folders-design.md)."
- The matching plans in `docs/superpowers/plans/` are left as they are; they record what was done.
- `docs/LEDGERLENS_PRODUCT_DESIGN.md` doesn't mention the shared package, so it doesn't change here.

---

## 4. Testing

There is no new behaviour, so there are no new tests. The existing suite is the safety net:

1. Before the move, record the baseline: `$PY -m pytest tests/unit/ledgerlens_tools -q` gives 248 passed.
2. After the move, `$PY -m pytest tests/unit/list_card_transactions -q` gives 248 passed.
3. `$PY -m pytest tests/unit -q` passes as a whole, including `test_mcp_registry.py`, so the new test package doesn't disturb the other unit tests.
4. `ruff format --check` and `ruff check` are clean on both new folders.
5. `grep -rn "ledgerlens\." gateway tests --include=*.py` finds nothing (the `TODO(ledgerlens)` tags have no dot after the name, so they don't match). `grep -rn "ledgerlens_tools" . --exclude-dir=docs` finds nothing (ignoring `node_modules` and `.git`).

---

## 5. Risks

| # | Risk | Handling |
|---|---|---|
| S1 | **Moving without `__init__.py` in the test folder.** Two tools' tests would clash on basenames such as `test_errors.py` once `list_credit_cards` lands. | The test folder becomes a package now, before the second tool exists. |
| S2 | **Test package name equals the production package name.** It would shadow the production package. | The test package drops the `_lambda` suffix (§2). |
| S3 | **A stale `__pycache__`** from the old location gets imported. | Remove the old folders entirely, including `__pycache__`. |
| S4 | **Copies drift apart** once more tools exist. A fix in one copy is missed in another. | Accepted (§1). Each later tool spec lists which files it copied and from where. |
