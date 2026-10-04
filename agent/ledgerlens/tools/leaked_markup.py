"""Strip tool-call markup some models leak into their reply text.

On Bedrock, DeepSeek V3.2 sometimes starts the text after a tool call with its raw
tool-call marker, "<｜DSML｜function_calls", which the chat would show to the
customer. The frontend renders text from each event's "data" field, so the
filter cleans that field as it streams. The marker can arrive split across
chunks, so a chunk ending in the start of the marker is held back until the next
chunk or the end of the message.
"""

MARKERS = ("<｜DSML｜function_calls",)


def _strip(text: str) -> str:
    for marker in MARKERS:
        text = text.replace(marker + " ", "").replace(marker, "")
    return text


def _held_tail(text: str) -> int:
    """Length of the longest text ending that could start a marker (0 if none)."""
    for size in range(min(len(text), max(len(m) for m in MARKERS) - 1), 0, -1):
        if any(m.startswith(text[-size:]) for m in MARKERS):
            return size
    return 0


class LeakedMarkupFilter:
    """Remove the markers from Strands stream events before they reach the client."""

    def __init__(self):
        self._held = ""

    def clean(self, event: dict) -> list[dict]:
        """Return the events to send for one stream event: zero, one or two."""
        if isinstance(event.get("data"), str):
            text = _strip(self._held + event["data"])
            size = _held_tail(text)
            self._held = text[len(text) - size :] if size else ""
            text = text[: len(text) - size]
            return [{**event, "data": text}] if text else []
        if "message" in event or "result" in event:
            # The message is complete, so nothing held back can still become a marker.
            held, self._held = self._held, ""
            return ([{"data": held}] if held else []) + [_clean_message(event)]
        return [event]


def _clean_message(event: dict) -> dict:
    """Strip the markers from the text blocks of a complete message event."""
    message = event.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        return event
    content = [
        {**block, "text": _strip(block["text"])}
        if isinstance(block, dict) and isinstance(block.get("text"), str)
        else block
        for block in message["content"]
    ]
    return {**event, "message": {**message, "content": content}}
