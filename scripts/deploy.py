# Uitrollen op Educloud: de keuzes vragen, bewaren, en dan terraform apply. Start via deployment.py.

import re

import deployment
from deployment import CIDR, MODEL_NAME, MODELS, OFFERINGS, ask, check_tools, load_choices, save_choices, stop, terraform, terraform_init, yes


# Meer dan één model kan: de benchmark vergelijkt ze. Nummers uit de lijst, of zelf een naam zoals Ollama die kent.
def pick_models(current):
    print("\n🧠 Welke modellen moet Ollama ophalen? Zonder GPU, dus klein houden.")
    for key, (name, memory) in MODELS.items():
        print(f"   {key}  {name:14} {memory}")
    print("   Meerdere: nummers of namen met komma's ertussen, bijvoorbeeld 1,2 of 1,mistral:7b")
    answer = ask("Welke", current, rf"(\d|{MODEL_NAME})(,(\d|{MODEL_NAME}))*")
    names = [MODELS[part][0] if part in MODELS else part for part in answer.split(",")]
    if unknown := [n for n in names if re.fullmatch(r"\d", n)]:
        stop(f"Nummer {', '.join(unknown)} staat niet in de lijst.", icon="🤔")
    return ",".join(dict.fromkeys(names))


def pick_offering(current):
    print("\n💻 Welke grootte voor de VM met Ollama? Het geheugen bepaalt welk model past.")
    for key, name in OFFERINGS.items():
        print(f"   {key}  {name}")
    default = next((k for k, v in OFFERINGS.items() if v == current), "2")
    return OFFERINGS[ask("Welke", default, rf"[{''.join(OFFERINGS)}]")]


def run():
    check_tools("deploy")
    choices = load_choices()
    if deployment.INTERACTIVE:
        choices["ollama_models"] = pick_models(choices["ollama_models"])
    if deployment.INTERACTIVE:
        choices["openllm_service_offering"] = pick_offering(choices["openllm_service_offering"])
    if deployment.INTERACTIVE:
        print("\n🏭 GRFICSv3 is een nagebootste fabriek met een PLC. De benchmark heeft hem niet nodig (de cases zijn nagemaakt\n"
              "   verkeer); het is een tweede, grote VM voor demo's en echt verkeer.")
        choices["enable_grfics"] = yes("GRFICSv3 erbij?", "y" if choices["enable_grfics"] else "n")
    if deployment.INTERACTIVE:
        print("\n🔐 Wie mag bij SSH? De VM krijgt een publiek adres. Geef je eigen adres of het bereik van de VPN,\n"
              "   bijvoorbeeld 203.0.113.7/32; 0.0.0.0/0 is iedereen.")
        choices["ssh_cidrs"] = ask("Welk bereik (meerdere met komma's)", ",".join(choices["ssh_cidrs"]), rf"{CIDR}(,{CIDR})*").split(",")
    # Nog steeds interactief: er was echt een antwoord op elke vraag, dus de keuzes mogen bewaard worden.
    if deployment.INTERACTIVE:
        save_choices(choices)
    elif not deployment.CHOICES.exists():
        save_choices(choices)

    print(f"\n📋 Modellen: {choices['ollama_models']}\n📋 VM: {choices['openllm_service_offering']}"
          f"\n📋 GRFICSv3: {'ja' if choices['enable_grfics'] else 'nee'}\n📋 SSH vanaf: {', '.join(choices['ssh_cidrs'])}")
    if "0.0.0.0/0" in choices["ssh_cidrs"]:
        print("   ⚠️  SSH staat open voor iedereen; alleen je sleutel houdt een ander buiten.")
    terraform_init()
    print("\n🏗️  Terraform laat eerst zien wat het gaat doen, en begint pas als je yes typt.\n")
    # Zonder terminal kan niemand yes typen; dan alleen met de keuzes die al bewaard waren.
    if not terraform("apply", *([] if deployment.INTERACTIVE else ["-auto-approve", "-input=false"])):
        stop("terraform apply werkte niet, of je typte geen yes; de melding staat hierboven.\n"
             "   💡 Opnieuw draaien gaat verder waar het ophield.")
    print(f"\n🎉 Klaar! De VM met Ollama staat op {deployment.output('public_ip')}")
    print("💡 De benchmark draaien: python scripts/deployment.py bench")
    print("💡 Alles weer weg, zodat het geen capaciteit kost: python scripts/deployment.py undo\n")
