#!/bin/bash
# Zet Ollama en de benchmark op de VM. Uitgevoerd door de remote-exec provisioner in main.tf, nadat de bestanden in
# /tmp/cydes staan. Gaat uit van Ubuntu. Verwacht OLLAMA_MODELS: modelnamen gescheiden door komma's.
# Mag vaker draaien: bij andere modellen of een gewijzigde benchmark draait Terraform het opnieuw.
set -eu

OLLAMA_MODELS="${OLLAMA_MODELS:-qwen2.5:3b}"

# Cloud-init doet bij de eerste start zelf nog apt-get; zonder wachten botst dat op de apt-lock. "|| true": cloud-init
# kan een niet-nul status geven voor een onschuldige waarschuwing terwijl het wel klaar is.
cloud-init status --wait || true

apt-get update -y
apt-get install -y python3 python3-venv python3-pip curl

# Het installatiescript van Ollama zelf; het zet ook de dienst ollama.service neer. Zonder GPU draait alles op de CPU.
# Niet vast op een versie: de benchmark legt de versie die er staat vast bij elke meting.
if ! command -v ollama > /dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
systemctl enable --now ollama

# Even wachten tot de dienst antwoordt; direct na het starten weigert hij nog verbindingen.
for _ in $(seq 30); do
  curl -fsS http://127.0.0.1:11434/api/version > /dev/null && break
  sleep 2
done

IFS=',' read -ra MODELS <<< "${OLLAMA_MODELS}"
for model in "${MODELS[@]}"; do
  echo "Model ophalen: ${model} (kan even duren)..."
  ollama pull "${model}"
done

mkdir -p /opt/cydes/results
rm -rf /opt/cydes/bench
mv /tmp/cydes/bench /opt/cydes/bench
mv /tmp/cydes/requirements.txt /opt/cydes/requirements.txt

if [ ! -x /opt/cydes/venv/bin/python ]; then
  python3 -m venv /opt/cydes/venv
fi
/opt/cydes/venv/bin/pip install --quiet --upgrade pip
/opt/cydes/venv/bin/pip install --quiet -r /opt/cydes/requirements.txt
chown -R ubuntu:ubuntu /opt/cydes

echo "Klaar. Ollama $(ollama --version 2>/dev/null | awk '{print $NF}'), modellen: ${OLLAMA_MODELS}."
echo "Benchmark draaien:  cd /opt/cydes && venv/bin/python -m bench.run --models ${OLLAMA_MODELS}"
echo "Of vanaf je eigen pc: python scripts/deployment.py bench"
