output "public_ip" {
  description = "Het publieke adres van het netwerk: SSH op poort 22 gaat naar de VM met Ollama, op 2222 naar GRFICS."
  value       = cloudstack_network.isolated.source_nat_ip_address
}

output "ollama_models" {
  description = "De modellen die op de VM staan; deployment.py bench stelt ze voor."
  value       = var.ollama_models
}

output "ssh_private_key_path" {
  value = var.ssh_private_key_path
}

output "grfics" {
  value = var.enable_grfics
}
