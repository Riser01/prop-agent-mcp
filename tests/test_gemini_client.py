"""
Unit tests for GeminiClient and fallback simulator.
"""
import pytest
from src.agents.gemini_client import GeminiClient, resolve_gemini_api_key

def test_gemini_client_initialization():
    client = GeminiClient()
    assert client.model == "gemini-2.0-flash"
    assert hasattr(client, "api_key")

@pytest.mark.asyncio
async def test_gemini_fallback_when_unkeyed():
    # Force client with no api key to test fallback
    client = GeminiClient(api_key="")
    res = await client.generate_content(
        system_instruction="You are a property agent.",
        prompt="Schedule move-in on Saturday."
    )
    assert "text" in res
    assert "deterministic" in res["text"] or "Gemini API key" in res["text"]
    assert res["tool_calls"] == []
