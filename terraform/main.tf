# Een eigen isolated netwerk op Educloud (Apache CloudStack) met één VM voor Ollama en de benchmark, en als je dat
# aanzet een tweede VM met GRFICSv3. Los van het Shared netwerk en van het groepsproject. De VM's hebben geen GPU.
# Start dit via scripts/deployment.py: dat vraagt de keuzes en schrijft ze naar deployment.auto.tfvars.json.
#
# De schema's van cloudstack_network, cloudstack_firewall en cloudstack_port_forward zijn gecontroleerd tegen
# apache/cloudstack-terraform-provider op GitHub (2026-11-15).

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

locals {
  # Verandert er iets aan de benchmark, dan zet Terraform de nieuwe bestanden op de VM.
  bench_files = sort(concat(tolist(fileset("${path.module}/../bench", "*.py")), ["../requirements.txt"]))
  bench_hash  = sha1(join("", [for f in local.bench_files : filesha1("${path.module}/../bench/${f}")]))
}

resource "cloudstack_network" "isolated" {
  name             = var.network_name
  cidr             = var.network_cidr
  network_offering = "IsolatedNetworkOfferingWithSourceNAT - 400MBit"
  zone             = var.zone
  # Een publiek source-NAT-adres; zonder kom je er met SSH niet bij.
  source_nat_ip = true
}

resource "cloudstack_firewall" "isolated" {
  ip_address_id = cloudstack_network.isolated.source_nat_ip_id

  rule {
    cidr_list = var.ssh_cidrs
    protocol  = "tcp"
    # 22: de VM met Ollama. 2222: de VM met GRFICS, op hetzelfde publieke adres; alleen open als die er is.
    ports = var.enable_grfics ? ["22", "2222"] : ["22"]
  }
}

resource "cloudstack_instance" "openllm" {
  name             = "${var.network_name}-openllm"
  service_offering = var.openllm_service_offering
  template         = var.template
  zone             = var.zone
  network_id       = cloudstack_network.isolated.id
  keypair          = var.keypair
}

resource "cloudstack_instance" "grficstest" {
  count            = var.enable_grfics ? 1 : 0
  name             = "${var.network_name}-grfics"
  service_offering = var.grfics_service_offering
  template         = var.template
  zone             = var.zone
  network_id       = cloudstack_network.isolated.id
  keypair          = var.keypair
}

resource "cloudstack_port_forward" "ssh" {
  ip_address_id = cloudstack_network.isolated.source_nat_ip_id

  forward {
    protocol           = "tcp"
    private_port       = 22
    public_port        = 22
    virtual_machine_id = cloudstack_instance.openllm.id
  }

  dynamic "forward" {
    for_each = cloudstack_instance.grficstest
    content {
      protocol           = "tcp"
      private_port       = 22
      public_port        = 2222
      virtual_machine_id = forward.value.id
    }
  }

  depends_on = [cloudstack_firewall.isolated]
}

resource "null_resource" "bootstrap_openllm" {
  depends_on = [cloudstack_port_forward.ssh]

  # Opnieuw bij een nieuwe VM, andere modellen of een gewijzigde benchmark; het script mag vaker draaien.
  triggers = {
    instance_id = cloudstack_instance.openllm.id
    models      = var.ollama_models
    bench       = local.bench_hash
  }

  connection {
    type        = "ssh"
    host        = cloudstack_network.isolated.source_nat_ip_address
    user        = "ubuntu"
    private_key = file(pathexpand(var.ssh_private_key_path))
    timeout     = "3m"
  }

  # Eerst leeg: de file-provisioner zet een map anders ín een map die er al staat.
  provisioner "remote-exec" {
    inline = ["rm -rf /tmp/cydes && mkdir -p /tmp/cydes"]
  }

  provisioner "file" {
    source      = "${path.module}/../bench"
    destination = "/tmp/cydes/bench"
  }

  provisioner "file" {
    source      = "${path.module}/../requirements.txt"
    destination = "/tmp/cydes/requirements.txt"
  }

  provisioner "file" {
    source      = "${path.module}/bootstrap-openllm.sh"
    destination = "/tmp/cydes/bootstrap-openllm.sh"
  }

  provisioner "remote-exec" {
    inline = [
      "chmod +x /tmp/cydes/bootstrap-openllm.sh",
      # "sudo VAR=x script" start "VAR=x" als programma; via bash -c gaat het goed. De waarde is in variables.tf
      # beperkt tot tekens van een modelnaam, dus er kan geen opdracht in staan.
      "sudo bash -c 'OLLAMA_MODELS=${var.ollama_models} /tmp/cydes/bootstrap-openllm.sh'",
    ]
  }
}

resource "null_resource" "bootstrap_grfics" {
  count      = var.enable_grfics ? 1 : 0
  depends_on = [cloudstack_port_forward.ssh]

  triggers = {
    instance_id = cloudstack_instance.grficstest[0].id
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

# Een omgeving van vóór enable_grfics houdt haar GRFICS-VM in plaats van hem opnieuw te maken (als enable_grfics aan staat).
moved {
  from = cloudstack_instance.grficstest
  to   = cloudstack_instance.grficstest[0]
}

moved {
  from = null_resource.bootstrap_grfics
  to   = null_resource.bootstrap_grfics[0]
}
