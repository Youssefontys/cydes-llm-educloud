"""Vat een bestand met uitkomsten samen in één tabel per model en variant.

    python -m bench.report results/results.jsonl

Alleen de standaardbibliotheek."""
import json
import pathlib
import statistics
import sys


def summarise(path):
    meta, groups = None, {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("meta"):
            meta = row
        else:
            groups.setdefault((row["model"], row["variant"]), []).append(row)
    lines = []
    if meta:
        lines += [f"Gemeten op {meta['started']}: {meta['cpus']} CPU's, {meta['memory_gb']} GB, Ollama {meta['ollama']}, "
                  f"{meta['cases']} cases (dataset {meta['dataset']}), context {meta['num_ctx']} tokens.", ""]
        for name, info in meta["models"].items():
            lines.append(f"- {name}: {info['size_mb']} MB, {info['quantization']}, digest {str(info['digest'])[:12]}")
        lines.append("")
    lines += ["| Model | Variant | Runs | Juist oordeel | Geldig of niet juist | Geen oordeel | Ongeldige aanroepen per run | Aanroepen model per run "
              "| Mediaan seconden | Tokens per seconde | Piekgeheugen MB |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    pct = lambda rows, key: f"{100 * sum(bool(r[key]) for r in rows) / len(rows):.0f}%"
    for (model, variant), rows in groups.items():
        speeds = [r["tokens_per_second"] for r in rows if r["tokens_per_second"]]
        peaks = [r["peak_rss_mb"] for r in rows if r["peak_rss_mb"]]
        lines.append(f"| {model} | {variant} | {len(rows)} | {pct(rows, 'correct')} | {pct(rows, 'correct_binary')} "
                     f"| {sum(r['verdict'] is None for r in rows)} | {statistics.mean(r['invalid_calls'] for r in rows):.1f} "
                     f"| {statistics.mean(r['llm_calls'] for r in rows):.1f} | {statistics.median(r['wall_seconds'] for r in rows):.0f} "
                     f"| {statistics.mean(speeds):.1f} | {max(peaks) if peaks else '-'} |" if speeds else
                     f"| {model} | {variant} | {len(rows)} | {pct(rows, 'correct')} | {pct(rows, 'correct_binary')} "
                     f"| {sum(r['verdict'] is None for r in rows)} | {statistics.mean(r['invalid_calls'] for r in rows):.1f} "
                     f"| {statistics.mean(r['llm_calls'] for r in rows):.1f} | {statistics.median(r['wall_seconds'] for r in rows):.0f} | - | {max(peaks) if peaks else '-'} |")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(summarise(sys.argv[1]))
