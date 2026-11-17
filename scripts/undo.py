# Alles weer weg van Educloud. Start via deployment.py undo.
# Terraform laat zien wat het weghaalt en vraagt zelf om yes; zonder terminal gebeurt er dus niets.

import deployment
from deployment import check_tools, stop, terraform, terraform_init


def run():
    check_tools("undo")
    if not deployment.INTERACTIVE:
        stop("Afbreken vraagt een terminal: Terraform wil dat je yes typt.", icon="✋")
    print("\n🧹 Dit haalt het netwerk en de VM's weg, met de modellen en alle uitkomsten die nog op de VM staan.")
    print("   Uitkomsten die je met bench hebt opgehaald, blijven lokaal in results/.\n")
    terraform_init()
    if not terraform("destroy"):
        stop("terraform destroy werkte niet, of je typte geen yes; de melding staat hierboven.")
    print("\n✅ Weg: het netwerk en de VM's bestaan niet meer op Educloud.")
    print("💡 Opnieuw neerzetten: python scripts/deployment.py deploy\n")
