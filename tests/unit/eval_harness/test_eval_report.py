"""Unit tests for evals/report.py."""

import json

import pytest

from evals import report


@pytest.mark.parametrize("k, n, lo, hi", [(9, 10, 0.596, 0.982), (10, 10, 0.722, 1.0), (27, 30, 0.744, 0.965)])
def test_wilson_matches_the_research_table(k, n, lo, hi):
    got = report.wilson(k, n)

    assert got[0] == pytest.approx(lo, abs=0.001) and got[1] == pytest.approx(hi, abs=0.001)


def test_wilson_of_nothing_is_zero():
    assert report.wilson(0, 0) == (0.0, 0.0)


def row(case, run, passed, prompt="v10", model="m", unsafe=(), failures=(), status="graded", aws=None):
    return {"case": case, "model": model, "prompt": prompt, "run": run, "status": status,
            "passed": passed, "unsafe": list(unsafe), "failures": list(failures),
            "first_failure": failures[0]["check"] if failures else None, "session_id": f"s-{case}-{run}",
            "tokens_in": 100, "tokens_out": 10, "latency_s": 2.0, "cost": 0.01, "aws": aws or {}}


ROWS = [row("A", r, True) for r in (1, 2, 3)] + [
    row("B", 1, True), row("B", 2, False, failures=[{"check": "c1", "reason": "x"}]),
    row("B", 3, True, unsafe=["privacy_leak"]), row("C", 1, False, status="harness_error")]


def test_summarize_counts_pass_rates_unsafe_and_harness_errors():
    [summary] = report.summarize(ROWS)

    assert summary["cases"] == 2
    assert summary["pass1"] == pytest.approx((1.0 + 2 / 3) / 2)
    assert summary["passk"] == 1 and summary["k"] == 3
    assert summary["unsafe_cases"] == 1
    assert summary["harness_errors"] == 1


def test_aws_agreement_compares_scores_with_the_local_verdict():
    rows = [row("A", 1, True, aws={"Builtin.GoalSuccessRate": 1.0}),
            row("A", 2, False, failures=[{"check": "c", "reason": "r"}], aws={"Builtin.GoalSuccessRate": 1.0})]

    [summary] = report.summarize(rows)

    assert summary["aws"]["Builtin.GoalSuccessRate"] == {"mean": 1.0, "agreement": 0.5, "n": 2}


def test_grid_marks_each_run():
    g = report.grid(ROWS)

    assert g["A"][("m", "v10")] == "✓✓✓"
    assert g["B"][("m", "v10")] == "✓✗✓"
    assert g["C"][("m", "v10")] == "E"


def test_regressions_are_checks_passing_on_v10_and_failing_on_v11():
    rows = [row("A", 1, True), row("A", 1, False, prompt="v11", failures=[{"check": "c9", "reason": "r"}])]

    assert report.regressions(rows, "v10", "v11") == [("m", "A", "c9")]


def test_write_report_writes_markdown_csv_and_grades(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    session = {"key": {"case": "E5a", "model": "deepseek.v3.2", "prompt": "v10", "run": 1},
               "session_id": "ll-x", "case_id": "E5a", "persona": "P03", "customer_id": "CLI-70U0WJ1NH1MN",
               "requests": [{"user_turn": 1, "kind": "say", "input": "", "text": "No puedo compartir eso.",
                             "tool_calls": [], "tool_results": [], "confirmations": [], "answers": [],
                             "usage": {"input": 1000, "output": 50}, "stop_reasons": [], "error": None,
                             "throttled": False, "unparsed": 0, "latency_s": 3.0}],
               "unexpected_confirmations": [], "missing_confirmations": [], "harness_error": None}
    (run_dir / "sessions.jsonl").write_text(json.dumps(session) + "\n", encoding="utf-8")

    out = report.write_report([run_dir], tmp_path / "report")

    text = out.read_text(encoding="utf-8")
    assert "deepseek.v3.2" in text and "E5a" in text and "pass^1" in text
    assert (tmp_path / "report" / "report.csv").exists()
    assert json.loads((tmp_path / "report" / "grades.jsonl").read_text(encoding="utf-8").splitlines()[0])["passed"]
