"""De MCP-client van de benchmark: start bench/mcp_server.py als proces, vraagt de tools op en voert ze uit.
De MCP-bibliotheek is asynchroon en de benchmark niet; daarom draait de sessie in een eigen thread en roept de
benchmark haar aan alsof het gewone functies zijn. Eén sessie voor de hele benchmark, zodat het opstarten van de
server niet in elke meting meetelt."""
import asyncio
import json
import pathlib
import sys
import threading

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpBridge:
    def __init__(self, dataset):
        self._loop = asyncio.new_event_loop()
        self._ready, self._stop, self._error = threading.Event(), None, None
        self._params = StdioServerParameters(command=sys.executable, args=["-m", "bench.mcp_server", *dataset.server_args()],
                                             cwd=str(pathlib.Path(__file__).resolve().parent.parent))
        self._thread = threading.Thread(target=self._loop.run_until_complete, args=(self._serve(),), daemon=True)
        self._thread.start()
        if not self._ready.wait(60) or self._error:
            raise RuntimeError(f"de MCP-server startte niet: {self._error or 'geen antwoord binnen 60 seconden'}")

    async def _serve(self):
        self._stop = asyncio.Event()
        try:
            async with stdio_client(self._params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    listed = await session.list_tools()
                    self._specs = [self._spec(t) for t in listed.tools]
                    self._ready.set()
                    await self._stop.wait()
        except Exception as error:  # naar de hoofdthread: daar wordt het een duidelijke melding
            self._error = error
            self._ready.set()

    @staticmethod
    def _spec(tool):
        # Het schema dat de server geeft, zonder case_id: dat veld vult de benchmark in, niet het model.
        params = json.loads(json.dumps(tool.input_schema))
        params.get("properties", {}).pop("case_id", None)
        params["required"] = [r for r in params.get("required", []) if r != "case_id"]
        return {"type": "function", "function": {"name": tool.name, "description": tool.description or "", "parameters": params}}

    def for_case(self, case):
        return _CaseTools(self, case["id"])

    def call(self, name, arguments):
        future = asyncio.run_coroutine_threadsafe(self._session.call_tool(name, arguments), self._loop)
        result = future.result(60)
        text = "".join(getattr(part, "text", "") for part in result.content)
        if getattr(result, "is_error", False):
            return {"error": text[:300]}, False
        try:
            data = json.loads(text)
        except ValueError:
            return {"error": text[:300]}, False
        return data, not (isinstance(data, dict) and "error" in data)

    def close(self):
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(10)


class _CaseTools:
    def __init__(self, bridge, case_id):
        self.bridge, self.case_id = bridge, case_id

    def specs(self):
        return self.bridge._specs

    def call(self, name, arguments):
        return self.bridge.call(name, {**arguments, "case_id": self.case_id})
