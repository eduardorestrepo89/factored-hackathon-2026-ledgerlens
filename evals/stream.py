"""Turn the agent's server-sent events into one compact record per request.

The runtime streams Strands callback events as `data: <json>` lines
(agent/ledgerlens/ledgerlens_agent.py, invocations). Graders read only this
digest: complete `message` events (never text deltas), `confirmation` events,
raw Bedrock `event` chunks for token usage and stop reasons, and
`{"status": "error"}`. A line that isn't JSON is counted, never raised.
"""

import json
from typing import Iterable, Iterator


def parse_sse(lines: Iterable[str | bytes]) -> Iterator[dict]:
    """Yield each `data:` line's JSON object; bad JSON yields {"_unparsed": line}."""
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            yield {"_unparsed": line[:200]}
            continue
        if isinstance(event, dict):
            yield event


def bare_tool_name(name: str) -> str:
    """gateway_<target>___<tool> -> <tool>."""
    return str(name).rpartition("___")[2]


def parse_tool_body(content) -> object:
    """A tool result's JSON body, unwrapping the Lambda's {"content": [{"text"}]} once."""
    text = "".join(
        block["text"]
        for block in content or []
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    if (
        isinstance(body, dict)
        and isinstance(body.get("content"), list)
        and body["content"]
    ):
        inner = body["content"][0]
        if isinstance(inner, dict) and isinstance(inner.get("text"), str):
            try:
                return json.loads(inner["text"])
            except json.JSONDecodeError:
                return {"raw": inner["text"]}
    return body


def digest(events: Iterable[dict]) -> dict:
    """Summarise one request's events for the graders."""
    out = {
        "text": "",
        "tool_calls": [],
        "tool_results": [],
        "confirmations": [],
        "usage": {"input": 0, "output": 0},
        "stop_reasons": [],
        "error": None,
        "throttled": False,
        "unparsed": 0,
    }
    texts: list[str] = []
    for event in events:
        if "_unparsed" in event:
            out["unparsed"] += 1
            continue
        if event.get("status") == "error":
            out["error"] = str(event.get("error") or "unknown error")
            continue
        if isinstance(event.get("confirmation"), dict):
            out["confirmations"].append(event["confirmation"])
            continue
        if "event_loop_throttled_delay" in event:
            out["throttled"] = True
        raw = event.get("event")
        if isinstance(raw, dict):
            usage = (raw.get("metadata") or {}).get("usage") or {}
            out["usage"]["input"] += int(usage.get("inputTokens") or 0)
            out["usage"]["output"] += int(usage.get("outputTokens") or 0)
            stop = (raw.get("messageStop") or {}).get("stopReason")
            if stop:
                out["stop_reasons"].append(stop)
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if message.get("role") == "assistant":
                if isinstance(block.get("text"), str):
                    texts.append(block["text"])
                use = block.get("toolUse")
                if isinstance(use, dict):
                    out["tool_calls"].append(
                        {
                            "id": use.get("toolUseId"),
                            "name": bare_tool_name(use.get("name", "")),
                            "full_name": use.get("name"),
                            "input": use["input"]
                            if isinstance(use.get("input"), dict)
                            else {},
                        }
                    )
            elif message.get("role") == "user":
                res = block.get("toolResult")
                if isinstance(res, dict):
                    out["tool_results"].append(
                        {
                            "id": res.get("toolUseId"),
                            "status": res.get("status"),
                            "body": parse_tool_body(res.get("content")),
                        }
                    )
    out["text"] = "\n".join(t for t in texts if t.strip())
    return out
