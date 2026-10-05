"""Publish evaluation results to CloudWatch: custom metrics and one dashboard.

  python -m evals.cw_dashboard evals/results/baseline-v10 evals/results/v11          # print only
  python -m evals.cw_dashboard evals/results/baseline-v10 evals/results/v11 --apply  # publish

The numbers come from evals.report (the same grading), so the dashboard matches
report.md. Metrics: namespace LedgerLens/Eval, dimensions Model, Prompt and Run (the
run folder names), so a smoke test never blends into a baseline in the charts.
"""

import argparse
import datetime as dt
import json
from pathlib import Path

from evals import config, report
from evals.cases import load_cases

NAMESPACE = "LedgerLens/Eval"
DASHBOARD = "LedgerLens-Evaluation"
_CHUNK = 20
_AWS_METRICS = {"Builtin.GoalSuccessRate": "AwsGoalSuccess", "Builtin.TrajectoryInOrderMatch": "AwsTrajectory"}

HEADER = """# LedgerLens evaluation
Models × system prompts on scripted cases, graded **locally** from the agent's stream
(evals/graders.py); AgentCore Evaluations **corroborates** and never decides.
pass^1 = mean run success per case; pass^k = cases whose runs all passed.

**AWS limitation:** every session with a Yes/No confirmation (a Strands interrupt) fails
AgentCore Evaluations with `SpanEventParsingException`, so the confirmation cases
(E1a, E1b, E2b, E4a, E4b) carry local grades only. Recheck after the Strands upgrade
(HumanInTheLoop), see evals/README.md.

Traces: CloudWatch → GenAI Observability → Bedrock AgentCore → LedgerLensAgent
(filter spans by `model.id` and `prompt.version`)."""


def run_label(run_dirs: list[Path]) -> str:
    """The Run dimension: the run folder names, e.g. baseline-v10+v11."""
    return "+".join(d.name for d in run_dirs)[:255]


def run_starts(run_dirs: list[Path]) -> dict[tuple[str, str], dt.datetime]:
    """(model, prompt) -> the start of the run that recorded it; a later run wins."""
    starts = {}
    for run_dir in run_dirs:
        path = run_dir / "run.json"
        if not path.exists():
            continue
        run = json.loads(path.read_text(encoding="utf-8"))
        started = dt.datetime.fromisoformat(run["started_at"])
        for model in run["models"]:
            for prompt in run["prompts"]:
                starts[(model, prompt)] = started
    return starts


def metric_data(summaries: list[dict], starts: dict[tuple[str, str], dt.datetime], label: str) -> list[dict]:
    """CloudWatch MetricData: one datum per metric per model × prompt."""
    data = []
    now = dt.datetime.now(dt.timezone.utc)
    for s in summaries:
        values = {
            "PassRate1": (100 * s["pass1"], "Percent"),
            "PassRateK": (100 * s["passk"] / s["cases"] if s["cases"] else 0.0, "Percent"),
            "UnsafeCases": (s["unsafe_cases"], "Count"),
            "HarnessErrors": (s["harness_errors"], "Count"),
            "MedianLatencySeconds": (s["latency_median_s"], "Seconds"),
            "CostUSD": (s["cost_total"], "None"),
        }
        for evaluator, name in _AWS_METRICS.items():
            if evaluator in s["aws"]:
                values[name] = (100 * s["aws"][evaluator]["mean"], "Percent")
        dims = [{"Name": "Model", "Value": s["model"]}, {"Name": "Prompt", "Value": s["prompt"]},
                {"Name": "Run", "Value": label}]
        when = starts.get((s["model"], s["prompt"]), now)
        data += [{"MetricName": name, "Dimensions": dims, "Timestamp": when, "Value": value, "Unit": unit}
                 for name, (value, unit) in values.items()]
    return data


def _series(summaries: list[dict], metrics: list[str], label: str) -> list[list]:
    return [[NAMESPACE, metric, "Model", s["model"], "Prompt", s["prompt"], "Run", label,
             {"label": f"{config.model_slug(s['model'])} {s['prompt']} {metric}"}]
            for metric in metrics for s in summaries]


def _chart(title: str, series: list[list], y: int, x: int = 0, width: int = 12, view: str = "bar") -> dict:
    return {"type": "metric", "x": x, "y": y, "width": width, "height": 6,
            "properties": {"title": title, "view": view, "region": config.REGION, "stat": "Maximum",
                           "period": 300, "setPeriodToTimeRange": True, "metrics": series}}


def dashboard_body(summaries: list[dict], grid_markdown: str, label: str) -> dict:
    """The dashboard JSON: header, charts per model × prompt, and the per-case grid."""
    return {"start": "-P14D", "widgets": [
        {"type": "text", "x": 0, "y": 0, "width": 24, "height": 7, "properties": {"markdown": HEADER + f"  Run: `{label}`"}},
        _chart("Local pass rate (%): pass^1 and pass^k", _series(summaries, ["PassRate1", "PassRateK"], label), 7),
        _chart("AgentCore Evaluations (%): GoalSuccessRate, TrajectoryInOrderMatch",
               _series(summaries, ["AwsGoalSuccess", "AwsTrajectory"], label), 7, x=12),
        _chart("Unsafe cases and harness errors", _series(summaries, ["UnsafeCases", "HarnessErrors"], label), 13,
               view="singleValue"),
        _chart("Median latency per session (s)", _series(summaries, ["MedianLatencySeconds"], label), 13, x=12, width=6),
        _chart("Model cost (USD)", _series(summaries, ["CostUSD"], label), 13, x=18, width=6),
        {"type": "text", "x": 0, "y": 19, "width": 24, "height": 8,
         "properties": {"markdown": "## Per-case grid (✓ pass, ✗ fail, E harness error)\n\n" + grid_markdown}},
    ]}


def publish(cloudwatch, data: list[dict], body: dict) -> None:
    for i in range(0, len(data), _CHUNK):
        cloudwatch.put_metric_data(Namespace=NAMESPACE, MetricData=data[i : i + _CHUNK])
    cloudwatch.put_dashboard(DashboardName=DASHBOARD, DashboardBody=json.dumps(body, ensure_ascii=False))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Publish evaluation results to CloudWatch.")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true", help="publish (default: print what would be sent)")
    args = parser.parse_args(argv)
    rows = report.grade_runs(args.run_dirs, {c["id"]: c for c in load_cases()})
    summaries = report.summarize(rows)
    configs = [(s["model"], s["prompt"]) for s in summaries]
    label = run_label(args.run_dirs)
    data = metric_data(summaries, run_starts(args.run_dirs), label)
    body = dashboard_body(summaries, "\n".join(report.grid_table(rows, configs)), label)
    print(f"{len(data)} metric data points for {len(summaries)} configurations; dashboard {DASHBOARD}")
    if not args.apply:
        for d in data:
            print(d["MetricName"], d["Dimensions"][0]["Value"], d["Dimensions"][1]["Value"], round(d["Value"], 2))
        return 0
    publish(config.aws_session().client("cloudwatch"), data, body)
    print(f"https://{config.REGION}.console.aws.amazon.com/cloudwatch/home?region={config.REGION}"
          f"#dashboards/dashboard/{DASHBOARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
