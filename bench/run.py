"""Draait de benchmark: elk model, in elke variant, op elke case, en schrijft per run één regel naar een JSONL-bestand.

    python -m bench.run --models qwen2.5:3b,llama3.2:3b
    python -m bench.run --models qwen2.5:3b --variants manual,native --cases 10 --repeats 3

Op CPU duurt dit lang. Daarom schrijft het elke run meteen weg, en slaat het over wat al in het bestand staat: na een
onderbreking draai je dezelfde opdracht opnieuw en gaat het verder. De eerste regel van het bestand legt vast waarop
gemeten is (de versie van Ollama, de digest van elk model, CPU's en geheugen), want zonder dat zegt een meting niets.

Per run: het oordeel en of het klopt, het aantal aanroepen van het model en van de tools, hoeveel daarvan ongeldig
waren, de doorlooptijd, de tokens, de tokens per seconde en het piekgeheugen van Ollama.
Alleen de standaardbibliotheek, behalve mcp voor de variant mcp."""
import argparse
import datetime
import glob
import json
import os
import pathlib
import platform
import sys
import threading
import time
import urllib.error

from . import modbus, runners

VARIANTS = ("manual", "native", "mcp", "multi")


class PeakMemory:
    """Het hoogste geheugengebruik (RSS) van de processen van Ollama tijdens een run, in MB. Alleen op Linux."""

    def __init__(self):
        self.peak, self._stop = None, threading.Event()

    @staticmethod
    def is_ollama(argv0):
        # Het model draait niet in "ollama serve" (40 MB) maar in een eigen proces, /usr/local/lib/ollama/llama-server
        # (Ollama 0.40); oudere versies heten "ollama runner". Op de naam van het programma, want comm is per versie anders.
        name = argv0.rsplit("/", 1)[-1]
        return name in ("ollama", "llama-server") or "/ollama/" in argv0

    def _sample(self):
        total = 0
        for cmdline in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                path = pathlib.Path(cmdline)
                if self.is_ollama(path.read_bytes().split(b"\0")[0].decode(errors="replace")):
                    for line in path.with_name("status").read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            total += int(line.split()[1])
            except OSError:
                continue
        return total / 1024 if total else None

    def __enter__(self):
        def watch():
            while not self._stop.is_set():
                now = self._sample()
                if now is not None:
                    self.peak = max(self.peak or 0, now)
                self._stop.wait(0.5)
        self._thread = threading.Thread(target=watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(2)


def environment(models, args, cases):
    """Waarop gemeten is: zonder dit is een getal niet te vergelijken met een ander."""
    tags = {m["name"]: m for m in runners.ollama("/api/tags").get("models", [])}
    memory = None
    try:
        memory = round(int(pathlib.Path("/proc/meminfo").read_text().split()[1]) / 1024 / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    try:
        from importlib.metadata import version
        mcp_version = version("mcp")
    except Exception:
        mcp_version = None
    return {"meta": True, "started": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "ollama": runners.ollama("/api/version").get("version"), "mcp": mcp_version, "python": platform.python_version(),
            "machine": platform.machine(), "cpus": os.cpu_count(), "memory_gb": memory,
            "models": {m: {"digest": (tags.get(m) or {}).get("digest"), "size_mb": round(((tags.get(m) or {}).get("size") or 0) / 1e6),
                           "quantization": ((tags.get(m) or {}).get("details") or {}).get("quantization_level")} for m in models},
            "cases": len(cases), "seed": args.seed, "dataset": modbus.fingerprint(cases), "num_ctx": args.num_ctx,
            "temperature": 0, "max_steps": runners.MAX_STEPS}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--models", required=True, help="modelnamen zoals Ollama ze kent, gescheiden door komma's")
    parser.add_argument("--variants", default=",".join(VARIANTS), help=f"standaard alle vier: {','.join(VARIANTS)}")
    parser.add_argument("--cases", type=int, default=30, help="hoeveel cases (standaard 30)")
    parser.add_argument("--seed", type=int, default=1, help="de seed van de cases en van het model (standaard 1)")
    parser.add_argument("--repeats", type=int, default=1, help="hoe vaak elke case (standaard 1)")
    parser.add_argument("--num-ctx", type=int, default=4096, help="contextvenster in tokens (standaard 4096)")
    parser.add_argument("--out", default="results/results.jsonl", help="het JSONL-bestand met de uitkomsten")
    args = parser.parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    if unknown := [v for v in variants if v not in VARIANTS]:
        sys.exit(f"Onbekende variant: {', '.join(unknown)}. Kies uit: {', '.join(VARIANTS)}.")
    cases = modbus.make_cases(args.cases, args.seed)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        meta = environment(models, args, cases)
    except urllib.error.URLError as error:
        sys.exit(f"Ollama antwoordt niet op {runners.OLLAMA_URL}: {error.reason}. Draait de dienst (systemctl status ollama)?")
    if missing := [m for m in models if not meta["models"][m]["digest"]]:
        sys.exit(f"Niet in Ollama: {', '.join(missing)}. Haal ze eerst op met: ollama pull <model>")

    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("meta"):
                if row["dataset"] != meta["dataset"]:
                    sys.exit(f"{out} is met andere cases gemaakt (--cases of --seed verschilt). Kies een ander --out.")
            else:
                done.add((row["model"], row["variant"], row["case"], row["repeat"]))
    bridge = None
    if "mcp" in variants:
        try:
            from .mcp_bridge import McpBridge
        except ImportError:
            sys.exit("De variant mcp vraagt het pakket mcp: pip install -r requirements.txt, of laat mcp weg met --variants.")
        bridge = McpBridge(args.cases, args.seed)

    options = {"temperature": 0, "seed": args.seed, "num_ctx": args.num_ctx}
    total = len(models) * len(variants) * len(cases) * args.repeats
    print(f"{total} runs, waarvan {len(done)} al gedaan; uitkomsten in {out}")
    with out.open("a", encoding="utf-8") as f:
        if not done:
            f.write(json.dumps(meta) + "\n")
        n = 0
        try:
            for model in models:
                for variant in variants:
                    for repeat in range(1, args.repeats + 1):
                        for case in cases:
                            n += 1
                            if (model, variant, case["id"], repeat) in done:
                                continue
                            started, error, verdict, stats = time.monotonic(), None, None, runners.Stats()
                            with PeakMemory() as memory:
                                try:
                                    verdict, stats = runners.run_case(variant, model, case, options, bridge)
                                except Exception as problem:  # één mislukte run mag de rest niet stoppen
                                    error = f"{type(problem).__name__}: {problem}"[:300]
                            wall = time.monotonic() - started
                            row = {"model": model, "variant": variant, "case": case["id"], "repeat": repeat, "label": case["label"],
                                   "verdict": verdict, "correct": verdict == case["label"],
                                   "correct_binary": verdict is not None and (verdict == "valid") == (case["label"] == "valid"),
                                   "wall_seconds": round(wall, 2), **{k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()},
                                   "tokens_per_second": round(stats["output_tokens"] / stats["eval_seconds"], 2) if stats["eval_seconds"] else None,
                                   "peak_rss_mb": round(memory.peak) if memory.peak else None, "error": error}
                            f.write(json.dumps(row) + "\n")
                            f.flush()
                            mark = "goed" if row["correct"] else "FOUT" if verdict else "geen oordeel"
                            print(f"[{n}/{total}] {model} {variant} {case['id']}: {mark} ({verdict or error or '-'}), {wall:.0f} s")
        except KeyboardInterrupt:
            print("\nGestopt. Dezelfde opdracht opnieuw gaat verder waar dit ophield.")
        finally:
            if bridge:
                bridge.close()
    print(f"Klaar. Samenvatting: python -m bench.report {out}")


if __name__ == "__main__":
    main()
