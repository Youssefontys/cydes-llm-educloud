"""Minimale MCP-server die een lokaal, CPU-only Ollama-model als tool aanbiedt.
Status: voorbeeld, nog niet getest tegen een echte MCP-client. Stdio-transport (de MCP-
standaard, werkt met elke MCP-client die een proces start, bijv. over SSH): geen netwerkpoort,
dus niets om te tunnelen. Wil je hem over het netwerk bereikbaar maken (SSE/streamable-http),
check dan de transport-optie van de geinstalleerde mcp-versie, die is tussen versies veranderd.

Gebruik (op de VM, in de venv die bootstrap-openllm.sh aanmaakt):
    python3 mcp_server.py
"""
import os

import requests
from mcp.server.fastmcp import FastMCP

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

mcp = FastMCP("openllm-demo")


@mcp.tool()
def ask_local_llm(prompt: str) -> str:
    """Stel een vraag aan het lokale, CPU-only Ollama-model en krijg het antwoord terug."""
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": MODEL, "prompt": prompt, "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["response"]


if __name__ == "__main__":
    mcp.run()
