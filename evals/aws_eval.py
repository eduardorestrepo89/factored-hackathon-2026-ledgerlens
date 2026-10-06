"""Score recorded sessions with AgentCore Evaluations (spec section 6).

  AWS_PROFILE=ledgerlens evals/.venv/Scripts/python -m evals.aws_eval evals/results/baseline-v10

Needs CloudWatch Transaction Search on. Run it at least 180 s after the run's last
session: AgentCore reads the spans from CloudWatch, and ingestion takes 2-5
minutes. The scores corroborate the local verdict; they never override it.
"""

import argparse
import json
import os
import time
from pathlib import Path

from evals import config
from evals.cases import load_cases

TRAJECTORY = "Builtin.TrajectoryInOrderMatch"
GOAL = "Builtin.GoalSuccessRate"
INGESTION_WAIT_S = 300  # AWS: 2-5 minutes for CloudWatch to ingest spans
NO_RESULTS = "no evaluation results (spans not ingested yet?)"
_FIELDS = ("evaluatorId", "value", "label", "explanation", "errorCode")


def evaluator_ids(case: dict) -> list[str]:
    return ([TRAJECTORY] if case["expected_tools"] else []) + [GOAL]


def _field(item, name):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def evaluate_session(session: dict, case: dict, run, make_refs, agent_id: str) -> dict:
    """run = EvaluationClient.run; make_refs = ReferenceInputs (injected for tests)."""
    out = {
        "key": session["key"],
        "session_id": session["session_id"],
        "results": [],
        "error": None,
    }
    refs = {"assertions": case["assertions"]}
    if case["expected_tools"]:
        refs["expected_trajectory"] = case["expected_tools"]
    try:
        items = run(
            evaluator_ids=evaluator_ids(case),
            agent_id=agent_id,
            session_id=session["session_id"],
            reference_inputs=make_refs(**refs),
        )
        out["results"] = [
            {name: _field(item, name) for name in _FIELDS} for item in items
        ]
        if not out[
            "results"
        ]:  # the SDK returns [] when it finds no spans; retry on a rerun
            out["error"] = NO_RESULTS
    except Exception as e:  # one failed session must not stop the rest
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def evaluated_ids(path: Path) -> set[str]:
    """Session ids already scored without an error (a rerun retries the rest)."""
    if not path.exists():
        return set()
    records = (
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return {r["session_id"] for r in records if not r.get("error")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Score a run with AgentCore Evaluations."
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    os.environ.setdefault("AWS_PROFILE", config.AWS_PROFILE)
    from bedrock_agentcore.evaluation import EvaluationClient, ReferenceInputs

    sessions_path = args.run_dir / "sessions.jsonl"
    wait = sessions_path.stat().st_mtime + INGESTION_WAIT_S - time.time()
    if wait > 0:
        print(f"waiting {wait:.0f} s for span ingestion")
        time.sleep(wait)
    agent_id = json.loads((args.run_dir / "run.json").read_text(encoding="utf-8"))[
        "agent_runtime_arn"
    ].split("/")[-1]
    cases = {c["id"]: c for c in load_cases()}
    out_path = args.run_dir / "aws_eval.jsonl"
    done = evaluated_ids(out_path)
    client = EvaluationClient(region_name=config.REGION)
    with out_path.open("a", encoding="utf-8") as f:
        for line in sessions_path.read_text(encoding="utf-8").splitlines():
            session = json.loads(line)
            if session["harness_error"] or session["session_id"] in done:
                continue
            result = evaluate_session(
                session,
                cases[session["case_id"]],
                client.run,
                ReferenceInputs,
                agent_id,
            )
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(
                session["session_id"],
                result["error"] or [r["value"] for r in result["results"]],
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
