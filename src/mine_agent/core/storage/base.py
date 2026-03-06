from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from mine_agent.core.storage.models import Message


class ConversationStore(ABC):
    @abstractmethod
    async def get_messages(self, conversation_id: str) -> List[Message]:
        raise NotImplementedError

    @abstractmethod
    async def append_message(self, conversation_id: str, message: Message) -> None:
        raise NotImplementedError
