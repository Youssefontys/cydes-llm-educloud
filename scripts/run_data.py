# Een nieuwe dataset uit GRFICS: opnemen bij de PLC, de scenario's uitvoeren, ophalen en omzetten. Start via
# deployment.py data. De opname draait op de GRFICS-VM (bench/collect.py), het omzetten hier (bench/build.py).
# De ruwe opname komt in data/raw/<naam>/ (niet in git), de dataset in data/grfics-<naam>.json (wel in git).

import datetime
import shutil
import subprocess
import sys

import deployment
from deployment import REPO, ask, check_tools, output, ssh_options, stop, yes


def run():
    check_tools("data")
    ip = output("public_ip")
    if not ip:
        stop("Er is nog niets uitgerold (Terraform kent geen public_ip).\n   💡 Eerst: python scripts/deployment.py deploy")
    if output("grfics") != "true":
        stop("GRFICSv3 staat niet aan in deze omgeving.\n   💡 python scripts/deployment.py deploy, en kies bij GRFICSv3 ja.")
    name, writes, repeats, baseline = datetime.date.today().isoformat(), False, "3", "100"
    if deployment.INTERACTIVE:
        print("\n🏭 Eerst een basislijn van normaal verkeer, dan elk scenario een paar keer:\n"
              "   kali-read (unknown_client), ews-device-id (forbidden_function), ews-out-of-map (illegal_address).\n"
              "   Deze drie lezen alleen. Het vierde, hmi-write-back (unauthorized_write), schrijft dezelfde waarde terug\n"
              "   die er al stond: het proces verandert niet, maar het is wel een schrijfactie naar de PLC.")
        writes = yes("Het schrijfscenario erbij?")
        repeats = ask("🔁 Hoe vaak elk scenario", repeats, r"[1-9]\d?")
        baseline = ask("⏱️  Seconden basislijn (elke 8 seconden is één geldige case)", baseline, r"[1-9]\d{1,3}")
        name = ask("🏷️  Naam van deze opname", name, r"[A-Za-z0-9._-]{1,60}")
    folder, dataset = REPO / "data" / "raw" / name, REPO / "data" / f"grfics-{name}.json"
    if dataset.exists() and not (deployment.INTERACTIVE and yes(f"{dataset.relative_to(REPO)} bestaat al. Overschrijven?")):
        stop("Er is niets opgenomen; kies een andere naam.", icon="✋")
    target, options = f"ubuntu@{ip}", ["-p", "2222", *ssh_options()]
    copy = ["-P", "2222", *ssh_options()]
    remote = f"/tmp/cydes-collect/{name}"
    minutes = (int(baseline) + int(repeats) * (4 if writes else 3) * 12) / 60 + 1
    print(f"\n🎬 Opnemen op de GRFICS-VM, ongeveer {minutes:.0f} minuten...\n")
    steps = [[shutil.which("ssh"), *options, target, "rm -rf /tmp/cydes-collect && mkdir -p /tmp/cydes-collect"],
             [shutil.which("scp"), *copy, str(REPO / "bench" / "collect.py"), f"{target}:/tmp/cydes-collect/collect.py"],
             [shutil.which("ssh"), *options, target,
              # Elk argument is hierboven beperkt tot veilige tekens. sed: een CRLF van Windows eruit.
              f"sed -i 's/\\r$//' /tmp/cydes-collect/collect.py && sudo python3 /tmp/cydes-collect/collect.py --out {remote} "
              f"--repeats {repeats} --baseline {baseline}{' --writes' if writes else ''}"]]
    for step in steps:
        if subprocess.run(step, cwd=REPO).returncode != 0:
            stop("Opnemen werkte niet; de melding staat hierboven.\n   💡 Draait GRFICS? ssh -p 2222 ubuntu@<ip>, dan: cd /opt/grfics && sudo docker compose ps")
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.run([shutil.which("scp"), *copy, f"{target}:{remote}/capture.pcap", f"{target}:{remote}/marks.json", str(folder)], cwd=REPO).returncode != 0:
        stop(f"De opname ophalen werkte niet; hij staat nog op de GRFICS-VM in {remote}.")
    print("\n🧮 Omzetten naar cases...\n")
    if subprocess.run([sys.executable, "-m", "bench.build", str(folder), "--out", str(dataset)], cwd=REPO).returncode != 0:
        stop("Omzetten werkte niet; de opname staat in " + str(folder.relative_to(REPO)))
    print(f"\n🎉 Klaar: {dataset.relative_to(REPO)}. De ruwe opname staat in {folder.relative_to(REPO)} (niet in git).")
    print("💡 De benchmark erop: python scripts/deployment.py bench\n")
