"""MCP-server met de tools van de validatietaak: het beleid, de transacties van een case en de registers.
Dezelfde functies als de andere varianten gebruiken (bench/datasets.py), alleen nu achter het Model Context Protocol.
Stdio-transport: de benchmark start deze server zelf als proces; er gaat geen netwerkpoort open.

De tools en hun beschrijvingen komen rechtstreeks uit datasets.py, zodat het model via mcp precies hetzelfde ziet als
via native. Tot 2026-11-27 beschreef deze server de tools zelf, kaler (zie docs/experimenten.md); dat maakte het
verschil tussen native en mcp groter dan alleen het protocol.

De server kent alle cases en krijgt bij elke aanroep een case_id mee. Dat veld vult de benchmark in, het model ziet
het niet: zo kan het model geen andere case opvragen.

Los te starten, voor een eigen MCP-client:
    python -m bench.mcp_server --dataset data/grfics-2026-11-17.json
    python -m bench.mcp_server --cases 30 --seed 1"""
import argparse
import json

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import datasets

CASE_ID = {"type": "string", "description": "The case to look at; filled in by the benchmark."}


def input_schema(tool):
    """Het schema uit datasets.py, met case_id als laatste veld erbij (de bridge haalt het er weer af)."""
    params = json.loads(json.dumps(datasets.schema(tool)["function"]["parameters"]))
    params["properties"]["case_id"] = CASE_ID
    params["required"] = [*params["required"], "case_id"]
    return params


def make_server(dataset):
    cases = {c["id"]: c for c in dataset.cases}
    tools = {t["name"]: t for t in dataset.tools()}

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[types.Tool(name=t["name"], description=t["description"], input_schema=input_schema(t))
                                            for t in tools.values()])

    async def call_tool(ctx, params):
        arguments = dict(params.arguments or {})
        case = cases.get(arguments.pop("case_id", None))
        if params.name not in tools:
            result = {"error": f"unknown tool {params.name!r}"}
        elif case is None:
            result = {"error": "unknown case"}
        else:
            result = dataset.call(case, params.name, arguments)[0]
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result))])

    return Server("cydes-modbus", on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(server):
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset")
    parser.add_argument("--cases", type=int, default=30)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    anyio.run(serve, make_server(datasets.load(args.dataset, args.cases, args.seed)))
