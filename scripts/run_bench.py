# De benchmark op de VM draaien en de uitkomsten ophalen. Start via deployment.py bench.
# Het werk gebeurt op de VM (bench/run.py); dit script zet de gekozen dataset op de VM, start de benchmark over SSH,
# haalt het JSONL-bestand op en toont de tabellen.
# Valt de verbinding weg, dan is er niets verloren: dezelfde opdracht opnieuw gaat verder waar het ophield.

import datetime
import shutil
import subprocess
import sys
from pathlib import Path

import deployment
from deployment import MODEL_NAME, REPO, ask, check_tools, output, ssh_options, stop

sys.path.insert(0, str(REPO))
from bench import report  # noqa: E402  (alleen de standaardbibliotheek)
from bench.runners import VARIANTS  # noqa: E402

VARIANT = "|".join(VARIANTS)


def run():
    check_tools("bench")
    ip = output("public_ip")
    if not ip:
        stop("Er is nog niets uitgerold (Terraform kent geen public_ip).\n   💡 Eerst: python scripts/deployment.py deploy")
    target, options = f"ubuntu@{ip}", ssh_options()
    # De nieuwste GRFICS-dataset, of de nagemaakte cases als er nog geen is.
    found = sorted((REPO / "data").glob("grfics-*.json"))
    dataset = found[-1].name if found else "synthetic"
    models = output("ollama_models")
    variants, cases, repeats = ",".join(VARIANTS), "30", "1"
    name = datetime.date.today().isoformat()
    if deployment.INTERACTIVE:
        if found:
            print("\n📦 De datasets: " + ", ".join(f.name for f in found) + ", of synthetic (nagemaakt verkeer)")
        dataset = ask("📦 Welke dataset", dataset, r"synthetic|grfics-[A-Za-z0-9._-]{1,60}\.json")
        models = ask("🧠 Welke modellen (zoals ze op de VM staan)", models, rf"{MODEL_NAME}(,{MODEL_NAME})*")
        variants = ask("🔀 Welke varianten", variants, rf"({VARIANT})(,({VARIANT}))*")
        if dataset == "synthetic":
            cases = ask("📦 Hoeveel nagemaakte cases", cases, r"[1-9]\d{0,2}")
        repeats = ask("🔁 Hoe vaak elke case (meer dan 1 meet ook de consistentie)", repeats, r"[1-9]")
        # Dezelfde naam als een eerdere meting gaat daar verder; een nieuwe naam begint een nieuwe meting.
        name = ask("🏷️  Naam van deze meting", name, r"[A-Za-z0-9._-]{1,60}")
    if dataset == "synthetic":
        source, count = f"--cases {cases}", int(cases)
    else:
        local_data = REPO / "data" / dataset
        if not local_data.exists():
            stop(f"{local_data.relative_to(REPO)} bestaat niet.\n   💡 Een nieuwe opname: python scripts/deployment.py data")
        # De dataset naar de VM; scp schrijft hem over als hij er al staat.
        subprocess.run([shutil.which("ssh"), *options, target, "mkdir -p /opt/cydes/data"], cwd=REPO, check=False)
        if subprocess.run([shutil.which("scp"), *options, str(local_data), f"{target}:/opt/cydes/data/{dataset}"], cwd=REPO).returncode != 0:
            stop("De dataset naar de VM kopiëren werkte niet; de melding staat hierboven.")
        sys.path.insert(0, str(REPO))
        from bench import datasets
        source, count = f"--dataset data/{dataset}", len(datasets.load(local_data).cases)
    remote = f"results/{name}.jsonl"
    runs = len(models.split(",")) * len(variants.split(",")) * count * int(repeats)
    print(f"\n🏁 {runs} runs op {ip}. Zonder GPU duurt een run tientallen seconden tot minuten; laat dit venster open.\n"
          "   Ctrl+C of een weggevallen verbinding stopt het; dezelfde opdracht met dezelfde naam gaat daarna verder.\n")
    # Elk argument is hierboven beperkt tot veilige tekens, dus de opdracht kan niets anders worden op de VM.
    command = (f"cd /opt/cydes && venv/bin/python -m bench.run --models {models} --variants {variants} "
               f"{source} --repeats {repeats} --out {remote}")
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
    print("\n🎉 Klaar. De tabellen hierboven horen in de README onder Metingen, met de datum.\n")
