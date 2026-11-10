"""A tiny built-in model so Loopy runs without an API key, a model server, or a download."""

import asyncio
import re
from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

HELP = """\
**Loopy, offline demo model**

- Type a message and press **Enter**.
- **Ctrl+N** starts a new chat and **Ctrl+Q** quits.
- For a real model, restart with `loopy --model openai:<model-name>` (needs `OPENAI_API_KEY`),
  or with `loopy --model qwen3:8b --base-url http://localhost:11434/v1` for a local Ollama model.
"""


def user_prompts(messages: list[ModelMessage]) -> list[str]:
    prompts = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    prompts.append(part.content if isinstance(part.content, str) else str(part.content))
    return prompts


def reply_to(messages: list[ModelMessage]) -> str:
    prompts = user_prompts(messages)
    prompt = prompts[-1].strip() if prompts else ""
    if prompt.lower() in {"help", "/help", "?"}:
        return HELP
    return (
        f"> {prompt}\n\n"
        f"I'm Loopy's built-in offline model, so I can only echo you for now (message {len(prompts)} "
        "in this chat). The chat loop, streaming and usage tracking around me are real. "
        "Type `help` for keys, or restart with `--model` to use a real model."
    )


def offline_model(delay: float = 0.02) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(reply_to(messages))])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        for token in re.split(r"(\s+)", reply_to(messages)):
            if token:
                yield token
                if delay:
                    await asyncio.sleep(delay)

    return FunctionModel(respond, stream_function=stream, model_name="loopy-offline")
