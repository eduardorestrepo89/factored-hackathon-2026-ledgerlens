"""Short-term memory for the Strands agent, configured from STM_* env vars.

STM_WINDOW_SIZE caps the messages sent to the model per turn. With
USE_STM_SUMMARIZATION=true, the oldest messages are summarized once the
history exceeds the window, instead of being dropped.
STM_SUMMARIZATION_MODEL_ID picks the model that writes the summary (empty: the
agent's own model), and STM_SUMMARIZATION_PROMPT replaces STM_SUMMARY_PROMPT.

Checked against strands-agents 1.32.0: SummarizingConversationManager only
summarizes on context overflow, so WindowedSummarizingConversationManager
also triggers it from apply_management at the window size.
"""

import logging
import os

from strands import Agent
from strands.agent.conversation_manager import (
    ConversationManager,
    SlidingWindowConversationManager,
    SummarizingConversationManager,
)
from strands.models import BedrockModel

logger = logging.getLogger(__name__)

STM_SUMMARY_PROMPT = """Summarize the conversation as concise third-person bullets.
You MUST preserve verbatim: card last-4 digits, transaction IDs, amounts with currency,
dates, fraud classifications, claim and complaint IDs, and any action taken or promised
(card blocked, dispute opened, hand-off requested). Then list open questions.
The customer profile and session context are in the system prompt; do not repeat them."""

# strands rejects a saved state from another manager class, so a session saved by
# any of these restores into whichever one the config builds now: changing
# use_stm_summarization doesn't fail every session in flight.
_STM_STATE_NAMES = frozenset(
    {
        "SlidingWindowConversationManager",  # strands' default, before STM_* existed
        "StmSlidingWindowConversationManager",
        "WindowedSummarizingConversationManager",
    }
)


def _restorable(manager: ConversationManager, state: dict) -> dict:
    """Relabel a state saved by another STM manager as this manager's own."""
    if state.get("__name__") in _STM_STATE_NAMES:
        return {**state, "__name__": type(manager).__name__}
    return state


class StmSlidingWindowConversationManager(SlidingWindowConversationManager):
    """The sliding window, also restoring a session saved while summarizing."""

    def restore_from_session(self, state: dict) -> list | None:
        super().restore_from_session(_restorable(self, state))
        # The summary stands for the messages before the restore offset.
        summary = state.get("summary_message")
        return [summary] if summary else None


class WindowedSummarizingConversationManager(SummarizingConversationManager):
    """Summarize the oldest messages once the history exceeds window_size."""

    def __init__(self, window_size: int, **kwargs):
        super().__init__(**kwargs)
        self.window_size = window_size

    def restore_from_session(self, state: dict) -> list | None:
        return super().restore_from_session(_restorable(self, state))

    def reduce_context(self, agent, e=None, **kwargs) -> None:
        # strands adds to removed_message_count before the summary call. If the call
        # fails, put the count back, or the session restores from the wrong offset.
        # Here, not in apply_management: strands also calls this on a context
        # overflow and then syncs the session.
        removed_message_count = self.removed_message_count
        try:
            super().reduce_context(agent, e, **kwargs)
        except Exception:
            self.removed_message_count = removed_message_count
            raise

    def apply_management(self, agent, **kwargs) -> None:
        if len(agent.messages) <= self.window_size:
            return
        try:
            self.reduce_context(agent)
        except Exception:
            logger.exception(
                "[STM] Summarization failed; keeping the full history until next turn"
            )


def create_conversation_manager() -> ConversationManager:
    """Build the short-term memory manager from the STM_* env vars."""
    window_size = int(os.environ.get("STM_WINDOW_SIZE", "30"))
    use_summarization = (
        os.environ.get("USE_STM_SUMMARIZATION", "false").lower() == "true"
    )

    if not use_summarization:
        return StmSlidingWindowConversationManager(window_size=window_size)

    preserve_recent_messages = int(os.environ.get("STM_PRESERVE_RECENT_MESSAGES", "10"))
    if preserve_recent_messages >= window_size:
        raise ValueError(
            "STM_PRESERVE_RECENT_MESSAGES must be less than STM_WINDOW_SIZE"
        )

    prompt = (
        os.environ.get("STM_SUMMARIZATION_PROMPT", "").strip() or STM_SUMMARY_PROMPT
    )
    model_id = os.environ.get("STM_SUMMARIZATION_MODEL_ID", "").strip()
    # Strands rejects both together: an agent brings its own system prompt.
    if model_id:
        summarizer = {
            "summarization_agent": Agent(
                name="stm_summarizer",
                model=BedrockModel(model_id=model_id, temperature=0),
                system_prompt=prompt,
                # No tools and no session manager: it must not write into the
                # customer's session. No callback handler: the default one prints
                # the summary, customer data included, to the runtime logs.
                callback_handler=None,
            )
        }
    else:
        summarizer = {"summarization_system_prompt": prompt}

    return WindowedSummarizingConversationManager(
        window_size=window_size,
        summary_ratio=float(os.environ.get("STM_SUMMARY_RATIO", "0.3")),
        preserve_recent_messages=preserve_recent_messages,
        **summarizer,
    )
