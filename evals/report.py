"""Grade recorded sessions and write the comparison report (spec sections 6-7).

  python -m evals.report evals/results/baseline-v10 evals/results/v11 --out evals/results/report

The case is the unit: pass^1 is the mean trial success per case, pass^k the share
of cases whose k runs all passed (Wilson interval over cases), and a case is unsafe
when any of its runs is. Harness errors are counted, never graded.
"""

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from evals import config, graders
from evals.cases import load_cases


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def grade_runs(run_dirs: list[Path], cases_by_id: dict) -> list[dict]:
    """One row per (case, model, prompt, run); the last record of a key wins (resume)."""
    latest: dict[tuple, dict] = {}
    aws: dict[str, dict] = {}
    for run_dir in run_dirs:
        for record in _jsonl(run_dir / "aws_eval.jsonl"):
            if not record.get("error"):  # a failed attempt never hides a later success
                aws[record["session_id"]] = {r["evaluatorId"]: r["value"] for r in record["results"]
                                             if r.get("value") is not None}
        for session in _jsonl(run_dir / "sessions.jsonl"):
            k = session["key"]
            latest[(k["case"], k["model"], k["prompt"], k["run"])] = session
    rows = []
    for (case_id, model, prompt, run), session in sorted(latest.items()):
        graded = graders.grade(session, cases_by_id[case_id])
        tokens_in = sum(r["usage"]["input"] for r in session["requests"])
        tokens_out = sum(r["usage"]["output"] for r in session["requests"])
        rows.append({
            "case": case_id, "model": model, "prompt": prompt, "run": run,
            "status": graded["status"], "passed": graded["passed"], "unsafe": graded["unsafe"],
            "harness_error": graded.get("harness_error"),
            "failures": graded["failures"], "first_failure": graded["first_failure"],
            "session_id": session["session_id"], "tokens_in": tokens_in, "tokens_out": tokens_out,
            "latency_s": sum(r["latency_s"] for r in session["requests"]),
            "cost": config.session_cost(model, tokens_in, tokens_out) if model in config.PRICES else 0.0,
            "aws": aws.get(session["session_id"], {}),
        })
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    by_config: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_config[(r["model"], r["prompt"])].append(r)
    summaries = []
    for (model, prompt), items in sorted(by_config.items()):
        graded = [r for r in items if r["status"] == "graded"]
        per_case: dict[str, list[dict]] = defaultdict(list)
        for r in graded:
            per_case[r["case"]].append(r)
        n = len(per_case)
        k = max((len(v) for v in per_case.values()), default=0)
        all_pass = sum(1 for v in per_case.values() if all(r["passed"] for r in v))
        unsafe = sum(1 for v in per_case.values() if any(r["unsafe"] for r in v))
        aws: dict[str, dict] = {}
        for evaluator in sorted({e for r in graded for e in r["aws"]}):
            scored = [r for r in graded if evaluator in r["aws"]]
            aws[evaluator] = {
                "mean": statistics.mean(r["aws"][evaluator] for r in scored),
                "agreement": sum((r["aws"][evaluator] >= 0.5) == r["passed"] for r in scored) / len(scored),
                "n": len(scored),
            }
        summaries.append({
            "model": model, "prompt": prompt, "cases": n, "k": k,
            "pass1": statistics.mean(sum(r["passed"] for r in v) / len(v) for v in per_case.values()) if n else 0.0,
            "passk": all_pass, "passk_ci": wilson(all_pass, n),
            "unsafe_cases": unsafe, "unsafe_bound": (3 / n if n and not unsafe else None),
            "harness_errors": sum(1 for r in items if r["status"] == "harness_error"),
            "latency_median_s": statistics.median(r["latency_s"] for r in graded) if graded else 0.0,
            "tokens_in_mean": statistics.mean(r["tokens_in"] for r in graded) if graded else 0.0,
            "tokens_out_mean": statistics.mean(r["tokens_out"] for r in graded) if graded else 0.0,
            "cost_total": sum(r["cost"] for r in items),
            "aws": aws,
        })
    return summaries


def grid(rows: list[dict]) -> dict[str, dict[tuple, str]]:
    cells: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
    for r in sorted(rows, key=lambda r: r["run"]):
        mark = "E" if r["status"] == "harness_error" else ("✓" if r["passed"] else "✗")
        cells[r["case"]][(r["model"], r["prompt"])].append(mark)
    return {case: {cfg: "".join(marks) for cfg, marks in by_cfg.items()} for case, by_cfg in cells.items()}


def regressions(rows: list[dict], before: str, after: str) -> list[tuple[str, str, str]]:
    """(model, case, check) failing in some `after` run but in no `before` run."""
    failed: dict[tuple, set] = defaultdict(set)
    for r in rows:
        for f in r["failures"]:
            failed[(r["model"], r["case"], r["prompt"])].add(f["check"])
    found = set()
    for (model, case, prompt), checks in failed.items():
        if prompt == after and any(r["model"] == model and r["case"] == case and r["prompt"] == before
                                   for r in rows):
            found |= {(model, case, check) for check in checks - failed.get((model, case, before), set())}
    return sorted(found)


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def write_report(run_dirs: list[Path], out_dir: Path) -> Path:
    cases_by_id = {c["id"]: c for c in load_cases()}
    rows = grade_runs(run_dirs, cases_by_id)
    summaries = summarize(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "grades.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    with (out_dir / "report.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["model", "prompt", "cases", "k", "pass1", "passk", "passk_lo", "passk_hi",
                         "unsafe_cases", "harness_errors", "latency_median_s", "tokens_in_mean",
                         "tokens_out_mean", "cost_total"])
        for s in summaries:
            writer.writerow([s["model"], s["prompt"], s["cases"], s["k"], f"{s['pass1']:.3f}", s["passk"],
                             f"{s['passk_ci'][0]:.3f}", f"{s['passk_ci'][1]:.3f}", s["unsafe_cases"],
                             s["harness_errors"], f"{s['latency_median_s']:.1f}", f"{s['tokens_in_mean']:.0f}",
                             f"{s['tokens_out_mean']:.0f}", f"{s['cost_total']:.2f}"])

    configs = [(s["model"], s["prompt"]) for s in summaries]
    lines = ["# LedgerLens evaluation report", "",
             f"Runs: {', '.join(str(d) for d in run_dirs)}", "",
             "## Model × prompt", "",
             "| Model | Prompt | Cases | pass^1 | pass^k (95% CI) | Unsafe cases | Harness errors | Median latency | Tokens in/out | Cost |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for s in summaries:
        lo, hi = s["passk_ci"]
        unsafe = f"{s['unsafe_cases']}" + (f" (≤{_pct(s['unsafe_bound'])})" if s["unsafe_bound"] else "")
        lines.append(f"| {s['model']} | {s['prompt']} | {s['cases']} | {_pct(s['pass1'])} | "
                     f"{s['passk']}/{s['cases']} pass^{s['k']} ({_pct(lo)}–{_pct(hi)}) | {unsafe} | "
                     f"{s['harness_errors']} | {s['latency_median_s']:.1f} s | "
                     f"{s['tokens_in_mean']:.0f}/{s['tokens_out_mean']:.0f} | ${s['cost_total']:.2f} |")
    lines += ["", "## AgentCore Evaluations (corroborating, never deciding)", "",
              "| Model | Prompt | Evaluator | Mean | Agreement with local | Sessions |", "|---|---|---|---|---|---|"]
    for s in summaries:
        for evaluator, a in s["aws"].items():
            lines.append(f"| {s['model']} | {s['prompt']} | {evaluator} | {a['mean']:.2f} | "
                         f"{_pct(a['agreement'])} | {a['n']} |")
    g = grid(rows)
    lines += ["", "## Per-case grid (✓ pass, ✗ fail, E harness error)", "",
              "| Case | " + " | ".join(f"{m} {p}" for m, p in configs) + " |",
              "|---|" + "---|" * len(configs)]
    for case_id in sorted(g):
        lines.append(f"| {case_id} | " + " | ".join(g[case_id].get(cfg, "") for cfg in configs) + " |")
    prompts = sorted({p for _, p in configs})
    if len(prompts) >= 2:
        before, after = prompts[0], prompts[-1]
        found = regressions(rows, before, after)
        lines += ["", f"## Regressions {before} → {after}", ""]
        lines += [f"- {m} {c}: `{check}`" for m, c, check in found] or ["- none"]
    lines += ["", "## Failures", "", "| Model | Prompt | Case | Run | First failing check | Reason | Session |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["status"] == "graded" and not r["passed"]:
            reason = r["failures"][0]["reason"].replace("|", "/")[:120]
            lines.append(f"| {r['model']} | {r['prompt']} | {r['case']} | {r['run']} | "
                         f"{r['first_failure']} | {reason} | `{r['session_id']}` |")
    # Spec section 8 keeps these out of the pass rates; section 12 makes them findings
    # (e.g. a model that can't call the tools), so every reason is listed here.
    lines += ["", "## Harness and agent errors (retried once, not graded)", "",
              "| Model | Prompt | Case | Run | Reason | Session |", "|---|---|---|---|---|---|"]
    for r in rows:
        if r["status"] == "harness_error":
            reason = str(r["harness_error"]).replace("|", "/").replace("\n", " ")[:160]
            lines.append(f"| {r['model']} | {r['prompt']} | {r['case']} | {r['run']} | {reason} | "
                         f"`{r['session_id']}` |")
    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Grade runs and write the report.")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(write_report(args.run_dirs, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
