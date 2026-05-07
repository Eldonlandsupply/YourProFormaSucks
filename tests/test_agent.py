"""
Tests for agent.py (AI critique module).

Tests run without a GEMINI_API_KEY so no external API is called.
The module's own fallback path is tested.
"""
import pytest


@pytest.fixture(autouse=True)
def no_gemini_key(monkeypatch):
    """Ensure GEMINI_API_KEY is absent so tests use the mock path."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_roast_returns_string():
    import agent
    result = agent.roast("We project $1M revenue in year 1 with 80% gross margin.")
    assert isinstance(result, str)


def test_roast_returns_non_empty_string():
    import agent
    result = agent.roast("A simple projection.")
    assert len(result) > 0


def test_mock_response_contains_expected_prefix():
    import agent
    result = agent.roast("Any summary here.")
    assert result.startswith("[Mock critique]"), (
        f"Expected mock response starting with '[Mock critique]', got: {result[:50]!r}"
    )


def test_roast_handles_empty_string():
    import agent
    result = agent.roast("")
    assert isinstance(result, str)
    assert len(result) > 0


def test_roast_handles_long_input():
    import agent
    long_summary = "Revenue grows 10% monthly. " * 200
    result = agent.roast(long_summary)
    assert isinstance(result, str)


def test_roast_is_deterministic_without_api_key():
    """Without an API key, two calls with the same input should return the same string."""
    import agent
    s = "A proforma with 60% gross margin."
    assert agent.roast(s) == agent.roast(s)
