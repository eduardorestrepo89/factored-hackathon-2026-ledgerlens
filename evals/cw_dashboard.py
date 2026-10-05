"""Publish evaluation results to CloudWatch: custom metrics and one dashboard.

  python -m evals.cw_dashboard evals/results/baseline-v10 evals/results/haiku-v10          # print only
  python -m evals.cw_dashboard evals/results/baseline-v10 evals/results/haiku-v10 --apply  # publish

The numbers come from evals.report and evals.metrics (the same grading), so the
dashboard matches report.md. Metrics: namespace LedgerLens/Eval, dimensions Model,
Prompt (name + content hash, the id the traces carry as prompt.version) and Run (the
run folder that recorded the config), plus at most one extra dimension per family.
Data is stamped at publish time. A Run-less copy of the headline metrics gives one
line per model across prompt versions. Layout: datathon/reports/LedgerLens dashboard metrics.md.
"""

import argparse
import datetime as dt
import json
from pathlib import Path

from evals import config, metrics, report
from evals.cases import load_cases

NAMESPACE = "LedgerLens/Eval"
DASHBOARD = "LedgerLens-Evaluation"
_CHUNK = 20
_MAX_VALUES = 150  # PutMetricData accepts at most 150 values per datum
_AWS_METRICS = {"Builtin.GoalSuccessRate": "AwsGoalSuccess", "Builtin.TrajectoryInOrderMatch": "AwsTrajectory"}
TREND_METRICS = ("PassRate1", "PassRateK", "ToolCallValidity", "ProposalPrecision", "CostPerPassKCaseUSD")
TOOL_SLUGS = ("list-credit-cards", "list-card-transactions", "get-session-context", "transaction-fraud-detection",
              "explain-transaction", "classify-call-type", "block-credit-card", "open-claim", "human-agent-hand-off")

HEADER = """# LedgerLens evaluation
Models × system prompts on scripted cases, graded **locally** from the agent's stream (evals/graders.py);
AgentCore Evaluations **corroborates** and never decides. The case is the unit: pass^1 = mean run success
per case, pass^k = cases whose runs all passed (Wilson 95% band), unsafe bound = 3/n cases (rule of three).
Every number rests on a 10-case suite × 3 runs: read them as counts with their n.

**AWS limitation:** every session with a Yes/No confirmation (a Strands interrupt) fails AgentCore
Evaluations with `SpanEventParsingException`, so the confirmation cases (E1a, E1b, E2b, E4a, E4b) carry
local grades only. Recheck after the Strands upgrade (HumanInTheLoop), see evals/README.md.

**Zero-by-design panels:** the agent and the tool Lambdas turn failures into normal responses, so Runtime
and Lambda error metrics stay near 0; the log rows count the real failures. Traces: CloudWatch → GenAI
Observability → Bedrock AgentCore → LedgerLensAgent (filter by `model.id` and `prompt.version`)."""


def run_labels(run_dirs: list[Path]) -> dict[tuple[str, str], str]:
    """(model, prompt) -> the run folder that recorded it; a later folder wins."""
    labels = {}
    for run_dir in run_dirs:
        path = run_dir / "run.json"
        if path.exists():
            run = json.loads(path.read_text(encoding="utf-8"))
            labels.update({(m, p): run_dir.name[:255] for m in run["models"] for p in run["prompts"]})
    return labels


def prompt_ids(run_dirs: list[Path]) -> dict[tuple[str, str], str]:
    """(model, prompt) -> name-hash, the id the agent's spans carry as prompt.version."""
    ids = {}
    for run_dir in run_dirs:
        path = run_dir / "run.json"
        if path.exists():
            run = json.loads(path.read_text(encoding="utf-8"))
            ids.update({(m, p): f"{p}-{h}" for m in run["models"] for p, h in run["prompts"].items()})
    return ids


def _simple(s: dict, f: dict) -> dict[str, tuple[float | None, str]]:
    """Per-config metrics without an extra dimension: name -> (value or None, unit)."""
    lo, hi = s["passk_ci"]
    values = {
        "PassRate1": (100 * s["pass1"], "Percent"),
        "PassRateK": (100 * s["passk"] / s["cases"] if s["cases"] else None, "Percent"),
        "PassRateKLower": (100 * lo, "Percent"),
        "PassRateKUpper": (100 * hi, "Percent"),
        "SafeResolutionCases": (s["passk"], "Count"),
        "CasesTotal": (s["cases"], "Count"),
        "UnsafeCases": (s["unsafe_cases"], "Count"),
        "UnsafeBound95": (100 * s["unsafe_bound"] if s["unsafe_bound"] else None, "Percent"),
        "HarnessErrors": (s["harness_errors"], "Count"),
        "MedianLatencySeconds": (s["latency_median_s"], "Seconds"),
        "CostUSD": (s["cost_total"], "None"),
    }
    for evaluator, name in _AWS_METRICS.items():
        if evaluator in s["aws"]:
            values[name] = (100 * s["aws"][evaluator]["mean"], "Percent")
    if f:
        values.update({
            "ToolCallValidity": (f["tool_call_validity"], "Percent"),
            "ToolExecErrorRate": (f["tool_exec_error_rate"], "Percent"),
            "ToolCallsPerSession": (f["tool_calls_per_session"], "None"),
            "RepeatToolCallRate": (f["repeat_tool_call_rate"], "Percent"),
            "LocalTrajectoryMatch": (f["local_trajectory_match"], "Percent"),
            "ProposalPrecision": (f["proposal_precision"], "Percent"),
            "ProposalRecall": (f["proposal_recall"], "Percent"),
            "ReproposalAfterNoRate": (f["reproposal_after_no_rate"], "Percent"),
            "HandoffReasonAccuracy": (f["handoff_reason_accuracy"], "Percent"),
            "HandoffReasonInvalid": (f["handoff_reason_invalid"], "Count"),
            "YesUnknownToolRate": (f["yes_unknown_tool_rate"], "Percent"),
            "TypedYesExecuted": (f["typed_yes"]["executed"], "Count"),
            "TypedYesOpportunities": (f["typed_yes"]["opportunities"], "Count"),
            "PassAtK": (f["pass_at_k"], "Percent"),
            "FlakyCases": (f["flaky_cases"], "Count"),
            "AlwaysFailCases": (f["always_fail_cases"], "Count"),
            "HarnessRetries": (f["harness_retries"], "Count"),
            "TokensInPerSession": (f["tokens_in_per_session"], "Count"),
            "TokensOutPerSession": (f["tokens_out_per_session"], "Count"),
            "CostPerPassingTrialUSD": (f["cost_per_passing_trial"], "None"),
            "CostPerPassKCaseUSD": (f["cost_per_passk_case"], "None"),
            "GuardrailInterventions": (f["guardrail_interventions"], "Count"),
            "GuardrailRate": (100 * f["guardrail_interventions"] / f["requests"] if f["requests"] else None, "Percent"),
        })
    return values


def _dimensioned(f: dict) -> list[tuple[str, str, str, float | None, str]]:
    """Per-config metrics with one extra dimension: (name, dim, dim value, value, unit)."""
    if not f:
        return []
    out = []
    for check, v in f["check_failures"].items():
        out += [("CheckFailureRate", "Check", check, v["rate"], "Percent"),
                ("CheckFailures", "Check", check, v["failures"], "Count"),
                ("FirstFailures", "Check", check, v["first"], "Count")]
    out += [("PassRate1ByEvaluation", "Evaluation", k, v, "Percent") for k, v in f["pass_rate_by_evaluation"].items()]
    out += [("ToolCallDefects", "DefectType", k, v, "Count") for k, v in f["tool_call_defects"].items()]
    out += [("ToolErrors", "ErrorType", k, v, "Count") for k, v in f["tool_errors"].items()]
    out += [("UnexpectedProposals", "Cause", k, v, "Count") for k, v in f["unexpected_by_cause"].items()]
    for evaluator, v in f["aws"].items():
        short = evaluator.removeprefix("Builtin.")
        out += [("AwsScoredShare", "Evaluator", short, v["scored_share"], "Percent"),
                ("AwsSpanParseErrors", "Evaluator", short, v["span_parse_errors"], "Count")]
    out += [("UnsafeHits", "UnsafeType", k, v, "Count") for k, v in f["unsafe_hits"].items()]
    out += [("UnsafeOpportunities", "UnsafeType", k, v, "Count") for k, v in f["unsafe_opportunities"].items()]
    return out


def metric_data(summaries: list[dict], fams: dict, labels: dict, prompts: dict, when: dt.datetime) -> list[dict]:
    """CloudWatch MetricData for every model × prompt, stamped `when` (publish time)."""
    data = []
    for s in summaries:
        cfg = (s["model"], s["prompt"])
        f = fams.get(cfg, {})
        base = [{"Name": "Model", "Value": s["model"]}, {"Name": "Prompt", "Value": prompts.get(cfg, s["prompt"])}]
        run = base + [{"Name": "Run", "Value": labels.get(cfg, "unlabelled")}]
        simple = _simple(s, f)
        for name, (value, unit) in simple.items():
            if value is not None:
                data.append({"MetricName": name, "Dimensions": run, "Timestamp": when, "Value": value, "Unit": unit})
        for name in TREND_METRICS:
            value, unit = simple.get(name, (None, None))
            if value is not None:
                data.append({"MetricName": name, "Dimensions": base, "Timestamp": when, "Value": value, "Unit": unit})
        for name, dim, dim_value, value, unit in _dimensioned(f):
            if value is not None:
                data.append({"MetricName": name, "Dimensions": run + [{"Name": dim, "Value": dim_value}],
                             "Timestamp": when, "Value": value, "Unit": unit})
        if f:
            raw = [("RequestLatency", [{"Name": "Kind", "Value": kind}], values)
                   for kind, values in f["request_latencies"].items()]
            raw.append(("SessionLatency", [], f["session_latencies"]))
            for name, extra, values in raw:
                for i in range(0, len(values), _MAX_VALUES):
                    data.append({"MetricName": name, "Dimensions": run + extra, "Timestamp": when,
                                 "Values": values[i : i + _MAX_VALUES], "Unit": "Seconds"})
    return data


# --- dashboard ---------------------------------------------------------------------


def _series(summaries, metric_names, labels, prompts, stat=None):
    out = []
    for name in metric_names:
        for s in summaries:
            cfg = (s["model"], s["prompt"])
            options = {"label": f"{config.model_slug(s['model'])} {s['prompt']} {name}"}
            if stat:
                options["stat"] = stat
            out.append([NAMESPACE, name, "Model", s["model"], "Prompt", prompts.get(cfg, s["prompt"]),
                        "Run", labels.get(cfg, "unlabelled"), options])
    return out


def _search(metric: str, dim: str, runs: list[str], stat: str = "Maximum") -> list[list]:
    run_filter = " OR ".join(f'Run="{r}"' for r in runs)
    expr = f"SEARCH('{{{NAMESPACE},{dim},Model,Prompt,Run}} MetricName=\"{metric}\" ({run_filter})', '{stat}', 300)"
    return [[{"expression": expr, "id": f"e_{metric.lower()}", "label": ""}]]


def _metric(title, series, x, y, w=8, h=6, view="bar", stat="Maximum", period=300, whole_range=True):
    props = {"title": title, "view": view, "region": config.REGION, "stat": stat, "period": period,
             "metrics": series}
    if whole_range:
        props["setPeriodToTimeRange"] = True
    return {"type": "metric", "x": x, "y": y, "width": w, "height": h, "properties": props}


def _aws_search(title, expr, x, y, w=8, h=6, stat="Sum", period=3600):
    return _metric(title, [[{"expression": expr, "id": "e1", "label": ""}]], x, y, w, h,
                   view="timeSeries", stat=stat, period=period, whole_range=False)


def _logs(title, query, x, y, w=8, h=6):
    return {"type": "log", "x": x, "y": y, "width": w, "height": h,
            "properties": {"title": title, "query": query, "region": config.REGION, "view": "table"}}


def _text(markdown, y, h):
    return {"type": "text", "x": 0, "y": y, "width": 24, "height": h, "properties": {"markdown": markdown}}


def dashboard_body(summaries: list[dict], fams: dict, grid_markdown: str, labels: dict, prompts: dict,
                   live: dict | None) -> dict:
    """The dashboard JSON, top to bottom as in the research's layout."""
    runs = sorted(set(labels.values())) or ["unlabelled"]
    sv = lambda names: _series(summaries, names, labels, prompts)  # noqa: E731
    w = [_text(HEADER + "\n\nRuns: " + ", ".join(f"`{r}`" for r in runs), 0, 7)]
    # 1. business row
    w += [_metric("Safe automated resolution: cases passing every run, of n", sv(["SafeResolutionCases", "CasesTotal"]),
                  0, 7, view="singleValue"),
          _metric("Unsafe cases (and 95% bound %)", sv(["UnsafeCases", "UnsafeBound95"]), 8, 7, view="singleValue"),
          _metric("Cost per case passing every run (USD, model tokens)", sv(["CostPerPassKCaseUSD"]), 16, 7,
                  view="singleValue")]
    # 2. where it fails
    w += [_metric("Pass rate by evaluation (%)", _search("PassRate1ByEvaluation", "Evaluation", runs), 0, 13, w=12),
          _metric("Check failure rate (%) per check", _search("CheckFailureRate", "Check", runs), 12, 13, w=12)]
    # 3. confirmation quality
    w += [_metric("Proposal precision / recall (%)", sv(["ProposalPrecision", "ProposalRecall"]), 0, 19),
          _metric("Re-proposal after No, hand-off reason accuracy, Yes → Unknown tool (%)",
                  sv(["ReproposalAfterNoRate", "HandoffReasonAccuracy", "YesUnknownToolRate"]), 8, 19),
          _metric("Unexpected proposals by cause", _search("UnexpectedProposals", "Cause", runs), 16, 19)]
    # 4. tool quality
    w += [_metric("Tool-call validity and executed-tool error rate (%)", sv(["ToolCallValidity", "ToolExecErrorRate"]),
                  0, 25),
          _metric("Tool-call defects by type", _search("ToolCallDefects", "DefectType", runs), 8, 25),
          _metric("Trajectory match (%): local vs AgentCore", sv(["LocalTrajectoryMatch", "AwsTrajectory"]), 16, 25)]
    # 5. reliability
    w += [_metric("pass@k, pass^1, pass^k with Wilson band (%)",
                  sv(["PassAtK", "PassRate1", "PassRateK", "PassRateKLower", "PassRateKUpper"]), 0, 31, w=12),
          _metric("Flaky and always-failing cases; harness retries",
                  sv(["FlakyCases", "AlwaysFailCases", "HarnessRetries"]), 12, 31, w=6, view="singleValue"),
          _metric("AgentCore: share of sessions scored (%)", _search("AwsScoredShare", "Evaluator", runs), 18, 31, w=6)]
    # 6. efficiency
    w += [_metric("Request latency p50 / p95 (s)",
                  _series(summaries, ["RequestLatency"], labels, prompts, stat="p50")
                  + _series(summaries, ["RequestLatency"], labels, prompts, stat="p95"), 0, 37),
          _metric("Tokens per session (input, output)", sv(["TokensInPerSession", "TokensOutPerSession"]), 8, 37),
          _metric("Model cost (USD): run total, per passing trial", sv(["CostUSD", "CostPerPassingTrialUSD"]), 16, 37)]
    # 7. safety
    w += [_metric("Unsafe hits by type (opportunities in the next chart)", _search("UnsafeHits", "UnsafeType", runs),
                  0, 43),
          _metric("Unsafe opportunities by type", _search("UnsafeOpportunities", "UnsafeType", runs), 8, 43),
          _metric("Typed 'sí' that executed a write, of opportunities; guardrail interventions",
                  sv(["TypedYesExecuted", "TypedYesOpportunities", "GuardrailInterventions"]), 16, 43,
                  view="singleValue")]
    y = 49
    if live:
        rt, gw = live["runtime_log_group"], live["gateway_id"]
        runtime_stream = "filter @logStream like /runtime-logs/"  # each line is also in otel-rt-logs
        # 8. live operations (free AWS metrics)
        w += [_aws_search("Cedar AuthorizeAction denies (expected 0: a deny means a hook was bypassed)",
                          "SEARCH('{AWS/Bedrock-AgentCore,OperationName,TargetResource} MetricName=\"DenyDecisions\" "
                          f"OperationName=\"AuthorizeAction\" TargetResource=\"{gw}\"', 'Sum', 3600)", 0, y),
              _aws_search("Bedrock tokens per model (input and output)",
                          "SEARCH('{AWS/Bedrock,ModelId} (MetricName=\"InputTokenCount\" OR "
                          "MetricName=\"OutputTokenCount\")', 'Sum', 3600)", 8, y),
              _aws_search("Guardrail interventions by policy",
                          "SEARCH('{AWS/Bedrock/Guardrails,GuardrailPolicyType,Operation} "
                          "MetricName=\"InvocationsIntervened\"', 'Sum', 3600)", 16, y),
              _aws_search("Gateway tool invocations",
                          "SEARCH('{AWS/Bedrock-AgentCore,Method,Name,Operation,Protocol} "
                          "MetricName=\"Invocations\"', 'Sum', 3600)", 0, y + 6),
              _aws_search("Bedrock latency per model (ms)",
                          "SEARCH('{AWS/Bedrock,ModelId} MetricName=\"InvocationLatency\"', 'Average', 3600)",
                          8, y + 6, stat="Average"),
              _aws_search("Tool Lambda errors (timeouts and crashes only)",
                          "SEARCH('{AWS/Lambda,FunctionName} MetricName=\"Errors\" ledgerlens-', 'Sum', 3600)",
                          16, y + 6)]
        # 9. live behaviour (log lines the code already writes)
        tools = " | ".join(f"SOURCE '{g}'" for g in live["tool_log_groups"])
        w += [_logs("Sessions per model × prompt version",
                    f"SOURCE '{rt}' | {runtime_stream} and @message like /\\[PROMPT\\] version=/ "
                    "| parse @message /version=(?<version>\\S+) model=(?<model>\\S+) session=(?<session>\\S+)/ "
                    "| stats count_distinct(session) as sessions by model, version | sort sessions desc", 0, y + 12),
              _logs("Consent clicks per tool",
                    f"SOURCE '{rt}' | {runtime_stream} and @message like /\\[CONFIRM\\]/ "
                    "| parse @message /Customer (?<decision>approved|declined) (?<tool>\\w+)/ "
                    "| stats count(*) as clicks by tool, decision", 8, y + 12),
              _logs("Agent failures, customer-id overwrites, eval overrides",
                    f"SOURCE '{rt}' | {runtime_stream} "
                    "| parse @message /(?<signal>Agent run failed|\\[CUSTOMER-ID\\] Replaced|override ignored|"
                    "override rejected|\\[EVAL\\] override sub)/ | filter ispresent(signal) "
                    "| stats count(*) as n by signal", 16, y + 12),
              _logs("Handled tool errors per tool (Lambda metrics miss these)",
                    f"{tools} | filter @message like /returned an error|Unexpected error in/ "
                    "| stats count(*) as errors by @log", 0, y + 18, w=12),
              _logs("Hand-offs by priority",
                    f"SOURCE '{live['handoff_log_group']}' | filter @message like /queued HO-/ "
                    "| parse @message /priority=(?<priority>\\w+)/ | stats count(*) as handoffs by priority",
                    12, y + 18, w=12)]
        y += 24
    # 10. history
    trend = [[NAMESPACE, name, "Model", s["model"], "Prompt", prompts.get((s["model"], s["prompt"]), s["prompt"]),
              {"label": f"{config.model_slug(s['model'])} {s['prompt']} {name}"}]
             for name in ("PassRate1", "PassRateK") for s in summaries]
    w += [_metric("History: pass^1 and pass^k per model and prompt version, one point per publish (Run-less copy)",
                  trend, 0, y, w=24, view="timeSeries", period=3600, whole_range=False),
          _text("## Per-case grid (✓ pass, ✗ fail, E harness error)\n\n" + grid_markdown, y + 6, 9)]
    return {"start": "-P14D", "widgets": w}


def publish(cloudwatch, data: list[dict], body: dict) -> list:
    for i in range(0, len(data), _CHUNK):
        cloudwatch.put_metric_data(Namespace=NAMESPACE, MetricData=data[i : i + _CHUNK])
    response = cloudwatch.put_dashboard(DashboardName=DASHBOARD, DashboardBody=json.dumps(body, ensure_ascii=False))
    return (response or {}).get("DashboardValidationMessages", [])


def live_targets(session) -> dict:
    """The current gateway and log groups, read from the deployed stack."""
    outputs = config.stack_outputs(session)
    gateway = next((v for k, v in outputs.items() if k.endswith("GatewayId") or k == "GatewayId"), None)
    if gateway is None:
        gateway = session.client("bedrock-agentcore-control").list_gateways()["items"][0]["gatewayId"]
    runtime_id = outputs["RuntimeArn"].split("/")[-1]
    lam = f"/aws/lambda/{config.STACK_NAME}-"
    return {"gateway_id": gateway, "runtime_log_group": f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT",
            "tool_log_groups": [lam + slug for slug in TOOL_SLUGS], "handoff_log_group": lam + "human-agent-hand-off"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Publish evaluation results to CloudWatch.")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true", help="publish (default: print what would be sent)")
    args = parser.parse_args(argv)
    cases = {c["id"]: c for c in load_cases()}
    rows = report.grade_runs(args.run_dirs, cases)
    summaries = report.summarize(rows)
    fams = metrics.families(metrics.load_items(args.run_dirs, cases))
    configs = [(s["model"], s["prompt"]) for s in summaries]
    labels, prompts = run_labels(args.run_dirs), prompt_ids(args.run_dirs)
    data = metric_data(summaries, fams, labels, prompts, dt.datetime.now(dt.timezone.utc))
    print(f"{len(data)} metric data points for {len(summaries)} configurations; dashboard {DASHBOARD}")
    if not args.apply:
        for d in data[:40]:
            dims = ",".join(x["Value"] for x in d["Dimensions"][3:])
            print(d["MetricName"], d["Dimensions"][0]["Value"], dims, d.get("Value", d.get("Values")))
        return 0
    session = config.aws_session()
    body = dashboard_body(summaries, fams, "\n".join(report.grid_table(rows, configs)), labels, prompts,
                          live_targets(session))
    for message in publish(session.client("cloudwatch"), data, body):
        print("dashboard validation:", message)
    print(f"https://{config.REGION}.console.aws.amazon.com/cloudwatch/home?region={config.REGION}"
          f"#dashboards/dashboard/{DASHBOARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
