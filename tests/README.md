# Python tests

Unit tests for the Gateway tool Lambdas, the agent's helpers, the pre-token and Cedar policy Lambdas, the data pipeline, the eval harness and the deploy scripts. They need no AWS account or database.

## Run

From the repo root, with Python 3.11+:

```bash
python -m pip install pytest -r agent/ledgerlens/requirements.txt -r data_load/requirements.txt
python -m pytest                          # all 2,696 tests, about a minute
python -m pytest tests/unit/open_claim    # one folder
```

`requirements-dev.txt` doesn't install (its `aws-cdk-lib` and `constructs` pins conflict), so use the command above.

## Layout

```
tests/
├── conftest.py, pytest.ini   # pytest setup; testpaths come from pyproject.toml
├── integration/              # empty: no integration tests yet
└── unit/
    ├── <tool>/               # one folder per Gateway tool; its conftest.py puts
    │                         #   gateway/tools/<tool> on sys.path, fakes.py holds the test doubles
    ├── cedar_policy/         # the Cedar policy custom resource
    ├── pretoken_v3/          # the customer_id claim
    ├── eval_harness/         # evals/
    ├── test_*.py             # agent helpers, data_load stages, deploy scripts
    └── *_fixtures.py, data_load_s3.py   # shared fakes for the data pipeline tests
```

How imports work, the test strategy, what each file covers, and the frontend and CDK suites: [docs/testing.md](../docs/testing.md).
