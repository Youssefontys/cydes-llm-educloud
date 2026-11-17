"""Neemt Modbus-verkeer op bij de PLC van GRFICSv3 en voert daarin de scenario's uit. Draait op de GRFICS-VM, als root.

    sudo python3 collect.py --out /tmp/cydes-collect            alleen lezende scenario's
    sudo python3 collect.py --out /tmp/cydes-collect --writes   ook het schrijfscenario

Eerst een basislijn zonder scenario's, daarna elk scenario een paar keer, met tussenpozen. Schrijft capture.pcap en
marks.json: per scenario wanneer het begon en eindigde, in dezelfde klok als de opname.

De scenario's sturen echte Modbus-verzoeken vanuit de containers van GRFICS, met een kleine client in de
standaardbibliotheek van Python (die de containers al hebben):
  kali-read        de Kali (DMZ) leest de registers die de HMI ook leest           -> unknown_client
  ews-device-id    het engineering workstation vraagt de identificatie op (fc 43)  -> forbidden_function
  ews-out-of-map   het engineering workstation leest registers buiten de map        -> illegal_address
  hmi-write-back   de HMI leest holding register 10 en schrijft dezelfde waarde     -> unauthorized_write
                   terug; alleen met --writes. Dezelfde waarde, dus het proces verandert niet, maar het is een
                   schrijfactie naar de PLC.
Alleen de standaardbibliotheek."""
import argparse
import json
import pathlib
import signal
import subprocess
import time

GRFICS = "/opt/grfics"
PLC = "192.168.95.2"
# De client die in een container draait: verzoeken in volgorde, elk met een function code en de rest van de PDU in hex.
# "readback" leest eerst één holding register en schrijft die waarde terug met fc 6.
CLIENT = r"""
import socket, struct, sys
host, unit, steps = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
s = socket.create_connection((host, 502), timeout=5)
tid = 0
def ask(pdu):
    global tid
    tid += 1
    s.sendall(struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit) + pdu)
    head = s.recv(7)
    return s.recv(struct.unpack(">H", head[4:6])[0] - 1) if len(head) == 7 else b""
for step in steps:
    if step.startswith("readback:"):
        addr = int(step.split(":")[1])
        reply = ask(struct.pack(">BHH", 3, addr, 1))
        if len(reply) >= 4 and reply[0] == 3:
            ask(struct.pack(">BHH", 6, addr, struct.unpack(">H", reply[2:4])[0]))
    else:
        ask(bytes.fromhex(step))
s.close()
"""
SCENARIOS = {
    # fc 3, register 10, 4 registers: precies wat de HMI leest, maar van een andere client.
    "kali-read": ("kali", "unknown_client", ["03000a0004"]),
    # fc 43 met MEI-type 14: de identificatie van het apparaat lezen. Leest alleen, maar staat niet in het beleid.
    "ews-device-id": ("ews", "forbidden_function", ["2b0e0100"]),
    # fc 3, register 500, 10 registers: ver buiten wat de HMI gebruikt.
    "ews-out-of-map": ("ews", "illegal_address", ["0301f4000a"]),
    "hmi-write-back": ("hmi", "unauthorized_write", ["readback:10"]),
}


def container(service):
    out = subprocess.run(["docker", "compose", "ps", "-q", service], cwd=GRFICS, capture_output=True, text=True, check=True)
    if not out.stdout.strip():
        raise SystemExit(f"De container {service} draait niet; start GRFICS eerst (docker compose up -d in {GRFICS}).")
    return out.stdout.strip()


def run_scenario(service, steps):
    subprocess.run(["docker", "exec", container(service), "python3", "-c", CLIENT, PLC, "1", *steps], capture_output=True, timeout=30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--baseline", type=float, default=100, help="seconden basislijn (standaard 100)")
    parser.add_argument("--repeats", type=int, default=3, help="hoe vaak elk scenario (standaard 3)")
    parser.add_argument("--gap", type=float, default=12, help="seconden tussen twee scenario's (standaard 12)")
    parser.add_argument("--writes", action="store_true", help="ook het schrijfscenario hmi-write-back")
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pid = subprocess.run(["docker", "inspect", "--format", "{{.State.Pid}}", container("plc")], capture_output=True, text=True, check=True).stdout.strip()
    pcap = out / "capture.pcap"
    # In de netwerknaamruimte van de PLC, op de interface in het ICS-netwerk: daar komt al het Modbus-verkeer langs.
    dump = subprocess.Popen(["nsenter", "-t", pid, "-n", "tcpdump", "-i", "eth1", "-nn", "-U", "-w", str(pcap), "tcp port 502"],
                            stderr=subprocess.DEVNULL)
    time.sleep(2)
    began = time.time()
    print(f"Basislijn: {args.baseline:.0f} seconden zonder scenario's...", flush=True)
    time.sleep(args.baseline)
    baseline_until = time.time()
    marks = []
    chosen = [name for name in SCENARIOS if args.writes or name != "hmi-write-back"]
    for repeat in range(args.repeats):
        for name in chosen:
            service, rule, steps = SCENARIOS[name]
            time.sleep(args.gap / 2)
            start = time.time()
            run_scenario(service, steps)
            marks.append({"scenario": name, "rule": rule, "repeat": repeat + 1, "start": start, "end": time.time()})
            print(f"  {name} ({repeat + 1}/{args.repeats})", flush=True)
            time.sleep(args.gap / 2)
    time.sleep(2)
    dump.send_signal(signal.SIGINT)
    dump.wait(10)
    commit = subprocess.run(["git", "-c", f"safe.directory={GRFICS}", "rev-parse", "HEAD"], cwd=GRFICS, capture_output=True, text=True).stdout.strip()
    (out / "marks.json").write_text(json.dumps({"began": began, "baseline_until": baseline_until, "grfics_commit": commit,
                                                "writes": args.writes, "marks": marks}, indent=1) + "\n")
    print(f"Klaar: {pcap} ({pcap.stat().st_size // 1024} KB) en marks.json, {len(marks)} scenario's.")


if __name__ == "__main__":
    main()
