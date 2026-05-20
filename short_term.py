# memory/short_term.py  —  Phase 2
from __future__ import annotations
import logging
from langchain_core.messages import HumanMessage, AIMessage

logger = logging.getLogger(__name__)

class ShortTermMemory:
    """Sliding window of recent Human/AI message pairs."""

    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self.history: list[HumanMessage | AIMessage] = []
        logger.info(f"ShortTermMemory ready (window={window_size})")

    def add(self, role: str, content: str) -> None:
        self.history.append(
            HumanMessage(content=content) if role == "human"
            else AIMessage(content=content)
        )
        # Keep last N pairs (N*2 messages)
        limit = self.window_size * 2
        if len(self.history) > limit:
            self.history = self.history[-limit:]

    def get(self) -> list[HumanMessage | AIMessage]:
        return self.history

    def clear(self) -> None:
        self.history = []
        logger.info("ShortTermMemory cleared")

    def is_empty(self) -> bool:
        return len(self.history) == 0

    def summary(self) -> str:
        return f"{len(self.history)} messages in short-term window"

    def __len__(self) -> int:
        return len(self.history)