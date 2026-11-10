import argparse
import os

import pydantic_ai
from pydantic_ai.exceptions import UserError
from rich.table import Table
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, Markdown, Static

from loopy.agent.chat import ChatSession
from loopy.agent.models import ModelChoice, resolve_model


class UserMessage(Static):
    pass


class AssistantMessage(Markdown):
    pass


class ErrorMessage(Static):
    pass


class UsagePanel(Static):
    def show_usage(self, session: ChatSession) -> None:
        usage = session.usage
        if session.choice.runs_locally:
            cost = "$0 (local)"
        elif usage.cost is None:
            cost = "unknown"
        else:
            cost = f"${usage.cost:.4f}"
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold")
        table.add_column()
        table.add_row("Model", session.choice.label)
        table.add_row("Runs", "on this machine" if session.choice.runs_locally else "in the cloud")
        table.add_row("Requests", str(usage.requests))
        table.add_row("Tokens in", f"{usage.input_tokens:,}")
        table.add_row("Tokens out", f"{usage.output_tokens:,}")
        table.add_row("Cost", cost)
        table.add_row("Cloud calls", str(session.cloud_requests))
        self.update(table)


class LoopyApp(App[None]):
    TITLE = "Loopy"
    CSS_PATH = "tui.tcss"
    AUTO_FOCUS = "#prompt"
    BINDINGS = [
        Binding("ctrl+n", "new_chat", "New chat"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, choice: ModelChoice) -> None:
        super().__init__()
        # PydanticAI prints a first-run banner to the terminal, which would draw over the TUI.
        pydantic_ai.BANNER_ENABLED = False
        self.session = ChatSession(choice)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="chat"):
                yield VerticalScroll(id="messages")
                yield Input(placeholder="Ask Loopy something, or type help", id="prompt")
            yield UsagePanel(id="usage")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.session.choice.label
        self.query_one("#messages", VerticalScroll).anchor()
        self.query_one(UsagePanel).show_usage(self.session)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if not prompt:
            return
        event.input.clear()
        event.input.disabled = True
        reply = AssistantMessage()
        await self.query_one("#messages", VerticalScroll).mount(UserMessage(prompt, markup=False), reply)
        self.respond(prompt, reply)

    @work(exclusive=True)
    async def respond(self, prompt: str, reply: AssistantMessage) -> None:
        stream = Markdown.get_stream(reply)
        try:
            async for delta in self.session.stream(prompt):
                await stream.write(delta)
        except Exception as error:
            await self.query_one("#messages", VerticalScroll).mount(
                ErrorMessage(f"{type(error).__name__}: {error}", markup=False)
            )
        finally:
            await stream.stop()
            self.query_one(UsagePanel).show_usage(self.session)
            prompt_input = self.query_one("#prompt", Input)
            prompt_input.disabled = False
            prompt_input.focus()

    async def action_new_chat(self) -> None:
        self.workers.cancel_all()
        self.session.new_chat()
        await self.query_one("#messages", VerticalScroll).remove_children()
        prompt_input = self.query_one("#prompt", Input)
        prompt_input.disabled = False
        prompt_input.focus()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="loopy", description="Chat with Loopy in the terminal.")
    parser.add_argument(
        "--model",
        default=os.environ.get("LOOPY_MODEL", "offline"),
        help="'offline' (the built-in default), 'test' (PydanticAI's test model), a PydanticAI model "
        "name such as 'openai:<model>', or the name of a model served at --base-url",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LOOPY_BASE_URL"),
        help="OpenAI-compatible endpoint, for example http://localhost:11434/v1 for Ollama",
    )
    args = parser.parse_args(argv)
    try:
        choice = resolve_model(args.model, args.base_url, os.environ.get("LOOPY_API_KEY"))
    except UserError as error:
        parser.exit(2, f"loopy: {error}\n")
    LoopyApp(choice).run()
