"""Vat een bestand met uitkomsten samen in twee tabellen per model en variant: de kwaliteit en de kosten.

    python -m bench.report results/grfics-2026-11-17.jsonl

Kwaliteit:
  juist        het juiste oordeel (valid of precies de gebroken regel)
  precision    van de cases die het model als overtreding meldt, het deel dat echt een overtreding is
  recall       van de echte overtredingen, het deel dat het model als overtreding meldt
  F1           het harmonisch gemiddelde van die twee
  consistent   alleen bij herhalingen: het deel van de cases waarop elke herhaling hetzelfde oordeel gaf
Een case zonder oordeel telt als "geen overtreding gemeld". Alleen de standaardbibliotheek."""
import json
import pathlib
import statistics
import sys


def _mean(values, digits=1):
    values = [v for v in values if v is not None]
    return f"{statistics.mean(values):.{digits}f}" if values else "-"


def scores(rows):
    tp = sum(r["label"] != "valid" and r["verdict"] not in (None, "valid") for r in rows)
    fp = sum(r["label"] == "valid" and r["verdict"] not in (None, "valid") for r in rows)
    fn = sum(r["label"] != "valid" and r["verdict"] in (None, "valid") for r in rows)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if precision == 0 or recall == 0 else None)
    by_case = {}
    for r in rows:
        by_case.setdefault(r["case"], set()).add(r["verdict"])
    repeated = max(sum(1 for r in rows if r["case"] == c) for c in by_case) > 1
    consistent = sum(len(v) == 1 for v in by_case.values()) / len(by_case) if repeated else None
    return precision, recall, f1, consistent


def summarise(path):
    meta, groups = None, {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:  # een kapotte laatste regel, bv. door een harde kill tijdens het schrijven
            continue
        if row.get("meta"):
            meta = row
        else:
            groups.setdefault((row["model"], row["variant"]), []).append(row)
    pct = lambda value: "-" if value is None else f"{100 * value:.0f}%"
    lines = []
    if meta:
        source = meta.get("source") or {}
        lines += [f"Gemeten op {meta['started']}: {meta['cpus']} CPU's, {meta['memory_gb']} GB, Ollama {meta['ollama']}, "
                  f"dataset {meta.get('dataset', '?')} ({meta['cases']} cases, {meta.get('dataset_fingerprint', meta.get('dataset'))}"
                  f"{', ' + source['file'] if source.get('file') else ''}), context {meta['num_ctx']} tokens.", ""]
        for name, info in meta["models"].items():
            lines.append(f"- {name}: {info['size_mb']} MB, {info['quantization']}, digest {str(info['digest'])[:12]}")
        lines.append("")
    lines += ["| Model | Variant | Runs | Juist | Precision | Recall | F1 | Consistent | Geen oordeel | Ongeldige aanroepen per run | Volledig bewijs |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for (model, variant), rows in groups.items():
        precision, recall, f1, consistent = scores(rows)
        complete = [r["evidence_complete"] for r in rows if r.get("evidence_complete") is not None]
        evidence = pct(sum(complete) / len(complete)) if complete else "-"
        lines.append(f"| {model} | {variant} | {len(rows)} | {pct(sum(r['correct'] for r in rows) / len(rows))} | {pct(precision)} | {pct(recall)} "
                     f"| {pct(f1)} | {pct(consistent)} | {sum(r['verdict'] is None for r in rows)} | {_mean(r['invalid_calls'] for r in rows)} "
                     f"| {evidence} |")
    lines += ["", "| Model | Variant | Aanroepen model per run | Mediaan seconden | Tokens per seconde | CPU-seconden per run "
              "| Piekgeheugen MB | MCP-server MB | MCP-server CPU-seconden |", "|---|---|---|---|---|---|---|---|---|"]
    for (model, variant), rows in groups.items():
        peaks = [r.get("peak_rss_mb") for r in rows if r.get("peak_rss_mb")]
        mcp = [r.get("mcp_peak_rss_mb") for r in rows if r.get("mcp_peak_rss_mb")]
        lines.append(f"| {model} | {variant} | {_mean(r['llm_calls'] for r in rows)} | {statistics.median(r['wall_seconds'] for r in rows):.0f} "
                     f"| {_mean(r.get('tokens_per_second') for r in rows)} | {_mean([r.get('cpu_seconds') for r in rows], 0)} "
                     f"| {max(peaks) if peaks else '-'} | {max(mcp) if mcp else '-'} | {_mean([r.get('mcp_cpu_seconds') for r in rows], 1)} |")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(summarise(sys.argv[1]))
