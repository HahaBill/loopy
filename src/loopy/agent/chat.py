from collections.abc import AsyncIterator

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import RunUsage

from loopy.agent.models import ModelChoice

INSTRUCTIONS = (
    "You are Loopy, a local-first assistant that helps people automate digital tasks they repeat. "
    "Answer briefly."
)


class ChatSession:
    """One conversation with one model, plus the usage it has cost so far."""

    def __init__(self, choice: ModelChoice) -> None:
        self.choice = choice
        self.agent = Agent(choice.model, instructions=INSTRUCTIONS)
        self.history: list[ModelMessage] = []
        self.usage = RunUsage()
        self.cloud_requests = 0

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        async with self.agent.run_stream(prompt, message_history=self.history) as result:
            async for delta in result.stream_text(delta=True):
                yield delta
        self.history = result.all_messages()
        self.usage = self.usage + result.usage
        if not self.choice.runs_locally:
            self.cloud_requests += result.usage.requests

    def new_chat(self) -> None:
        self.history = []
