# CyDES: een LLM met beperkte middelen een validatietaak laten doen

Groepsproject, Fontys ICT semester 6 (Cyber Security Advanced). Deze repo is de meetopstelling.

**Hoofdvraag:** kan een LLM met beperkte middelen een validatietaak in security uitvoeren, en hoe?

Beperkte middelen is hier Fontys Educloud: een VM zonder GPU, met een paar CPU's en een paar GB geheugen. De modellen
draaien lokaal in Ollama.

| Deelvraag | Variant in de benchmark |
|---|---|
| 1. Hoe goed doet één agent de taak, met function calling? | `manual`: de tools staan als tekst in de prompt, het model antwoordt met JSON |
| 2. Maakt MCP het beter? | `mcp`: dezelfde tools, nu via een MCP-server. `native` is de tussenstap (zie hieronder) |
| 3. Maken meerdere agents het beter? | `multi`: een analist en een reviewer |

**Status: de benchmark is geschreven en getest met een nagemaakt model; met een echt model is nog niets gemeten.**
Wat er gemeten is, hoort onder [Metingen](#metingen) te staan, met datum. Zolang die tabel leeg is, is er geen uitkomst.

## De taak: Modbus-verkeer toetsen aan een beleid

Een case is een kort stuk Modbus/TCP-verkeer naar één PLC: 12 tot 25 transacties, elk met een tijd, het adres van de
afzender, de function code, het register en de geschreven waarden. Het model krijgt een beveiligingsbeleid met zes
regels en moet zeggen of het verkeer geldig is, of welke regel het breekt.

| Oordeel | Wat het betekent |
|---|---|
| `valid` | Geen regel gebroken |
| `unknown_client` | Een ander adres dan de HMI of het engineering workstation praat met de PLC |
| `forbidden_function` | Een function code buiten 3, 4, 6 en 16 |
| `illegal_address` | Een verzoek buiten de registers 0 tot 99 |
| `unauthorized_write` | Schrijven naar een register dat die afzender niet mag schrijven |
| `value_out_of_range` | Een setpoint buiten zijn grenzen |
| `write_flood` | Meer dan 5 schrijfverzoeken van één afzender binnen 10 seconden |

Waarom deze taak:

- **Het juiste antwoord staat vast.** Het beleid bestaat ook als code (`check()` in `bench/modbus.py`). Dat is de
  scheidsrechter, niet een mens. Elke case breekt hoogstens één regel, dus er is één goed antwoord.
- **Elke run krijgt dezelfde cases.** Het verkeer is nagemaakt met een vaste seed. Standaard 30 cases, waarvan 12 geldig
  en 3 per regel.
- **Het is een echte validatietaak**, in de taal van GRFICSv3: de adressen en rollen zijn die van de HMI, het engineering
  workstation en de PLC daar. GRFICS zelf is niet nodig om te meten.

Wat het niet is: echt verkeer. Het model krijgt de transacties als gegevens, niet als pakketten, en de overtredingen zijn
duidelijker dan in de praktijk. De uitkomst zegt dus iets over het toepassen van regels op gestructureerde gegevens met
tools, niet over het herkennen van een onbekende aanval.

## Dezelfde tools, vier manieren

Het model ziet de transacties niet in de prompt. Het moet ze opvragen met tools, tien per keer:

| Tool | Wat het geeft |
|---|---|
| `get_policy` | Het beleid |
| `get_transactions(start)` | Tien transacties vanaf `start`, en het totaal |
| `get_register_info(address)` | Wat een register is, wie het mag schrijven en de grenzen |
| `submit_verdict(verdict, reason)` | Het oordeel; hiermee stopt de run |

Alleen de manier van aanroepen verschilt per variant, zodat een verschil in uitkomst daaraan ligt:

| Variant | Hoe het model de tools aanroept |
|---|---|
| `manual` | De tools staan als tekst in de prompt; het model antwoordt met `{"tool": ..., "arguments": ...}` en de benchmark ontleedt dat zelf |
| `native` | De tool-aanroepen van Ollama zelf (het veld `tools`) |
| `mcp` | Als `native`, maar de tools komen van een MCP-server (`bench/mcp_server.py`) en worden daar uitgevoerd |
| `multi` | Twee agents na elkaar: de analist bekijkt het verkeer en geeft bevindingen door, de reviewer controleert ze en geeft het oordeel |

`native` staat erbij omdat `mcp` twee dingen tegelijk verandert ten opzichte van `manual`: de tool-aanroepen van Ollama,
en MCP. Het verschil tussen `manual` en `native` is het eerste, het verschil tussen `native` en `mcp` is MCP zelf.

`multi` gebruikt geen framework zoals CrewAI: het zijn twee keer dezelfde lus met een andere opdracht. Zo meet je wat een
tweede agent kost en oplevert, niet wat een framework erbij doet.

Niet elk model kent de tool-aanroepen van Ollama. Een model dat ze niet kent, kan alleen `manual`; kijk op
ollama.com (zoek op "tools") voor je een model in de vergelijking zet.

## Wat er gemeten wordt

Per run, in één regel van een JSONL-bestand:

- het oordeel en of het klopt, ook alleen op "geldig of niet";
- het aantal aanroepen van het model en van de tools, en hoeveel daarvan ongeldig waren (geen JSON, een tool die niet
  bestaat, verkeerde argumenten);
- de doorlooptijd, de tokens in en uit, en de tokens per seconde;
- het piekgeheugen van Ollama tijdens de run.

De eerste regel van het bestand legt vast waarop gemeten is: het aantal CPU's, het geheugen, de versie van Ollama en van
`mcp`, en per model de digest, de grootte en de kwantisatie. Temperatuur 0 en een vaste seed; een run stopt na 12 stappen.

## Zo draai je het

Je hebt Terraform, Python 3 en een SSH-sleutelpaar in je Educloud-account nodig, en de VPN van Fontys.

1. Kopieer `terraform/terraform.tfvars.example` naar `terraform/terraform.tfvars` en vul je sleutels van Educloud, de
   zone, het template en de naam van je sleutelpaar in. Dat bestand komt niet in git.
2. Zet de omgeving neer. Het script vraagt welke modellen, welke grootte, of GRFICSv3 erbij moet en wie bij SSH mag;
   daarna laat Terraform zien wat het gaat doen en begint het pas als je `yes` typt.
   ```bash
   python scripts/deployment.py deploy
   ```
3. Draai de benchmark. Het script start hem op de VM, haalt de uitkomsten op naar `results/` en toont de tabel.
   ```bash
   python scripts/deployment.py bench
   ```
4. Breek alles weer af als je klaar bent.
   ```bash
   python scripts/deployment.py undo
   ```

Een ander model of een andere grootte: `deploy` opnieuw. Je keuzes staan in `terraform/deployment.auto.tfvars.json`, dus
het script stelt de vorige voor en Terraform verandert alleen wat anders is.

Zonder GPU duurt een run tientallen seconden tot minuten. Daarom schrijft de benchmark elke run meteen weg en slaat hij
over wat al gedaan is: valt de verbinding weg, dan start je `bench` opnieuw met dezelfde naam en gaat hij verder.

Op de VM zelf, of op een eigen machine met Ollama:

```bash
python -m bench.run --models qwen2.5:3b,llama3.2:3b
```

```bash
python -m bench.report results/results.jsonl
```

## Wat erin zit

| Bestand | Wat |
|---|---|
| `bench/modbus.py` | De cases, het beleid, de scheidsrechter en de tools |
| `bench/runners.py` | De vier varianten |
| `bench/mcp_server.py`, `bench/mcp_bridge.py` | De MCP-server met de tools, en de client die de benchmark gebruikt |
| `bench/run.py`, `bench/report.py` | De benchmark draaien en meten, en de uitkomsten samenvatten |
| `tests/test_bench.py` | Tests zonder echt model |
| `scripts/deployment.py` | Neerzetten, de benchmark draaien en afbreken; de opdrachten staan in `deploy.py`, `run_bench.py` en `undo.py` |
| `terraform/` | Het netwerk en de VM's op Educloud; `bootstrap-openllm.sh` zet Ollama en de benchmark op de VM |
| `requirements.txt` | Alleen `mcp`, vast op een versie; de rest is de standaardbibliotheek |

## Getest, en niet getest

```bash
python -m unittest discover -s tests -v
```

De tests gebruiken een nagemaakte Ollama die zich gedraagt als een model dat de taak goed doet. Daarmee is getest:

- de cases: dezelfde seed geeft dezelfde cases, en de scheidsrechter vindt in elke case precies de bedoelde regel;
- alle vier de varianten van begin tot eind, `mcp` door de echte MCP-server heen: met het nagemaakte model komt elke
  variant op 100% uit;
- dat ongeldige aanroepen geteld worden, dat een onderbroken benchmark verdergaat zonder dubbel werk, en dat een model
  dat niet in Ollama staat de benchmark stopt voordat er iets draait.

Niet getest:

- **Geen enkel echt model.** De tests zeggen dat de meetopstelling klopt, niets over hoe goed een model is.
- **Niets op Educloud.** `terraform validate` slaagt; `terraform apply`, het script op de VM en `deployment.py bench` zijn
  met deze versie niet gedraaid.
- **Het piekgeheugen** is alleen op Linux te meten en dus lokaal niet getest.

## Metingen

| Datum | VM | Modellen | Bestand | Uitkomst |
|---|---|---|---|---|
| nog niet gemeten | | | | |

Zet bij een meting die telt het JSONL-bestand in git (`git add -f results/<naam>.jsonl`) en de tabel van
`bench.report` hieronder.

## GRFICSv3

Met "GRFICSv3 erbij" zet `deploy` een tweede, grote VM neer met de nagebootste fabriek van Fortiphyd
(`terraform/bootstrap-grfics.sh`). Dat is voor demo's en om later echt verkeer op te nemen; de benchmark gebruikt hem
niet. Het script test eerst of het netwerk van Educloud VLAN's en macvlan toelaat, want daar hangt GRFICS van af.

De VM is bereikbaar op poort 2222 van hetzelfde publieke adres. Er draaien een bewust kwetsbare omgeving en een Kali op:
beperk bij `deploy` wie bij SSH mag.
