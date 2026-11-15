#!/bin/bash
# Uitgevoerd door de remote-exec provisioner in main.tf, na de file-provisioners. Gaat uit
# van Ubuntu. Verwacht OLLAMA_MODEL als omgevingsvariabele (door Terraform meegegeven).
# Status: geschreven, nog niet tegen een echte VM gedraaid; de mcp/crewai-versies in requirements
# zijn niet vastgepind, dus check bij problemen eerst of een package-update de boosdoener is.
set -eu

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"

# Cloud-init doet zelf nog apt-get op de eerste boot; SSH staat vaak al open voor dat klaar is.
# Zonder dit wachten botst onze apt-get met die van cloud-init op de apt-lock (zo ook gezien).
# "|| true": cloud-init kan een niet-nul status geven voor een onschuldige waarschuwing terwijl
# hij wel degelijk klaar is ("status: done" stond er al); alleen wachten tot hij stopt, verder
# niets.
sudo cloud-init status --wait || true

sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip curl

# Officiele installer; zet ook een systemd-service (ollama.service) neer, CPU-only als er
# geen GPU gevonden wordt, dat is hier altijd het geval op Educloud.
curl -fsSL https://ollama.com/install.sh | sudo sh
sudo systemctl enable --now ollama

echo "Model ophalen: ${OLLAMA_MODEL} (kan even duren)..."
ollama pull "${OLLAMA_MODEL}"

sudo mkdir -p /opt/openllm
sudo mv /tmp/mcp_server.py /opt/openllm/mcp_server.py
sudo mv /tmp/multi_agent_demo.py /opt/openllm/multi_agent_demo.py

sudo python3 -m venv /opt/openllm/venv
sudo /opt/openllm/venv/bin/pip install --upgrade pip
sudo /opt/openllm/venv/bin/pip install "mcp[cli]" crewai requests

# OLLAMA_MODEL blijvend beschikbaar voor wie hier later inlogt, niet alleen voor deze sessie.
echo "export OLLAMA_MODEL=${OLLAMA_MODEL}" | sudo tee /etc/profile.d/openllm.sh > /dev/null
sudo chown -R ubuntu:ubuntu /opt/openllm

echo "Klaar. Model ${OLLAMA_MODEL} staat in Ollama (CPU-only)."
echo "MCP-server (stdio) testen:   cd /opt/openllm && venv/bin/python3 mcp_server.py"
echo "Multi-agent-demo draaien:    cd /opt/openllm && venv/bin/python3 multi_agent_demo.py \"een onderwerp\""
