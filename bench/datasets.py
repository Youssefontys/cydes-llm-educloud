"""De twee datasets en de tools die het model erop krijgt.

  synthetic   nagemaakt verkeer met een vaste seed (bench/modbus.py); handig om te testen zonder GRFICS
  grfics      echt verkeer uit GRFICSv3, opgenomen met bench/collect.py en omgezet met deployment.py data

Elke dataset geeft hetzelfde aan de varianten: de cases, het beleid voor het model, de tools (get_policy,
get_transactions en één tool voor de registers), het juiste antwoord per case, en wat de variant zonder tools in de
prompt krijgt. Alleen de standaardbibliotheek."""
import json
import pathlib

from . import grfics, modbus

PAGE = 30
FIELDS = ("Fields: i (index), t (seconds since the start of the case), src (client IP), dst (server IP), fc (function code), "
          "addr (first register or coil), count, values (written values or null), exception (exception code of the reply, or null).")
REPORT = {"name": "report_findings", "description": "Hand your findings to the reviewer and stop.",
          "parameters": {"findings": {"type": "string", "description": "What you checked, and every transaction that looks wrong, with its index."}}}


def schema(tool):
    """Het tool als JSON-schema, in de vorm die Ollama en MCP verwachten."""
    required = [k for k in tool["parameters"] if k not in ("reason", "confidence")]
    return {"type": "function", "function": {"name": tool["name"], "description": tool["description"],
                                             "parameters": {"type": "object", "properties": tool["parameters"], "required": required}}}


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class Dataset:
    name, verdicts, cases = "", (), []
    register_tool = {}

    def tools(self):
        return [{"name": "get_policy", "description": "Return the security policy the Modbus traffic must follow.", "parameters": {}},
                {"name": "get_transactions",
                 "description": f"Return up to {PAGE} Modbus transactions of this case, starting at index 'start', and the total number. {FIELDS}",
                 "parameters": {"start": {"type": "integer", "description": "Index of the first transaction, 0 or higher."}}},
                self.register_tool]

    def submit(self):
        return {"name": "submit_verdict",
                "description": "Give the final answer and stop. verdict is 'valid' or the name of the broken rule: " + ", ".join(self.verdicts[1:]) + ".",
                "parameters": {"verdict": {"type": "string", "enum": list(self.verdicts)},
                               "reason": {"type": "string", "description": "One sentence: which transaction and why."},
                               "confidence": {"type": "string", "enum": ["low", "medium", "high"],
                                             "description": "How sure you are of this verdict, given the evidence you checked."}}}

    def call(self, case, name, arguments):
        """Voert een tool uit op deze case. Geeft (resultaat, geldig): een onbekende naam of verkeerde argumenten is ongeldig."""
        if not isinstance(arguments, dict):
            return {"error": "arguments must be an object"}, False
        if name == "get_policy":
            return self.policy(), True
        if name == "get_transactions":
            start = arguments.get("start", 0)
            if not _int(start) or start < 0:
                return {"error": "start must be an integer of 0 or higher"}, False
            return {"total": len(case["transactions"]), "start": start, "transactions": case["transactions"][start:start + PAGE]}, True
        if name == self.register_tool["name"]:
            result = self.registers(arguments)
            return result, "error" not in result
        names = ", ".join(t["name"] for t in self.tools())
        return {"error": f"unknown tool {name!r}; the tools are {names} and the final tool"}, False

    def evidence(self, case):
        """Alles in één keer, voor de variant zonder tools: het beleid, de registers en alle transacties."""
        return {"policy": self.policy(), "registers": self.all_registers(), "transactions": case["transactions"]}


class Synthetic(Dataset):
    name, verdicts = "synthetic", modbus.VERDICTS
    register_tool = {"name": "get_register_info", "description": "Return what one register is, who may write it and its limits.",
                     "parameters": {"address": {"type": "integer", "description": "Register address."}}}

    def __init__(self, cases=30, seed=1):
        self.cases, self.seed = modbus.make_cases(cases, seed), seed
        self.fingerprint = modbus.fingerprint(self.cases)
        self.source = {"kind": "synthetic", "cases": cases, "seed": seed}

    def policy(self):
        return modbus.POLICY

    def registers(self, arguments):
        return modbus.register_info(arguments.get("address"))

    def all_registers(self):
        return "Registers 0-39 are process values; 40-45 are setpoints with the limits in the policy; 46-99 are configuration (0-65535)."

    def check(self, transactions):
        return modbus.check(transactions)

    def server_args(self):
        return ["--cases", str(len(self.cases)), "--seed", str(self.seed)]


class Grfics(Dataset):
    name, verdicts = "grfics", grfics.VERDICTS
    register_tool = {"name": "get_register_map", "description": "Return the register map of one server: which tables and address ranges may be touched.",
                     "parameters": {"server": {"type": "string", "description": "IP address of the server, as in dst."}}}

    def __init__(self, path):
        self.path = pathlib.Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("kind") != "grfics":
            raise ValueError(f"{path} is geen GRFICS-dataset")
        self.raw_policy, self.cases = data["policy"], data["cases"]
        self.fingerprint = grfics.fingerprint(self.raw_policy, self.cases)
        self.source = {"kind": "grfics", "file": self.path.name, **data.get("source", {})}

    def policy(self):
        return grfics.model_policy(self.raw_policy)

    def registers(self, arguments):
        server = arguments.get("server")
        if not isinstance(server, str):
            return {"error": "server must be an IP address as a string"}
        return grfics.register_map(self.raw_policy, server)

    def all_registers(self):
        return {ip: grfics.register_map(self.raw_policy, ip)["map"] for ip in self.raw_policy["servers"]}

    def check(self, transactions):
        return grfics.check(self.raw_policy, transactions)

    def server_args(self):
        return ["--dataset", str(self.path.resolve())]


def load(path=None, cases=30, seed=1):
    return Grfics(path) if path else Synthetic(cases, seed)
