"""De validatietaak op echt verkeer uit GRFICSv3: Modbus/TCP bij de PLC, getoetst aan een beleid dat uit een
basislijn van datzelfde verkeer is afgeleid.

Hoe GRFICSv3 Modbus gebruikt (gemeten op 2026-11-17, 90 seconden bij de PLC):
  - de PLC (192.168.95.2) is zelf client: hij leest en stuurt zes veldapparaten (192.168.95.10 tot .15) met
    function code 4 en 16, tien keer per seconde;
  - de HMI (192.168.90.107, in de DMZ) leest de PLC elke twee seconden met function code 1, 3 en 4;
  - het engineering workstation (192.168.95.5) zat niet in de basislijn.

Het beleid is wat de basislijn doet, plus de rol van het engineering workstation: wie met welke server mag praten,
met welke function codes, binnen welke registers, en wie mag schrijven. Alles daarbuiten breekt een regel.

Een case is een venster van ongeveer acht seconden: de verzoeken aan de PLC in dat venster, en één ronde van de PLC
langs de veldapparaten. Een overtreding komt uit een scenario dat echt in GRFICS is uitgevoerd (bench/collect.py),
niet uit een nagemaakte transactie. Het juiste antwoord geeft check(), net als bij de nagemaakte cases.
Alleen de standaardbibliotheek."""
import hashlib
import json

RULES = ("unknown_client", "forbidden_function", "illegal_address", "unauthorized_write")
VERDICTS = ("valid", *RULES)
WRITE_CODES = (5, 6, 15, 16, 23)
# Welke tabel een function code raakt; een code die hier niet staat, raakt geen register.
TABLES = {1: "coils", 5: "coils", 15: "coils", 2: "discrete_inputs", 3: "holding_registers", 6: "holding_registers",
          16: "holding_registers", 23: "holding_registers", 4: "input_registers"}
PLC, HMI, EWS = "192.168.95.2", "192.168.90.107", "192.168.95.5"
ROLES = {PLC: "PLC", HMI: "HMI", EWS: "engineering workstation", **{f"192.168.95.{n}": f"field device {n - 9}" for n in range(10, 16)}}
RULE_TEXT = {
    "unknown_client": "Only the clients listed for a server may send it Modbus requests.",
    "forbidden_function": "A client may only use the function codes listed for that server.",
    "illegal_address": "A request may only touch registers inside the server's register map (get_register_map).",
    "unauthorized_write": "Only clients marked as writer may use a write function code (5, 6, 15, 16, 23).",
}


def derive_policy(baseline):
    """Het beleid uit de basislijn: per server de clients, function codes en registers die daar voorkwamen.
    Het engineering workstation krijgt erbij: lezen en schrijven op de PLC, met de schrijfcodes."""
    servers = {}
    for t in baseline:
        server = servers.setdefault(t["dst"], {"clients": {}, "functions": set(), "map": {}})
        client = server["clients"].setdefault(t["src"], {"write": False})
        client["write"] = client["write"] or t["fc"] in WRITE_CODES
        server["functions"].add(t["fc"])
        table = TABLES.get(t["fc"])
        if table and t["addr"] is not None and t["count"]:
            low, high = server["map"].get(table, (t["addr"], t["addr"] + t["count"] - 1))
            server["map"][table] = (min(low, t["addr"]), max(high, t["addr"] + t["count"] - 1))
    if PLC in servers:
        servers[PLC]["clients"][EWS] = {"write": True}
        servers[PLC]["functions"] |= {5, 6, 15, 16}
    return {"servers": {ip: {"role": ROLES.get(ip, "unknown"),
                             "clients": {c: {"role": ROLES.get(c, "unknown"), "write": v["write"]} for c, v in sorted(s["clients"].items())},
                             "functions": sorted(s["functions"]),
                             "map": {k: list(v) for k, v in sorted(s["map"].items())}} for ip, s in sorted(servers.items())},
            "rules": RULE_TEXT}


def check(policy, transactions):
    """De regels die dit verkeer breekt, in de volgorde van RULES; leeg is geldig. Per transactie telt de eerste
    regel die hij breekt: een onbekende client breekt niet ook nog de regel over function codes."""
    broken = set()
    for t in transactions:
        server = policy["servers"].get(t["dst"])
        client = server and server["clients"].get(t["src"])
        table = TABLES.get(t["fc"])
        if not client:
            broken.add("unknown_client")
        elif t["fc"] not in server["functions"]:
            broken.add("forbidden_function")
        # Een function code zonder tabel (bv. 43, device-id) raakt geen register; niets om te checken.
        elif table and not _inside(server["map"].get(table), t):
            broken.add("illegal_address")
        elif t["fc"] in WRITE_CODES and not client["write"]:
            broken.add("unauthorized_write")
    return [r for r in RULES if r in broken]


def _inside(span, t):
    return bool(span) and t["addr"] is not None and bool(t["count"]) and span[0] <= t["addr"] and t["addr"] + t["count"] - 1 <= span[1]


def model_policy(policy):
    """Het beleid zoals het model het met get_policy krijgt: de regels, de clients en de function codes. De
    registermap haalt het model apart op, met get_register_map."""
    return {"rules": policy["rules"],
            "servers": {ip: {"role": s["role"], "clients": s["clients"], "function_codes": s["functions"]} for ip, s in policy["servers"].items()},
            "verdicts": "Answer 'valid' if no rule is broken, otherwise the name of the one rule that is broken."}


def _table_note():
    grouped = {}
    for fc, table in TABLES.items():
        grouped.setdefault(table, []).append(fc)
    return "; ".join(f"{table} (function codes {', '.join(str(fc) for fc in sorted(fcs))})" for table, fcs in sorted(grouped.items()))


def register_map(policy, server):
    s = policy["servers"].get(server)
    if s is None:
        return {"error": f"{server!r} is not a server in the policy; the servers are {', '.join(policy['servers'])}"}
    # Alleen wat in het beleid staat; wat een register betekent, staat er niet in en zegt de tool dus ook niet. De
    # koppeling function code -> tabel is wel protocolkennis, geen beleidskennis, en staat er daarom wel in: zonder
    # dat moet het model zelf onthouden welke function code bij welke tabel hoort, en dat ging vaak genoeg mis.
    return {"server": server, "role": s["role"], "map": {k: {"first": v[0], "last": v[1]} for k, v in s["map"].items()},
            "note": f"Ranges are inclusive. A table that is not listed may not be touched. The meaning of a register is "
                     f"not known. Tables by function code: {_table_note()}."}


def build_cases(transactions, marks, baseline_until, window=8.0):
    """Cases uit een opname: vensters uit de basislijn (geldig) en rond elk scenario (één overtreding).
    transactions: uit pcap.transactions; marks: [{"scenario", "rule", "start", "end"}] uit collect.py, in dezelfde klok."""
    baseline = [t for t in transactions if t["t"] < baseline_until]
    policy = derive_policy(baseline)
    plc_side = [t for t in transactions if t["dst"] == PLC]
    polls = [t for t in transactions if t["src"] == PLC]
    centres = [("valid", baseline[0]["t"] + window / 2 + i * window) for i in range(int((baseline_until - baseline[0]["t"] - window) // window))]
    centres += [(m["rule"], (m["start"] + m["end"]) / 2) for m in marks]
    cases, skipped = [], []
    for label, centre in centres:
        start, end = centre - window / 2, centre + window / 2
        # Eén ronde van de PLC langs de zes veldapparaten, de eerste in het venster: genoeg om de veldkant te zien.
        first = next((p["t"] for p in polls if p["t"] >= start), None)
        cycle = [p for p in polls if first is not None and first <= p["t"] < first + 0.09]
        chosen = sorted([t for t in plc_side if start <= t["t"] < end] + cycle, key=lambda t: t["t"])
        rows = [{**t, "t": round(t["t"] - start, 2)} for t in chosen]
        for i, row in enumerate(rows):
            row["i"] = i
        if check(policy, rows) == ([] if label == "valid" else [label]):
            cases.append({"id": f"grfics-{len(cases) + 1:03d}", "label": label, "transactions": rows})
        else:
            skipped.append({"label": label, "centre": centre, "found": check(policy, rows)})
    return policy, cases, skipped


def fingerprint(policy, cases):
    return hashlib.sha256(json.dumps([policy, cases], sort_keys=True).encode()).hexdigest()[:12]
