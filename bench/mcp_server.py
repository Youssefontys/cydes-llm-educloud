"""MCP-server met de tools van de validatietaak: het beleid, de transacties van een case en de registers.
Dezelfde functies als de andere varianten gebruiken (bench/modbus.py), alleen nu achter het Model Context Protocol.
Stdio-transport: de benchmark start deze server zelf als proces; er gaat geen netwerkpoort open.

De server kent alle cases en krijgt bij elke aanroep een case_id mee. Dat veld vult de benchmark in, het model ziet
het niet: zo kan het model geen andere case opvragen.

Los te starten, voor een eigen MCP-client:  python -m bench.mcp_server --cases 30 --seed 1"""
import argparse
import json

from mcp.server.mcpserver import MCPServer  # mcp 2.x; in 1.x heette dit FastMCP

from . import modbus

mcp = MCPServer("cydes-modbus")
CASES = {}


def _run(case_id, name, arguments):
    case = CASES.get(case_id)
    if case is None:
        return json.dumps({"error": f"unknown case {case_id!r}"})
    return json.dumps(modbus.call_tool(case, name, arguments)[0])


@mcp.tool(structured_output=False)
def get_policy(case_id: str) -> str:
    """Return the security policy the Modbus traffic must follow."""
    return _run(case_id, "get_policy", {})


@mcp.tool(structured_output=False)
def get_transactions(case_id: str, start: int = 0) -> str:
    """Return up to 10 Modbus transactions of this case, starting at index 'start', and the total number."""
    return _run(case_id, "get_transactions", {"start": start})


@mcp.tool(structured_output=False)
def get_register_info(case_id: str, address: int) -> str:
    """Return what one register is, who may write it and its limits."""
    return _run(case_id, "get_register_info", {"address": address})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=30)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    CASES.update({c["id"]: c for c in modbus.make_cases(args.cases, args.seed)})
    mcp.run()
