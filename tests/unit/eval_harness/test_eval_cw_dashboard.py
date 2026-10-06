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


def series(widget):
    """The explicit LedgerLens/Eval series of a metric widget: (metric, dimensions, options)."""
    out = []
    for row in widget["properties"]["metrics"]:
        if row[0] == cw_dashboard.NAMESPACE:
            out.append((row[1], dict(zip(row[2:-1:2], row[3:-1:2])), row[-1]))
    return out


def test_the_dashboard_reads_as_numbered_sections_under_one_header():
    b = body()
    texts = [w["properties"]["markdown"] for w in b["widgets"] if w["type"] == "text"]
    headings = [t for t in texts if t.startswith("### ")]

    assert "SpanEventParsingException" in texts[0] and b["widgets"][0]["y"] == 0
    assert [h[4] for h in headings] == list("12345678")
    assert all(w["properties"].get("title") for w in b["widgets"] if w["type"] != "text")
    assert len(json.dumps(b, ensure_ascii=False).encode("utf-8")) < 1_000_000


def test_widgets_tile_the_24_column_grid_without_overlap():
    taken = set()
    for w in body()["widgets"]:
        assert 0 <= w["x"] and w["x"] + w["width"] <= 24
        cells = {(x, y) for x in range(w["x"], w["x"] + w["width"]) for y in range(w["y"], w["y"] + w["height"])}
        assert not cells & taken, w["properties"].get("title")
        taken |= cells


def test_series_carry_short_labels_and_the_model_colour_with_older_prompts_lighter():
    [w] = widgets_titled(body(), "pass^1: % of runs that pass")
    [(_, v10_dims, v10), (_, _, v11)] = series(w)

    assert [v10["label"], v11["label"]] == ["DeepSeek V3.2 · v10", "DeepSeek V3.2 · v11"]
    assert v11["color"] == "#2a78d6" and v10["color"] != v11["color"]
    assert v10_dims == {"Model": "deepseek.v3.2", "Prompt": "v10-0085ea98", "Run": "baseline-v10"}
    for widget in body()["widgets"]:
        for row in widget["properties"].get("metrics", []):
            assert "deepseek.v3.2" not in row[-1].get("label", ""), widget["properties"]["title"]


def test_percent_charts_have_a_fixed_0_to_100_axis_and_the_80_percent_target():
    b = body()
    for start in ("Safe resolution", "pass^1: % of runs", "pass^3 by prompt version", "pass^1 by prompt version"):
        [w] = widgets_titled(b, start)
        props = w["properties"]
        assert props["yAxis"]["left"]["min"] == 0 and props["yAxis"]["left"]["max"] == 100, start
        assert props["annotations"]["horizontal"][0]["value"] == 80, start


def test_bars_aggregate_the_range_and_only_the_history_has_a_time_axis():
    """A bar chart without setPeriodToTimeRange draws one time bucket and drops configs published in
    another; republished values are identical, so the range aggregate equals the latest publish."""
    for w in body()["widgets"]:
        props = w["properties"]
        if w["type"] == "metric" and series(w) and not props["title"].startswith("Live"):
            assert bool(props.get("setPeriodToTimeRange")) == (props["view"] == "bar"), props["title"]
            assert props["view"] != "timeSeries" or "by prompt version" in props["title"], props["title"]


def test_history_holds_the_run_less_trend_copy_flat_between_publishes():
    [w] = widgets_titled(body(), "pass^3 by prompt version")
    hidden = series(w)
    exprs = [row[0]["expression"] for row in w["properties"]["metrics"] if "expression" in row[0]]

    assert all("Run" not in dims and opts["visible"] is False for _, dims, opts in hidden)
    assert exprs == ["FILL(m0, REPEAT)", "FILL(m1, REPEAT)"]


def test_the_drill_down_variable_swaps_one_unquoted_filter_in_sections_3_and_4_only():
    b = body()
    [var] = b["variables"]
    holders = [w["properties"].get("title", "") for w in b["widgets"] if var["pattern"] in json.dumps(w)]

    assert var["type"] == "pattern" and var["defaultValue"] == var["pattern"]
    assert [v["label"] for v in var["values"]] == ["DeepSeek V3.2 · v10", "DeepSeek V3.2 · v11"]
    assert var["pattern"] == "Run=v11 Prompt=v11-1234abcd Model=deepseek.v3.2"  # newest prompt, no quotes
    assert holders == ["Conversation and tool quality (%)",
                       "Failing checks: % of sessions whose case runs the check (top 10)",
                       "Defective tool calls, tool errors, unexpected proposals (count)",
                       "Scripted unsafe detectors: hits vs chances, typed consent (count)"]


def test_the_drill_down_defaults_to_the_production_model():
    haiku = {**SUMMARY, "model": cw_dashboard.PRODUCTION_MODEL}
    b = cw_dashboard.dashboard_body([SUMMARY, haiku], {CFG: FAMILY}, "| Case |", LABELS, PROMPT_IDS, None)

    assert b["variables"][0]["defaultValue"].endswith("Model=" + cw_dashboard.PRODUCTION_MODEL)


def test_failing_checks_are_sorted_from_a_search_over_the_drill_down_config():
    [w] = widgets_titled(body(), "Failing checks")
    search, top = (row[0]["expression"] for row in w["properties"]["metrics"])

    assert "{LedgerLens/Eval,Check,Model,Prompt,Run}" in search and 'MetricName="CheckFailureRate"' in search
    assert top == "SORT(e0, MAX, DESC, 10)" and w["properties"]["view"] == "table"


def test_live_rows_use_the_current_gateway_and_the_runtime_log_stream_only():
    b = body()
    [guards] = widgets_titled(b, "Live guards")
    [decisions] = widgets_titled(b, "Customer decisions")
    [traffic] = widgets_titled(b, "Sessions and turns")

    assert "ledgerlens-bank-assistant-gateway-0emkqlikrv" in json.dumps(guards)
    assert guards["properties"]["sparkline"] and guards["properties"]["setPeriodToTimeRange"]
    # Converse calls publish interventions per guardrail ARN; Operation=ApplyGuardrail is another API.
    assert "{AWS/Bedrock/Guardrails,GuardrailArn,GuardrailVersion}" in json.dumps(guards)
    assert "ApplyGuardrail" not in json.dumps(guards)
    assert decisions["type"] == "log"
    assert decisions["properties"]["query"].startswith("SOURCE '/aws/bedrock-agentcore/runtimes/agent-ABC-DEFAULT'")
    assert "runtime-logs" in decisions["properties"]["query"]  # each line is also in otel-rt-logs
    assert 'replace(model, "deepseek.v3.2", "DeepSeek V3.2")' in traffic["properties"]["query"]
    assert sum(w["type"] == "log" for w in b["widgets"]) == 3


def test_without_live_targets_the_live_rows_are_left_out():
    b = cw_dashboard.dashboard_body([SUMMARY], {CFG: FAMILY}, "| Case |", LABELS, PROMPT_IDS, None)
    titles = [w["properties"].get("title", "") for w in b["widgets"]]

    assert widgets_titled(b, "Safe resolution") and not any(t.startswith("Live") for t in titles)
    assert not any(w["type"] == "log" for w in b["widgets"])
    assert not any("### 7" in w["properties"].get("markdown", "") for w in b["widgets"])


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
