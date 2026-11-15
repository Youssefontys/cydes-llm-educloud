variable "cloudstack_api_url" {
  type    = string
  default = null
}

variable "cloudstack_api_key" {
  type      = string
  sensitive = true
  default   = null
}

variable "cloudstack_secret_key" {
  type      = string
  sensitive = true
  default   = null
}

variable "zone" {
  description = "Zelfde zone als het personlijke account, bijv. Eindhoven-Zone."
  type        = string
}

variable "template" {
  description = "OS-template voor de testinstance, bijv. de Ubuntu 24.04 Cloud-template."
  type        = string
}

variable "network_name" {
  description = "Naam van het nieuwe isolated netwerk."
  type        = string
  default     = "cydes-llm-test"
}

variable "network_cidr" {
  description = "Eigen CIDR voor dit isolated netwerk, los van het bestaande Shared netwerk (10.70.x.x)."
  type        = string
  default     = "10.1.1.0/24"
}

variable "ssh_private_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519"
}

variable "openllm_service_offering" {
  description = "Compute offering voor de openllm-VM. CPU-only, dus RAM is de echte beperking voor welk model past."
  type        = string
  default     = "Medium Instance+"
}

variable "ollama_model" {
  description = "Ollama-modelnaam om te pullen en te draaien, bijv. qwen2.5:3b of llama3.2:3b. Klein genoeg om op CPU te draaien."
  type        = string
  default     = "qwen2.5:3b"
}
