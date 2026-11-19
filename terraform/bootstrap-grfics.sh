#!/bin/bash
# Uitgevoerd door de remote-exec provisioner in main.tf. Gaat uit van Ubuntu. Verwacht
# GRFICS_SIEM ("yes"/"no") als omgevingsvariabele. Draait en levert een werkende GRFICSv3
# op Educloud; bevestigd door de opname van 2026-11-17 (zie docs/methodologie.md).
#
# Test eerst, apart en vroeg, of CloudStack's netwerk getagd VLAN-verkeer + macvlan toelaat
# op de guest-NIC. GRFICSv3's eigen docker-compose.yml heeft dit nodig voor de twee
# ICS-netwerken (b-ics-net, c-dmz-net). Lukt dit niet, dan heeft de rest van dit script geen
# zin, en wil je dat in een duidelijke foutmelding zien, niet begraven in een mislukte
# docker-compose-up na tien minuten wachten.
set -eu

GRFICS_SIEM="${GRFICS_SIEM:-no}"

sudo cloud-init status --wait || true

sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg git iproute2 vlan

IFACE=$(ip -o route get 1.1.1.1 | awk '{for (i=1;i<=NF;i++) if ($i=="dev") print $(i+1)}')
echo "Primaire interface: ${IFACE}"

sudo modprobe 8021q || true

echo "Test: VLAN-subinterface ${IFACE}.95 aanmaken..."
if ! sudo ip link add link "${IFACE}" name "${IFACE}.95" type vlan id 95 2>/tmp/vlan_test.err; then
  echo "FOUT: kan geen VLAN-subinterface aanmaken op ${IFACE}."
  cat /tmp/vlan_test.err
  echo "Dit is het risico dat al in LEESMIJ.md stond: GRFICSv3's macvlan-netwerken hebben"
  echo "getagd VLAN-verkeer op de guest-NIC nodig. CloudStack's virtuele switch laat dat"
  echo "hier kennelijk niet door. De rest van dit script draait daarom niet."
  exit 42
fi

echo "Test: macvlan bovenop ${IFACE}.95 aanmaken..."
if ! sudo ip link add link "${IFACE}.95" name test-macvlan0 type macvlan mode bridge 2>/tmp/macvlan_test.err; then
  echo "FOUT: VLAN-subinterface lukt, macvlan erbovenop niet."
  cat /tmp/macvlan_test.err
  sudo ip link delete "${IFACE}.95"
  exit 43
fi

sudo ip link delete test-macvlan0
sudo ip link delete "${IFACE}.95"
echo "VLAN + macvlan-test geslaagd op ${IFACE}. GRFICSv3's netwerkopzet zou moeten kunnen werken."

# Docker, zelfde officiele-repo-methode als bij de andere VM's.
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo mkdir -p /opt/grfics
sudo git clone --depth 1 https://github.com/Fortiphyd/GRFICSv3.git /opt/grfics
cd /opt/grfics

# De compose gebruikt letterlijk "eth0" als macvlan-parent (met het commentaar erbij: "replace
# eth0 with your actual host NIC"); hier is dat niet per se eth0.
sudo sed -i "s/eth0\./${IFACE}./g" docker-compose.yml

# router verwacht een echt gegenereerd secret op de plek van de letterlijke placeholder-tekst.
sudo sed -i "s/FWUI_SECRET_KEY=some-long-secret-you-generate/FWUI_SECRET_KEY=$(openssl rand -hex 32)/" docker-compose.yml

echo "Images pullen (geen lokale build, gebruikt de gepubliceerde fortiphyd/grfics-* images)..."
if [ "${GRFICS_SIEM}" = "yes" ]; then
  sudo docker compose --profile siem pull
  sudo docker compose --profile siem up -d
else
  sudo docker compose pull
  sudo docker compose up -d
fi

echo "Klaar. Services draaien op hun interne poorten; niets staat hier publiek open."
echo "Via een SSH-tunnel naar deze VM (poort 2222 op het publieke IP) bereik je:"
echo "  localhost:80    simulation (3D-proces)"
echo "  localhost:8080   plc"
echo "  localhost:6080   ews (noVNC)"
echo "  localhost:6081   hmi / ScadaLTS"
echo "  localhost:6088   kali (noVNC)"
echo "  localhost:8888   caldera"
if [ "${GRFICS_SIEM}" = "yes" ]; then
  echo "  localhost:5601   wazuh dashboard"
fi
echo "Status bekijken: cd /opt/grfics && sudo docker compose ps"
