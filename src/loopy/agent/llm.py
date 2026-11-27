"""One request to one model, with what it cost in tokens, dollars and seconds.

`ModelSpec` is the part of an experiment config that names a model. `PydanticAIChat` sends a plain list of
{"role", "content"} messages through the same model layer the app uses (`loopy.agent.models.resolve_model`),
so experiments and the app reach models the same way. `ScriptedChat` replays fixed replies for tests.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol
from urllib.parse import urlparse

Message = dict[str, str]


@dataclass(frozen=True)
class ModelSpec:
    key: str  # the name configs and logs use, for example "small" or "cloud"
    role: str  # "small" (the model Loopy tries first) or "cloud" (the bigger model it can pay for)
    name: str  # the model id the server expects
    base_url: str | None = None  # an OpenAI-compatible endpoint; None means a PydanticAI model name
    api_key_env: str | None = None  # the environment variable holding the key (never the key itself)
    usd_per_mtok_in: float = 0.0
    usd_per_mtok_out: float = 0.0
    temperature: float = 0.0
    max_tokens: int = 1500
    seed: int | None = 123
    context_budget_tokens: int | None = None  # trim old steps when the prompt would exceed this estimate
    request_timeout: float = 180.0
    extra_body: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, key: str, data: dict[str, Any]) -> "ModelSpec":
        known = {item.name for item in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"model '{key}': unknown settings {sorted(unknown)}")
        return cls(key=key, **data)

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.usd_per_mtok_in + output_tokens * self.usd_per_mtok_out) / 1_000_000

    @property
    def provider(self) -> str:
        """Who bills for this model: "local", a host's registered domain, or a PydanticAI provider name."""
        host = urlparse(self.base_url).hostname if self.base_url else None
        if not host:
            return "pydantic-ai:" + self.name.split(":", 1)[0]
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return "local"
        return ".".join(host.split(".")[-2:])


@dataclass
class Reply:
    text: str
    input_tokens: int
    output_tokens: int
    seconds: float
    model_id: str | None = None
    finish_reason: str | None = None
    thinking: str = ""
    attempts: int = 1


class ChatModel(Protocol):
    spec: ModelSpec
    runs_locally: bool

    def complete(self, messages: list[Message]) -> Reply: ...


def merge_same_role(messages: Iterable[Message]) -> list[Message]:
    """Join neighbouring messages from the same role. Some chat templates reject two user turns in a row."""
    merged: list[Message] = []
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1] = {"role": message["role"], "content": merged[-1]["content"] + "\n\n" + message["content"]}
        else:
            merged.append(dict(message))
    return merged


class PydanticAIChat:
    def __init__(self, spec: ModelSpec, retries: int = 4) -> None:
        from loopy.agent.models import resolve_model

        api_key = os.environ.get(spec.api_key_env) if spec.api_key_env else None
        if spec.api_key_env and not api_key:
            raise RuntimeError(f"{spec.api_key_env} is not set. Put it in .env (see .env.example).")
        choice = resolve_model(spec.name, spec.base_url, api_key)
        self.spec = spec
        self.model = choice.model
        self.runs_locally = choice.runs_locally
        self.retries = retries

    def complete(self, messages: list[Message]) -> Reply:
        from pydantic_ai.direct import model_request_sync
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            SystemPromptPart,
            TextPart,
            ThinkingPart,
            UserPromptPart,
        )

        history: list[Any] = []
        for message in merge_same_role(messages):
            if message["role"] == "assistant":
                history.append(ModelResponse(parts=[TextPart(content=message["content"])]))
            elif message["role"] == "system":
                history.append(ModelRequest(parts=[SystemPromptPart(content=message["content"])]))
            else:
                history.append(ModelRequest(parts=[UserPromptPart(content=message["content"])]))

        settings: dict[str, Any] = {
            "temperature": self.spec.temperature,
            "max_tokens": self.spec.max_tokens,
            "timeout": self.spec.request_timeout,
        }
        if self.spec.seed is not None:
            settings["seed"] = self.spec.seed
        if self.spec.extra_body:
            settings["extra_body"] = self.spec.extra_body

        attempt = 0
        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                response = model_request_sync(self.model, history, model_settings=settings)
                break
            except Exception:
                if attempt >= self.retries:
                    raise
                time.sleep(min(60.0, 2.0 * 2**attempt))
        seconds = time.perf_counter() - started
        text = "".join(part.content for part in response.parts if isinstance(part, TextPart))
        thinking = "".join(part.content for part in response.parts if isinstance(part, ThinkingPart))
        return Reply(
            text=text,
            input_tokens=int(response.usage.input_tokens or 0),
            output_tokens=int(response.usage.output_tokens or 0),
            seconds=seconds,
            model_id=response.model_name,
            finish_reason=str(response.finish_reason) if response.finish_reason else None,
            thinking=thinking,
            attempts=attempt,
        )


@dataclass
class ScriptedChat:
    """A stand-in model for tests: returns the next scripted reply, or asks a function."""

    spec: ModelSpec
    script: list[str] | Callable[[list[Message]], str]
    runs_locally: bool = True
    calls: list[list[Message]] = field(default_factory=list)

    def complete(self, messages: list[Message]) -> Reply:
        self.calls.append([dict(message) for message in messages])
        if callable(self.script):
            text = self.script(messages)
        else:
            if not self.script:
                raise RuntimeError("ScriptedChat ran out of replies")
            text = self.script.pop(0)
        prompt_chars = sum(len(message["content"]) for message in messages)
        return Reply(text=text, input_tokens=prompt_chars // 4, output_tokens=len(text) // 4, seconds=0.0)


def load_env_file(path: Path | str) -> list[str]:
    """Read KEY=VALUE lines into os.environ without overriding what is already set. Returns the names."""
    path = Path(path)
    names: list[str] = []
    if not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value
        names.append(name)
    return names
