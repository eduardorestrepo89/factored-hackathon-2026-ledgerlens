"""The metric families behind the dashboard, computed from recorded sessions.

Research: datathon/reports/LedgerLens dashboard metrics.md. Every function here is
pure: an item is {"session", "case", "grade", "aws"}, where aws maps an evaluator id
to {"value", "errorCode"}. Harness-error sessions are left out; rates are percentages
(0-100) and None when nothing could be measured.
"""

import json
from collections import defaultdict
from pathlib import Path

from evals import config, graders

HARNESS_CHECKS = ("unexpected_confirmation", "missing_confirmation")
ENUMS = {
    "human_agent_hand_off": {"reason": {"FRAUD_CONFIRMED", "CUSTOMER_REQUEST", "UNRESOLVED", "OUT_OF_SCOPE"},
                             "priority": {"high", "normal"}},
    "block_credit_card": {"reason": {"suspected_fraud", "lost", "stolen", "customer_request"}},
    "open_claim": {"claim_type": {"fraud", "dispute"}},
}
ARRAY_FIELDS = {"human_agent_hand_off": ("related_ids",), "open_claim": ("transaction_ids",)}
DEFECT_TYPES = ("bare_tool_name", "array_sent_as_string", "enum_outside_spec", "null_argument")
CAUSES = ("reproposal_after_no", "retry_after_unknown_tool", "unrequested")
UNSAFE_TYPES = tuple(graders.UNSAFE)


def _pct(part: float, whole: float) -> float | None:
    return 100 * part / whole if whole else None


def _raw(result: dict) -> str:
    return json.dumps(result.get("body"), ensure_ascii=False)


def _bare(name: str) -> str:
    return str(name).rpartition("___")[2]


def load_items(run_dirs: list[Path], cases_by_id: dict) -> list[dict]:
    """One item per (case, model, prompt, run); a later record of the same key wins."""
    latest, aws = {}, {}
    for run_dir in run_dirs:
        for path, sink in ((run_dir / "aws_eval.jsonl", "aws"), (run_dir / "sessions.jsonl", "sessions")):
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if sink == "aws":
                    if not record.get("error"):
                        aws[record["session_id"]] = {r["evaluatorId"]: {"value": r.get("value"),
                                                                        "errorCode": r.get("errorCode")}
                                                     for r in record["results"]}
                else:
                    k = record["key"]
                    latest[(k["case"], k["model"], k["prompt"], k["run"])] = record
    items = []
    for _, session in sorted(latest.items()):
        case = cases_by_id[session["case_id"]]
        items.append({"session": session, "case": case, "grade": graders.grade(session, case),
                      "aws": aws.get(session["session_id"], {})})
    return items


def _call_defects(c: dict) -> set[str]:
    found = set()
    if not str(c.get("full_name", "")).startswith("gateway_"):
        found.add("bare_tool_name")
    for field in ARRAY_FIELDS.get(c["name"], ()):
        if field in c["input"] and not isinstance(c["input"][field], list):
            found.add("array_sent_as_string")
    for field, allowed in ENUMS.get(c["name"], {}).items():
        if field in c["input"] and c["input"][field] not in allowed:
            found.add("enum_outside_spec")
    if any(v is None for v in c["input"].values()):
        found.add("null_argument")
    return found


def _proposals(session: dict, case: dict):
    """Yield (confirmation, cause or None) in stream order, replaying the runner's answer queue."""
    queue = [q["tool"] for q in case["confirmations"]]
    declined, unknown = set(), set()
    names = {}
    for r in session["requests"]:
        declined |= {a["tool"] for a in r["answers"] if a["answer"] == "no"}
        names.update({c["id"]: c["name"] for c in r["tool_calls"]})
        names.update({a["toolUseId"]: a["tool"] for a in r["answers"]})
        unknown |= {names.get(res["id"]) for res in r["tool_results"] if "Unknown tool" in _raw(res)}
        for c in r["confirmations"]:
            names[c.get("toolUseId")] = c.get("tool")
            if queue and queue[0] == c.get("tool"):
                queue.pop(0)
                yield c, None
            elif c.get("tool") in declined:
                yield c, "reproposal_after_no"
            elif c.get("tool") in unknown:
                yield c, "retry_after_unknown_tool"
            else:
                yield c, "unrequested"


def _gold_handoff_reason(case: dict) -> str | None:
    for spec in case["checks"]:
        if spec["check"] == "confirmation" and spec.get("tool") == graders.HANDOFF:
            return (spec.get("details") or {}).get("reason")
    return None


def _config_families(items: list[dict]) -> dict:
    graded = [i for i in items if i["grade"]["status"] == "graded"]
    f: dict = {"sessions": len(graded)}

    # where it fails
    checks = defaultdict(lambda: {"failures": 0, "sessions": 0, "first": 0})
    by_eval = defaultdict(list)
    for i in graded:
        failing = {x["check"] for x in i["grade"]["failures"]}
        for name in [s["check"] for s in i["case"]["checks"]] + list(HARNESS_CHECKS):
            checks[name]["sessions"] += 1
            checks[name]["failures"] += name in failing
            checks[name]["first"] += i["grade"]["first_failure"] == name
        by_eval[i["case"]["evaluation"]].append(i["grade"]["passed"])
    f["check_failures"] = {k: {**v, "rate": _pct(v["failures"], v["sessions"])} for k, v in sorted(checks.items())}
    f["pass_rate_by_evaluation"] = {k: _pct(sum(v), len(v)) for k, v in sorted(by_eval.items())}

    # tool quality
    calls = [c for i in graded for r in i["session"]["requests"] for c in r["tool_calls"]]
    defects = {t: 0 for t in DEFECT_TYPES}
    defective = 0
    for c in calls:
        found = _call_defects(c)
        defective += bool(found)
        for t in found:
            defects[t] += 1
    f["tool_calls"], f["tool_call_defects"] = len(calls), defects
    f["tool_call_validity"] = _pct(len(calls) - defective, len(calls))
    results = [res for i in graded for r in i["session"]["requests"] for res in r["tool_results"]]
    executed = [res for res in results if not _raw(res).startswith('{"raw": "Not done:')]
    errors = {"unknown_tool": 0, "tool_error": 0, "other": 0}
    for res in executed:
        if "Unknown tool" in _raw(res):
            errors["unknown_tool"] += 1
        elif isinstance(res.get("body"), dict) and "error" in res["body"]:
            errors["tool_error"] += 1
        elif res.get("status") != "success":
            errors["other"] += 1
    f["tool_executed"], f["tool_errors"] = len(executed), errors
    f["tool_exec_error_rate"] = _pct(sum(errors.values()), len(executed))
    repeats = 0
    for i in graded:
        seen = set()
        for r in i["session"]["requests"]:
            for c in r["tool_calls"]:
                key = (c["name"], json.dumps(c["input"], sort_keys=True))
                repeats += key in seen
                seen.add(key)
    f["tool_calls_per_session"] = len(calls) / len(graded) if graded else None
    f["repeat_tool_call_rate"] = _pct(repeats, len(calls))
    traj = [i for i in graded if i["case"]["expected_tools"]]
    matched = 0
    for i in traj:
        made = iter(c["name"] for r in i["session"]["requests"] for c in r["tool_calls"])
        matched += all(any(m == _bare(t) for m in made) for t in i["case"]["expected_tools"])
    f["local_trajectory_match"] = _pct(matched, len(traj))

    # confirmation quality
    causes = {c: 0 for c in CAUSES}
    proposals = 0
    sessions_with_no = sessions_reproposing = 0
    for i in graded:
        session_causes = []
        for _, cause in _proposals(i["session"], i["case"]):
            proposals += 1
            if cause:
                causes[cause] += 1
                session_causes.append(cause)
        if any(a["answer"] == "no" for r in i["session"]["requests"] for a in r["answers"]):
            sessions_with_no += 1
            sessions_reproposing += "reproposal_after_no" in session_causes
    expected = sum(1 for i in graded for q in i["case"]["confirmations"] if not q.get("optional"))
    missing = sum(len(i["session"]["missing_confirmations"]) for i in graded)
    f["proposals"], f["unexpected_by_cause"] = proposals, causes
    f["proposal_precision"] = _pct(proposals - sum(causes.values()), proposals)
    f["proposal_recall"] = _pct(expected - missing, expected)
    f["reproposal_after_no_rate"] = _pct(sessions_reproposing, sessions_with_no)
    handoffs = [(c, _gold_handoff_reason(i["case"])) for i in graded for r in i["session"]["requests"]
                for c in r["confirmations"] if c.get("tool") == graders.HANDOFF]
    with_gold = [(c, gold) for c, gold in handoffs if gold]
    f["handoff_reason_accuracy"] = _pct(sum((c.get("details") or {}).get("reason") == g for c, g in with_gold),
                                        len(with_gold))
    f["handoff_reason_invalid"] = sum((c.get("details") or {}).get("reason") not in ENUMS[graders.HANDOFF]["reason"]
                                      for c, _ in handoffs)
    yes = unknown_after_yes = 0
    typed = typed_executed = 0
    for i in graded:
        res_by_id = {res["id"]: res for r in i["session"]["requests"] for res in r["tool_results"]}
        for r in i["session"]["requests"]:
            for a in r["answers"]:
                res = res_by_id.get(a["toolUseId"])
                if a["answer"] == "yes":
                    yes += 1
                    unknown_after_yes += bool(res and "Unknown tool" in _raw(res))
                elif a["answer"] == "typed":
                    typed += 1
                    typed_executed += bool(res and res.get("status") == "success")
    f["yes_unknown_tool_rate"] = _pct(unknown_after_yes, yes)
    f["typed_yes"] = {"opportunities": typed, "executed": typed_executed}

    # reliability
    runs = defaultdict(list)
    for i in graded:
        runs[i["case"]["id"]].append(i["grade"]["passed"])
    f["pass_at_k"] = _pct(sum(any(v) for v in runs.values()), len(runs))
    f["flaky_cases"] = sum(0 < sum(v) < len(v) for v in runs.values())
    f["always_fail_cases"] = sum(sum(v) == 0 for v in runs.values())
    aws = defaultdict(lambda: {"applicable": 0, "scored": 0, "span_parse_errors": 0})
    for i in graded:
        for evaluator, r in i["aws"].items():
            aws[evaluator]["applicable"] += 1
            aws[evaluator]["scored"] += r.get("value") is not None
            aws[evaluator]["span_parse_errors"] += r.get("errorCode") == "SpanEventParsingException"
    f["aws"] = {k: {**v, "scored_share": _pct(v["scored"], v["applicable"])} for k, v in sorted(aws.items())}
    f["harness_retries"] = sum(i["session"].get("attempt") == 2 for i in graded)

    # efficiency
    f["request_latencies"] = {"customer": [r["latency_s"] for i in graded for r in i["session"]["requests"]
                                           if r["kind"] == "say"],
                              "button": [r["latency_s"] for i in graded for r in i["session"]["requests"]
                                         if r["kind"] != "say"]}
    f["session_latencies"] = [sum(r["latency_s"] for r in i["session"]["requests"]) for i in graded]
    tokens = [(sum(r["usage"]["input"] for r in i["session"]["requests"]),
               sum(r["usage"]["output"] for r in i["session"]["requests"]), i["session"]["key"]["model"])
              for i in graded]
    f["tokens_in_per_session"] = sum(t[0] for t in tokens) / len(tokens) if tokens else None
    f["tokens_out_per_session"] = sum(t[1] for t in tokens) / len(tokens) if tokens else None
    cost = sum(config.session_cost(m, a, b) for a, b, m in tokens if m in config.PRICES)
    passing = sum(i["grade"]["passed"] for i in graded)
    passk = sum(all(v) for v in runs.values())
    f["cost_total"] = cost
    f["cost_per_passing_trial"] = cost / passing if passing else None
    f["cost_per_passk_case"] = cost / passk if passk else None
    f["requests"] = sum(len(i["session"]["requests"]) for i in graded)
    f["guardrail_interventions"] = sum("guardrail_intervened" in r["stop_reasons"]
                                       for i in graded for r in i["session"]["requests"])

    # safety
    f["unsafe_hits"] = {t: sum(t in i["grade"]["unsafe"] for i in graded) for t in UNSAFE_TYPES}
    replies = sum(1 for i in graded for r in i["session"]["requests"] if r["text"].strip())
    f["unsafe_opportunities"] = {
        "write_without_yes": sum(1 for i in graded for r in i["session"]["requests"] for c in r["confirmations"]
                                 if c.get("tool") in graders.WRITE_TOOLS),
        "foreign_customer_id": sum(1 for c in calls if "customer_id" in c["input"]),
        "privacy_leak": replies,
        "pan_echo": replies,
    }
    return f


def families(items: list[dict]) -> dict[tuple[str, str], dict]:
    """(model, prompt) -> the metric families for that configuration."""
    by_config = defaultdict(list)
    for i in items:
        k = i["session"]["key"]
        by_config[(k["model"], k["prompt"])].append(i)
    return {cfg: _config_families(group) for cfg, group in sorted(by_config.items())}
