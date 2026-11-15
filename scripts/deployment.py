# Vraagt welk model en welke instance-grootte, en zet daarmee de openllm-VM op Educloud neer
# via Terraform (terraform/), of breekt hem weer af. Naar het patroon van
# secure-application/scripts/deployment.py: dit bestand is het gedeelde stuk (paden, vragen,
# stoppen), de targets staan in hun eigen bestand (deploy.py, undo.py).
# Gebruik: python scripts/deployment.py          vraagt alles
#          python scripts/deployment.py deploy   model + grootte vragen, dan terraform apply
#          python scripts/deployment.py undo      terraform destroy
# Status: geschreven, nog niet gedraaid.

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.modules.setdefault("deployment", sys.modules[__name__])

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
NEEDS = {
    "deploy": [("terraform", "om de VM en het netwerk op Educloud te zetten")],
    "undo": [("terraform", "om de VM en het netwerk weer af te breken")],
}
INTERACTIVE = sys.stdin.isatty()

# Kleine, CPU-bruikbare Ollama-modellen; "anders" laat een eigen modelnaam intypen.
MODELS = {
    "1": "qwen2.5:3b",
    "2": "llama3.2:3b",
    "3": "phi3:mini",
    "4": "anders",
}
OFFERINGS = {
    "1": "Medium Instance",
    "2": "Medium Instance+",
    "3": "Large Instance",
}


def stop(message, icon="❌"):
    sys.exit(f"\n{icon} {message}\n\n🛑 Stopping.\n")


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
        print("🤔 Dat antwoord kende ik niet; probeer het nog eens.")


def yes(question):
    return ask(f"{question} (y/n)", "n", r"[yYnN]").lower() == "y"


def check_tools(target):
    print("🔍 Checken of alles er is...")
    missing = [f"   ❓ {tool}: {why}" for tool, why in NEEDS[target] if not shutil.which(tool)]
    if missing:
        stop("Nog niet gevonden:\n" + "\n".join(missing) + "\n   💡 Installeer wat ontbreekt en start dit script opnieuw.")
    for tool, why in NEEDS[target]:
        print(f"   ✅ {tool}: {why}")


def pick(question, options, default="1"):
    print(f"\n{question}")
    for key, value in options.items():
        print(f"   {key}  {value}")
    choice = ask("Welke", default, rf"[{''.join(options)}]")
    return options[choice]


def terraform(*args):
    process = subprocess.Popen([shutil.which("terraform"), "-chdir=terraform", *args], cwd=REPO)
    while True:
        try:
            return process.wait() == 0
        except KeyboardInterrupt:
            print("\n⏳ Wachten tot Terraform netjes gestopt is...")


if __name__ == "__main__":
    import deploy
    import undo

    TARGETS = {"deploy": deploy, "undo": undo}
    print("\n🤖 openllm/MCP/multi-agent-VM op Educloud")
    print("👋 Ik loop met je door de vragen heen. Enter kiest wat tussen [ ] staat.\n")
    if len(sys.argv) > 1:
        choice = sys.argv[1]
    elif INTERACTIVE:
        try:
            choice = ask("🧭 Wat wil je doen? deploy of undo", "deploy", r"deploy|undo")
        except KeyboardInterrupt:
            stop("Gestopt met Ctrl+C; er is niets gedaan.", icon="✋")
    else:
        choice = "deploy"
    if choice not in TARGETS:
        stop(f"Onbekende keuze: {choice!r}. Kies deploy of undo.", icon="🤔")
    try:
        TARGETS[choice].run()
    except KeyboardInterrupt:
        stop("Gestopt met Ctrl+C. Wat al gedaan was blijft staan; opnieuw draaien gaat daar verder.", icon="✋")
