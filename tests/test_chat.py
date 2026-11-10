import asyncio

from loopy.agent.chat import ChatSession
from loopy.agent.models import ModelChoice
from loopy.agent.offline import offline_model


def offline_session() -> ChatSession:
    return ChatSession(ModelChoice(offline_model(delay=0), "offline demo model", runs_locally=True))


async def collect(session: ChatSession, prompt: str) -> str:
    return "".join([delta async for delta in session.stream(prompt)])


def test_offline_session_streams_replies_and_keeps_history():
    session = offline_session()

    async def chat() -> tuple[str, str]:
        return await collect(session, "split the dinner bill"), await collect(session, "again")

    first, second = asyncio.run(chat())

    assert "split the dinner bill" in first
    assert "message 1 " in first
    assert "message 2 " in second
    assert len(session.history) == 4
    assert session.usage.requests == 2
    assert session.cloud_requests == 0


def test_help_lists_the_keys():
    reply = asyncio.run(collect(offline_session(), "help"))

    assert "Ctrl+N" in reply


def test_new_chat_forgets_history():
    session = offline_session()
    asyncio.run(collect(session, "hello"))

    session.new_chat()

    assert session.history == []
    assert session.usage.requests == 1
