import asyncio
from collections.abc import AsyncIterator

from pydantic_ai.models.function import AgentInfo, FunctionModel
from textual.widgets import Input

from loopy.agent.models import ModelChoice
from loopy.agent.offline import offline_model
from loopy.app.tui import AssistantMessage, ErrorMessage, LoopyApp, UserMessage


def offline_app() -> LoopyApp:
    return LoopyApp(ModelChoice(offline_model(delay=0), "offline demo model", runs_locally=True))


async def send(app: LoopyApp, pilot, prompt: str) -> None:
    app.query_one("#prompt", Input).value = prompt
    await pilot.press("enter")
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_prompt_gets_a_streamed_reply():
    async def scenario() -> None:
        app = offline_app()
        async with app.run_test() as pilot:
            await send(app, pilot, "turn these emails into to-dos")

            assert len(app.query(UserMessage)) == 1
            assert "turn these emails into to-dos" in app.query_one(AssistantMessage).source
            assert app.session.usage.requests == 1
            assert not app.query_one("#prompt", Input).disabled

    asyncio.run(scenario())


def test_new_chat_clears_the_conversation():
    async def scenario() -> None:
        app = offline_app()
        async with app.run_test() as pilot:
            await send(app, pilot, "hello")
            await pilot.press("ctrl+n")
            await pilot.pause()

            assert not app.query(AssistantMessage)
            assert app.session.history == []

    asyncio.run(scenario())


def test_model_errors_are_shown_in_the_chat():
    async def failing_stream(messages: list, info: AgentInfo) -> AsyncIterator[str]:
        raise RuntimeError("model server is down")
        yield ""

    async def scenario() -> None:
        app = LoopyApp(ModelChoice(FunctionModel(stream_function=failing_stream), "broken", runs_locally=True))
        async with app.run_test() as pilot:
            await send(app, pilot, "hello")

            assert len(app.query(ErrorMessage)) == 1
            assert not app.query_one("#prompt", Input).disabled

    asyncio.run(scenario())
