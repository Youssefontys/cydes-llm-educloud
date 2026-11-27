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

**Status:** de benchmark draait op Educloud, op een dataset uit GRFICS van 2026-11-17. De metingen die tellen staan
onder [Metingen](#metingen), met datum. De hoofdmeting (2026-11-27, 60 cases): Qwen3.5 4B haalt via `direct` 44/60 en via
`manual` 42/60, beide significant beter dan altijd `valid` (30/60) en onderling gelijk. Gemma 4 E2B via `multi`, op 20
cases nog de beste, komt op 32/60 en is niet beter dan altijd `valid`. `native` tegen `mcp` op 60 cases loopt. Zie
[docs/experimenten.md](docs/experimenten.md).

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

Voor de volledige methodologie (precies hoe de opname, het afleiden van het beleid en het labelen van cases werken,
stap voor stap met verwijzingen naar de code) zie [docs/methodologie.md](docs/methodologie.md). Hier de samenvatting.

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

Een zesde variant, `decide`, is voor **decision models** (Ollama-capability "decision", zoals pplx-decider-flash): geen
tekst en geen tools, maar hetzelfde bewijs als `direct` als toestand, één keuzevraag met de labels (omschreven met de
regelteksten uit het beleid) en een kans per label terug, via Ollama's `/v1/systemone`. De kansen en de confidence
staan per run in het resultaatbestand (`probabilities`, `decision_confidence`). `decide` hoort niet bij de standaard
`--variants`; geef hem expliciet mee, met een decision model. Zie het plan in [docs/experimenten.md](docs/experimenten.md).

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

Voor modellen die kunnen "denken" (zoals qwen3.5 en lfm2.5): `--think off` of `--think on` zet dat expliciet; zonder
de optie wordt niets meegestuurd. De keuze staat in de metadata van het resultaatbestand. Vergelijk alleen metingen
die op dezelfde VM-grootte zijn gedaan: bij temperatuur 0 kan alleen al een ander aantal CPU's de oordelen veranderen
(zie [docs/experimenten.md](docs/experimenten.md)).

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
| `docs/methodologie.md` | Hoe elke dataset is gemaakt: echte opname versus synthetisch, stap voor stap |
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
- **Een zuivere vergelijking van `native` en `mcp`**: de MCP-server beschrijft de tools anders dan de andere
  varianten (zie [docs/experimenten.md](docs/experimenten.md)).

## Metingen

Waarom we iets probeerden, en wat dat liet zien: [docs/experimenten.md](docs/experimenten.md).

| Datum | VM | Modellen | Dataset | Bestand | Uitkomst |
|---|---|---|---|---|---|
| 2026-11-17 | Medium Instance+ (2 CPU, 12 GB) | qwen2.5:3b | grfics-2026-11-17.json (20 cases) | [results/2026-11-17-qwen2.5-3b.jsonl](results/2026-11-17-qwen2.5-3b.jsonl) | zie tabellen hieronder |
| 2026-11-18 | Medium Instance+ (2 CPU, 12 GB) | qwen2.5:3b | grfics-2026-11-17.json (20 cases) | [results/2026-11-18-qwen2.5-3b.jsonl](results/2026-11-18-qwen2.5-3b.jsonl) | herhaling, met `reason` en `evidence_complete`; zie tabellen hieronder |
| 2026-11-19 | Medium Instance+ (2 CPU, 12 GB) | qwen2.5:3b | grfics-2026-11-17.json (20 cases) | [results/2026-11-19-qwen2.5-3b.jsonl](results/2026-11-19-qwen2.5-3b.jsonl) | bewijs afgedwongen + `PAGE` 10→30; zie tabellen hieronder en [docs/experimenten.md](docs/experimenten.md) |
| 2026-11-24 | Large Instance (4 CPU, 16 GB) | qwen3.5:4b-q4_K_M | grfics-2026-11-17.json (20 cases) | [results/2026-11-24-qwen3.5-4b-4cpu.jsonl](results/2026-11-24-qwen3.5-4b-4cpu.jsonl) | architectuurvergelijking; zie hieronder |
| 2026-11-24 | Large Instance (4 CPU, 16 GB) | qwen2.5:3b | grfics-2026-11-17.json (20 cases) | [results/2026-11-24-qwen2.5-3b-4cpu.jsonl](results/2026-11-24-qwen2.5-3b-4cpu.jsonl) | architectuurvergelijking; zie hieronder |
| 2026-11-25 | Large Instance (4 CPU, 16 GB) | gemma4:e2b-it-qat | grfics-2026-11-17.json (20 cases) | [results/2026-11-24-gemma4-e2b-4cpu.jsonl](results/2026-11-24-gemma4-e2b-4cpu.jsonl) | `native`-winnaar in `native`, `mcp`, `multi`; zie hieronder |
| 2026-11-27 | Large Instance (4 CPU, 16 GB) | qwen3.5:4b-q4_K_M, gemma4:e2b-it-qat | grfics-2026-11-17.json (20 cases) | [herhaling Qwen](results/2026-11-27-herhaling-qwen3.5-4b-t0.7.jsonl), [herhaling Gemma](results/2026-11-27-herhaling-gemma4-e2b-t0.7.jsonl) | 3 herhalingen bij temperatuur 0,7: alleen `direct` stabiel; zie [docs/experimenten.md](docs/experimenten.md) |
| 2026-11-27 | Large Instance (4 CPU, 16 GB) | qwen3.5:4b-q4_K_M, gemma4:e2b-it-qat | grfics-2026-11-27.json (60 cases) | [Qwen](results/2026-11-27-qwen3.5-4b-60cases.jsonl), [Gemma](results/2026-11-27-gemma4-e2b-60cases.jsonl) | **hoofdmeting**; zie [docs/experimenten.md](docs/experimenten.md) |

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

### 2026-11-19: bewijs afgedwongen, PAGE 10→30, num_predict-cap

Gemeten op 2026-11-19T05:19:50+00:00: dezelfde VM, hetzelfde model en dezelfde dataset als hierboven; context 4096
tokens. qwen2.5:3b: 1930 MB, Q4_K_M, digest 357c53fb659c.

| Model | Variant | Runs | Juist | Precision | Recall | F1 | Consistent | Geen oordeel | Ongeldige aanroepen per run | Volledig bewijs |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b | direct | 20 | 15% | 45% | 100% | 62% | - | 0 | 0.0 | - |
| qwen2.5:3b | manual | 20 | 55% | 100% | 11% | 20% | - | 0 | 0.0 | 100% |
| qwen2.5:3b | native | 20 | 45% | 60% | 33% | 43% | - | 3 | 3.6 | 100% |
| qwen2.5:3b | mcp | 20 | 35% | 100% | 11% | 20% | - | 6 | 3.6 | 100% |
| qwen2.5:3b | multi | 20 | 45% | 56% | 56% | 56% | - | 3 | 3.7 | 100% |

| Model | Variant | Aanroepen model per run | Mediaan seconden | Tokens per seconde | CPU-seconden per run | Piekgeheugen MB | MCP-server MB | MCP-server CPU-seconden |
|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b | direct | 1.0 | 129 | 3.5 | 254 | 5123 | - | - |
| qwen2.5:3b | manual | 4.7 | 145 | 3.8 | 352 | 8407 | - | - |
| qwen2.5:3b | native | 7.8 | 645 | 3.4 | 1332 | 10384 | - | - |
| qwen2.5:3b | mcp | 8.0 | 775 | 3.3 | 1911 | 10387 | 66 | 0.0 |
| qwen2.5:3b | multi | 11.2 | 995 | 3.5 | 2072 | 10386 | - | - |

Bewijs afdwingen werkte: "Volledig bewijs" ging van 0-5% naar 100%. De kwaliteit ging **niet** overal mee omhoog.
`manual`, `native` en `mcp` gingen er qua F1 op achteruit (60%→20%, 67%→43%, 31%→20%): met volledig bewijs koos het
model vaker `valid` bij een echte overtreding dan voorheen met onvolledig bewijs. Alleen `multi` werd beter
(43%→56%) — de reviewer-stap lijkt baat te hebben bij afgedwongen bewijs waar de losse agents dat niet hebben. De
kosten gingen flink omhoog: 2-3x zoveel modelaanroepen en CPU-tijd per run. Omdat drie dingen tegelijk veranderden
(bewijs afdwingen, `PAGE` 10→30, `num_predict`-cap), is de oorzaak van de verslechtering nog niet geïsoleerd — zie
[docs/experimenten.md](docs/experimenten.md) voor de vervolghypothese.

### 2026-11-24 en -25: drie modellen op 4 CPU's

Gemeten vanaf 2026-11-24T02:57:29+00:00: 4 CPU's, 15,6 GB, Ollama 0.40.16, dataset grfics (20 cases, 24c87dc58556,
grfics-2026-11-17.json), context 4096 tokens, `--think off`, MAX_STEPS 12, bewijs afgedwongen, `PAGE` 30.
qwen3.5:4b-q4_K_M: 3324 MB, Q4_K_M, digest d8b0f5e9760c. qwen2.5:3b: 1930 MB, Q4_K_M, digest 357c53fb659c.
gemma4:e2b-it-qat: 4336 MB, Q4_0, digest 07ea59a47401.

| Model | Variant | Runs | Juist | Precision | Recall | F1 | Consistent | Geen oordeel | Ongeldige aanroepen per run | Volledig bewijs |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5:4b-q4_K_M | direct | 20 | 65% | 75% | 67% | 71% | - | 0 | 0.0 | - |
| qwen3.5:4b-q4_K_M | manual | 20 | 70% | 100% | 33% | 50% | - | 0 | 0.0 | 100% |
| qwen3.5:4b-q4_K_M | native | 20 | 15% | 100% | 11% | 20% | - | 15 | 3.8 | 100% |
| qwen3.5:4b-q4_K_M | mcp | 20 | 50% | 67% | 22% | 33% | - | 9 | 3.0 | 100% |
| qwen3.5:4b-q4_K_M | multi | 20 | 15% | 100% | 11% | 20% | - | 16 | 8.1 | 100% |
| qwen2.5:3b | direct | 20 | 10% | 45% | 100% | 62% | - | 0 | 0.0 | - |
| qwen2.5:3b | manual | 20 | 60% | 100% | 44% | 62% | - | 0 | 0.1 | 100% |
| qwen2.5:3b | native | 20 | 35% | 50% | 22% | 31% | - | 5 | 3.8 | 100% |
| qwen2.5:3b | mcp | 20 | 55% | 100% | 44% | 62% | - | 4 | 3.6 | 100% |
| qwen2.5:3b | multi | 20 | 45% | 60% | 67% | 63% | - | 1 | 5.5 | 100% |
| gemma4:e2b-it-qat | native | 20 | 60% | 75% | 33% | 46% | - | 3 | 0.0 | 100% |
| gemma4:e2b-it-qat | mcp | 20 | 5% | - | 0% | 0% | - | 19 | 8.3 | 100% |
| gemma4:e2b-it-qat | multi | 20 | 75% | 100% | 56% | 71% | - | 1 | 0.0 | 100% |

| Model | Variant | Aanroepen model per run | Mediaan seconden | Tokens per seconde | CPU-seconden per run | Piekgeheugen MB | MCP-server MB | MCP-server CPU-seconden |
|---|---|---|---|---|---|---|---|---|
| qwen3.5:4b-q4_K_M | direct | 1.0 | 82 | 4.7 | 334 | 8492 | - | - |
| qwen3.5:4b-q4_K_M | manual | 4.0 | 111 | 4.9 | 439 | 12131 | - | - |
| qwen3.5:4b-q4_K_M | native | 11.7 | 715 | 4.6 | 3057 | 11888 | - | - |
| qwen3.5:4b-q4_K_M | mcp | 11.2 | 733 | 4.7 | 3002 | 11781 | 65 | 0.0 |
| qwen3.5:4b-q4_K_M | multi | 22.6 | 1652 | 4.7 | 6314 | 12037 | - | - |
| qwen2.5:3b | direct | 1.0 | 68 | 6.2 | 268 | 4344 | - | - |
| qwen2.5:3b | manual | 4.5 | 74 | 6.6 | 415 | 7729 | - | - |
| qwen2.5:3b | native | 7.2 | 335 | 5.9 | 1697 | 10397 | - | - |
| qwen2.5:3b | mcp | 7.3 | 321 | 6.1 | 1450 | 10400 | 65 | 0.0 |
| qwen2.5:3b | multi | 13.1 | 594 | 6.1 | 2883 | 10398 | - | - |
| gemma4:e2b-it-qat | native | 4.0 | 51 | 9.1 | 212 | 5815 | - | - |
| gemma4:e2b-it-qat | mcp | 11.8 | 134 | 8.8 | 524 | 9787 | 66 | 0.0 |
| gemma4:e2b-it-qat | multi | 8.0 | 160 | 8.8 | 645 | 12573 | - | - |

Altijd `valid` zeggen haalt al 55% (11 van de 20 cases zijn valid). Gemma 4 E2B via `multi` is de beste meting tot
nu toe: 75% juist, F1 71%, geen vals alarm. Gemma via `native` is het goedkoopst per juist oordeel. Met één model in
alle varianten wint `manual` (Qwen3.5 4B 70%, qwen2.5:3b 60%). De tool-lussen van de Qwen-modellen lopen vaak vast op
het stappenbudget: 15 en 16 keer geen oordeel bij Qwen3.5 4B in `native` en `multi`. De 19 keer geen oordeel van
Gemma via `mcp` komt door een fout in de benchmark: de MCP-server beschrijft de tools kaler dan de andere varianten,
waardoor Gemma `get_register_map` een case-id geeft in plaats van een IP-adres. Uitwerking in
[docs/experimenten.md](docs/experimenten.md).

## GRFICSv3

Met "GRFICSv3 erbij" zet `deploy` een tweede, grote VM neer met de nagebootste fabriek van Fortiphyd
(`terraform/bootstrap-grfics.sh`). Het script test eerst of het netwerk van Educloud VLAN's en macvlan toelaat, want daar
hangt GRFICS van af.

De VM is bereikbaar op poort 2222 van hetzelfde publieke adres. Er draaien een bewust kwetsbare omgeving en een Kali op:
beperk bij `deploy` wie bij SSH mag.
