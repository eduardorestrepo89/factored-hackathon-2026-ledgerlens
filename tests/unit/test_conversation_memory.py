"""Unit tests for the Strands agent's short-term memory (conversation manager).

The module lives at ``patterns/strands-single-agent/tools/conversation_memory.py``
and is configured from STM_* env vars. It imports strands (requirements-dev.txt).
"""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.handlers.callback_handler import null_callback_handler

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "patterns" / "strands-single-agent"

STM_ENV = (
    "STM_WINDOW_SIZE",
    "USE_STM_SUMMARIZATION",
    "STM_SUMMARY_RATIO",
    "STM_PRESERVE_RECENT_MESSAGES",
    "STM_SUMMARIZATION_MODEL_ID",
    "STM_SUMMARIZATION_PROMPT",
)
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


@pytest.fixture(scope="module")
def memory():
    """Import tools/conversation_memory.py from the strands pattern."""
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    return importlib.import_module("tools.conversation_memory")


@pytest.fixture(autouse=True)
def no_stm_env(monkeypatch):
    for name in STM_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def summarizing(monkeypatch):
    monkeypatch.setenv("USE_STM_SUMMARIZATION", "true")


def _messages(n):
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": [{"text": f"m{i}"}]}
        for i in range(n)
    ]


def _windowed(memory, window_size, preserve_recent_messages):
    return memory.WindowedSummarizingConversationManager(
        window_size=window_size,
        preserve_recent_messages=preserve_recent_messages,
        summarization_system_prompt="summarize",
    )


def test_default_is_a_sliding_window_of_30_messages(memory):
    manager = memory.create_conversation_manager()

    # a sliding window that also restores sessions saved while summarizing
    assert type(manager) is memory.StmSlidingWindowConversationManager
    assert isinstance(manager, SlidingWindowConversationManager)
    assert manager.window_size == 30


def test_window_size_comes_from_the_env(memory, monkeypatch):
    monkeypatch.setenv("STM_WINDOW_SIZE", "12")

    assert memory.create_conversation_manager().window_size == 12


def test_summarization_flag_is_case_insensitive_and_reads_its_settings(
    memory, monkeypatch
):
    monkeypatch.setenv("USE_STM_SUMMARIZATION", "TRUE")
    monkeypatch.setenv("STM_WINDOW_SIZE", "20")
    monkeypatch.setenv("STM_SUMMARY_RATIO", "0.5")
    monkeypatch.setenv("STM_PRESERVE_RECENT_MESSAGES", "6")

    manager = memory.create_conversation_manager()

    assert isinstance(manager, memory.WindowedSummarizingConversationManager)
    assert manager.window_size == 20
    assert manager.summary_ratio == 0.5
    assert manager.preserve_recent_messages == 6


def test_preserved_messages_must_be_fewer_than_the_window(
    memory, monkeypatch, summarizing
):
    monkeypatch.setenv("STM_WINDOW_SIZE", "10")
    monkeypatch.setenv("STM_PRESERVE_RECENT_MESSAGES", "10")

    with pytest.raises(ValueError, match="STM_PRESERVE_RECENT_MESSAGES"):
        memory.create_conversation_manager()


def test_default_summarizer_is_the_agents_model_with_the_banking_prompt(
    memory, summarizing
):
    manager = memory.create_conversation_manager()

    assert manager.summarization_agent is None
    assert manager.summarization_system_prompt == memory.STM_SUMMARY_PROMPT


def test_prompt_override_replaces_the_banking_prompt(memory, monkeypatch, summarizing):
    monkeypatch.setenv("STM_SUMMARIZATION_PROMPT", "Keep every amount.")

    manager = memory.create_conversation_manager()

    assert manager.summarization_system_prompt == "Keep every amount."


def test_model_id_builds_a_summarization_agent_on_that_model(
    memory, monkeypatch, summarizing
):
    monkeypatch.setenv("STM_SUMMARIZATION_MODEL_ID", HAIKU)

    manager = memory.create_conversation_manager()
    summarizer = manager.summarization_agent

    # Strands rejects an agent and a prompt together, so the prompt moves to the agent.
    assert manager.summarization_system_prompt is None
    assert summarizer.model.get_config()["model_id"] == HAIKU
    assert summarizer.system_prompt == memory.STM_SUMMARY_PROMPT
    # Privacy: it never writes into the customer's session or prints the summary.
    assert summarizer._session_manager is None
    assert summarizer.callback_handler is null_callback_handler


def test_summarization_agent_gets_the_prompt_override(memory, monkeypatch, summarizing):
    monkeypatch.setenv("STM_SUMMARIZATION_MODEL_ID", HAIKU)
    monkeypatch.setenv("STM_SUMMARIZATION_PROMPT", "Keep every amount.")

    manager = memory.create_conversation_manager()

    assert manager.summarization_agent.system_prompt == "Keep every amount."


def test_whitespace_only_settings_count_as_empty(memory, monkeypatch, summarizing):
    monkeypatch.setenv("STM_SUMMARIZATION_MODEL_ID", "  ")
    monkeypatch.setenv("STM_SUMMARIZATION_PROMPT", " \n ")

    manager = memory.create_conversation_manager()

    assert manager.summarization_agent is None
    assert manager.summarization_system_prompt == memory.STM_SUMMARY_PROMPT


def test_apply_management_summarizes_only_above_the_window(memory, monkeypatch):
    manager = _windowed(memory, window_size=4, preserve_recent_messages=2)
    calls = []
    monkeypatch.setattr(
        manager, "reduce_context", lambda agent, **_: calls.append(agent)
    )
    at_window = SimpleNamespace(messages=_messages(4))
    above_window = SimpleNamespace(messages=_messages(5))

    manager.apply_management(at_window)
    manager.apply_management(above_window)

    assert calls == [above_window]


def _throttled(messages, agent):
    raise RuntimeError("throttled")


def test_a_failed_summary_keeps_the_history_and_the_removed_count(memory, monkeypatch):
    # strands counts the removed messages before it calls the model
    manager = _windowed(memory, window_size=4, preserve_recent_messages=2)
    monkeypatch.setattr(manager, "_generate_summary", _throttled)
    agent = SimpleNamespace(messages=_messages(5))
    before = list(agent.messages)

    manager.apply_management(agent)

    assert manager.removed_message_count == 0
    assert agent.messages == before


def test_a_failed_overflow_summary_keeps_the_removed_count(memory, monkeypatch):
    # On a context overflow strands calls reduce_context itself, and its finally
    # block then syncs the session: the count must already be back by then.
    manager = _windowed(memory, window_size=30, preserve_recent_messages=10)
    monkeypatch.setattr(manager, "_generate_summary", _throttled)
    agent = SimpleNamespace(messages=_messages(31))
    before = list(agent.messages)

    with pytest.raises(RuntimeError, match="throttled"):
        manager.reduce_context(agent)

    assert manager.removed_message_count == 0
    assert agent.messages == before


def test_turning_summarization_on_restores_a_sliding_window_session(memory):
    # strands rejects a saved state from another manager class, which would fail
    # every session in flight when use_stm_summarization changes.
    saved = SlidingWindowConversationManager(window_size=30).get_state()
    saved["removed_message_count"] = 4
    manager = _windowed(memory, window_size=30, preserve_recent_messages=10)

    prepend = manager.restore_from_session(saved)

    assert prepend is None
    assert manager.removed_message_count == 4


def test_turning_summarization_off_keeps_the_sessions_summary(memory):
    summarizing = _windowed(memory, window_size=30, preserve_recent_messages=10)
    summary = {"role": "user", "content": [{"text": "summary of m0-m8"}]}
    summarizing._summary_message = summary
    summarizing.removed_message_count = 9
    manager = memory.create_conversation_manager()  # summarization off

    prepend = manager.restore_from_session(summarizing.get_state())

    # the summary stands for the 9 messages before the restore offset
    assert prepend == [summary]
    assert manager.removed_message_count == 9


def test_the_window_restores_sessions_saved_by_the_strands_default(memory):
    # Sessions in flight before this change were saved by Agent's default manager.
    saved = SlidingWindowConversationManager().get_state()
    saved["removed_message_count"] = 2
    manager = memory.create_conversation_manager()

    manager.restore_from_session(saved)

    assert manager.removed_message_count == 2


def test_an_unrelated_manager_state_is_still_rejected(memory):
    saved = {"__name__": "NullConversationManager", "removed_message_count": 0}

    with pytest.raises(ValueError, match="Invalid conversation manager state"):
        memory.create_conversation_manager().restore_from_session(saved)


def test_31_messages_become_a_summary_plus_the_newest_22(memory, monkeypatch):
    manager = memory.WindowedSummarizingConversationManager(
        window_size=30,
        summary_ratio=0.3,
        preserve_recent_messages=10,
        summarization_system_prompt="summarize",
    )
    summary = {"role": "user", "content": [{"text": "summary of m0-m8"}]}
    monkeypatch.setattr(manager, "_generate_summary", lambda messages, agent: summary)
    messages = _messages(31)
    agent = SimpleNamespace(messages=list(messages))

    manager.apply_management(agent)

    # int(31 * 0.3) = 9 oldest messages become one summary
    assert agent.messages == [summary] + messages[9:]
    assert manager.removed_message_count == 9
