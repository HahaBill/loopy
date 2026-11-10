from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.openai import OpenAIProvider

from loopy.agent.offline import offline_model

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


@dataclass(frozen=True)
class ModelChoice:
    model: Model
    label: str
    runs_locally: bool


def resolve_model(name: str = "offline", base_url: str | None = None, api_key: str | None = None) -> ModelChoice:
    """Turn the `--model` / `--base-url` options into a PydanticAI model.

    `name` is "offline" for Loopy's built-in model, "test" for PydanticAI's test model, a PydanticAI
    model name such as "openai:<model>", or, when `base_url` is set, the model name an
    OpenAI-compatible server (Ollama, vLLM, llama.cpp) expects.
    """
    if name == "offline":
        return ModelChoice(offline_model(), "offline demo model", runs_locally=True)
    if name == "test":
        return ModelChoice(TestModel(), "PydanticAI test model", runs_locally=True)
    if base_url:
        host = urlparse(base_url).hostname or base_url
        # The OpenAI client refuses an empty key; local servers ignore it.
        provider = OpenAIProvider(base_url=base_url, api_key=api_key or "local")
        return ModelChoice(OpenAIChatModel(name, provider=provider), f"{name} @ {host}", host in LOCAL_HOSTS)
    return ModelChoice(infer_model(name), name, runs_locally=False)
