# Zet de omgeving voor de benchmark op Educloud neer, draait de benchmark, en breekt alles weer af.
# Gebruik: python scripts/deployment.py          vraagt wat je wilt doen
#          python scripts/deployment.py deploy   modellen, grootte, GRFICS en SSH kiezen, dan terraform apply
#          python scripts/deployment.py data     een nieuwe dataset uit GRFICS: opnemen, scenario's, omzetten
#          python scripts/deployment.py bench    de benchmark op de VM draaien en de uitkomsten ophalen
#          python scripts/deployment.py undo     terraform destroy
# Naar het patroon van secure-app: dit bestand is het gedeelde stuk (paden, vragen, stoppen, Terraform), elke opdracht
# staat in een eigen bestand (deploy.py, run_data.py, run_bench.py, undo.py).
# Je keuzes staan in terraform/deployment.auto.tfvars.json: een volgende keer stelt het script dezelfde voor, en
# Terraform leest dat bestand vanzelf. Werkt op Windows en Linux: geen shell, alleen lijsten van argumenten.

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# De opdrachten importeren wat ze delen uit dit bestand. Als script heet het __main__; zo is het onder beide namen
# dezelfde module, met dezelfde INTERACTIVE.
sys.modules.setdefault("deployment", sys.modules[__name__])

# Emoji ook als de uitvoer naar een pipe of bestand gaat: Python schrijft daar op Windows anders cp1252.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
TERRAFORM = REPO / "terraform"
CHOICES = TERRAFORM / "deployment.auto.tfvars.json"
NEEDS = {
    "deploy": [("terraform", "om het netwerk en de VM op Educloud te zetten")],
    "bench": [("terraform", "om het adres van de VM op te vragen"), ("ssh", "om de benchmark op de VM te starten"),
              ("scp", "om de uitkomsten op te halen")],
    "data": [("terraform", "om het adres van de VM op te vragen"), ("ssh", "om de opname op de GRFICS-VM te starten"),
             ("scp", "om de opname op te halen")],
    "undo": [("terraform", "om het netwerk en de VM weer af te breken")],
}
# Zonder terminal geen vragen: dan gelden de keuzes van de vorige keer. ask() zet het uit bij EOF.
INTERACTIVE = sys.stdin.isatty()

# Kleine modellen die zonder GPU bruikbaar zijn. De tweede kolom is de grootte van de download, niet het geheugen tijdens
# het draaien; dat meet de benchmark (qwen2.5:3b: 2,5 GB). Of een model tool-aanroepen kent, bepaalt of native, mcp en
# multi ermee werken: het onderzoek naar MCP noemt Qwen3 en Llama 3.2 met het label tools in Ollama, Gemma 3 niet.
# Controleer het op ollama.com/search?c=tools voor je een model in de vergelijking zet.
MODELS = {
    "1": ("qwen2.5:3b", "1,9 GB"),
    "2": ("qwen3:1.7b", "1,4 GB"),
    "3": ("qwen3:4b", "2,5 GB"),
    "4": ("llama3.2:3b", "2,0 GB"),
    "5": ("llama3.2:1b", "1,3 GB"),
}
OFFERINGS = {"1": "Medium Instance", "2": "Medium Instance+", "3": "Large Instance"}
MODEL_NAME = r"[A-Za-z0-9._/-]+(:[A-Za-z0-9._-]+)?"
CIDR = r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}"


def stop(message, icon="❌"):
    sys.exit(f"\n{icon} {message}\n\n🛑 Gestopt.\n")


# Een vraag met een standaard; alleen een antwoord dat helemaal op pattern past.
# Geen invoer (EOF) telt als geen terminal: op Windows lijkt NUL er ook een.
def ask(question, default, pattern):
    global INTERACTIVE
    while True:
        try:
            answer = input(f"{question} [{default}]: ").strip() or default
        except EOFError:
            print()
            INTERACTIVE = False
            return default
        if re.fullmatch(pattern, answer):
            return answer
        print("🤔 Dat antwoord ken ik niet; probeer het nog eens.")


def yes(question, default="n"):
    return ask(f"{question} (y/n)", default, r"[yYnN]").lower() == "y"


# Stopt met een lijst van wat ontbreekt, voordat er iets gebeurt.
def check_tools(target):
    print("🔍 Kijken of alles er is...")
    missing = [f"   ❓ {tool}: {why}" for tool, why in NEEDS[target] if not shutil.which(tool)]
    if missing:
        stop("Nog niet gevonden:\n" + "\n".join(missing) + "\n   💡 Installeer wat ontbreekt en start dit script opnieuw.")
    for tool, why in NEEDS[target]:
        print(f"   ✅ {tool}: {why}")
    if not (TERRAFORM / "terraform.tfvars").exists():
        stop("terraform/terraform.tfvars ontbreekt.\n"
             "   💡 Kopieer terraform/terraform.tfvars.example en vul je sleutels van Educloud, de zone, het template en je\n"
             "      SSH-sleutelpaar in.")


# De keuzes van de vorige keer, of de standaard als er nog geen zijn of het bestand niet te lezen is.
def load_choices():
    defaults = {"ollama_models": "qwen2.5:3b", "openllm_service_offering": "Medium Instance+", "enable_grfics": True,
                "ssh_cidrs": ["0.0.0.0/0"]}
    try:
        saved = json.loads(CHOICES.read_text(encoding="utf-8"))
        return {**defaults, **{k: v for k, v in saved.items() if k in defaults}}
    except (FileNotFoundError, ValueError):
        return defaults


def save_choices(choices):
    CHOICES.write_text(json.dumps(choices, indent=2) + "\n", encoding="utf-8")


# Terraform met zijn eigen uitvoer en vragen; Ctrl+C gaat naar Terraform, dat netjes stopt en de state bewaart.
def terraform(*args):
    process = subprocess.Popen([shutil.which("terraform"), f"-chdir={TERRAFORM}", *args], cwd=REPO)
    while True:
        try:
            return process.wait() == 0
        except KeyboardInterrupt:
            print("\n⏳ Wachten tot Terraform netjes gestopt is; nog een keer Ctrl+C breekt het hard af...")


def terraform_init():
    # Altijd: het is snel als alles er al staat, en na een nieuwe versie van de provider is het nodig.
    if not terraform("init", "-input=false"):
        stop("terraform init werkte niet; de melding staat hierboven.\n"
             "   💡 Zit je op de VPN van Fontys, en kloppen de sleutels in terraform/terraform.tfvars?")


# Opties voor ssh en scp: de sleutel uit Terraform, en accept-new: de sleutel van een nieuwe VM wordt onthouden, een
# gewijzigde sleutel van een bekende VM geweigerd.
def ssh_options():
    key = str(Path(output("ssh_private_key_path") or "~/.ssh/id_ed25519").expanduser())
    return ["-i", key, "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30"]


# Eén output van Terraform als tekst; "" als hij er niet is (nog niets uitgerold).
def output(name):
    result = subprocess.run([shutil.which("terraform"), f"-chdir={TERRAFORM}", "output", "-raw", name],
                            cwd=REPO, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


if __name__ == "__main__":
    import deploy
    import run_bench
    import run_data
    import undo

    TARGETS = {"deploy": deploy, "data": run_data, "bench": run_bench, "undo": undo}
    print("\n🤖 CyDES: een LLM met beperkte middelen een validatietaak laten doen, op Educloud")
    print("👋 Ik loop met je door de vragen. Enter kiest wat tussen [ ] staat.\n")
    if len(sys.argv) > 1:
        choice = sys.argv[1]
    elif INTERACTIVE:
        try:
            choice = ask("🧭 Wat wil je doen? deploy, data, bench of undo", "deploy", r"deploy|data|bench|undo")
        except KeyboardInterrupt:
            stop("Gestopt met Ctrl+C; er is niets gedaan.", icon="✋")
    else:
        choice = "deploy"
    if choice not in TARGETS:
        stop(f"Onbekende keuze: {choice!r}. Kies deploy, data, bench of undo.", icon="🤔")
    try:
        TARGETS[choice].run()
    except KeyboardInterrupt:
        stop("Gestopt met Ctrl+C. Wat al gedaan was blijft staan; opnieuw draaien gaat daar verder.", icon="✋")
