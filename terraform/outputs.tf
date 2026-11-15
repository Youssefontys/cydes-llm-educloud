output "network_id" {
  value = cloudstack_network.isolated.id
}

output "public_ip" {
  description = "Het source-NAT IP van het isolated netwerk; SSH hierop op poort 22 gaat naar de openllm-VM."
  value       = cloudstack_network.isolated.source_nat_ip_address
}

output "openllm_instance_id" {
  value = cloudstack_instance.openllm.id
}
