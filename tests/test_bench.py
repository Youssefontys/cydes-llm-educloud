"""Tests van de benchmark zonder echt model: een nagemaakte Ollama speelt het model.

    python -m unittest discover -s tests -v

De nagemaakte Ollama gedraagt zich als een model dat de taak goed doet: beleid lezen, alle transacties opvragen en
dan het oordeel geven dat modbus.check() geeft. Zo test dit de hele keten (de prompt, het ontleden van het antwoord,
de tools, de MCP-server en de meting), en moet elke variant op 100% uitkomen. Een tweede "model" geeft eerst onzin,
om te testen dat ongeldige aanroepen geteld worden. Dit zegt niets over hoe goed een echt model is."""
import http.server
import json
import pathlib
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from bench import modbus, report, run, runners  # noqa: E402


def fake_model(messages, tools, sloppy):
    """Het volgende antwoord van een model dat de taak goed doet, afgeleid uit het gesprek tot nu toe."""
    native = bool(tools)
    final = "report_findings" if any(t["function"]["name"] == "report_findings" for t in tools or []) else "submit_verdict"
    if not native and "report_findings" in messages[0]["content"]:
        final = "report_findings"
    seen, total, policy = [], None, False
    for m in messages:
        text = m.get("content") or ""
        if m["role"] == "tool" or text.startswith("TOOL RESULT: "):
            data = json.loads(text.removeprefix("TOOL RESULT: "))
            policy = policy or "rules" in data
            if "transactions" in data:
                total = data["total"]
                seen += data["transactions"]
    turns = sum(m["role"] == "assistant" for m in messages)
    if sloppy and turns == 0:
        return {"role": "assistant", "content": "I think it is fine."}
    if not policy:
        name, arguments = "get_policy", {}
    elif total is None or len(seen) < total:
        name, arguments = "get_transactions", {"start": len(seen)}
    else:
        broken = modbus.check(seen)
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
        message = fake_model(body["messages"], body.get("tools"), body["model"].startswith("sloppy"))
        self._send({"message": message, "prompt_eval_count": 100, "eval_count": 20, "eval_duration": 2_000_000_000})

    def log_message(self, *args):
        pass


class Dataset(unittest.TestCase):
    def test_same_seed_same_cases(self):
        self.assertEqual(modbus.fingerprint(modbus.make_cases(30, 1)), modbus.fingerprint(modbus.make_cases(30, 1)))
        self.assertNotEqual(modbus.fingerprint(modbus.make_cases(30, 1)), modbus.fingerprint(modbus.make_cases(30, 2)))

    def test_every_case_breaks_exactly_its_own_rule(self):
        cases = modbus.make_cases(120, 7)
        for case in cases:
            self.assertEqual(modbus.check(case["transactions"]), [] if case["label"] == "valid" else [case["label"]], case["id"])
        self.assertEqual({c["label"] for c in cases}, set(modbus.VERDICTS))
        self.assertEqual(sum(c["label"] == "valid" for c in cases), 48)

    def test_the_checker_by_hand(self):
        ok = {"t": 0.0, "src": modbus.HMI, "unit": 1, "fc": 3, "addr": 0, "count": 10, "values": None}
        write = lambda t, addr, value, src=modbus.HMI: {"t": t, "src": src, "unit": 1, "fc": 6, "addr": addr, "count": 1, "values": [value]}
        self.assertEqual(modbus.check([ok]), [])
        self.assertEqual(modbus.check([{**ok, "src": "10.0.0.9"}]), ["unknown_client"])
        self.assertEqual(modbus.check([{**ok, "fc": 8}]), ["forbidden_function"])
        self.assertEqual(modbus.check([{**ok, "addr": 95}]), ["illegal_address"])
        self.assertEqual(modbus.check([write(0, 40, 3000)]), [])
        self.assertEqual(modbus.check([write(0, 40, 3001)]), ["value_out_of_range"])
        self.assertEqual(modbus.check([write(0, 5, 1)]), ["unauthorized_write"])
        self.assertEqual(modbus.check([write(0, 60, 1)]), ["unauthorized_write"])
        self.assertEqual(modbus.check([write(0, 60, 1, modbus.EWS)]), [])
        self.assertEqual(modbus.check([write(i * 2.0, 42, 50) for i in range(5)]), [])
        self.assertEqual(modbus.check([write(i * 2.0, 42, 50) for i in range(6)]), ["write_flood"])
        self.assertEqual(modbus.check([write(i * 2.1, 42, 50) for i in range(6)]), [])

    def test_tools_refuse_bad_arguments(self):
        case = modbus.make_cases(3, 1)[0]
        self.assertTrue(modbus.call_tool(case, "get_policy", {})[1])
        self.assertEqual(len(modbus.call_tool(case, "get_transactions", {"start": 0})[0]["transactions"]), modbus.PAGE)
        for name, arguments in (("get_transactions", {"start": -1}), ("get_transactions", {"start": "0"}), ("get_register_info", {"address": 100}),
                                ("get_register_info", {}), ("delete_everything", {}), ("get_policy", "x")):
            self.assertFalse(modbus.call_tool(case, name, arguments)[1], (name, arguments))
        # Het antwoord staat niet in wat een tool teruggeeft.
        self.assertNotIn("label", json.dumps(modbus.call_tool(case, "get_transactions", {"start": 0})[0]))


class Benchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        runners.OLLAMA_URL = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def rows(self, *argv):
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder) / "r.jsonl"
            run.main([*argv, "--out", str(out)])
            run.main([*argv, "--out", str(out)])  # een tweede keer: niets opnieuw, niets dubbel
            lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            self.assertIn("| Model | Variant |", report.summarise(out))
        self.assertTrue(lines[0]["meta"])
        self.assertEqual(lines[0]["ollama"], "0.0.0-fake")
        return lines[1:]

    def test_three_variants_score_everything_with_a_good_model(self):
        rows = self.rows("--models", "good:1b", "--variants", "manual,native,multi", "--cases", "14")
        self.assertEqual(len(rows), 3 * 14)
        self.assertTrue(all(r["correct"] and r["invalid_calls"] == 0 and r["error"] is None for r in rows), [r for r in rows if not r["correct"]][:2])
        by = {v: [r for r in rows if r["variant"] == v] for v in ("manual", "native", "multi")}
        # Een case van meer dan 10 transacties vraagt twee pagina's; multi doet het werk twee keer.
        self.assertTrue(all(r["llm_calls"] >= 3 for r in rows))
        self.assertGreater(sum(r["llm_calls"] for r in by["multi"]), sum(r["llm_calls"] for r in by["native"]))
        self.assertEqual(rows[0]["tokens_per_second"], 10.0)

    def test_invalid_calls_are_counted(self):
        rows = self.rows("--models", "sloppy:1b", "--variants", "manual,native", "--cases", "5")
        self.assertTrue(all(r["correct"] and r["invalid_calls"] == 1 for r in rows), rows[:2])

    def test_mcp_variant_uses_the_same_tools_through_the_server(self):
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest("het pakket mcp is niet geinstalleerd")
        rows = self.rows("--models", "good:1b", "--variants", "mcp", "--cases", "8")
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r["correct"] and r["invalid_calls"] == 0 and r["error"] is None for r in rows), rows[:2])

    def test_unknown_model_stops_before_anything_runs(self):
        with self.assertRaises(SystemExit) as stop:
            run.main(["--models", "nope:1b", "--out", str(pathlib.Path(tempfile.gettempdir()) / "cydes-nope.jsonl")])
        self.assertIn("Niet in Ollama", str(stop.exception))


if __name__ == "__main__":
    unittest.main()
