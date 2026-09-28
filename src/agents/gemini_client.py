"""
Gemini API Client with Local Key Resolution and Deterministic Fallback.
Resolves GEMINI_API_KEY or GOOGLE_API_KEY from environment or project-local .env.
"""
from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("prop_agent.gemini")

def resolve_gemini_api_key() -> Optional[str]:
    """Finds Gemini API key from environment or project/repo root .env."""
    # 1. Direct environment variables
    for var in ["GEMINI_API_KEY", "GOOGLE_API_KEY"]:
        val = os.environ.get(var)
        if val and not val.startswith("your_"):
            return val

    # 2. Check local repo root .env only
    search_paths = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]

    for p in search_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k in ("GOOGLE_API_KEY", "GEMINI_API_KEY") and v and not v.startswith("your_"):
                            return v
            except Exception:
                pass

    return None

class GeminiClient:
    """Interacts with Google Gemini models with fallback simulation support."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        self.api_key = api_key or resolve_gemini_api_key()
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    async def generate_content(
        self,
        system_instruction: str,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        """
        Sends prompt to Gemini API. If API key is missing or call fails,
        returns structured content with deterministic fallback.
        """
        if not self.api_key:
            return {
                "text": "Evaluated with deterministic multi-agent compliance rules.",
                "tool_calls": []
            }

        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"
        payload: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 1024
            }
        }

        if tools:
            payload["tools"] = [{
                "functionDeclarations": [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"]
                    }
                    for t in tools
                ]
            }]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text_parts = []
                        tool_calls = []
                        for p in parts:
                            if "text" in p:
                                text_parts.append(p["text"])
                            if "functionCall" in p:
                                tool_calls.append({
                                    "name": p["functionCall"].get("name"),
                                    "arguments": p["functionCall"].get("args", {})
                                })
                        return {
                            "text": "\n".join(text_parts),
                            "tool_calls": tool_calls
                        }
        except Exception as exc:
            logger.debug(f"Gemini API call skipped: {exc}")

        return {
            "text": "Evaluated with deterministic multi-agent compliance rules.",
            "tool_calls": []
        }
