# Stap 1 van de test: een eigen isolated netwerk op Educloud, los van het bestaande Shared
# netwerk (DHCP-S6-7-Internet-Only) en los van het groepsproject "Advanced Cyber CyDES LLM".
# Eerst alleen het netwerk, de firewall/port-forward, en één kleine testinstance om te
# bevestigen dat SSH er echt doorheen komt, voor er een zwaardere VM op komt.
#
# Resource-schema's (cloudstack_network, cloudstack_firewall, cloudstack_port_forward)
# gecontroleerd tegen apache/cloudstack-terraform-provider op GitHub, 2026-11-15.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    cloudstack = {
      source  = "cloudstack/cloudstack"
      version = "~> 0.5.0"
    }
  }
}

provider "cloudstack" {
  api_url    = var.cloudstack_api_url
  api_key    = var.cloudstack_api_key
  secret_key = var.cloudstack_secret_key
}

resource "cloudstack_network" "isolated" {
  name             = var.network_name
  cidr             = var.network_cidr
  network_offering = "IsolatedNetworkOfferingWithSourceNAT - 400MBit"
  zone             = var.zone
  # Zet meteen een public/source-NAT IP erop; die heb je nodig om er bij SSH te kunnen komen.
  source_nat_ip = true
}

resource "cloudstack_firewall" "isolated" {
  ip_address_id = cloudstack_network.isolated.source_nat_ip_id

  rule {
    cidr_list = ["0.0.0.0/0"]
    protocol  = "tcp"
    # 22: openllm. 2222: grfics-test (zelfde publieke IP, dus een andere poort per VM).
    ports = ["22", "2222"]
  }
}

# Zelfde sleutel als dependency-track-educloud, al geregistreerd op dit account onder die naam.
# CloudStack weigert dezelfde public key twee keer te registreren, dus hergebruik de naam
# in plaats van een nieuwe cloudstack_ssh_keypair-resource voor hetzelfde keybestand te maken.
resource "cloudstack_instance" "openllm" {
  name             = "${var.network_name}-openllm"
  service_offering = var.openllm_service_offering
  template         = var.template
  zone             = var.zone
  network_id       = cloudstack_network.isolated.id
  keypair          = "dependency-track-admin"
}

resource "cloudstack_instance" "grficstest" {
  name             = "${var.network_name}-grfics"
  service_offering = var.grfics_service_offering
  template         = var.template
  zone             = var.zone
  network_id       = cloudstack_network.isolated.id
  keypair          = "dependency-track-admin"
}

resource "cloudstack_port_forward" "ssh" {
  ip_address_id = cloudstack_network.isolated.source_nat_ip_id

  forward {
    protocol           = "tcp"
    private_port       = 22
    public_port        = 22
    virtual_machine_id = cloudstack_instance.openllm.id
  }

  forward {
    protocol           = "tcp"
    private_port       = 22
    public_port        = 2222
    virtual_machine_id = cloudstack_instance.grficstest.id
  }

  depends_on = [cloudstack_firewall.isolated]
}

resource "null_resource" "bootstrap_openllm" {
  depends_on = [cloudstack_port_forward.ssh]

  triggers = {
    instance_id = cloudstack_instance.openllm.id
    model       = var.ollama_model
  }

  connection {
    type        = "ssh"
    host        = cloudstack_network.isolated.source_nat_ip_address
    user        = "ubuntu"
    private_key = file(pathexpand(var.ssh_private_key_path))
    timeout     = "3m"
  }

  provisioner "file" {
    source      = "${path.module}/../scripts/mcp_server.py"
    destination = "/tmp/mcp_server.py"
  }

  provisioner "file" {
    source      = "${path.module}/../scripts/multi_agent_demo.py"
    destination = "/tmp/multi_agent_demo.py"
  }

  provisioner "file" {
    source      = "${path.module}/bootstrap-openllm.sh"
    destination = "/tmp/bootstrap-openllm.sh"
  }

  provisioner "remote-exec" {
    inline = [
      "chmod +x /tmp/bootstrap-openllm.sh",
      # "sudo VAR=x script" probeert "VAR=x" als programma te starten; via bash -c wel goed.
      "sudo bash -c 'OLLAMA_MODEL=${var.ollama_model} /tmp/bootstrap-openllm.sh'",
    ]
  }
}

resource "null_resource" "bootstrap_grfics" {
  depends_on = [cloudstack_port_forward.ssh]

  triggers = {
    instance_id = cloudstack_instance.grficstest.id
  }

  connection {
    type        = "ssh"
    host        = cloudstack_network.isolated.source_nat_ip_address
    port        = 2222
    user        = "ubuntu"
    private_key = file(pathexpand(var.ssh_private_key_path))
    timeout     = "3m"
  }

  provisioner "file" {
    source      = "${path.module}/bootstrap-grfics.sh"
    destination = "/tmp/bootstrap-grfics.sh"
  }

  provisioner "remote-exec" {
    inline = [
      "chmod +x /tmp/bootstrap-grfics.sh",
      "sudo bash -c 'GRFICS_SIEM=${var.grfics_siem} /tmp/bootstrap-grfics.sh'",
    ]
  }
}
