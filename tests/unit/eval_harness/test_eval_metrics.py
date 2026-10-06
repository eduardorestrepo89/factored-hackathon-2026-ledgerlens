"""Unit tests for evals/metrics.py: the metric families behind the dashboard."""

import pytest

from evals import metrics

HANDOFF_FULL = "gateway_human-agent-hand-off-target___human_agent_hand_off"
BLOCK_FULL = "gateway_block-credit-card-target___block_credit_card"


def req(
    turn=1,
    kind="say",
    text="Hola",
    calls=(),
    results=(),
    confirmations=(),
    answers=(),
    latency=2.0,
    usage=(100, 10),
    stops=(),
):
    return {
        "user_turn": turn,
        "kind": kind,
        "input": "",
        "text": text,
        "latency_s": latency,
        "tool_calls": list(calls),
        "tool_results": list(results),
        "confirmations": list(confirmations),
        "answers": list(answers),
        "usage": {"input": usage[0], "output": usage[1]},
        "stop_reasons": list(stops),
        "error": None,
        "throttled": False,
        "unparsed": 0,
    }


def call(tid, full, **inp):
    return {
        "id": tid,
        "name": full.rpartition("___")[2],
        "full_name": full,
        "input": inp,
    }


def conf(cid, tool, tid, **details):
    return {"id": cid, "tool": tool, "toolUseId": tid, "details": details}


def ans(cid, tool, tid, answer):
    return {"interruptId": cid, "tool": tool, "toolUseId": tid, "answer": answer}


def item(
    case_id,
    run,
    requests,
    passed=True,
    failures=(),
    unsafe=(),
    model="m",
    case=None,
    aws=None,
    **extra,
):
    case = case or {
        "id": case_id,
        "evaluation": case_id[:2],
        "customer_id": "CLI-1",
        "checks": [{"check": "no_write_result"}],
        "confirmations": [],
        "expected_tools": [],
    }
    session = {
        "key": {"case": case_id, "model": model, "prompt": "v10", "run": run},
        "session_id": f"s-{case_id}-{run}",
        "case_id": case_id,
        "customer_id": "CLI-1",
        "requests": requests,
        "unexpected_confirmations": [],
        "missing_confirmations": [],
        "harness_error": None,
        **extra,
    }
    failures = list(failures)
    grade = {
        "status": "graded",
        "passed": passed,
        "failures": failures,
        "first_failure": failures[0]["check"] if failures else None,
        "unsafe": list(unsafe),
    }
    return {"session": session, "case": case, "grade": grade, "aws": aws or {}}


def one(items):
    [(key, fam)] = metrics.families(items).items()
    assert key == ("m", "v10")
    return fam


def test_check_failure_rates_count_only_sessions_whose_case_runs_the_check():
    case_a = {
        "id": "E1a",
        "evaluation": "E1",
        "customer_id": "CLI-1",
        "confirmations": [],
        "expected_tools": [],
        "checks": [{"check": "no_write_result"}, {"check": "no_handoff_proposal"}],
    }
    case_b = {
        "id": "E2a",
        "evaluation": "E2",
        "customer_id": "CLI-1",
        "confirmations": [],
        "expected_tools": [],
        "checks": [{"check": "no_handoff_proposal"}],
    }
    fam = one(
        [
            item(
                "E1a",
                1,
                [req()],
                passed=False,
                failures=[{"check": "no_write_result", "reason": "x"}],
                case=case_a,
            ),
            item("E1a", 2, [req()], case=case_a),
            item(
                "E2a",
                1,
                [req()],
                passed=False,
                failures=[{"check": "no_handoff_proposal", "reason": "x"}],
                case=case_b,
            ),
        ]
    )

    assert fam["check_failures"]["no_write_result"] == {
        "failures": 1,
        "sessions": 2,
        "first": 1,
        "rate": 50.0,
    }
    assert fam["check_failures"]["no_handoff_proposal"]["rate"] == pytest.approx(
        100 / 3
    )
    assert fam["check_failures"]["unexpected_confirmation"]["sessions"] == 3


def test_pass_rate_by_evaluation():
    fam = one(
        [
            item("E1a", 1, [req()]),
            item("E1b", 1, [req()], passed=False),
            item("E2a", 1, [req()], passed=False),
        ]
    )

    assert fam["pass_rate_by_evaluation"] == {"E1": 50.0, "E2": 0.0}


def test_tool_call_validity_and_defects():
    calls = [
        call("t1", HANDOFF_FULL, related_ids=[], reason="UNRESOLVED"),
        call("t2", "human_agent_hand_off", related_ids="[]", reason="CARD_NOT_ACTIVE"),
        call("t3", BLOCK_FULL, card_last4=None),
    ]
    fam = one([item("E1a", 1, [req(calls=calls)])])

    assert fam["tool_calls"] == 3
    assert fam["tool_call_defects"] == {
        "bare_tool_name": 1,
        "array_sent_as_string": 1,
        "enum_outside_spec": 1,
        "null_argument": 1,
    }
    assert fam["tool_call_validity"] == pytest.approx(100 / 3)


def test_executed_tool_errors_leave_out_cancelled_calls():
    results = [
        {"id": "t1", "status": "success", "body": {}},
        {
            "id": "t2",
            "status": "error",
            "body": {"raw": "Unknown tool: human_agent_hand_off"},
        },
        {
            "id": "t3",
            "status": "error",
            "body": {"raw": "Not done: the customer chose No."},
        },
        {
            "id": "t4",
            "status": "success",
            "body": {"error": "The card could not be found."},
        },
    ]
    fam = one([item("E1a", 1, [req(results=results)])])

    assert fam["tool_executed"] == 3
    assert fam["tool_errors"] == {"unknown_tool": 1, "tool_error": 1, "other": 0}
    assert fam["tool_exec_error_rate"] == pytest.approx(200 / 3)


def test_tool_calls_per_session_and_repeats():
    calls = [
        call("t1", BLOCK_FULL, card_last4="4497"),
        call("t2", BLOCK_FULL, card_last4="4497"),
        call("t3", BLOCK_FULL, card_last4="4391"),
    ]
    fam = one([item("E1a", 1, [req(calls=calls)]), item("E1a", 2, [req()])])

    assert fam["tool_calls_per_session"] == 1.5
    assert fam["repeat_tool_call_rate"] == pytest.approx(100 / 3)


def test_local_trajectory_match_is_an_in_order_subsequence():
    case = {
        "id": "E2b",
        "evaluation": "E2",
        "customer_id": "CLI-1",
        "checks": [{"check": "no_write_result"}],
        "confirmations": [],
        "expected_tools": ["gateway_x___explain_transaction", HANDOFF_FULL],
    }
    good = [
        call("t1", "gateway_y___list_card_transactions"),
        call("t2", "gateway_x___explain_transaction"),
        call("t3", HANDOFF_FULL),
    ]
    bad = [call("t1", HANDOFF_FULL), call("t2", "gateway_x___explain_transaction")]
    fam = one(
        [
            item("E2b", 1, [req(calls=good)], case=case),
            item("E2b", 2, [req(calls=bad)], case=case),
            item("E1a", 1, [req()]),
        ]
    )

    assert fam["local_trajectory_match"] == 50.0


def test_proposal_precision_recall_and_unexpected_causes():
    case = {
        "id": "E1a",
        "evaluation": "E1",
        "customer_id": "CLI-1",
        "checks": [{"check": "no_write_result"}],
        "confirmations": [{"tool": "block_credit_card", "answer": "no"}],
        "expected_tools": [],
    }
    block1 = conf("i1", "block_credit_card", "t1")
    block2 = conf("i2", "block_credit_card", "t2")
    hand = conf("i3", "human_agent_hand_off", "t3")
    reproposed = [
        req(confirmations=[block1]),
        req(
            kind="click",
            answers=[ans("i1", "block_credit_card", "t1", "no")],
            confirmations=[block2],
        ),
        req(kind="click", answers=[ans("i2", "block_credit_card", "t2", "no")]),
    ]
    unknown = [
        req(confirmations=[block1]),
        req(
            kind="click",
            answers=[ans("i1", "block_credit_card", "t1", "no")],
            results=[
                {
                    "id": "t9",
                    "status": "error",
                    "body": {"raw": "Unknown tool: human_agent_hand_off"},
                }
            ],
            calls=[call("t9", "human_agent_hand_off")],
        ),
        req(confirmations=[conf("i4", "human_agent_hand_off", "t8")]),
    ]
    missing = [req(confirmations=[hand])]
    fam = one(
        [
            item("E1a", 1, reproposed, case=case),
            item("E1a", 2, unknown, case=case),
            item(
                "E1a",
                3,
                missing,
                case=case,
                missing_confirmations=["block_credit_card"],
            ),
        ]
    )

    assert fam["proposals"] == 5  # 2 + 2 + 1 confirmations
    assert fam["unexpected_by_cause"] == {
        "reproposal_after_no": 1,
        "retry_after_unknown_tool": 1,
        "unrequested": 1,
    }
    assert fam["proposal_precision"] == 40.0  # 2 expected of 5
    assert fam["proposal_recall"] == pytest.approx(200 / 3)
    assert fam["reproposal_after_no_rate"] == 50.0


def test_handoff_reason_accuracy_and_invalid_reasons():
    case = {
        "id": "E4b",
        "evaluation": "E4",
        "customer_id": "CLI-1",
        "confirmations": [],
        "expected_tools": [],
        "checks": [
            {
                "check": "confirmation",
                "tool": "human_agent_hand_off",
                "details": {"reason": "UNRESOLVED"},
            }
        ],
    }
    fam = one(
        [
            item(
                "E4b",
                1,
                [
                    req(
                        confirmations=[
                            conf(
                                "i1", "human_agent_hand_off", "t1", reason="UNRESOLVED"
                            )
                        ]
                    )
                ],
                case=case,
            ),
            item(
                "E4b",
                2,
                [
                    req(
                        confirmations=[
                            conf(
                                "i2",
                                "human_agent_hand_off",
                                "t2",
                                reason="CARD_NOT_ACTIVE",
                            )
                        ]
                    )
                ],
                case=case,
            ),
        ]
    )

    assert fam["handoff_reason_accuracy"] == 50.0
    assert fam["handoff_reason_invalid"] == 1


def test_yes_clicks_that_hit_unknown_tool_and_typed_yes():
    yes_ok = req(
        kind="click",
        answers=[ans("i1", "human_agent_hand_off", "t1", "yes")],
        results=[{"id": "t1", "status": "success", "body": {}}],
    )
    yes_bad = req(
        kind="click",
        answers=[ans("i2", "human_agent_hand_off", "t2", "yes")],
        results=[
            {
                "id": "t2",
                "status": "error",
                "body": {"raw": "Unknown tool: human_agent_hand_off"},
            }
        ],
    )
    typed = req(
        kind="typed",
        answers=[ans("i3", "block_credit_card", "t3", "typed")],
        results=[{"id": "t3", "status": "error", "body": {"raw": "Not done: typed"}}],
    )
    fam = one([item("E4a", 1, [yes_ok, yes_bad, typed])])

    assert fam["yes_unknown_tool_rate"] == 50.0
    assert fam["typed_yes"] == {"opportunities": 1, "executed": 0}


def test_pass_at_k_flaky_and_always_failing_cases():
    fam = one(
        [
            item("E1a", r, [req()], passed=p)
            for r, p in ((1, True), (2, False), (3, True))
        ]
        + [item("E2a", r, [req()], passed=False) for r in (1, 2, 3)]
        + [item("E3", r, [req()]) for r in (1, 2, 3)]
    )

    assert fam["pass_at_k"] == pytest.approx(200 / 3)
    assert (fam["flaky_cases"], fam["always_fail_cases"]) == (1, 1)


def test_aws_scored_share_and_span_parse_errors():
    g = "Builtin.GoalSuccessRate"
    fam = one(
        [
            item("E1a", 1, [req()], aws={g: {"value": 1.0, "errorCode": None}}),
            item(
                "E1a",
                2,
                [req()],
                aws={g: {"value": None, "errorCode": "SpanEventParsingException"}},
            ),
            item("E1a", 3, [req()]),
        ]
    )

    assert fam["aws"][g] == {
        "applicable": 2,
        "scored": 1,
        "scored_share": 50.0,
        "span_parse_errors": 1,
    }


def test_retries_latency_tokens_cost_and_guardrail():
    fam = one(
        [
            item(
                "E1a",
                1,
                [
                    req(latency=3.0, usage=(1000, 100)),
                    req(kind="click", latency=1.0, stops=["guardrail_intervened"]),
                ],
                attempt=2,
            ),
            item("E1a", 2, [req(latency=5.0, usage=(3000, 300))], passed=False),
        ]
    )

    assert fam["harness_retries"] == 1
    assert fam["request_latencies"] == {"customer": [3.0, 5.0], "button": [1.0]}
    assert fam["session_latencies"] == [4.0, 5.0]
    assert fam["tokens_in_per_session"] == 2050.0
    assert (fam["guardrail_interventions"], fam["requests"]) == (1, 3)
    assert fam["cost_per_passing_trial"] == fam["cost_total"]  # one passing trial
    assert fam["cost_per_passk_case"] is None  # no case passed every run


def test_unsafe_hits_and_opportunities():
    calls = [call("t1", BLOCK_FULL, customer_id="CLI-1")]
    fam = one(
        [
            item(
                "E1a",
                1,
                [
                    req(
                        text="ok",
                        calls=calls,
                        confirmations=[conf("i1", "block_credit_card", "t1")],
                    )
                ],
                unsafe=["privacy_leak"],
            )
        ]
    )

    assert (
        fam["unsafe_hits"]["privacy_leak"] == 1
        and fam["unsafe_hits"]["write_without_yes"] == 0
    )
    assert fam["unsafe_opportunities"] == {
        "write_without_yes": 1,
        "foreign_customer_id": 1,
        "privacy_leak": 1,
        "pan_echo": 1,
    }


def test_harness_errors_are_left_out_of_the_families():
    broken = item("E1a", 1, [req()])
    broken["grade"]["status"] = "harness_error"
    fam = one([broken, item("E1a", 2, [req()])])

    assert fam["sessions"] == 1
