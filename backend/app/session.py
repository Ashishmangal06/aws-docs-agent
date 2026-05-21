import logging
from collections import defaultdict
from langchain.schema import HumanMessage, AIMessage, BaseMessage

logger = logging.getLogger(__name__)

# In-memory store: {session_id: [BaseMessage, ...]}
# For production: replace with Redis via langchain_community.chat_message_histories.RedisChatMessageHistory
_store: dict[str, list[BaseMessage]] = defaultdict(list)

MAX_HISTORY_TURNS = 10  # keep last 10 turns (20 messages) per session


class SessionStore:

    @staticmethod
    def get_history(session_id: str) -> list[BaseMessage]:
        return _store[session_id]

    @staticmethod
    def add_turn(session_id: str, user_message: str, assistant_message: str):
        _store[session_id].append(HumanMessage(content=user_message))
        _store[session_id].append(AIMessage(content=assistant_message))

        # Trim to last MAX_HISTORY_TURNS turns
        max_messages = MAX_HISTORY_TURNS * 2
        if len(_store[session_id]) > max_messages:
            _store[session_id] = _store[session_id][-max_messages:]

        logger.debug(
            f"Session {session_id}: {len(_store[session_id])} messages stored"
        )

    @staticmethod
    def clear(session_id: str):
        _store[session_id] = []
        logger.info(f"Session {session_id} cleared")

    @staticmethod
    def all_sessions() -> list[str]:
        return list(_store.keys())