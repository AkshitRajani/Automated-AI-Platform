"""Tests for profiling mode resolution."""
from scoring.agent.config import (
    DEFAULT_SCORING_MODEL_ARN,
    bedrock_settings,
    has_bedrock,
    resolve_profiling_mode,
    resolved_model_arn,
)


def test_resolve_auto_without_bedrock_uses_regex(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ARN", raising=False)
    monkeypatch.delenv("SCORING_BEDROCK_MODEL_ARN", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    assert resolve_profiling_mode("auto") == "regex"
    assert not has_bedrock()


def test_resolve_auto_with_aws_keys_uses_agent(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ARN", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    assert has_bedrock()
    assert resolve_profiling_mode("auto") == "agent"
    assert resolved_model_arn() == DEFAULT_SCORING_MODEL_ARN
    settings = bedrock_settings()
    assert settings["model_arn"] == DEFAULT_SCORING_MODEL_ARN
    assert settings["region"]


def test_explicit_bedrock_model_override(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ARN", "us.anthropic.claude-custom")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    assert resolved_model_arn() == "us.anthropic.claude-custom"


def test_resolve_regex_explicit(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    assert resolve_profiling_mode("regex") == "regex"
