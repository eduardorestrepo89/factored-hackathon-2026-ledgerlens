"""Unit tests for evals/cw_dashboard.py (pure builders; fake CloudWatch)."""

import datetime as dt
import json

from evals import cw_dashboard

NOW = dt.datetime(2026, 10, 5, 9, 0, tzinfo=dt.timezone.utc)
CFG = ("deepseek.v3.2", "v10")
SUMMARY = {"model": "deepseek.v3.2", "prompt": "v10", "cases": 10, "k": 3, "pass1": 0.6, "passk": 4,
           "passk_ci": (0.17, 0.69), "unsafe_cases": 0, "unsafe_bound": 0.3, "harness_errors": 1,
           "latency_median_s": 12.5, "tokens_in_mean": 9000.0, "tokens_out_mean": 200.0, "cost_total": 0.42,
           "aws": {"Builtin.GoalSuccessRate": {"mean": 0.75, "agreement": 0.8, "n": 5}}}
FAMILY = {"sessions": 30, "check_failures": {"no_write_result": {"failures": 1, "sessions": 3, "first": 1, "rate": 33.3}},
          "pass_rate_by_evaluation": {"E1": 50.0, "E2": 0.0}, "tool_calls": 10,
          "tool_call_defects": {"bare_tool_name": 1, "array_sent_as_string": 0, "enum_outside_spec": 0, "null_argument": 0},
          "tool_call_validity": 90.0, "tool_executed": 8, "tool_errors": {"unknown_tool": 1, "tool_error": 0, "other": 0},
          "tool_exec_error_rate": 12.5, "tool_calls_per_session": 0.33, "repeat_tool_call_rate": None,
          "local_trajectory_match": 66.7, "proposals": 5,
          "unexpected_by_cause": {"reproposal_after_no": 1, "retry_after_unknown_tool": 1, "unrequested": 0},
          "proposal_precision": 60.0, "proposal_recall": 75.0, "reproposal_after_no_rate": 10.0,
          "handoff_reason_accuracy": 50.0, "handoff_reason_invalid": 1, "yes_unknown_tool_rate": 60.0,
          "typed_yes": {"opportunities": 3, "executed": 0}, "pass_at_k": 80.0, "flaky_cases": 4, "always_fail_cases": 2,
          "aws": {"Builtin.GoalSuccessRate": {"applicable": 30, "scored": 18, "scored_share": 60.0, "span_parse_errors": 12}},
          "harness_retries": 0, "request_latencies": {"customer": [3.0, 5.0], "button": [1.0]},
          "session_latencies": [4.0, 5.0], "tokens_in_per_session": 13000.0, "tokens_out_per_session": 270.0,
          "cost_total": 0.42, "cost_per_passing_trial": 0.023, "cost_per_passk_case": 0.105, "requests": 60,
          "guardrail_interventions": 0,
          "unsafe_hits": {"write_without_yes": 0, "foreign_customer_id": 0, "privacy_leak": 0, "pan_echo": 0},
          "unsafe_opportunities": {"write_without_yes": 21, "foreign_customer_id": 20, "privacy_leak": 60, "pan_echo": 60}}
LABELS = {CFG: "baseline-v10", ("deepseek.v3.2", "v11"): "v11"}
PROMPT_IDS = {CFG: "v10-0085ea98", ("deepseek.v3.2", "v11"): "v11-1234abcd"}
LIVE = {"gateway_id": "ledgerlens-bank-assistant-gateway-0emkqlikrv",
        "runtime_log_group": "/aws/bedrock-agentcore/runtimes/agent-ABC-DEFAULT",
        "tool_log_groups": ["/aws/lambda/ledgerlens-bank-assistant-list-credit-cards"],
        "handoff_log_group": "/aws/lambda/ledgerlens-bank-assistant-human-agent-hand-off"}


def data():
    return cw_dashboard.metric_data([SUMMARY], {CFG: FAMILY}, LABELS, PROMPT_IDS, NOW)


def pick(name, **dims):
    found = [d for d in data() if d["MetricName"] == name
             and all({x["Name"]: x["Value"] for x in d["Dimensions"]}.get(k) == v for k, v in dims.items())]
    assert len(found) == 1, (name, dims, len(found))
    return found[0]


def body():
    return cw_dashboard.dashboard_body([SUMMARY, {**SUMMARY, "prompt": "v11"}], {CFG: FAMILY}, "| Case |\n|---|",
                                       LABELS, PROMPT_IDS, LIVE)


def test_headline_metrics_keep_their_values_units_and_dimensions():
    d = pick("PassRate1", Run="baseline-v10")

    assert d["Value"] == 60.0 and d["Unit"] == "Percent"
    assert d["Dimensions"] == [{"Name": "Model", "Value": "deepseek.v3.2"},
                               {"Name": "Prompt", "Value": "v10-0085ea98"}, {"Name": "Run", "Value": "baseline-v10"}]
    assert pick("PassRateK", Run="baseline-v10")["Value"] == 40.0
    assert pick("AwsGoalSuccess")["Value"] == 75.0


def test_data_is_stamped_at_publish_time_not_at_the_run_start():
    """CloudWatch shows data stamped hours back late or drops it after two weeks."""
    assert all(d["Timestamp"] == NOW for d in data())


def test_family_metrics_are_published_with_one_extra_dimension_each():
    assert pick("CheckFailureRate", Check="no_write_result")["Value"] == 33.3
    assert pick("PassRate1ByEvaluation", Evaluation="E2")["Value"] == 0.0
    assert pick("ToolCallDefects", DefectType="bare_tool_name")["Value"] == 1
    assert pick("UnexpectedProposals", Cause="retry_after_unknown_tool")["Value"] == 1
    assert pick("AwsScoredShare", Evaluator="GoalSuccessRate")["Value"] == 60.0
    assert pick("UnsafeOpportunities", UnsafeType="write_without_yes")["Value"] == 21
    assert pick("YesUnknownToolRate")["Value"] == 60.0
    assert pick("SafeResolutionCases")["Value"] == 4 and pick("CasesTotal")["Value"] == 10
    assert pick("PassRateKLower")["Value"] == 17.0


def test_a_metric_that_could_not_be_measured_publishes_no_datum():
    names = {d["MetricName"] for d in data()}

    assert "RepeatToolCallRate" not in names and "AwsTrajectory" not in names


def test_latency_is_sent_as_raw_values_so_cloudwatch_computes_percentiles():
    d = pick("RequestLatency", Kind="customer")

    assert d["Values"] == [3.0, 5.0] and d["Unit"] == "Seconds" and "Value" not in d
    assert pick("SessionLatency")["Values"] == [4.0, 5.0]


def test_a_run_less_trend_copy_gives_one_line_across_prompt_versions():
    trend = [d for d in data() if len(d["Dimensions"]) == 2]

    assert {d["MetricName"] for d in trend} == set(cw_dashboard.TREND_METRICS)
    assert all(d["Dimensions"] == [{"Name": "Model", "Value": "deepseek.v3.2"},
                                   {"Name": "Prompt", "Value": "v10-0085ea98"}] for d in trend)


def test_run_labels_and_prompt_ids_come_from_each_run_folder(tmp_path):
    for name, prompts in (("baseline-v10", {"v10": "0085ea98"}), ("v11", {"v11": "aaaa1111"}),
                          ("rerun-v11", {"v11": "bbbb2222"})):
        (tmp_path / name).mkdir()
        (tmp_path / name / "run.json").write_text(json.dumps({"models": ["m1"], "prompts": prompts}), encoding="utf-8")
    dirs = [tmp_path / "baseline-v10", tmp_path / "v11", tmp_path / "rerun-v11", tmp_path / "missing"]

    assert cw_dashboard.run_labels(dirs) == {("m1", "v10"): "baseline-v10", ("m1", "v11"): "rerun-v11"}
    assert cw_dashboard.prompt_ids(dirs) == {("m1", "v10"): "v10-0085ea98", ("m1", "v11"): "v11-bbbb2222"}


def widgets_titled(b, start):
    return [w for w in b["widgets"] if w["properties"].get("title", "").startswith(start)]


def test_the_dashboard_has_the_rows_from_the_research():
    b = body()
    titles = [w["properties"].get("title", "") for w in b["widgets"]]
    text = json.dumps(b, ensure_ascii=False)

    for start in ("Safe automated resolution", "Pass rate by evaluation", "Check failure rate",
                  "Proposal precision", "Tool-call validity", "pass@k", "Request latency", "Unsafe hits",
                  "Cedar AuthorizeAction denies", "Bedrock tokens per model", "Guardrail interventions",
                  "Consent clicks", "History"):
        assert any(t.startswith(start) for t in titles), start
    assert "SpanEventParsingException" in text and len(text.encode("utf-8")) < 1_000_000


def test_dimensioned_families_are_charted_with_search_over_the_published_runs():
    [w] = widgets_titled(body(), "Check failure rate")
    [expr] = [m[0]["expression"] for m in w["properties"]["metrics"]]

    assert 'MetricName="CheckFailureRate"' in expr and "{LedgerLens/Eval,Check,Model,Prompt,Run}" in expr
    assert 'Run="baseline-v10"' in expr and 'Run="v11"' in expr


def test_live_rows_use_the_current_gateway_and_the_runtime_log_stream_only():
    b = body()
    [cedar] = widgets_titled(b, "Cedar AuthorizeAction denies")
    [consent] = widgets_titled(b, "Consent clicks")

    assert "ledgerlens-bank-assistant-gateway-0emkqlikrv" in json.dumps(cedar)
    assert consent["type"] == "log"
    assert consent["properties"]["query"].startswith("SOURCE '/aws/bedrock-agentcore/runtimes/agent-ABC-DEFAULT'")
    assert "runtime-logs" in consent["properties"]["query"]  # each line is also in otel-rt-logs


def test_without_live_targets_the_live_rows_are_left_out():
    b = cw_dashboard.dashboard_body([SUMMARY], {CFG: FAMILY}, "| Case |", LABELS, PROMPT_IDS, None)

    assert not widgets_titled(b, "Consent clicks") and widgets_titled(b, "Safe automated resolution")


def test_publish_sends_metric_data_in_chunks_and_puts_the_dashboard():
    calls = []

    class FakeCloudWatch:
        def put_metric_data(self, **kw):
            calls.append(("metrics", kw["Namespace"], len(kw["MetricData"])))

        def put_dashboard(self, **kw):
            calls.append(("dashboard", kw["DashboardName"], json.loads(kw["DashboardBody"])["widgets"][0]["type"]))
            return {"DashboardValidationMessages": []}

    payload = [{"MetricName": f"m{i}"} for i in range(45)]
    cw_dashboard.publish(FakeCloudWatch(), payload, {"widgets": [{"type": "text"}]})

    assert calls == [("metrics", "LedgerLens/Eval", 20), ("metrics", "LedgerLens/Eval", 20),
                     ("metrics", "LedgerLens/Eval", 5), ("dashboard", "LedgerLens-Evaluation", "text")]
