# De benchmark op de VM draaien en de uitkomsten ophalen. Start via deployment.py bench.
# Het werk gebeurt op de VM (bench/run.py); dit script start het over SSH, haalt het JSONL-bestand op en toont de tabel.
# Valt de verbinding weg, dan is er niets verloren: dezelfde opdracht opnieuw gaat verder waar het ophield.

import datetime
import shutil
import subprocess
import sys
from pathlib import Path

import deployment
from deployment import MODEL_NAME, REPO, ask, check_tools, output, stop

sys.path.insert(0, str(REPO))
from bench import report  # noqa: E402  (alleen de standaardbibliotheek)

VARIANTS = "manual,native,mcp,multi"


def run():
    check_tools("bench")
    ip = output("public_ip")
    if not ip:
        stop("Er is nog niets uitgerold (Terraform kent geen public_ip).\n   💡 Eerst: python scripts/deployment.py deploy")
    key = str(Path(output("ssh_private_key_path") or "~/.ssh/id_ed25519").expanduser())
    models = output("ollama_models")
    variants, cases, repeats = VARIANTS, "30", "1"
    name = datetime.date.today().isoformat()
    if deployment.INTERACTIVE:
        models = ask("🧠 Welke modellen (zoals ze op de VM staan)", models, rf"{MODEL_NAME}(,{MODEL_NAME})*")
        variants = ask("🔀 Welke varianten", variants, r"(manual|native|mcp|multi)(,(manual|native|mcp|multi))*")
        cases = ask("📦 Hoeveel cases", cases, r"[1-9]\d{0,2}")
        repeats = ask("🔁 Hoe vaak elke case", repeats, r"[1-9]")
        # Dezelfde naam als een eerdere meting gaat daar verder; een nieuwe naam begint een nieuwe meting.
        name = ask("🏷️  Naam van deze meting", name, r"[A-Za-z0-9._-]{1,60}")
    remote = f"results/{name}.jsonl"
    target = f"ubuntu@{ip}"
    # accept-new: de sleutel van een nieuwe VM wordt onthouden, een gewijzigde sleutel van een bekende VM geweigerd.
    options = ["-i", key, "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30"]
    runs = len(models.split(",")) * len(variants.split(",")) * int(cases) * int(repeats)
    print(f"\n🏁 {runs} runs op {ip}. Zonder GPU duurt een run tientallen seconden tot minuten; laat dit venster open.\n"
          "   Ctrl+C of een weggevallen verbinding stopt het; dezelfde opdracht met dezelfde naam gaat daarna verder.\n")
    # Elk argument is hierboven beperkt tot veilige tekens, dus de opdracht kan niets anders worden op de VM.
    command = (f"cd /opt/cydes && venv/bin/python -m bench.run --models {models} --variants {variants} "
               f"--cases {cases} --repeats {repeats} --out {remote}")
    finished = subprocess.run([shutil.which("ssh"), *options, target, command], cwd=REPO).returncode == 0

    local = REPO / "results" / f"{name}.jsonl"
    local.parent.mkdir(exist_ok=True)
    if subprocess.run([shutil.which("scp"), *options, f"{target}:/opt/cydes/{remote}", str(local)], cwd=REPO).returncode != 0:
        stop("De uitkomsten ophalen werkte niet; ze staan nog op de VM in /opt/cydes/results/.")
    print(f"\n📥 Uitkomsten in {local.relative_to(REPO)}\n")
    print(report.summarise(local))
    if not finished:
        stop("De benchmark is niet afgemaakt; hierboven staat wat er al is.\n"
             "   💡 Opnieuw: python scripts/deployment.py bench, met dezelfde naam.", icon="⏸️")
    print("\n🎉 Klaar. De tabel hierboven hoort in de README onder Metingen, met de datum.\n")
