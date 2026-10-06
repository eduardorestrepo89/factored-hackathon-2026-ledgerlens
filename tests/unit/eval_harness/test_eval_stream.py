"""Unit tests for evals/stream.py."""

import json

from evals import stream

CALL = {"toolUseId": "t1", "name": "gateway_block-credit-card-target___block_credit_card",
        "input": {"customer_id": "CLI-X", "card_last4": "4497", "reason": "suspected_fraud"}}


def assistant(*blocks):
    return {"message": {"role": "assistant", "content": list(blocks)}}


def result(tool_use_id, status, text):
    return {"message": {"role": "user", "content": [
        {"toolResult": {"toolUseId": tool_use_id, "status": status, "content": [{"text": text}]}}
    ]}}


def test_parse_sse_skips_comments_blanks_and_bad_json():
    lines = [": keep-alive", "", 'data: {"data": "Ho"}', b'data: {"data": "la"}', "data: {oops", 'data: "just text"']

    events = list(stream.parse_sse(lines))

    assert events == [{"data": "Ho"}, {"data": "la"}, {"_unparsed": "data: {oops"}]


def test_bare_tool_name_strips_the_gateway_prefix():
    assert stream.bare_tool_name(CALL["name"]) == "block_credit_card"
    assert stream.bare_tool_name("plain") == "plain"


def test_tool_body_unwraps_the_lambda_envelope_once():
    inner = json.dumps({"decline": {"contradicts_card_state": True}})
    outer = json.dumps({"content": [{"type": "text", "text": inner}]})

    assert stream.parse_tool_body([{"text": outer}]) == {"decline": {"contradicts_card_state": True}}


def test_tool_body_keeps_plain_text_raw():
    assert stream.parse_tool_body([{"text": "Not done: the customer chose No."}]) == {
        "raw": "Not done: the customer chose No."
    }
    assert stream.parse_tool_body([{"text": '{"error": "boom"}'}]) == {"error": "boom"}
    assert stream.parse_tool_body(None) == {"raw": ""}


def test_digest_collects_text_calls_results_confirmations_and_usage():
    events = [
        {"data": "ignored delta"},
        {"event": {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 7}}}},
        {"event": {"messageStop": {"stopReason": "tool_use"}}},
        assistant({"text": "Puedo bloquear la tarjeta 4497."}, {"toolUse": CALL}),
        {"confirmation": {"id": "i1", "tool": "block_credit_card", "toolUseId": "t1",
                          "details": {"card_last4": "4497", "reason": "suspected_fraud"}}},
        {"event": {"metadata": {"usage": {"inputTokens": 50, "outputTokens": 3}}}},
        {"event_loop_throttled_delay": 2},
    ]

    d = stream.digest(events)

    assert d["text"] == "Puedo bloquear la tarjeta 4497."
    assert d["tool_calls"] == [{"id": "t1", "name": "block_credit_card", "full_name": CALL["name"],
                                "input": CALL["input"]}]
    assert d["confirmations"][0]["id"] == "i1"
    assert d["usage"] == {"input": 150, "output": 10}
    assert d["stop_reasons"] == ["tool_use"]
    assert d["throttled"] is True
    assert d["error"] is None


def test_digest_reads_tool_results_and_errors():
    events = [result("t1", "error", "Not done: the customer chose No."),
              {"status": "error", "error": "eval override rejected: bad model"},
              {"_unparsed": "data: {"}]

    d = stream.digest(events)

    assert d["tool_results"] == [{"id": "t1", "status": "error",
                                  "body": {"raw": "Not done: the customer chose No."}}]
    assert d["error"] == "eval override rejected: bad model"
    assert d["unparsed"] == 1
