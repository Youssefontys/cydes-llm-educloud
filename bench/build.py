"""Maakt van een opname van bench/collect.py een GRFICS-dataset voor de benchmark.

    python -m bench.build data/raw/2026-11-17 --out data/grfics-2026-11-17.json

Leest capture.pcap en marks.json, leidt het beleid af uit de basislijn, bouwt de cases en controleert dat elke case
precies de bedoelde regel breekt (of geen). Een venster dat dat niet doet, valt weg en staat in de uitvoer.
Het pcap-bestand zelf komt niet in de dataset: alleen de hash, zodat te zien is uit welke opname hij komt.
Alleen de standaardbibliotheek."""
import argparse
import collections
import datetime
import hashlib
import json
import pathlib
import sys

from . import grfics, pcap


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", help="de map met capture.pcap en marks.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--window", type=float, default=8.0, help="seconden per case (standaard 8)")
    args = parser.parse_args(argv)
    folder = pathlib.Path(args.folder)
    raw = (folder / "capture.pcap").read_bytes()
    marks = json.loads((folder / "marks.json").read_text(encoding="utf-8"))
    transactions = pcap.transactions(raw)
    if not transactions:
        sys.exit("Geen Modbus-verkeer in de opname.")
    policy, cases, skipped = grfics.build_cases(transactions, marks["marks"], marks["baseline_until"], args.window)
    data = {"kind": "grfics", "created": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "source": {"pcap_sha256": hashlib.sha256(raw).hexdigest(), "transactions": len(transactions),
                       "grfics_commit": marks.get("grfics_commit"), "writes": marks.get("writes", False),
                       "scenarios": sorted({m["scenario"] for m in marks["marks"]}), "window_seconds": args.window},
            "policy": policy, "cases": cases}
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    labels = collections.Counter(c["label"] for c in cases)
    print(f"{len(cases)} cases in {out}: " + ", ".join(f"{k} {v}" for k, v in sorted(labels.items())))
    print(f"Transacties per case: {min(len(c['transactions']) for c in cases)} tot {max(len(c['transactions']) for c in cases)}.")
    for s in skipped:
        print(f"  weggevallen: een venster voor {s['label']} brak {s['found'] or 'geen regel'}")


if __name__ == "__main__":
    main()
