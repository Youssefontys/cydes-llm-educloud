"""MCP-server met de tools van de validatietaak: het beleid, de transacties van een case en de registers.
Dezelfde functies als de andere varianten gebruiken (bench/datasets.py), alleen nu achter het Model Context Protocol.
Stdio-transport: de benchmark start deze server zelf als proces; er gaat geen netwerkpoort open.

De server kent alle cases en krijgt bij elke aanroep een case_id mee. Dat veld vult de benchmark in, het model ziet
het niet: zo kan het model geen andere case opvragen.

Los te starten, voor een eigen MCP-client:
    python -m bench.mcp_server --dataset data/grfics-2026-11-17.json
    python -m bench.mcp_server --cases 30 --seed 1"""
import argparse
import json

from mcp.server.mcpserver import MCPServer  # mcp 2.x; in 1.x heette dit FastMCP

from . import datasets

mcp = MCPServer("cydes-modbus")
DATASET = None
CASES = {}


def _run(case_id, name, arguments):
    case = CASES.get(case_id)
    if case is None:
        return json.dumps({"error": f"unknown case {case_id!r}"})
    return json.dumps(DATASET.call(case, name, arguments)[0])


@mcp.tool(structured_output=False)
def get_policy(case_id: str) -> str:
    """Return the security policy the Modbus traffic must follow."""
    return _run(case_id, "get_policy", {})


@mcp.tool(structured_output=False)
def get_transactions(case_id: str, start: int = 0) -> str:
    """Return up to 10 Modbus transactions of this case, starting at index 'start', and the total number."""
    return _run(case_id, "get_transactions", {"start": start})


# De registertool verschilt per dataset; hij wordt pas na het laden aangemeld, zodat het model alleen de juiste ziet.
def get_register_info(case_id: str, address: int) -> str:
    """Return what one register is, who may write it and its limits."""
    return _run(case_id, "get_register_info", {"address": address})


def get_register_map(case_id: str, server: str) -> str:
    """Return the register map of one server: which tables and address ranges may be touched."""
    return _run(case_id, "get_register_map", {"server": server})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset")
    parser.add_argument("--cases", type=int, default=30)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    DATASET = datasets.load(args.dataset, args.cases, args.seed)
    CASES.update({c["id"]: c for c in DATASET.cases})
    mcp.tool(structured_output=False)(get_register_map if DATASET.name == "grfics" else get_register_info)
    mcp.run()
