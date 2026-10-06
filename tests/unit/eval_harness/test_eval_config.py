"""Unit tests for evals/config.py."""

import pytest

from evals import config


def test_username_is_an_email_per_persona():
    assert config.username("P07") == "eval-p07@ledgerlens.example"


def test_model_slug_keeps_only_letters_digits_and_dashes():
    assert config.model_slug("openai.gpt-oss-120b-1:0") == "openai-gpt-oss-120b-1-0"
    assert config.model_slug("deepseek.v3.2") == "deepseek-v3-2"


def test_session_cost_uses_per_million_prices():
    assert config.session_cost("deepseek.v3.2", 1_000_000, 1_000_000) == pytest.approx(2.47)


def test_every_priced_model_has_a_token_estimate():
    assert set(config.PRICES) == set(config.ESTIMATED_TOKENS)


def test_env_round_trip_skips_comments_and_blanks(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# secrets\n\nEVAL_PASSWORD_P07=a=b\n", encoding="utf-8")

    assert config.read_env(path) == {"EVAL_PASSWORD_P07": "a=b"}

    config.write_env({"B": "2", "A": "1"}, path)
    assert path.read_text(encoding="utf-8") == "A=1\nB=2\n"


def test_a_missing_env_file_reads_as_empty(tmp_path):
    assert config.read_env(tmp_path / "missing") == {}
