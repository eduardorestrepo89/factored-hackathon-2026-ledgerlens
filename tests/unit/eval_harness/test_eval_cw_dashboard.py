"""Unit tests for evals/cw_dashboard.py (pure builders; fake CloudWatch)."""

import datetime as dt
import json

from evals import cw_dashboard

NOW = dt.datetime(2026, 10, 5, 9, 0, tzinfo=dt.timezone.utc)
SUMMARY = {"model": "deepseek.v3.2", "prompt": "v10", "cases": 10, "k": 3, "pass1": 0.6, "passk": 4,
           "passk_ci": (0.17, 0.69), "unsafe_cases": 0, "unsafe_bound": 0.3, "harness_errors": 1,
           "latency_median_s": 12.5, "tokens_in_mean": 9000.0, "tokens_out_mean": 200.0, "cost_total": 0.42,
           "aws": {"Builtin.GoalSuccessRate": {"mean": 0.75, "agreement": 0.8, "n": 5}}}
LABELS = {("deepseek.v3.2", "v10"): "baseline-v10", ("deepseek.v3.2", "v11"): "v11"}


def datum(data, name):
    [d] = [d for d in data if d["MetricName"] == name]
    return d


def test_metric_data_has_one_datum_per_metric_with_model_prompt_and_run():
    data = cw_dashboard.metric_data([SUMMARY], LABELS, NOW)

    assert datum(data, "PassRate1")["Value"] == 60.0 and datum(data, "PassRate1")["Unit"] == "Percent"
    assert datum(data, "PassRateK")["Value"] == 40.0
    assert datum(data, "UnsafeCases")["Value"] == 0 and datum(data, "UnsafeCases")["Unit"] == "Count"
    assert datum(data, "HarnessErrors")["Value"] == 1
    assert datum(data, "MedianLatencySeconds")["Unit"] == "Seconds"
    assert datum(data, "CostUSD")["Value"] == 0.42
    assert datum(data, "AwsGoalSuccess")["Value"] == 75.0
    assert all(d["Dimensions"] == [{"Name": "Model", "Value": "deepseek.v3.2"},
                                   {"Name": "Prompt", "Value": "v10"},
                                   {"Name": "Run", "Value": "baseline-v10"}] for d in data)


def test_data_is_stamped_at_publish_time_not_at_the_run_start():
    """CloudWatch shows data stamped hours back late or drops it after two weeks."""
    data = cw_dashboard.metric_data([SUMMARY], LABELS, NOW)

    assert all(d["Timestamp"] == NOW for d in data)


def test_a_missing_aws_score_publishes_no_datum():
    data = cw_dashboard.metric_data([SUMMARY], LABELS, NOW)

    assert "AwsTrajectory" not in {d["MetricName"] for d in data}


def test_run_labels_name_each_config_by_the_run_folder_that_recorded_it(tmp_path):
    for name, prompts in (("baseline-v10", ["v10"]), ("v11", ["v11"]), ("rerun-v11", ["v11"])):
        (tmp_path / name).mkdir()
        (tmp_path / name / "run.json").write_text(json.dumps(
            {"models": ["m1", "m2"], "prompts": {p: "abcd1234" for p in prompts}}), encoding="utf-8")

    labels = cw_dashboard.run_labels([tmp_path / "baseline-v10", tmp_path / "v11",
                                      tmp_path / "rerun-v11", tmp_path / "missing"])

    assert labels == {("m1", "v10"): "baseline-v10", ("m2", "v10"): "baseline-v10",
                      ("m1", "v11"): "rerun-v11", ("m2", "v11"): "rerun-v11"}


def test_dashboard_body_charts_every_config_with_its_own_run_and_carries_the_limitation_and_grid():
    body = cw_dashboard.dashboard_body([SUMMARY, {**SUMMARY, "prompt": "v11"}],
                                       "| Case | x |\n|---|---|\n| E1a | ✓✓✗ |", LABELS)

    text = json.dumps(body, ensure_ascii=False)
    metrics = [w for w in body["widgets"] if w["type"] == "metric"]
    charted = {m[1] for w in metrics for m in w["properties"]["metrics"]}
    assert {"PassRate1", "PassRateK", "UnsafeCases", "HarnessErrors", "AwsGoalSuccess",
            "AwsTrajectory", "MedianLatencySeconds", "CostUSD"} <= charted
    pass_rates = next(w for w in metrics if w["properties"]["title"].startswith("Local pass rate"))
    assert len(pass_rates["properties"]["metrics"]) == 4  # 2 metrics x 2 configs
    assert {tuple(m[6:8]) for m in pass_rates["properties"]["metrics"]} == {("Run", "baseline-v10"), ("Run", "v11")}
    assert "SpanEventParsingException" in text and "E1a | ✓✓✗" in text
    assert len(text.encode("utf-8")) < 1_000_000


def test_publish_sends_metric_data_in_chunks_and_puts_the_dashboard():
    calls = []

    class FakeCloudWatch:
        def put_metric_data(self, **kw):
            calls.append(("metrics", kw["Namespace"], len(kw["MetricData"])))

        def put_dashboard(self, **kw):
            calls.append(("dashboard", kw["DashboardName"], json.loads(kw["DashboardBody"])["widgets"][0]["type"]))

    data = [{"MetricName": f"m{i}"} for i in range(45)]
    cw_dashboard.publish(FakeCloudWatch(), data, {"widgets": [{"type": "text"}]})

    assert calls == [("metrics", "LedgerLens/Eval", 20), ("metrics", "LedgerLens/Eval", 20),
                     ("metrics", "LedgerLens/Eval", 5), ("dashboard", "LedgerLens-Evaluation", "text")]
