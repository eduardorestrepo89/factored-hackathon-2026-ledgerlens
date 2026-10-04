"""Unit tests for the filter that strips leaked tool-call markup from the stream.

The module lives at ``agent/ledgerlens/tools/leaked_markup.py`` and has no
runtime dependencies. The marker text is the one DeepSeek V3.2 leaked on Bedrock.
"""

import importlib
import sys
from pathlib import Path

import pytest

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "agent" / "ledgerlens"
MARKER = "<｜DSML｜function_calls"


@pytest.fixture(scope="module")
def markup():
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    return importlib.import_module("tools.leaked_markup")


def streamed_text(markup, chunks):
    """Feed text chunks, then the end of the message; return the text sent."""
    stream = markup.LeakedMarkupFilter()
    events = [e for c in chunks for e in stream.clean({"data": c})]
    events += stream.clean({"message": {"role": "assistant", "content": []}})
    return "".join(e["data"] for e in events if "data" in e)


def test_the_marker_is_removed_from_a_chunk(markup):
    assert streamed_text(markup, [f"{MARKER} La tarjeta 4497 está bloqueada."]) == (
        "La tarjeta 4497 está bloqueada."
    )


def test_a_marker_split_across_chunks_is_removed(markup):
    chunks = ["Revisemos los cargos.\n\n<｜DS", "ML｜func", "tion_calls Estos son"]

    assert streamed_text(markup, chunks) == "Revisemos los cargos.\n\nEstos son"


def test_text_that_only_looks_like_a_marker_start_is_kept(markup):
    # "<" at the end of a chunk is held back, then sent when the message ends.
    assert streamed_text(markup, ["Monto <", " 500 USD"]) == "Monto < 500 USD"
    assert streamed_text(markup, ["termina en 4497 <"]) == "termina en 4497 <"


def test_complete_messages_are_cleaned_too(markup):
    event = {"message": {"role": "assistant", "content": [{"text": f"{MARKER} Listo"}, {"toolUse": {}}]}}

    cleaned = markup.LeakedMarkupFilter().clean(event)

    assert cleaned == [{"message": {"role": "assistant", "content": [{"text": "Listo"}, {"toolUse": {}}]}}]


def test_other_events_pass_through(markup):
    event = {"current_tool_use": {"name": "x"}, "delta": {"toolUse": {"input": ""}}}

    assert markup.LeakedMarkupFilter().clean(event) == [event]
