"""Run the evaluation matrix against the deployed LedgerLens agent.

  python -m evals.runner --models deepseek.v3.2 openai.gpt-oss-120b-1:0 \\
      --prompts v10 --runs 3 --out evals/results/baseline-v10

Every session is appended to <out>/sessions.jsonl as soon as it ends, so a crash
loses nothing; --resume skips finished (case, model, prompt, run) keys. A harness
error (HTTP failure, error event) is retried once with a new session id and is
never graded as an agent failure.
Spec: docs/superpowers/specs/2026-10-04-eval-harness-design.md section 8.
"""

import argparse
import base64
import datetime
import functools
import hashlib
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import httpx
import jwt

from evals import config, stream
from evals.cases import load_cases, load_prompt

BUTTON_PROMPT = "[button]"  # the click request needs a non-empty prompt; the agent ignores it
MAX_CONFIRMATION_ROUNDS = 4
TOKEN_REFRESH_MARGIN_S = 300
OVERRIDE_REJECTED = "eval override rejected"
P07_CARD = "4497"


def session_id_for(key: dict) -> str:
    """ll-<case>-<model>-<prompt>-r<run>-<hex>: 33-100 chars of [a-zA-Z0-9-_], new each call."""
    prompt = re.sub(r"[^a-zA-Z0-9]+", "-", key["prompt"])
    prefix = f"ll-{key['case']}-{config.model_slug(key['model'])}-{prompt}-r{key['run']}-"
    return (prefix[:68] + uuid.uuid4().hex)[:100]


def key_id(key: dict) -> tuple:
    return (key["case"], key["model"], key["prompt"], key["run"])


def _new_session(case: dict, key: dict) -> dict:
    return {
        "key": key,
        "session_id": session_id_for(key),
        "case_id": case["id"],
        "persona": case["persona"],
        "customer_id": case["customer_id"],
        "requests": [],
        "unexpected_confirmations": [],
        "missing_confirmations": [],
        "harness_error": None,
    }


def run_session(case: dict, key: dict, eval_payload: dict, send) -> dict:
    """Drive one scripted session; send(session_id, body) -> (events, latency_s)."""
    session = _new_session(case, key)
    queue = list(case["confirmations"])

    def post(user_turn, kind, prompt, answers=(), clicks=None):
        body = {"prompt": prompt, "runtimeSessionId": session["session_id"], "eval": eval_payload}
        if clicks is not None:
            body["confirmations"] = clicks
        events, latency = send(session["session_id"], body)
        record = {"user_turn": user_turn, "kind": kind, "input": prompt,
                  "answers": list(answers), "latency_s": latency, **stream.digest(events)}
        session["requests"].append(record)
        return record

    for turn, message in enumerate(case["turns"], 1):
        record = post(turn, "say", message)
        rounds = 0
        while record["confirmations"] and not record["error"]:
            rounds += 1
            if rounds > MAX_CONFIRMATION_ROUNDS:
                session["harness_error"] = f"more than {MAX_CONFIRMATION_ROUNDS} confirmation rounds"
                return session
            answers, typed = [], None
            for pending in record["confirmations"]:
                if queue and queue[0]["tool"] == pending.get("tool"):
                    answer = queue.pop(0)["answer"]
                else:
                    session["unexpected_confirmations"].append(pending.get("tool"))
                    answer = "no"
                if isinstance(answer, dict):
                    typed = answer["type"]
                answers.append({"interruptId": pending.get("id"), "toolUseId": pending.get("toolUseId"),
                                "tool": pending.get("tool"), "answer": answer})
            if typed is not None:
                # A typed reply answers every pending confirmation (confirmation_hook.resume_prompt).
                for a in answers:
                    a["answer"] = "typed"
                record = post(turn, "typed", typed, answers)
            else:
                clicks = [{"interruptId": a["interruptId"], "approved": a["answer"] == "yes"} for a in answers]
                record = post(turn, "click", BUTTON_PROMPT, answers, clicks)
        if record["error"]:
            session["harness_error"] = record["error"]
            return session
    session["missing_confirmations"] = [q["tool"] for q in queue if not q.get("optional")]
    return session


def run_with_retry(case: dict, key: dict, eval_payload: dict, send) -> dict:
    """Run a session; retry a harness error once with a new session id."""
    for attempt in (1, 2):
        try:
            session = run_session(case, key, eval_payload, send)
        except Exception as e:  # login, HTTP or digest failure: record it, never crash the matrix
            session = {**_new_session(case, key), "harness_error": f"{type(e).__name__}: {e}"}
        session["attempt"] = attempt
        error = session["harness_error"]
        if not error or error.startswith(OVERRIDE_REJECTED):
            return session
    return session


class Logins:
    """Cognito access tokens per persona, refreshed 5 minutes before they expire."""

    def __init__(self, cognito, client_id: str, passwords: dict[str, str], clock=time.time):
        self._cognito, self._client_id, self._passwords, self._clock = cognito, client_id, passwords, clock
        self._tokens: dict[str, str] = {}
        self._lock = threading.Lock()

    def token(self, persona: str) -> str:
        with self._lock:
            token = self._tokens.get(persona)
            if token is None or self._expires(token) - self._clock() < TOKEN_REFRESH_MARGIN_S:
                result = self._cognito.initiate_auth(
                    AuthFlow="USER_PASSWORD_AUTH",
                    ClientId=self._client_id,
                    AuthParameters={"USERNAME": config.username(persona),
                                    "PASSWORD": self._passwords[persona]},
                )
                token = self._tokens[persona] = result["AuthenticationResult"]["AccessToken"]
            return token

    @staticmethod
    def _expires(token: str) -> float:
        return jwt.decode(token, options={"verify_signature": False}).get("exp", 0)


def make_send(http: httpx.Client, runtime_arn: str, logins: Logins):
    """send(persona, session_id, body) -> (events, latency_s) against the runtime."""
    url = (f"https://bedrock-agentcore.{config.REGION}.amazonaws.com/runtimes/"
           f"{quote(runtime_arn, safe='')}/invocations?qualifier=DEFAULT")

    def send(persona: str, session_id: str, body: dict):
        headers = {"Authorization": f"Bearer {logins.token(persona)}",
                   "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
                   "Content-Type": "application/json"}
        start = time.monotonic()
        with http.stream("POST", url, headers=headers, json=body) as response:
            response.raise_for_status()
            events = list(stream.parse_sse(response.iter_lines()))
        return events, time.monotonic() - start

    return send


def precheck_p07(lambda_client) -> str | None:
    """None when P07's card 4497 is Active with no open case; else what's wrong."""
    context = {"custom": {"bedrockAgentCoreToolName": "get-session-context-target___get_session_context"}}
    response = lambda_client.invoke(
        FunctionName="ledgerlens-get-session-context",
        ClientContext=base64.b64encode(json.dumps(context).encode()).decode(),
        Payload=json.dumps({"customer_id": config.PERSONAS["P07"]}).encode(),
    )
    outer = json.loads(response["Payload"].read())
    body = stream.parse_tool_body(outer.get("content"))
    if not isinstance(body, dict) or body.get("cards") is None:
        return f"P07 session context unreadable: {str(outer)[:200]}"
    status = {c.get("card_last4"): c.get("product_status") for c in body["cards"]}.get(P07_CARD)
    if status != "Active":
        return f"P07 card {P07_CARD} is {status}, expected Active"
    if body.get("open_cases"):
        return f"P07 has {len(body['open_cases'])} open case(s), expected none"
    return None


class CostGuard:
    """Stops new sessions once the spent estimate reaches the cap."""

    def __init__(self, cap_usd: float):
        self.cap, self.spent = cap_usd, 0.0
        self._lock = threading.Lock()

    def add(self, usd: float) -> None:
        with self._lock:
            self.spent += usd

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.cap


def matrix(cases: list[dict], models: list[str], prompts: list[str], runs: int) -> list[tuple[dict, dict]]:
    return [(c, {"case": c["id"], "model": m, "prompt": p, "run": r})
            for p in prompts for m in models for c in cases for r in range(1, runs + 1)]


def done_keys(path: Path) -> set[tuple]:
    """Keys already recorded without a harness error."""
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if not record.get("harness_error"):
            done.add(key_id(record["key"]))
    return done


def session_cost(session: dict) -> float:
    tokens_in = sum(r["usage"]["input"] for r in session["requests"])
    tokens_out = sum(r["usage"]["output"] for r in session["requests"])
    return config.session_cost(session["key"]["model"], tokens_in, tokens_out)


def run_matrix(jobs, send, out_path: Path, guard: CostGuard, concurrency: int, prompt_texts: dict) -> list[dict]:
    lock = threading.Lock()

    def job(case, key):
        if guard.exhausted:
            return None
        payload = {"model_id": key["model"], "prompt_name": key["prompt"],
                   "system_prompt": prompt_texts[key["prompt"]]}
        session = run_with_retry(case, key, payload, functools.partial(send, case["persona"]))
        guard.add(session_cost(session))
        with lock:
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(session, ensure_ascii=False) + "\n")
            status = f"ERROR {session['harness_error']}" if session["harness_error"] else "ok"
            print(f"{key_id(key)} {status} spent=${guard.spent:.2f}", flush=True)
        return session

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return [s for s in pool.map(lambda j: job(*j), jobs) if s is not None]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run LedgerLens evaluation sessions.")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--prompts", nargs="+", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", nargs="*", help="case ids (default: all)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-cost", type=float, default=15.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-precheck", action="store_true")
    args = parser.parse_args(argv)

    unknown = [m for m in args.models if m not in config.PRICES]
    if unknown:
        parser.error(f"no price for {unknown}; add it to evals/config.py PRICES")
    cases = load_cases()
    if args.cases:
        missing = set(args.cases) - {c["id"] for c in cases}
        if missing:
            parser.error(f"unknown case ids {sorted(missing)}")
        cases = [c for c in cases if c["id"] in args.cases]
    prompt_texts = {name: load_prompt(name) for name in args.prompts}

    out_path = args.out / "sessions.jsonl"
    if out_path.exists() and not args.resume:
        parser.error(f"{out_path} exists; pass --resume or use another --out")
    done = done_keys(out_path) if args.resume else set()
    jobs = [(c, k) for c, k in matrix(cases, args.models, args.prompts, args.runs) if key_id(k) not in done]
    estimate = sum(config.session_cost(k["model"], *config.ESTIMATED_TOKENS[k["model"]]) for _, k in jobs)
    print(f"{len(jobs)} sessions, estimated ${estimate:.2f}, cap ${args.max_cost:.2f}")
    if args.dry_run:
        for _, k in jobs:
            print(key_id(k))
        return 0

    env = config.read_env()
    personas = sorted({c["persona"] for c, _ in jobs})
    passwords = {p: env.get(f"EVAL_PASSWORD_{p}") for p in personas}
    if not all(passwords.values()):
        parser.error(f"evals/.env lacks passwords for {[p for p, v in passwords.items() if not v]}")
    session = config.aws_session()
    outputs = config.stack_outputs(session)
    if not args.skip_precheck and "P07" in personas:
        problem = precheck_p07(session.client("lambda"))
        if problem:
            print(f"PRECHECK FAILED: {problem}")
            return 1

    args.out.mkdir(parents=True, exist_ok=True)
    run_info = {
        "models": args.models,
        "prompts": {n: hashlib.sha256(t.encode("utf-8")).hexdigest()[:8] for n, t in prompt_texts.items()},
        "runs": args.runs,
        "cases": [c["id"] for c in cases],
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "agent_runtime_arn": outputs["RuntimeArn"],
    }
    (args.out / "run.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")
    logins = Logins(session.client("cognito-idp"), outputs["CognitoClientId"], passwords)
    guard = CostGuard(args.max_cost)
    with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0)) as http:
        sessions = run_matrix(jobs, make_send(http, outputs["RuntimeArn"], logins),
                              out_path, guard, args.concurrency, prompt_texts)
    errors = [s for s in sessions if s["harness_error"]]
    print(f"done: {len(sessions)} sessions, {len(errors)} harness errors, spent ${guard.spent:.2f}")
    if any(s["harness_error"].startswith(OVERRIDE_REJECTED) for s in errors):
        print("The agent rejected the eval override: check the login's group and EVAL_MODEL_IDS.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
