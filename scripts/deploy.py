# Vraagt model en instance-grootte, dan terraform apply. Helpers komen uit deployment.py.
import deployment


def run():
    deployment.check_tools("deploy")

    if not (deployment.REPO / "terraform" / "terraform.tfvars").exists():
        deployment.stop(
            "terraform/terraform.tfvars ontbreekt nog.\n"
            "   💡 Kopieer terraform/terraform.tfvars.example en vul je Educloud-sleutels, zone en template in."
        )

    model = deployment.pick(
        "🧠 Welk model moet Ollama draaien? (CPU-only, dus klein houden)",
        deployment.MODELS,
    )
    if model == "anders":
        model = input("   Modelnaam (zoals Ollama die kent, bijv. 'mistral:7b'): ").strip() or model

    offering = deployment.pick(
        "💻 Welke instance-grootte voor de openllm-VM?",
        deployment.OFFERINGS,
        default="2",
    )

    print(f"\n📋 Model: {model}\n📋 Instance: {offering}\n")
    if deployment.INTERACTIVE and not deployment.yes("Doorgaan en terraform apply draaien?"):
        deployment.stop("Afgebroken op jouw vraag; er is niets aangemaakt.", icon="✋")

    ok = deployment.terraform(
        "apply", "-auto-approve",
        f"-var=ollama_model={model}",
        f"-var=openllm_service_offering={offering}",
    )
    if not ok:
        deployment.stop("Terraform is misgegaan; zie de foutmelding hierboven.")
    print("\n✅ Klaar. Zie de Terraform-outputs voor het public_ip, en LEESMIJ.md voor hoe je erbij komt.")
