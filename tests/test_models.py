import pytest
from pydantic_ai.exceptions import UserError

from loopy.agent.models import resolve_model


def test_offline_is_the_default_and_runs_locally():
    choice = resolve_model()

    assert choice.runs_locally
    assert choice.label == "offline demo model"


def test_pydantic_ai_test_model_runs_locally():
    assert resolve_model("test").runs_locally


def test_base_url_on_localhost_counts_as_local():
    choice = resolve_model("qwen3:8b", base_url="http://localhost:11434/v1")

    assert choice.runs_locally
    assert choice.label == "qwen3:8b @ localhost"


def test_remote_base_url_counts_as_cloud():
    assert not resolve_model("some-model", base_url="https://api.example.com/v1").runs_locally


def test_cloud_model_without_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(UserError):
        resolve_model("openai:gpt-6.1-sol")
