# Breekt alles af dat deployment.py heeft opgezet. Helpers komen uit deployment.py.
import deployment


def run():
    deployment.check_tools("undo")
    if deployment.INTERACTIVE and not deployment.yes("⚠️  Dit verwijdert de VM en het isolated netwerk op Educloud. Doorgaan?"):
        deployment.stop("Afgebroken op jouw vraag; er is niets verwijderd.", icon="✋")
    ok = deployment.terraform("destroy", "-auto-approve")
    if not ok:
        deployment.stop("Terraform destroy is misgegaan; zie de foutmelding hierboven.")
    print("\n✅ Weg. Netwerk en VM bestaan niet meer op Educloud.")
