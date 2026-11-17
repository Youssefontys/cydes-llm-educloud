"""De validatietaak: Modbus-verkeer toetsen aan een beveiligingsbeleid.

Een case is een kort stuk Modbus/TCP-verkeer (12 tot 25 transacties) naar één PLC. Het model moet zeggen of het
verkeer aan het beleid voldoet ("valid"), of welke regel het breekt. Het verkeer is nagemaakt met een vaste seed, dus
elke run krijgt precies dezelfde cases, en het juiste antwoord komt niet van een mens maar van check(): een gewone
functie die het beleid regel voor regel naloopt. Elke case breekt hoogstens één regel, zodat er één goed antwoord is.

De adressen en rollen volgen GRFICSv3 (HMI en engineering workstation in 192.168.95.0/24, een PLC met holding
registers), maar de benchmark heeft GRFICS zelf niet nodig: zo is de uitkomst te herhalen op een VM zonder simulatie.
Alleen de standaardbibliotheek."""
import hashlib
import json
import random

HMI, EWS = "192.168.95.10", "192.168.95.5"
RULES = ("unknown_client", "forbidden_function", "illegal_address", "unauthorized_write", "value_out_of_range", "write_flood")
VERDICTS = ("valid", *RULES)

SETPOINTS = {
    40: ("pressure_setpoint_kpa", 0, 3000),
    41: ("level_setpoint_pct", 0, 100),
    42: ("feed1_valve_pct", 0, 100),
    43: ("feed2_valve_pct", 0, 100),
    44: ("purge_valve_pct", 0, 100),
    45: ("product_valve_pct", 0, 100),
}
READ_CODES, WRITE_CODES = (3, 4), (6, 16)
MAX_ADDRESS, FLOOD_WRITES, FLOOD_SECONDS = 99, 5, 10

POLICY = {
    "plc": "192.168.95.2, unit 1, registers 0-99",
    "rules": {
        "unknown_client": f"Only the HMI ({HMI}) and the engineering workstation ({EWS}) may talk to the PLC.",
        "forbidden_function": "Only function codes 3, 4 (read) and 6, 16 (write) are allowed.",
        "illegal_address": "A request may only touch registers 0-99 (address + count - 1 must be 99 or lower).",
        "unauthorized_write": "Registers 0-39 are read-only for everyone. Registers 40-45 (setpoints) may be written by the "
                              "HMI and the engineering workstation. Registers 46-99 (configuration) may only be written by "
                              "the engineering workstation.",
        "value_out_of_range": "A value written to a setpoint register must be within its limits: register 40 is 0-3000, "
                              "registers 41-45 are 0-100.",
        "write_flood": f"One client may send at most {FLOOD_WRITES} write requests in any {FLOOD_SECONDS}-second window.",
    },
    "verdicts": "Answer 'valid' if no rule is broken, otherwise the name of the one rule that is broken.",
}


def register_info(address):
    if not isinstance(address, int) or isinstance(address, bool) or not 0 <= address <= MAX_ADDRESS:
        return {"error": f"register {address!r} does not exist; registers are 0-{MAX_ADDRESS}"}
    if address < 40:
        return {"address": address, "kind": "process value", "writable_by": []}
    if address in SETPOINTS:
        name, low, high = SETPOINTS[address]
        return {"address": address, "kind": "setpoint", "name": name, "min": low, "max": high, "writable_by": ["hmi", "ews"]}
    return {"address": address, "kind": "configuration", "min": 0, "max": 65535, "writable_by": ["ews"]}


def check(transactions):
    """Het beleid als code: de regels die dit verkeer breekt, in de volgorde van RULES. Leeg is geldig."""
    broken = set()
    writes = {}
    for t in transactions:
        if t["src"] not in (HMI, EWS):
            broken.add("unknown_client")
        if t["fc"] not in READ_CODES + WRITE_CODES:
            broken.add("forbidden_function")
            continue
        if t["addr"] < 0 or t["addr"] + t["count"] - 1 > MAX_ADDRESS:
            broken.add("illegal_address")
            continue
        if t["fc"] in WRITE_CODES:
            writes.setdefault(t["src"], []).append(t["t"])
            for offset, value in enumerate(t["values"]):
                address = t["addr"] + offset
                if address < 40 or (address > 45 and t["src"] != EWS):
                    broken.add("unauthorized_write")
                elif address in SETPOINTS and not SETPOINTS[address][1] <= value <= SETPOINTS[address][2]:
                    broken.add("value_out_of_range")
    for times in writes.values():
        times.sort()
        for i in range(len(times) - FLOOD_WRITES):
            if times[i + FLOOD_WRITES] - times[i] <= FLOOD_SECONDS:
                broken.add("write_flood")
    return [r for r in RULES if r in broken]


def _read(rng, t, src=HMI):
    fc = rng.choice(READ_CODES)
    addr = rng.choice((0, 10, 20, 40))
    return {"t": t, "src": src, "unit": 1, "fc": fc, "addr": addr, "count": rng.choice((2, 6, 10)), "values": None}


def _write(t, src, addr, values, fc=None):
    return {"t": t, "src": src, "unit": 1, "fc": fc or (6 if len(values) == 1 else 16), "addr": addr, "count": len(values), "values": values}


def _valid_write(rng, t):
    if rng.random() < 0.25:
        return _write(t, EWS, rng.randint(50, 98), [rng.randint(0, 500)])
    addr = rng.choice(sorted(SETPOINTS))
    return _write(t, HMI, addr, [rng.randint(SETPOINTS[addr][1], SETPOINTS[addr][2])])


def _violation(rng, rule, t):
    if rule == "unknown_client":
        return [{**_read(rng, t), "src": f"192.168.95.{rng.choice((23, 77, 101, 150, 200))}"}]
    if rule == "forbidden_function":
        return [{**_read(rng, t, rng.choice((HMI, EWS))), "fc": rng.choice((5, 8, 15, 22, 23, 43, 90))}]
    if rule == "illegal_address":
        addr = rng.choice((95, 98, 120, 400))
        return [{**_read(rng, t), "addr": addr, "count": rng.choice((6, 10))}]
    if rule == "unauthorized_write":
        if rng.random() < 0.5:
            return [_write(t, HMI, rng.randint(50, 98), [rng.randint(0, 500)])]
        return [_write(t, rng.choice((HMI, EWS)), rng.randint(0, 38), [rng.randint(0, 100)])]
    if rule == "value_out_of_range":
        addr = rng.choice(sorted(SETPOINTS))
        return [_write(t, HMI, addr, [SETPOINTS[addr][2] + rng.choice((1, 50, 400, 6000))])]
    if rule == "write_flood":
        return [_write(round(t + i * rng.choice((0.3, 0.5)), 1), HMI, 42, [rng.randint(0, 100)]) for i in range(rng.randint(6, 8))]
    raise ValueError(rule)


def make_cases(n=30, seed=1):
    """n cases met een vaste seed: ongeveer 40% geldig, de rest gelijk verdeeld over de zes regels."""
    rng = random.Random(seed)
    valid = round(n * 0.4)
    labels = ["valid"] * valid + [RULES[i % len(RULES)] for i in range(n - valid)]
    rng.shuffle(labels)
    cases = []
    for number, label in enumerate(labels, 1):
        for _ in range(100):
            transactions, t = [], 0.0
            for _ in range(rng.randint(12, 17)):
                # Geldige schrijfacties liggen minstens 4 seconden uit elkaar: nooit vanzelf een flood.
                if transactions and rng.random() < 0.15 and all(t - x["t"] >= 4 for x in transactions if x["fc"] in WRITE_CODES):
                    transactions.append(_valid_write(rng, t))
                else:
                    transactions.append(_read(rng, t))
                t = round(t + rng.choice((0.8, 1.0, 1.2)), 1)
            if label != "valid":
                transactions += _violation(rng, label, round(rng.uniform(1, t), 1))
            transactions.sort(key=lambda x: x["t"])
            for i, tx in enumerate(transactions):
                tx["i"] = i
            if check(transactions) == ([] if label == "valid" else [label]):
                break
        else:
            raise RuntimeError(f"geen case voor {label} gevonden")
        cases.append({"id": f"case-{number:03d}", "label": label, "transactions": transactions})
    return cases


def fingerprint(cases):
    return hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()[:12]


# ---- de tools die het model krijgt; in elke variant dezelfde vier ----

PAGE = 10
TOOLS = [
    {"name": "get_policy", "description": "Return the security policy the Modbus traffic must follow.", "parameters": {}},
    {"name": "get_transactions",
     "description": f"Return up to {PAGE} Modbus transactions of this case, starting at index 'start', and the total number. "
                    "Fields: i (index), t (seconds), src (client IP), fc (function code), addr (first register), count, values (written values or null).",
     "parameters": {"start": {"type": "integer", "description": "Index of the first transaction, 0 or higher."}}},
    {"name": "get_register_info", "description": "Return what one register is, who may write it and its limits.",
     "parameters": {"address": {"type": "integer", "description": "Register address."}}},
]
SUBMIT = {"name": "submit_verdict",
          "description": "Give the final answer and stop. verdict is 'valid' or the name of the broken rule: " + ", ".join(RULES) + ".",
          "parameters": {"verdict": {"type": "string", "enum": list(VERDICTS)},
                         "reason": {"type": "string", "description": "One sentence: which transaction and why."}}}
REPORT = {"name": "report_findings", "description": "Hand your findings to the reviewer and stop.",
          "parameters": {"findings": {"type": "string", "description": "What you checked, and every transaction that looks wrong, with its index."}}}


def schema(tool):
    """Het tool als JSON-schema, in de vorm die Ollama en MCP verwachten."""
    required = [k for k in tool["parameters"] if k not in ("reason",)]
    return {"type": "function", "function": {"name": tool["name"], "description": tool["description"],
                                             "parameters": {"type": "object", "properties": tool["parameters"], "required": required}}}


def call_tool(case, name, arguments):
    """Voert een tool uit op deze case. Geeft (resultaat, geldig): een onbekende naam of verkeerde argumenten is ongeldig."""
    if not isinstance(arguments, dict):
        return {"error": "arguments must be an object"}, False
    if name == "get_policy":
        return POLICY, True
    if name == "get_transactions":
        start = arguments.get("start", 0)
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            return {"error": "start must be an integer of 0 or higher"}, False
        return {"total": len(case["transactions"]), "start": start, "transactions": case["transactions"][start:start + PAGE]}, True
    if name == "get_register_info":
        info = register_info(arguments.get("address"))
        return info, "error" not in info
    return {"error": f"unknown tool {name!r}; the tools are get_policy, get_transactions, get_register_info and the final tool"}, False
