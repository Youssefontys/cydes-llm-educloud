"""Draait de benchmark: elk model, in elke variant, op elke case, en schrijft per run één regel naar een JSONL-bestand.

    python -m bench.run --models qwen2.5:3b --dataset data/grfics-2026-11-17.json
    python -m bench.run --models qwen2.5:3b,llama3.2:3b --variants direct,manual,native --repeats 3
    python -m bench.run --models qwen2.5:3b --cases 10              zonder --dataset: de nagemaakte cases

Op CPU duurt dit lang. Daarom schrijft het elke run meteen weg, en slaat het over wat al in het bestand staat: na een
onderbreking draai je dezelfde opdracht opnieuw en gaat het verder. De eerste regel van het bestand legt vast waarop
gemeten is (de versie van Ollama, de digest van elk model, de dataset, CPU's en geheugen), want zonder dat zegt een
meting niets.

Per run: het oordeel en of het klopt, het aantal aanroepen van het model en van de tools, hoeveel daarvan ongeldig
waren, de doorlooptijd, de tokens, de tokens per seconde, en van Ollama en (bij mcp) van de MCP-server het
piekgeheugen en de CPU-tijd. Alleen de standaardbibliotheek, behalve mcp voor de variant mcp."""
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

from . import datasets, runners

VARIANTS = runners.VARIANTS


class ProcessMeter:
    """Piekgeheugen (RSS, MB) en CPU-tijd (seconden) van de processen die bij match passen, tijdens een run. Alleen op Linux."""

    TICK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") and "SC_CLK_TCK" in getattr(os, "sysconf_names", {}) else 100

    def __init__(self, match):
        self.match, self.peak_mb, self.cpu_seconds, self._stop = match, None, None, threading.Event()

    def _processes(self):
        """{pid: (rss in kB, cpu-ticks)} van de passende processen."""
        found = {}
        for cmdline in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                path = pathlib.Path(cmdline)
                argv = path.read_bytes().split(b"\0")
                if not self.match([a.decode(errors="replace") for a in argv if a]):
                    continue
                rss = next((int(line.split()[1]) for line in path.with_name("status").read_text().splitlines() if line.startswith("VmRSS:")), 0)
                # Na de naam tussen haakjes: veld 14 en 15 (utime, stime) staan op plek 11 en 12.
                fields = path.with_name("stat").read_text().rsplit(")", 1)[1].split()
                found[path.parent.name] = (rss, int(fields[11]) + int(fields[12]))
            except (OSError, IndexError, ValueError):
                continue
        return found

    def __enter__(self):
        self._start = self._processes()
        self._last = dict(self._start)

        def watch():
            while not self._stop.is_set():
                now = self._processes()
                if now:
                    self._last.update(now)
                    total = sum(rss for rss, _ in now.values()) / 1024
                    self.peak_mb = max(self.peak_mb or 0, total) or None
                self._stop.wait(0.5)
        self._thread = threading.Thread(target=watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(2)
        self._last.update(self._processes())
        if self._last:
            ticks = sum(t - self._start.get(pid, (0, 0))[1] for pid, (_, t) in self._last.items())
            self.cpu_seconds = round(ticks / self.TICK, 2)


def is_ollama(argv):
    # Het model draait niet in "ollama serve" (40 MB) maar in een eigen proces, /usr/local/lib/ollama/llama-server
    # (Ollama 0.40); oudere versies heten "ollama runner". Op de naam van het programma.
    first = argv[0] if argv else ""
    return first.rsplit("/", 1)[-1] in ("ollama", "llama-server") or "/ollama/" in first


def is_mcp_server(argv):
    return "bench.mcp_server" in argv


def environment(models, args, dataset):
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
            "dataset": dataset.name, "dataset_fingerprint": dataset.fingerprint, "source": dataset.source, "cases": len(dataset.cases),
            "num_ctx": args.num_ctx, "temperature": 0, "seed": args.seed, "max_steps": runners.MAX_STEPS}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--models", required=True, help="modelnamen zoals Ollama ze kent, gescheiden door komma's")
    parser.add_argument("--variants", default=",".join(VARIANTS), help=f"standaard alle vijf: {','.join(VARIANTS)}")
    parser.add_argument("--dataset", help="een GRFICS-dataset (data/grfics-*.json); zonder: de nagemaakte cases")
    parser.add_argument("--cases", type=int, default=30, help="alleen zonder --dataset: hoeveel nagemaakte cases (standaard 30)")
    parser.add_argument("--seed", type=int, default=1, help="de seed van het model, en van de nagemaakte cases (standaard 1)")
    parser.add_argument("--only", help="alleen deze cases, ids gescheiden door komma's; voor een korte proef")
    parser.add_argument("--repeats", type=int, default=1, help="hoe vaak elke case (standaard 1); meer geeft de consistentie")
    parser.add_argument("--num-ctx", type=int, default=4096, help="contextvenster in tokens (standaard 4096)")
    parser.add_argument("--out", default="results/results.jsonl", help="het JSONL-bestand met de uitkomsten")
    args = parser.parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    if unknown := [v for v in variants if v not in VARIANTS]:
        sys.exit(f"Onbekende variant: {', '.join(unknown)}. Kies uit: {', '.join(VARIANTS)}.")
    try:
        dataset = datasets.load(args.dataset, args.cases, args.seed)
    except (OSError, ValueError, KeyError) as problem:
        sys.exit(f"De dataset is niet te lezen: {problem}")
    if args.only:
        wanted = args.only.split(",")
        if unknown := [c for c in wanted if c not in {case["id"] for case in dataset.cases}]:
            sys.exit(f"Niet in de dataset: {', '.join(unknown)}.")
        dataset.cases = [case for case in dataset.cases if case["id"] in wanted]
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        meta = environment(models, args, dataset)
    except urllib.error.URLError as error:
        sys.exit(f"Ollama antwoordt niet op {runners.OLLAMA_URL}: {error.reason}. Draait de dienst (systemctl status ollama)?")
    if missing := [m for m in models if not meta["models"][m]["digest"]]:
        sys.exit(f"Niet in Ollama: {', '.join(missing)}. Haal ze eerst op met: ollama pull <model>")

    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("meta"):
                if row.get("dataset_fingerprint") != meta["dataset_fingerprint"]:
                    sys.exit(f"{out} is met een andere dataset gemaakt. Kies een ander --out.")
            else:
                done.add((row["model"], row["variant"], row["case"], row["repeat"]))
    bridge = None
    if "mcp" in variants:
        try:
            from .mcp_bridge import McpBridge
        except ImportError:
            sys.exit("De variant mcp vraagt het pakket mcp: pip install -r requirements.txt, of laat mcp weg met --variants.")
        bridge = McpBridge(dataset)

    options = {"temperature": 0, "seed": args.seed, "num_ctx": args.num_ctx}
    total = len(models) * len(variants) * len(dataset.cases) * args.repeats
    print(f"{total} runs op de dataset {dataset.name} ({len(dataset.cases)} cases), waarvan {len(done)} al gedaan; uitkomsten in {out}")
    with out.open("a", encoding="utf-8") as f:
        if not done:
            f.write(json.dumps(meta) + "\n")
        n = 0
        try:
            for model in models:
                for variant in variants:
                    for repeat in range(1, args.repeats + 1):
                        for case in dataset.cases:
                            n += 1
                            if (model, variant, case["id"], repeat) in done:
                                continue
                            started, error, verdict, reason, stats = time.monotonic(), None, None, None, runners.Stats()
                            with ProcessMeter(is_ollama) as llm, ProcessMeter(is_mcp_server) as server:
                                try:
                                    verdict, reason, stats = runners.run_case(variant, model, dataset, case, options, bridge)
                                except Exception as problem:  # één mislukte run mag de rest niet stoppen
                                    error = f"{type(problem).__name__}: {problem}"[:300]
                            wall = time.monotonic() - started
                            row = {"model": model, "variant": variant, "case": case["id"], "repeat": repeat, "label": case["label"],
                                   "verdict": verdict, "reason": reason, "correct": verdict == case["label"],
                                   "correct_binary": verdict is not None and (verdict == "valid") == (case["label"] == "valid"),
                                   "wall_seconds": round(wall, 2), **{k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()},
                                   "tokens_per_second": round(stats["output_tokens"] / stats["eval_seconds"], 2) if stats["eval_seconds"] else None,
                                   "peak_rss_mb": round(llm.peak_mb) if llm.peak_mb else None, "cpu_seconds": llm.cpu_seconds,
                                   "mcp_peak_rss_mb": round(server.peak_mb) if variant == "mcp" and server.peak_mb else None,
                                   "mcp_cpu_seconds": server.cpu_seconds if variant == "mcp" else None, "error": error}
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
