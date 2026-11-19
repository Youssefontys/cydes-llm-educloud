# CyDES: een LLM met beperkte middelen een validatietaak laten doen

Groepsproject, Fontys ICT semester 6 (Cyber Security Advanced). Deze repo is de meetopstelling.

**Hoofdvraag:** kan een LLM met beperkte middelen een validatietaak in security uitvoeren, en hoe?

Beperkte middelen is hier Fontys Educloud: een VM zonder GPU, met een paar CPU's en een paar GB geheugen. De modellen
draaien lokaal in Ollama. Het bewijs komt uit GRFICSv3, een nagebootste fabriek met een PLC.

| Deelvraag | Variant in de benchmark |
|---|---|
| 0. Referentie: wat doet het model zonder tools? | `direct`: al het bewijs in de prompt, één antwoord |
| 1. Hoe goed doet één agent de taak, met function calling? | `manual` (variant A): de tools als tekst, het model antwoordt met JSON |
| 2. Maakt MCP het beter? | `mcp` (variant B): dezelfde tools via een MCP-server. `native` is de tussenstap |
| 3. Maken meerdere agents het beter? | `multi` (variant C): een analist en een reviewer |

**Status:** de benchmark draait op Educloud, op een dataset uit GRFICS van 2026-11-17. Er is alleen een proefrun gedaan;
een meting die telt staat onder [Metingen](#metingen), met datum. Zolang die tabel leeg is, is er geen uitkomst.

## De taak: Modbus-verkeer bij de PLC toetsen aan een beleid

Een case is een venster van ongeveer acht seconden Modbus/TCP-verkeer bij de PLC van GRFICSv3: 16 tot 25 transacties,
elk met een tijd, de afzender, de server, de function code, het register, de geschreven waarden en de exception uit het
antwoord. Het model moet zeggen of het verkeer aan het beleid voldoet, of welke regel het breekt.

| Oordeel | Wat het betekent |
|---|---|
| `valid` | Geen regel gebroken |
| `unknown_client` | Een client die niet bij die server hoort, stuurt hem een verzoek |
| `forbidden_function` | Een function code die die server in het beleid niet heeft |
| `illegal_address` | Een verzoek buiten de registermap van die server |
| `unauthorized_write` | Een schrijfactie van een client die alleen mag lezen |

### Waar het bewijs vandaan komt

Hoe GRFICSv3 Modbus gebruikt, gemeten bij de PLC op 2026-11-17:

- de PLC (192.168.95.2) is zelf client: hij leest en stuurt zes veldapparaten (192.168.95.10 tot .15) met function code
  4 en 16, tien keer per seconde;
- de HMI (192.168.90.107) staat in de DMZ en leest de PLC elke twee seconden, met function code 1, 3 en 4;
- het engineering workstation (192.168.95.5) praat in normaal bedrijf niet met de PLC.

`deployment.py data` neemt dat verkeer op in de netwerkruimte van de PLC (`bench/collect.py`), eerst een basislijn van
honderd seconden en daarna scenario's die echt in GRFICS worden uitgevoerd:

| Scenario | Vanaf | Wat | Breekt |
|---|---|---|---|
| `kali-read` | de Kali (DMZ) | leest dezelfde registers als de HMI | `unknown_client` |
| `ews-device-id` | het engineering workstation | vraagt de identificatie op, function code 43 | `forbidden_function` |
| `ews-out-of-map` | het engineering workstation | leest register 500 tot 509 | `illegal_address` |
| `hmi-write-back` | de HMI | schrijft de waarde van holding register 10 terug | `unauthorized_write` |

De eerste drie lezen alleen. Het vierde schrijft dezelfde waarde terug die er al stond, zodat het proces niet verandert,
maar het blijft een schrijfactie naar de PLC; het draait alleen als je het bij `data` kiest.

`bench/build.py` maakt er cases van:

- **Het beleid komt uit de basislijn** (`derive_policy` in `bench/grfics.py`): per server de clients, de function codes
  en de registers die daar voorkwamen. Het engineering workstation krijgt erbij dat het de PLC mag lezen en schrijven,
  omdat dat zijn rol is.
- **Het juiste antwoord geeft code**, niet een mens: `check()` loopt het beleid na. Een case die niet precies de bedoelde
  regel breekt, valt weg.
- **Een case is een venster** met de verzoeken aan de PLC en één ronde van de PLC langs de veldapparaten. Het hele
  verkeer (zestig verzoeken per seconde) past niet in een klein model; dit houdt het bewijs dat ertoe doet.

De dataset van 2026-11-17 (`data/grfics-2026-11-17.json`) heeft 20 cases: 11 geldig, en 3 per regel voor
`unknown_client`, `forbidden_function` en `illegal_address`. Het schrijfscenario zit er niet in. De ruwe opname
(`data/raw/`) staat niet in git; de dataset noemt de hash ervan.

Twee dingen die de opname liet zien en die los van de benchmark tellen:

- **De Kali in de DMZ krijgt antwoord van de PLC.** De firewall van de router laat al het verkeer door
  (`-A FORWARD -j ACCEPT`), dus de segmentatie tussen DMZ en ICS-netwerk houdt niets tegen.
- **De PLC weigert function code 43 zelf** (exception 1), maar beantwoordt een leesverzoek buiten de registers die de
  HMI gebruikt wel.

### Wat dit wel en niet meet

Het meet of een model een beleid kan toepassen op echt Modbus-verkeer dat het met tools moet ophalen. Het meet niet of
een model een onbekende aanval herkent: elk scenario breekt één regel uit een bekend beleid. En het beleid is afgeleid
uit honderd seconden normaal verkeer; wat daar niet in voorkwam, is verboden.

Zonder GRFICS kan de benchmark ook op nagemaakt verkeer draaien (`bench/modbus.py`, zonder `--dataset`). Dat is voor de
tests en om iets te proberen; die cases hebben ook `value_out_of_range` en `write_flood`.

## Dezelfde tools, vijf manieren

Behalve bij `direct` ziet het model de transacties niet in de prompt. Het moet ze opvragen, tien per keer:

| Tool | Wat het geeft |
|---|---|
| `get_policy` | De regels, per server de clients met hun schrijfrecht, en de function codes |
| `get_transactions(start)` | Tien transacties vanaf `start`, en het totaal |
| `get_register_map(server)` | De registermap van een server; wat een register betekent, staat er bewust niet in |
| `submit_verdict(verdict, reason)` | Het oordeel; hiermee stopt de run |

| Variant | Hoe het model bij het bewijs komt |
|---|---|
| `direct` | Variant 0: het beleid, de registermaps en alle transacties staan in de prompt; één antwoord als JSON |
| `manual` | De tools staan als tekst in de prompt; het model antwoordt met `{"tool": ..., "arguments": ...}` en de benchmark ontleedt dat zelf |
| `native` | De tool-aanroepen van Ollama zelf (het veld `tools`) |
| `mcp` | Als `native`, maar de tools komen van een MCP-server (`bench/mcp_server.py`) en worden daar uitgevoerd |
| `multi` | Twee agents na elkaar: de analist bekijkt het verkeer en geeft bevindingen door, de reviewer controleert ze en geeft het oordeel |

`native` staat erbij omdat `mcp` twee dingen tegelijk verandert ten opzichte van `manual`: de tool-aanroepen van Ollama,
en MCP. Het verschil tussen `manual` en `native` is het eerste, het verschil tussen `native` en `mcp` is MCP zelf.

`multi` gebruikt geen framework: het zijn twee keer dezelfde lus met een andere opdracht. Het onderzoek naar MCP noemt
vier rollen (hoofd, security, analyse, verificatie); twee is het kleinste dat al laat zien wat een tweede agent kost.

Niet elk model kent de tool-aanroepen van Ollama. Een model dat ze niet kent, kan alleen `direct` en `manual`.

## Wat er gemeten wordt

Per run, in één regel van een JSONL-bestand:

- het oordeel en of het klopt;
- het aantal aanroepen van het model en van de tools, en hoeveel daarvan ongeldig waren;
- de doorlooptijd, de tokens in en uit, en de tokens per seconde;
- van Ollama het piekgeheugen en de CPU-tijd, en bij `mcp` ook die van de MCP-server apart.

`bench.report` maakt er twee tabellen van. Kwaliteit: juist oordeel, precision, recall en F1 (een overtreding melden
tegenover geen melden), en bij herhalingen de consistentie. Kosten: aanroepen, tijd, tokens per seconde, CPU-tijd en
geheugen.

De eerste regel van het bestand legt vast waarop gemeten is: CPU's, geheugen, de versie van Ollama en van `mcp`, per
model de digest, de grootte en de kwantisatie, en de dataset met zijn vingerafdruk. Temperatuur 0 en een vaste seed;
een run stopt na 12 stappen.

## Zo draai je het

Je hebt Terraform, Python 3 en een SSH-sleutelpaar in je Educloud-account nodig, en de VPN van Fontys.

1. Kopieer `terraform/terraform.tfvars.example` naar `terraform/terraform.tfvars` en vul je sleutels van Educloud, de
   zone, het template en de naam van je sleutelpaar in. Dat bestand komt niet in git.
2. Zet de omgeving neer. Het script vraagt welke modellen, welke grootte, of GRFICSv3 erbij moet en wie bij SSH mag;
   daarna laat Terraform zien wat het gaat doen en begint het pas als je `yes` typt.
   ```bash
   python scripts/deployment.py deploy
   ```
3. Alleen voor een nieuwe dataset: neem verkeer op in GRFICS en zet het om. Dat duurt een paar minuten. Met de dataset
   die al in de repo staat, kun je deze stap overslaan.
   ```bash
   python scripts/deployment.py data
   ```
4. Draai de benchmark. Het script zet de gekozen dataset op de VM, start de benchmark, haalt de uitkomsten op naar
   `results/` en toont de tabellen.
   ```bash
   python scripts/deployment.py bench
   ```
5. Breek alles weer af als je klaar bent.
   ```bash
   python scripts/deployment.py undo
   ```

Een ander model of een andere grootte: `deploy` opnieuw. Je keuzes staan in `terraform/deployment.auto.tfvars.json`, dus
het script stelt de vorige voor en Terraform verandert alleen wat anders is.

Zonder GPU duurt een run één tot zes minuten. Twintig cases in vijf varianten is per model dus enkele uren. Daarom
schrijft de benchmark elke run meteen weg en slaat hij over wat al gedaan is: valt de verbinding weg, dan start je
`bench` opnieuw met dezelfde naam en gaat hij verder.

Op de VM zelf, of op een eigen machine met Ollama:

```bash
python -m bench.run --models qwen2.5:3b --dataset data/grfics-2026-11-17.json
```

```bash
python -m bench.report results/results.jsonl
```

Voor een korte proef: `--only grfics-001,grfics-012` draait alleen die cases, `--variants direct,native` alleen die
varianten.

## Wat erin zit

| Bestand | Wat |
|---|---|
| `bench/collect.py` | Op de GRFICS-VM: opnemen bij de PLC en de scenario's uitvoeren |
| `bench/pcap.py`, `bench/build.py` | Modbus uit de opname halen, en er een dataset van maken |
| `bench/grfics.py` | Het beleid uit de basislijn, de scheidsrechter en de cases |
| `bench/modbus.py` | Nagemaakt verkeer, voor de tests |
| `bench/datasets.py` | De twee datasets en de tools die het model krijgt |
| `bench/runners.py` | De vijf varianten |
| `bench/mcp_server.py`, `bench/mcp_bridge.py` | De MCP-server met de tools, en de client die de benchmark gebruikt |
| `bench/run.py`, `bench/report.py` | De benchmark draaien en meten, en de uitkomsten samenvatten |
| `data/grfics-*.json` | De datasets; de ruwe opnames in `data/raw/` staan niet in git |
| `tests/test_bench.py` | Tests zonder echt model en zonder GRFICS |
| `scripts/deployment.py` | Neerzetten, opnemen, de benchmark draaien en afbreken; de opdrachten staan in `deploy.py`, `run_data.py`, `run_bench.py` en `undo.py` |
| `terraform/` | Het netwerk en de VM's op Educloud; `bootstrap-openllm.sh` zet Ollama en de benchmark op de VM |
| `requirements.txt` | Alleen `mcp`, vast op een versie; de rest is de standaardbibliotheek |

## Getest, en niet getest

```bash
python -m unittest discover -s tests -v
```

De tests gebruiken een nagemaakte Ollama die zich gedraagt als een model dat de taak goed doet, en bouwen zelf een klein
pcap-bestand met Modbus-verkeer. Daarmee is getest:

- het lezen van Modbus uit een pcap, het beleid uit de basislijn, en dat elke case precies de bedoelde regel breekt;
- alle vijf de varianten van begin tot eind, op de nagemaakte en op de GRFICS-dataset, `mcp` door de echte MCP-server
  heen: met het nagemaakte model komt elke variant op 100% uit;
- dat ongeldige aanroepen geteld worden, de consistentie bij herhalingen, precision, recall en F1, en dat een
  onderbroken benchmark verdergaat zonder dubbel werk.

Op Educloud (2026-11-17):

- `deploy`: de VM met Ollama en de GRFICS-VM staan, en de benchmark staat in `/opt/cydes`;
- de opname: `collect.py` op de GRFICS-VM, met de drie lezende scenario's, en `build.py` op die opname;
- een proefrun met `qwen2.5:3b` (zie [Metingen](#metingen)).

Niet getest:

- **Het schrijfscenario** (`hmi-write-back`) is niet in GRFICS uitgevoerd.
- **`deployment.py data` en `bench` als geheel**: de stappen erin zijn met de hand gedaan, de scripts zelf niet.
- **Andere modellen dan `qwen2.5:3b`.**

## Metingen

| Datum | VM | Modellen | Dataset | Bestand | Uitkomst |
|---|---|---|---|---|---|
| 2026-11-17 | Medium Instance+ (2 CPU, 12 GB) | qwen2.5:3b | grfics-2026-11-17.json (20 cases) | [results/2026-11-17-qwen2.5-3b.jsonl](results/2026-11-17-qwen2.5-3b.jsonl) | zie tabellen hieronder |
| 2026-11-18 | Medium Instance+ (2 CPU, 12 GB) | qwen2.5:3b | grfics-2026-11-17.json (20 cases) | [results/2026-11-18-qwen2.5-3b.jsonl](results/2026-11-18-qwen2.5-3b.jsonl) | herhaling, met `reason` en `evidence_complete`; zie tabellen hieronder |

Een proefrun telt niet als meting: die is om te zien dat de keten werkt. Zet bij een meting die telt het JSONL-bestand
in git (`git add -f results/<naam>.jsonl`) en de tabellen van `bench.report` hieronder.

Gemeten op 2026-11-17T15:53:56+00:00: 2 CPU's, 11,7 GB, Ollama 0.40.16, dataset grfics (20 cases, 24c87dc58556,
grfics-2026-11-17.json), context 4096 tokens. qwen2.5:3b: 1930 MB, Q4_K_M, digest 357c53fb659c.

| Model | Variant | Runs | Juist | Precision | Recall | F1 | Consistent | Geen oordeel | Ongeldige aanroepen per run | Volledig bewijs |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b | direct | 20 | 15% | 45% | 100% | 62% | - | 0 | 0.0 | - |
| qwen2.5:3b | manual | 20 | 35% | 55% | 67% | 60% | - | 0 | 0.0 | - |
| qwen2.5:3b | native | 20 | 45% | 83% | 56% | 67% | - | 4 | 1.1 | - |
| qwen2.5:3b | mcp | 20 | 35% | 50% | 22% | 31% | - | 2 | 0.4 | - |
| qwen2.5:3b | multi | 20 | 45% | 60% | 33% | 43% | - | 2 | 1.6 | - |

| Model | Variant | Aanroepen model per run | Mediaan seconden | Tokens per seconde | CPU-seconden per run | Piekgeheugen MB | MCP-server MB | MCP-server CPU-seconden |
|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b | direct | 1.0 | 128 | 3.5 | 251 | 4345 | - | - |
| qwen2.5:3b | manual | 4.5 | 88 | 4.0 | 201 | 6226 | - | - |
| qwen2.5:3b | native | 4.0 | 292 | 3.8 | 695 | 8273 | - | - |
| qwen2.5:3b | mcp | 4.4 | 316 | 3.7 | 752 | 10365 | 66 | 0.0 |
| qwen2.5:3b | multi | 7.5 | 445 | 3.7 | 992 | 10372 | - | - |

"Volledig bewijs" staat op "-": deze meting liep met de code van voor `evidence_complete` (zie [bench/runners.py](bench/runners.py)
en de commit die het toevoegde). `mcp` heeft de laagste recall (22%): het model mist de meeste overtredingen en zegt te
vaak `valid`. `native` heeft de beste F1 (67%) ondanks maar 45% exacte treffers, dankzij hoge precision. `multi` kost
7,5x zoveel modelaanroepen als `direct` en bijna 1.000 CPU-seconden per run, voor een F1 die lager is dan `native`.

### 2026-11-18: dezelfde meting, met reason en evidence_complete

Gemeten op 2026-11-18T16:54:03+00:00: dezelfde VM, hetzelfde model en dezelfde dataset als hierboven; context 4096
tokens. qwen2.5:3b: 1930 MB, Q4_K_M, digest 357c53fb659c.

| Model | Variant | Runs | Juist | Precision | Recall | F1 | Consistent | Geen oordeel | Ongeldige aanroepen per run | Volledig bewijs |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b | direct | 20 | 15% | 45% | 100% | 62% | - | 0 | 0.0 | - |
| qwen2.5:3b | manual | 20 | 35% | 55% | 67% | 60% | - | 0 | 0.0 | 0% |
| qwen2.5:3b | native | 20 | 45% | 83% | 56% | 67% | - | 4 | 1.1 | 0% |
| qwen2.5:3b | mcp | 20 | 35% | 50% | 22% | 31% | - | 2 | 0.4 | 5% |
| qwen2.5:3b | multi | 20 | 45% | 60% | 33% | 43% | - | 2 | 1.6 | 5% |

| Model | Variant | Aanroepen model per run | Mediaan seconden | Tokens per seconde | CPU-seconden per run | Piekgeheugen MB | MCP-server MB | MCP-server CPU-seconden |
|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b | direct | 1.0 | 133 | 3.5 | 260 | 4347 | - | - |
| qwen2.5:3b | manual | 4.5 | 92 | 4.0 | 208 | 6227 | - | - |
| qwen2.5:3b | native | 4.0 | 294 | 3.8 | 702 | 8272 | - | - |
| qwen2.5:3b | mcp | 4.4 | 314 | 3.7 | 751 | 10375 | 66 | 0.0 |
| qwen2.5:3b | multi | 7.5 | 447 | 3.7 | 1004 | 10376 | - | - |

De kwaliteit komt nagenoeg overeen met de meting van 17-11 (reproduceerbaar), en de nieuwe kolom legt de kernoorzaak
bloot: in 0-5% van de runs had het model alle transacties gezien voordat het oordeelde. Bij de rest (gemiddeld
10-12 van de ~24 transacties gezien) deed het model het ongeveer even goed als gokken op de meerderheidsklasse
(valid), niet beter. Ook sloeg het model in 50-60% van de runs de registertool (`get_register_map`) helemaal over,
wat `illegal_address`-overtredingen structureel onzichtbaar maakt. Twee runs liepen vast op de timeout van 900s in
`ollama()` (`native` en `multi`), niet alleen bij een groter model.

## GRFICSv3

Met "GRFICSv3 erbij" zet `deploy` een tweede, grote VM neer met de nagebootste fabriek van Fortiphyd
(`terraform/bootstrap-grfics.sh`). Het script test eerst of het netwerk van Educloud VLAN's en macvlan toelaat, want daar
hangt GRFICS van af.

De VM is bereikbaar op poort 2222 van hetzelfde publieke adres. Er draaien een bewust kwetsbare omgeving en een Kali op:
beperk bij `deploy` wie bij SSH mag.
