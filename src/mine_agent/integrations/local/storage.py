from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, List

from mine_agent.core.storage.base import ConversationStore
from mine_agent.core.storage.models import Message


class InMemoryConversationStore(ConversationStore):
    def __init__(self) -> None:
        self._messages: DefaultDict[str, List[Message]] = defaultdict(list)

    async def get_messages(self, conversation_id: str) -> List[Message]:
        return list(self._messages[conversation_id])

    async def append_message(self, conversation_id: str, message: Message) -> None:
        self._messages[conversation_id].append(message)
