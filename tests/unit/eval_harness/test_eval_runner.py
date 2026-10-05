"""Unit tests for evals/runner.py (no AWS: fake send, fake Cognito, httpx MockTransport)."""

import base64
import io
import json
import re

import httpx
import jwt
import pytest

from evals import runner

KEY = {"case": "E1a", "model": "openai.gpt-oss-120b-1:0", "prompt": "v10", "run": 3}
PAYLOAD = {"model_id": "deepseek.v3.2", "prompt_name": "v10", "system_prompt": "P"}
BLOCK = {"id": "i1", "tool": "block_credit_card", "toolUseId": "t1", "details": {"card_last4": "4497"}}
HANDOFF = {"id": "i2", "tool": "human_agent_hand_off", "toolUseId": "t2", "details": {"reason": "UNRESOLVED"}}


def case(**over):
    base = {"id": "E1a", "persona": "P07", "customer_id": "CLI-EX6BOAOEFZHQ",
            "turns": ["hola", "no lo hice"], "confirmations": [{"tool": "block_credit_card", "answer": "no"}],
            "checks": [{"check": "no_write_result"}], "expected_tools": [], "assertions": ["a"]}
    return {**base, **over}


class FakeSend:
    """Replies with scripted event lists, one per request; records every body."""

    def __init__(self, *replies):
        self.replies, self.bodies, self.session_ids = list(replies), [], []

    def __call__(self, session_id, body):
        self.session_ids.append(session_id)
        self.bodies.append(body)
        return self.replies.pop(0), 0.5


def text(t):
    return [{"message": {"role": "assistant", "content": [{"text": t}]}}]


def test_session_ids_fit_the_runtime_header_rule():
    sid = runner.session_id_for(KEY)

    assert 33 <= len(sid) <= 100
    assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9\-_]*", sid)
    assert sid != runner.session_id_for(KEY)


def test_a_no_click_is_sent_with_the_eval_payload_on_every_request():
    send = FakeSend(text("¿Lo reconoces?"), text("Puedo bloquearla.") + [{"confirmation": BLOCK}],
                    text("No la bloqueé."))

    session = runner.run_session(case(), KEY, PAYLOAD, send)

    assert [r["kind"] for r in session["requests"]] == ["say", "say", "click"]
    assert send.bodies[2]["confirmations"] == [{"interruptId": "i1", "approved": False}]
    assert send.bodies[2]["prompt"] == runner.BUTTON_PROMPT
    assert all(b["eval"] == PAYLOAD and b["runtimeSessionId"] == session["session_id"] for b in send.bodies)
    assert session["requests"][2]["answers"][0]["answer"] == "no"
    assert session["missing_confirmations"] == [] and session["harness_error"] is None


def test_a_typed_answer_covers_every_pending_confirmation():
    typed = case(turns=["perdí la tarjeta"],
                 confirmations=[{"tool": "block_credit_card", "answer": {"type": "Sí, bloquéala"}},
                                {"tool": "human_agent_hand_off", "answer": "no"}])
    send = FakeSend(text("Elige") + [{"confirmation": BLOCK}, {"confirmation": HANDOFF}], text("Ok"))

    session = runner.run_session(typed, KEY, PAYLOAD, send)

    assert "confirmations" not in send.bodies[1] and send.bodies[1]["prompt"] == "Sí, bloquéala"
    assert [a["answer"] for a in session["requests"][1]["answers"]] == ["typed", "typed"]


def test_an_unexpected_confirmation_is_declined_and_recorded():
    send = FakeSend(text("Te paso con alguien") + [{"confirmation": HANDOFF}], text("Ok"))

    session = runner.run_session(case(turns=["hola"], confirmations=[]), KEY, PAYLOAD, send)

    assert session["unexpected_confirmations"] == ["human_agent_hand_off"]
    assert send.bodies[1]["confirmations"] == [{"interruptId": "i2", "approved": False}]


def test_a_missing_confirmation_is_recorded_unless_optional():
    required = runner.run_session(case(turns=["hola"]), KEY, PAYLOAD, FakeSend(text("Hola")))
    optional = runner.run_session(
        case(turns=["hola"], confirmations=[{"tool": "block_credit_card", "answer": "no", "optional": True}]),
        KEY, PAYLOAD, FakeSend(text("Hola")))

    assert required["missing_confirmations"] == ["block_credit_card"]
    assert optional["missing_confirmations"] == []


def test_an_error_event_stops_the_session_as_a_harness_error():
    send = FakeSend([{"status": "error", "error": "eval override rejected: bad model"}])

    session = runner.run_session(case(), KEY, PAYLOAD, send)

    assert session["harness_error"] == "eval override rejected: bad model"
    assert len(send.bodies) == 1


def test_endless_confirmations_are_a_harness_error():
    send = FakeSend(*[text("x") + [{"confirmation": HANDOFF}]] * 10)

    session = runner.run_session(case(turns=["hola"], confirmations=[]), KEY, PAYLOAD, send)

    assert "confirmation rounds" in session["harness_error"]


def test_a_failed_attempt_is_retried_once_with_a_new_session_id():
    calls = []

    def flaky(session_id, body):
        calls.append(session_id)
        if len(calls) == 1:
            raise httpx.ConnectError("boom")
        return text("ok"), 0.1

    session = runner.run_with_retry(case(turns=["hola"], confirmations=[]), KEY, PAYLOAD, flaky)

    assert session["harness_error"] is None and session["attempt"] == 2
    assert calls[0] != calls[1]


def test_an_override_rejection_is_not_retried():
    send = FakeSend([{"status": "error", "error": "eval override rejected: x"}])

    session = runner.run_with_retry(case(), KEY, PAYLOAD, send)

    assert session["attempt"] == 1 and len(send.bodies) == 1


def token(exp):
    return jwt.encode({"sub": "s", "exp": exp}, "test-signing-key-of-32-bytes-ok!", algorithm="HS256")


class FakeCognito:
    def __init__(self, exps):
        self.exps, self.calls = list(exps), []

    def initiate_auth(self, **kwargs):
        self.calls.append(kwargs)
        return {"AuthenticationResult": {"AccessToken": token(self.exps.pop(0))}}


def test_logins_reuse_a_fresh_token():
    cognito = FakeCognito([10_000])
    logins = runner.Logins(cognito, "client", {"P07": "pw"}, clock=lambda: 1_000)

    logins.token("P07")
    logins.token("P07")

    assert len(cognito.calls) == 1
    assert cognito.calls[0]["AuthParameters"] == {"USERNAME": "eval-p07@ledgerlens.example", "PASSWORD": "pw"}


def test_logins_refresh_a_token_close_to_expiry():
    now = {"t": 1_000}
    cognito = FakeCognito([1_000 + 400, 99_999])
    logins = runner.Logins(cognito, "client", {"P07": "pw"}, clock=lambda: now["t"])

    first = logins.token("P07")
    now["t"] += 200  # 200 s left: inside the 300 s margin
    second = logins.token("P07")

    assert first != second and len(cognito.calls) == 2


def test_make_send_posts_to_the_runtime_and_parses_sse():
    seen = {}

    def handler(request):
        seen["host"], seen["path"] = request.url.host, request.url.raw_path.decode()
        seen["headers"], seen["body"] = request.headers, json.loads(request.content)
        return httpx.Response(200, content=b': ping\n\ndata: {"data": "x"}\n\ndata: {"status": "error", "error": "e"}\n\n')

    class StaticLogins:
        def token(self, persona):
            return "TOKEN"

    arn = "arn:aws:bedrock-agentcore:us-east-1:111:runtime/LedgerLens-abc"
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        events, latency = runner.make_send(http, arn, StaticLogins())("P07", "sid-1", {"prompt": "hola"})

    assert seen["host"] == "bedrock-agentcore.us-east-1.amazonaws.com"
    assert seen["path"] == ("/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A111%3Aruntime%2F"
                            "LedgerLens-abc/invocations?qualifier=DEFAULT")
    assert seen["body"] == {"prompt": "hola"}
    assert seen["headers"]["Authorization"] == "Bearer TOKEN"
    assert seen["headers"]["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] == "sid-1"
    assert events == [{"data": "x"}, {"status": "error", "error": "e"}] and latency >= 0


class FakeLambda:
    def __init__(self, body):
        self.body, self.kwargs = body, None

    def invoke(self, **kwargs):
        self.kwargs = kwargs
        outer = {"content": [{"type": "text", "text": json.dumps(self.body)}]}
        return {"Payload": io.BytesIO(json.dumps(outer).encode())}


@pytest.mark.parametrize("body, problem", [
    ({"cards": [{"card_last4": "4497", "product_status": "Active"}], "open_cases": []}, None),
    ({"cards": [{"card_last4": "4497", "product_status": "Blocked"}], "open_cases": []}, "Blocked"),
    ({"cards": [{"card_last4": "4497", "product_status": "Active"}], "open_cases": [{"x": 1}]}, "open case"),
])
def test_precheck_p07(body, problem):
    fake = FakeLambda(body)

    result = runner.precheck_p07(fake)

    assert (result is None) if problem is None else (problem in result)
    context = json.loads(base64.b64decode(fake.kwargs["ClientContext"]))
    assert context["custom"]["bedrockAgentCoreToolName"] == "get-session-context-target___get_session_context"
    assert json.loads(fake.kwargs["Payload"]) == {"customer_id": "CLI-EX6BOAOEFZHQ"}


def test_matrix_and_done_keys(tmp_path):
    cases = [case(id="A"), case(id="B")]
    jobs = runner.matrix(cases, ["m1", "m2"], ["v10"], 3)
    path = tmp_path / "sessions.jsonl"
    path.write_text(json.dumps({"key": jobs[0][1], "harness_error": None}) + "\n"
                    + json.dumps({"key": jobs[1][1], "harness_error": "HTTP 503"}) + "\n", encoding="utf-8")

    assert len(jobs) == 12
    assert runner.done_keys(path) == {runner.key_id(jobs[0][1])}


def test_cost_guard_stops_at_the_cap():
    guard = runner.CostGuard(1.0)
    guard.add(0.6)
    assert not guard.exhausted
    guard.add(0.5)
    assert guard.exhausted
