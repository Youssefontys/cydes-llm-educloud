"""Tests van de benchmark zonder echt model: een nagemaakte Ollama speelt het model.

    python -m unittest discover -s tests -v

De nagemaakte Ollama gedraagt zich als een model dat de taak goed doet: beleid lezen, alle transacties opvragen en
dan het oordeel geven dat de scheidsrechter van de dataset geeft. Zo test dit de hele keten (de prompt, het ontleden
van het antwoord, de tools, de MCP-server en de meting), en moet elke variant op 100% uitkomen. Een tweede "model"
geeft eerst onzin, om te testen dat ongeldige aanroepen geteld worden. Dit zegt niets over hoe goed een echt model is.

De GRFICS-tests bouwen zelf een klein pcap-bestand met Modbus-verkeer; ze hebben GRFICS niet nodig."""
import http.server
import json
import pathlib
import struct
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from bench import build, datasets, grfics, modbus, pcap, report, run, runners  # noqa: E402

CHECK = {"fn": None}  # de scheidsrechter van de dataset die de lopende test gebruikt


def fake_model(messages, tools, sloppy, json_mode):
    """Het volgende antwoord van een model dat de taak goed doet, afgeleid uit het gesprek tot nu toe."""
    if json_mode and "All evidence is below" in messages[0]["content"]:  # variant 0
        evidence = json.loads(messages[1]["content"].split("\n\n", 1)[1])
        broken = CHECK["fn"](evidence["transactions"])
        return {"role": "assistant", "content": json.dumps({"verdict": broken[0] if broken else "valid", "reason": "checked"})}
    native = bool(tools)
    names = [t["function"]["name"] for t in tools or []]
    final = "report_findings" if "report_findings" in names or (not native and "report_findings" in messages[0]["content"]) else "submit_verdict"
    seen, total, policy = [], None, False
    for m in messages:
        text = m.get("content") or ""
        if m["role"] == "tool" or text.startswith("TOOL RESULT: "):
            data = json.loads(text.removeprefix("TOOL RESULT: "))
            policy = policy or "rules" in data
            if "transactions" in data:
                total = data["total"]
                seen += data["transactions"]
    if sloppy and sum(m["role"] == "assistant" for m in messages) == 0:
        return {"role": "assistant", "content": "I think it is fine."}
    if not policy:
        name, arguments = "get_policy", {}
    elif total is None or len(seen) < total:
        name, arguments = "get_transactions", {"start": len(seen)}
    else:
        broken = CHECK["fn"](seen)
        verdict = broken[0] if broken else "valid"
        name, arguments = (final, {"findings": f"I found: {verdict}"}) if final == "report_findings" else (final, {"verdict": verdict, "reason": "checked"})
    if native:
        return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}
    return {"role": "assistant", "content": json.dumps({"tool": name, "arguments": arguments})}


class FakeOllama(http.server.BaseHTTPRequestHandler):
    def _send(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        if self.path == "/api/version":
            self._send({"version": "0.0.0-fake"})
        else:
            self._send({"models": [{"name": n, "digest": "sha256:" + n, "size": 2_000_000_000, "details": {"quantization_level": "Q4_K_M"}}
                                   for n in ("good:1b", "sloppy:1b")]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["options"]["temperature"] == 0 and body["stream"] is False
        message = fake_model(body["messages"], body.get("tools"), body["model"].startswith("sloppy"), body.get("format") == "json")
        self._send({"message": message, "prompt_eval_count": 100, "eval_count": 20, "eval_duration": 2_000_000_000})

    def log_message(self, *args):
        pass


# ---- een klein pcap-bestand met Modbus/TCP, zoals tcpdump het schrijft ----

def _ip(a):
    return bytes(int(x) for x in a.split("."))


def _packet(t, src, sport, dst, dport, payload, seq):
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, 0x18, 65535, 0, 0) + payload
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0, _ip(src), _ip(dst)) + tcp
    frame = b"\x00" * 12 + b"\x08\x00" + ip
    return struct.pack("<IIII", int(t), int((t % 1) * 1e6), len(frame), len(frame)) + frame


def make_pcap(requests):
    """requests: [(t, src, dst, pdu, exception)]; een verzoek naar poort 502 en, als exception, een foutantwoord."""
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for n, (t, src, dst, pdu, exception) in enumerate(requests):
        port = 40000 + n
        out += _packet(t, src, port, dst, 502, struct.pack(">HHHB", n, 0, len(pdu) + 1, 1) + pdu, n)
        reply = bytes([pdu[0] | 0x80, exception]) if exception else pdu[:1] + b"\x00"
        out += _packet(t + 0.001, dst, 502, src, port, struct.pack(">HHHB", n, 0, len(reply) + 1, 1) + reply, n)
    return out


def grfics_traffic(start=1_000_000.0, seconds=40):
    """Een basislijn zoals in GRFICS, en daarna één verzoek per scenario."""
    rows, t = [], start
    while t < start + seconds:
        for d in range(10, 16):
            rows.append((t, grfics.PLC, f"192.168.95.{d}", struct.pack(">BHH", 4, 1, 2), 0))
            rows.append((t, grfics.PLC, f"192.168.95.{d}", struct.pack(">BHHB", 16, 1, 1, 2) + b"\x00\x05", 0))
        if round(t - start, 1) % 2 == 0:
            rows += [(t + 0.05, grfics.HMI, grfics.PLC, struct.pack(">BHH", 1, 0, 41), 0),
                     (t + 0.05, grfics.HMI, grfics.PLC, struct.pack(">BHH", 3, 10, 4), 0),
                     (t + 0.05, grfics.HMI, grfics.PLC, struct.pack(">BHH", 4, 100, 13), 0)]
        t = round(t + 0.5, 1)
    baseline_until = t
    scenarios = [("unknown_client", ("192.168.90.6", struct.pack(">BHH", 3, 10, 4), 0)),
                 ("forbidden_function", (grfics.EWS, bytes.fromhex("2b0e0100"), 1)),
                 ("illegal_address", (grfics.EWS, struct.pack(">BHH", 3, 500, 10), 0)),
                 ("unauthorized_write", (grfics.HMI, struct.pack(">BHH", 6, 10, 7), 0))]
    marks = []
    for rule, (src, pdu, exception) in scenarios:
        t += 10
        rows.append((t, src, grfics.PLC, pdu, exception))
        marks.append({"scenario": rule, "rule": rule, "start": t - 0.01, "end": t + 0.01})
        for d in range(10, 16):  # de PLC gaat intussen door
            rows.append((t - 3, grfics.PLC, f"192.168.95.{d}", struct.pack(">BHH", 4, 1, 2), 0))
    return make_pcap(sorted(rows)), {"baseline_until": baseline_until, "marks": marks, "grfics_commit": "test"}


class Synthetic(unittest.TestCase):
    def test_same_seed_same_cases(self):
        self.assertEqual(modbus.fingerprint(modbus.make_cases(30, 1)), modbus.fingerprint(modbus.make_cases(30, 1)))
        self.assertNotEqual(modbus.fingerprint(modbus.make_cases(30, 1)), modbus.fingerprint(modbus.make_cases(30, 2)))

    def test_every_case_breaks_exactly_its_own_rule(self):
        cases = modbus.make_cases(120, 7)
        for case in cases:
            self.assertEqual(modbus.check(case["transactions"]), [] if case["label"] == "valid" else [case["label"]], case["id"])
        self.assertEqual({c["label"] for c in cases}, set(modbus.VERDICTS))

    def test_the_checker_by_hand(self):
        ok = {"t": 0.0, "src": modbus.HMI, "unit": 1, "fc": 3, "addr": 0, "count": 10, "values": None}
        write = lambda t, addr, value, src=modbus.HMI: {"t": t, "src": src, "unit": 1, "fc": 6, "addr": addr, "count": 1, "values": [value]}
        self.assertEqual(modbus.check([ok]), [])
        self.assertEqual(modbus.check([{**ok, "src": "10.0.0.9"}]), ["unknown_client"])
        self.assertEqual(modbus.check([{**ok, "fc": 8}]), ["forbidden_function"])
        self.assertEqual(modbus.check([write(0, 40, 3001)]), ["value_out_of_range"])
        self.assertEqual(modbus.check([write(i * 2.0, 42, 50) for i in range(6)]), ["write_flood"])

    def test_tools_refuse_bad_arguments(self):
        d = datasets.Synthetic(3, 1)
        case = d.cases[0]
        self.assertTrue(d.call(case, "get_policy", {})[1])
        self.assertEqual(len(d.call(case, "get_transactions", {"start": 0})[0]["transactions"]), datasets.PAGE)
        for name, arguments in (("get_transactions", {"start": -1}), ("get_transactions", {"start": "0"}), ("get_register_info", {"address": 100}),
                                ("get_register_info", {}), ("delete_everything", {}), ("get_policy", "x")):
            self.assertFalse(d.call(case, name, arguments)[1], (name, arguments))
        self.assertNotIn("label", json.dumps(d.call(case, "get_transactions", {"start": 0})[0]))


class Grfics(unittest.TestCase):
    def test_pcap_gives_the_requests_with_their_exceptions(self):
        raw, _ = grfics_traffic(seconds=2)
        rows = pcap.transactions(raw)
        # Twee seconden basislijn: 4 rondes van 12 verzoeken, 1 keer de HMI met 3; daarna 4 scenario's en 4 keer 6 polls.
        self.assertEqual(len(rows), 4 * 12 + 3 + 4 + 4 * 6)
        device_id = next(r for r in rows if r["fc"] == 43)
        self.assertEqual((device_id["src"], device_id["exception"], device_id["addr"]), (grfics.EWS, 1, None))
        write = next(r for r in rows if r["fc"] == 16)
        self.assertEqual((write["addr"], write["count"], write["values"]), (1, 1, [5]))
        self.assertEqual(next(r for r in rows if r["fc"] == 1)["count"], 41)
        self.assertEqual([r["t"] for r in rows], sorted(r["t"] for r in rows))

    def test_policy_comes_from_the_baseline(self):
        raw, marks = grfics_traffic()
        rows = pcap.transactions(raw)
        policy = grfics.derive_policy([r for r in rows if r["t"] < marks["baseline_until"]])
        plc = policy["servers"][grfics.PLC]
        self.assertEqual(plc["clients"][grfics.HMI], {"role": "HMI", "write": False})
        self.assertTrue(plc["clients"][grfics.EWS]["write"])
        self.assertEqual(plc["map"], {"coils": [0, 40], "holding_registers": [10, 13], "input_registers": [100, 112]})
        self.assertNotIn(43, plc["functions"])
        self.assertEqual(policy["servers"]["192.168.95.12"]["clients"], {grfics.PLC: {"role": "PLC", "write": True}})

    def test_every_case_breaks_exactly_its_own_rule(self):
        raw, marks = grfics_traffic()
        policy, cases, skipped = grfics.build_cases(pcap.transactions(raw), marks["marks"], marks["baseline_until"])
        self.assertEqual(skipped, [])
        self.assertEqual({c["label"] for c in cases}, set(grfics.VERDICTS))
        for case in cases:
            self.assertEqual(grfics.check(policy, case["transactions"]), [] if case["label"] == "valid" else [case["label"]])
            self.assertEqual([t["i"] for t in case["transactions"]], list(range(len(case["transactions"]))))

    def test_the_checker_by_hand(self):
        raw, marks = grfics_traffic()
        policy = grfics.derive_policy([r for r in pcap.transactions(raw) if r["t"] < marks["baseline_until"]])
        read = {"src": grfics.HMI, "dst": grfics.PLC, "fc": 3, "addr": 10, "count": 4, "values": None}
        self.assertEqual(grfics.check(policy, [read]), [])
        self.assertEqual(grfics.check(policy, [{**read, "count": 5}]), ["illegal_address"])
        self.assertEqual(grfics.check(policy, [{**read, "fc": 2}]), ["forbidden_function"])
        self.assertEqual(grfics.check(policy, [{**read, "src": "192.168.90.6", "fc": 43}]), ["unknown_client"])
        self.assertEqual(grfics.check(policy, [{**read, "fc": 6, "count": 1, "values": [7]}]), ["unauthorized_write"])
        self.assertEqual(grfics.check(policy, [{**read, "src": grfics.EWS, "fc": 6, "count": 1, "values": [7]}]), [])
        self.assertEqual(grfics.check(policy, [{**read, "src": "192.168.95.13", "dst": "192.168.95.11"}]), ["unknown_client"])

    def test_dataset_file_and_its_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            raw, marks = grfics_traffic()
            (pathlib.Path(folder) / "capture.pcap").write_bytes(raw)
            (pathlib.Path(folder) / "marks.json").write_text(json.dumps(marks))
            build.main([folder, "--out", f"{folder}/d.json"])
            d = datasets.load(f"{folder}/d.json")
        case = d.cases[0]
        self.assertEqual(d.name, "grfics")
        self.assertNotIn("map", json.dumps(d.call(case, "get_policy", {})[0]["servers"]))
        self.assertEqual(d.call(case, "get_register_map", {"server": grfics.PLC})[0]["map"]["holding_registers"], {"first": 10, "last": 13})
        self.assertFalse(d.call(case, "get_register_map", {"server": "10.0.0.1"})[1])
        self.assertFalse(d.call(case, "get_register_map", {"server": 5})[1])
        self.assertNotIn("label", json.dumps(d.evidence(case)))


class Benchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        runners.OLLAMA_URL = f"http://127.0.0.1:{cls.server.server_port}"
        cls.folder = tempfile.TemporaryDirectory()
        raw, marks = grfics_traffic()
        (pathlib.Path(cls.folder.name) / "capture.pcap").write_bytes(raw)
        (pathlib.Path(cls.folder.name) / "marks.json").write_text(json.dumps(marks))
        cls.grfics_file = f"{cls.folder.name}/grfics.json"
        build.main([cls.folder.name, "--out", cls.grfics_file])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.folder.cleanup()

    def rows(self, *argv):
        dataset_path = next((argv[i + 1] for i, a in enumerate(argv) if a == "--dataset"), None)
        dataset = datasets.load(dataset_path, *(int(argv[i + 1]) for i, a in enumerate(argv) if a == "--cases"))
        CHECK["fn"] = dataset.check
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder) / "r.jsonl"
            run.main([*argv, "--out", str(out)])
            run.main([*argv, "--out", str(out)])  # een tweede keer: niets opnieuw, niets dubbel
            lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            summary = report.summarise(out)
        self.assertIn("| Model | Variant | Runs | Juist | Precision |", summary)
        self.assertTrue(lines[0]["meta"])
        self.assertEqual(lines[0]["dataset"], dataset.name)
        return lines[1:]

    def assert_perfect(self, rows):
        self.assertTrue(all(r["correct"] and r["invalid_calls"] == 0 and r["error"] is None for r in rows), [r for r in rows if not r["correct"]][:2])
        precision, recall, f1, _ = report.scores(rows)
        self.assertEqual((precision, recall, f1), (1.0, 1.0, 1.0))

    def test_synthetic_all_local_variants(self):
        rows = self.rows("--models", "good:1b", "--variants", "direct,manual,native,multi", "--cases", "14")
        self.assertEqual(len(rows), 4 * 14)
        self.assert_perfect(rows)
        by = {v: [r for r in rows if r["variant"] == v] for v in ("direct", "native", "multi")}
        self.assertTrue(all(r["llm_calls"] == 1 for r in by["direct"]))
        self.assertGreater(sum(r["llm_calls"] for r in by["multi"]), sum(r["llm_calls"] for r in by["native"]))

    def test_grfics_all_local_variants(self):
        rows = self.rows("--models", "good:1b", "--variants", "direct,manual,native,multi", "--dataset", self.grfics_file)
        self.assertEqual({r["label"] for r in rows}, set(grfics.VERDICTS))
        self.assert_perfect(rows)

    def test_invalid_calls_are_counted(self):
        rows = self.rows("--models", "sloppy:1b", "--variants", "manual,native", "--cases", "5")
        self.assertTrue(all(r["correct"] and r["invalid_calls"] == 1 for r in rows), rows[:2])

    def test_repeats_give_consistency(self):
        rows = self.rows("--models", "good:1b", "--variants", "direct", "--cases", "4", "--repeats", "2")
        self.assertEqual(len(rows), 8)
        self.assertEqual(report.scores(rows)[3], 1.0)

    def test_mcp_variant_uses_the_same_tools_through_the_server(self):
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest("het pakket mcp is niet geinstalleerd")
        for argv in (("--cases", "6"), ("--dataset", self.grfics_file)):
            rows = self.rows("--models", "good:1b", "--variants", "mcp", *argv)
            self.assert_perfect(rows)

    def test_unknown_model_stops_before_anything_runs(self):
        with self.assertRaises(SystemExit) as stop:
            run.main(["--models", "nope:1b", "--out", str(pathlib.Path(tempfile.gettempdir()) / "cydes-nope.jsonl")])
        self.assertIn("Niet in Ollama", str(stop.exception))


class Scores(unittest.TestCase):
    def test_precision_recall_f1(self):
        rows = [{"case": "a", "label": "valid", "verdict": "valid"}, {"case": "b", "label": "valid", "verdict": "unknown_client"},
                {"case": "c", "label": "illegal_address", "verdict": "unknown_client"}, {"case": "d", "label": "illegal_address", "verdict": None}]
        precision, recall, f1, consistent = report.scores(rows)
        self.assertEqual((precision, recall, round(f1, 3), consistent), (0.5, 0.5, 0.5, None))

    def test_process_names(self):
        self.assertTrue(run.is_ollama(["/usr/local/lib/ollama/llama-server", "--model", "x"]))
        self.assertTrue(run.is_ollama(["/usr/local/bin/ollama", "serve"]))
        self.assertFalse(run.is_ollama(["/opt/cydes/venv/bin/python", "-m", "bench.run"]))
        self.assertTrue(run.is_mcp_server(["python", "-m", "bench.mcp_server", "--dataset", "x"]))


if __name__ == "__main__":
    unittest.main()
