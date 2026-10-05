"""Unit tests for evals/aws_eval.py (fake SDK)."""

from types import SimpleNamespace

from evals import aws_eval

CASE = {"id": "E1a", "assertions": ["A"], "expected_tools": ["gateway_x___block_credit_card"]}
SESSION = {"key": {"case": "E1a"}, "session_id": "ll-1"}


def refs(**kwargs):
    return kwargs


def test_trajectory_runs_only_when_tools_are_expected():
    assert aws_eval.evaluator_ids(CASE) == [aws_eval.TRAJECTORY, aws_eval.GOAL]
    assert aws_eval.evaluator_ids({**CASE, "expected_tools": []}) == [aws_eval.GOAL]


def test_evaluate_session_passes_ground_truth_and_keeps_results():
    seen = {}

    def run(**kwargs):
        seen.update(kwargs)
        return [{"evaluatorId": aws_eval.GOAL, "value": 1.0, "label": "PASS", "explanation": "ok"},
                SimpleNamespace(evaluatorId=aws_eval.TRAJECTORY, value=0.0, label="FAIL",
                                explanation="order", errorCode=None)]

    out = aws_eval.evaluate_session(SESSION, CASE, run, refs, "agent-1")

    assert seen["agent_id"] == "agent-1" and seen["session_id"] == "ll-1"
    assert seen["reference_inputs"] == {"assertions": ["A"],
                                        "expected_trajectory": ["gateway_x___block_credit_card"]}
    assert [r["value"] for r in out["results"]] == [1.0, 0.0]
    assert out["error"] is None


def test_no_expected_trajectory_is_sent_without_tools():
    seen = {}

    aws_eval.evaluate_session(SESSION, {**CASE, "expected_tools": []},
                              lambda **kw: seen.update(kw) or [], refs, "a")

    assert seen["reference_inputs"] == {"assertions": ["A"]}


def test_a_failing_call_is_recorded_not_raised():
    def run(**kwargs):
        raise RuntimeError("no spans")

    out = aws_eval.evaluate_session(SESSION, CASE, run, refs, "a")

    assert out["error"] == "RuntimeError: no spans" and out["results"] == []


def test_no_results_means_the_spans_are_not_there_yet():
    out = aws_eval.evaluate_session(SESSION, CASE, lambda **kw: [], refs, "a")

    assert out["error"] == aws_eval.NO_RESULTS


def test_only_successful_scores_count_as_done(tmp_path):
    import json

    path = tmp_path / "aws_eval.jsonl"
    path.write_text(json.dumps({"session_id": "a", "error": None, "results": [{"value": 1}]}) + "\n"
                    + json.dumps({"session_id": "b", "error": "no spans", "results": []}) + "\n",
                    encoding="utf-8")

    assert aws_eval.evaluated_ids(path) == {"a"}
    assert aws_eval.evaluated_ids(tmp_path / "missing.jsonl") == set()
