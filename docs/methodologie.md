# Methodologie: waar de data vandaan komt

Dit project gebruikt twee datasets die qua herkomst fundamenteel verschillend zijn. Dit document legt vast hoe elke
dataset is gemaakt, zodat het verschil tussen "echt opgenomen" en "verzonnen" niet verloren gaat. Zie ook
[../README.md](../README.md) voor de taak zelf en de metingen die erop draaien.

| | GRFICS-dataset (`data/grfics-*.json`) | Synthetische dataset (`bench/modbus.py`) |
|---|---|---|
| Aard | Echt opgenomen Modbus/TCP-verkeer | Volledig verzonnen verkeer |
| Bron | GRFICSv3, een nagebootste fabriek (Fortiphyd) | Een RNG met een vaste seed |
| Gebruikt in de drie metingen (17/18/19-11)? | Ja, in alle drie | Nee, nooit |
| Waarvoor dan wel? | De meting die telt | `tests/test_bench.py`, en losse proefruns zonder dat GRFICS moet draaien |

## De GRFICS-dataset: echt verkeer, geen aangepaste waarden

De vraag "is dit echte data met aangepaste values, of iets anders?" heeft een duidelijk antwoord: **geen van
beide**. Er is niets aangepast — elke waarde in een case is een byte die werkelijk over het netwerk ging, in een
testbed waar een echte PLC echt Modbus-verzoeken beantwoordt. Wat wél bewust is opgezet, is *welk* verkeer er op
welk moment voorkwam, door een experiment te ontwerpen in plaats van verkeer achteraf te labelen.

### Stap 1 — Opname (`bench/collect.py`, draait op de GRFICS-VM)

Een proces in de netwerknaamruimte van de PLC-container vangt met `tcpdump` al het TCP-verkeer op poort 502, op de
interface die in het ICS-netwerk hangt. Dat levert één `capture.pcap` op met al het Modbus-verkeer dat er in die
periode echt bij de PLC langskwam — van de PLC zelf (die als client zes veldapparaten bedient), van de HMI, en van
wat er verder gebeurt.

De opname bestaat uit twee delen, in dezelfde doorlopende meting:

1. **Een basislijn van 100 seconden** zonder enige ingreep: alleen het normale, geautomatiseerde verkeer van de
   fabriek (PLC ↔ veldapparaten, HMI ↔ PLC).
2. **Vier scenario's**, elk een paar keer herhaald met tussenpozen, uitgevoerd als echte Modbus-aanvragen vanuit de
   bestaande containers van GRFICS (Kali, engineering workstation, HMI) naar de echte PLC:

   | Scenario | Container | Modbus-aanvraag (hex PDU) | Breekt |
   |---|---|---|---|
   | `kali-read` | `kali` | `03000a0004` — fc 3, register 10, 4 registers: exact wat de HMI leest | `unknown_client` |
   | `ews-device-id` | `ews` | `2b0e0100` — fc 43, MEI-type 14: identificatie opvragen | `forbidden_function` |
   | `ews-out-of-map` | `ews` | `0301f4000a` — fc 3, register 500, 10 registers: ver buiten de HMI-map | `illegal_address` |
   | `hmi-write-back` | `hmi` | leest holding register 10, schrijft dezelfde waarde terug (fc 6) | `unauthorized_write` |

   Dit zijn geen gesimuleerde of nagebouwde pakketten: het is een kleine Python-client (standaardbibliotheek, al in
   de container aanwezig) die een echte TCP-verbinding naar de PLC opzet en een echt Modbus-verzoek verstuurt. De
   PLC antwoordt daar ook echt op — inclusief de exception die hij soms teruggeeft (zie README, "Wat de opname
   liet zien").

   Elk scenario schrijft weg wanneer het begon en eindigde (`marks.json`), in dezelfde klok als de pcap-opname, en
   welke regel het *bedoeld* breekt. Dat laatste is de enige plek waar een mens iets vastlegt vóór de meting — de
   rest is het resultaat van wat er op de lijn gebeurde.

Het schrijfscenario (`hmi-write-back`) staat wel in de code maar is voor de dataset van 2026-11-17 niet gebruikt
(`--writes` stond uit): die dataset heeft dus geen `unauthorized_write`-cases.

### Stap 2 — Van pakketten naar transacties (`bench/pcap.py`)

Leest de pcap met alleen de standaardbibliotheek (geen `scapy`/`dpkt`) en zet elk Modbus/TCP-request-en-reply-paar
om in een transactie: tijdstip, client, server, function code, eerste register, aantal, geschreven waarden, en de
exception-code uit de reply (of null). Dit is een directe, verliesvrije vertaling van wat er op de lijn stond.

### Stap 3 — Beleid afleiden uit de basislijn (`derive_policy` in `bench/grfics.py`)

Het beleid is **niet** door een mens opgeschreven. Het is mechanisch afgeleid uit de 100 seconden basislijn: voor
elke server die daarin voorkwam, welke clients hem benaderden, met welke function codes, binnen welke
registerranges, en of een client ooit een schrijfcode gebruikte. Alles wat niet in de basislijn voorkwam, is per
definitie niet toegestaan. De enige handmatige toevoeging: het engineering workstation krijgt ook leze/schrijfrecht
op de PLC, omdat dat zijn rol is (hij zat niet in de basislijn, maar zou er in het echt wel bij mogen).

Dit is een bewuste methodologische keuze met een consequentie die het README ook benoemt: de benchmark test of een
model een *gegeven, al afgeleid* beleid kan toepassen, niet of het een onbekende aanval herkent. Een scenario dat
niets doet wat niet in de basislijn voorkwam, zou dus ook niet als overtreding worden gezien door het beleid zelf
— los van wat het model daarover zegt.

### Stap 4 — Cases maken en labelen (`build_cases` in `bench/grfics.py`)

Een case is een venster van ~8 seconden: de verzoeken aan de PLC in dat venster, plus één ronde van de PLC langs de
zes veldapparaten (zodat het model ook die kant van het verkeer ziet). Er zijn twee soorten vensters:

- **Geldige vensters**: opeenvolgende 8-seconden-stukken uit de basislijn zelf (vóór enig scenario).
- **Overtredingsvensters**: gecentreerd op het tijdstip van een scenario uit `marks.json`.

Het label van een venster komt niet van de persoon die het scenario draaide, maar van **`check()`**: dezelfde
scheidsrechterfunctie die ook de kwaliteit van het model beoordeelt, toegepast op het afgeleide beleid en de echte
transacties in dat venster. Een venster wordt alleen aan de dataset toegevoegd als `check()` **precies** de regel
teruggeeft die het scenario bedoelde te breken (of niets, voor een geldig venster) — niet toevallig een andere
regel, en niet meerdere. Vensters die daar niet aan voldoen, worden overgeslagen (`skipped` in `build_cases`) en
komen niet in de dataset. Dat is dus een dubbele controle: het experimentontwerp *bedoelt* een bepaalde overtreding,
en de code *bevestigt* onafhankelijk dat precies die overtreding (en niets anders) in dat venster zit.

De dataset van 2026-11-17 kwam zo uit op 20 cases: 11 geldig, en 3 voor elk van `unknown_client`,
`forbidden_function` en `illegal_address` (3 scenario's × 3 herhalingen, allemaal geslaagd voor de dubbele check).

### Wat dit betekent voor de geldigheid van de meting

- **Geen aangepaste of verzonnen waarden.** Elke byte in een case is overgekomen op een echte Modbus-verbinding.
- **Het label is geen mening, het is een functie-aanroep** op het afgeleide beleid — reproduceerbaar, niet
  onderhevig aan annotatorbias.
- **De dekking is beperkt tot wat er is uitgevoerd.** Vier scenario's, elk een bekende regelovertreding; geen
  onbekende aanvallen, geen combinaties van regels in één venster.
- **Het beleid zelf is afgeleid, niet gegeven door een mens die de echte beveiligingsvereisten kent.** Zie README,
  "Wat dit wel en niet meet", voor de volledige toelichting.

## De synthetische dataset: voor tests, niet voor metingen

`bench/modbus.py` genereert Modbus-verkeer volledig programmatisch: een `random.Random(seed)` bepaalt clients,
function codes, registers en tijdstippen binnen vaste grenzen (`MAX_ADDRESS`, vaste client-rollen HMI/EWS). Er is
geen PLC, geen netwerk, geen pakket dat ooit heeft bestaan buiten deze functie-aanroep. Het label komt uit dezelfde
soort `check()`-functie, maar toegepast op verzonnen in plaats van opgenomen transacties.

Dit dataset bestaat voor één reden: `tests/test_bench.py` moet de hele keten (prompt, tool-afhandeling, MCP-server,
meting) kunnen testen zonder dat de GRFICS-VM draait, en je moet snel iets kunnen proberen
(`python -m bench.run` zonder `--dataset`). **Geen van de drie metingen die in de README staan (17-11, 18-11,
19-11) gebruikt deze dataset** — ze draaien allemaal met `--dataset data/grfics-2026-11-17.json`, dus op de echte
opname.

## Traceerbaarheid: stap → code

| Stap | Bestand | Functie |
|---|---|---|
| Opnemen bij de PLC, scenario's uitvoeren | `bench/collect.py` | `main`, `run_scenario`, `SCENARIOS` |
| Pcap → transacties | `bench/pcap.py` | `transactions` |
| Beleid afleiden uit de basislijn | `bench/grfics.py` | `derive_policy` |
| Cases maken en labelen | `bench/grfics.py` | `build_cases` |
| Scheidsrechter (ook gebruikt om het model te beoordelen) | `bench/grfics.py` | `check` |
| Opname → dataset-bestand | `bench/build.py` | `main` |
| Synthetisch verkeer (alleen tests) | `bench/modbus.py` | `make_cases`, `check` |
