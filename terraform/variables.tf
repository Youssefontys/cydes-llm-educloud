variable "cloudstack_api_url" {
  description = "Het API-endpoint van Educloud, eindigt op /client/api. Leeg laten kan: dan via CLOUDSTACK_API_URL."
  type        = string
  default     = null
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
  description = "De zone van je account, bijvoorbeeld Eindhoven-Zone."
  type        = string
}

variable "template" {
  description = "Het OS-template; de scripts gaan uit van Ubuntu met cloud-init."
  type        = string
}

variable "network_name" {
  description = "Naam van het eigen isolated netwerk; ook het begin van de naam van elke VM."
  type        = string
  default     = "cydes-llm-test"
}

variable "network_cidr" {
  description = "Eigen CIDR voor dit netwerk, los van het bestaande Shared netwerk (10.70.x.x)."
  type        = string
  default     = "10.1.1.0/24"
}

# Elk groepslid heeft een eigen sleutel in zijn eigen account; de naam stond eerst vast in main.tf.
variable "keypair" {
  description = "Naam van een SSH-sleutelpaar dat al in je Educloud-account staat (Compute, SSH key pairs)."
  type        = string
  default     = "dependency-track-admin"
}

variable "ssh_private_key_path" {
  description = "De private key die bij dat sleutelpaar hoort, voor de provisioners en voor deployment.py bench."
  type        = string
  default     = "~/.ssh/id_ed25519"
}

# Wie bij SSH mag. De VM hangt met een publiek adres aan internet; met GRFICS aan draait er een bewust kwetsbare
# omgeving achter. Beperk dit waar het kan tot je eigen adres of het bereik van de VPN.
variable "ssh_cidrs" {
  description = "De adresbereiken die SSH mogen bereiken, bijvoorbeeld [\"203.0.113.7/32\"]. 0.0.0.0/0 is iedereen."
  type        = list(string)
  default     = ["0.0.0.0/0"]

  validation {
    condition     = length(var.ssh_cidrs) > 0 && alltrue([for c in var.ssh_cidrs : can(cidrhost(c, 0))])
    error_message = "Geef minstens één geldig bereik, zoals 203.0.113.7/32."
  }
}

variable "openllm_service_offering" {
  description = "De grootte van de VM met Ollama. Zonder GPU bepaalt het geheugen welk model past."
  type        = string
  default     = "Medium Instance+"
}

# Een lijst, omdat de benchmark modellen vergelijkt. Alleen tekens die in een modelnaam horen: de waarde gaat naar een shell.
variable "ollama_models" {
  description = "De modellen die Ollama ophaalt, gescheiden door komma's, bijvoorbeeld qwen2.5:3b,llama3.2:3b."
  type        = string
  default     = "qwen2.5:3b"

  validation {
    condition     = can(regex("^[A-Za-z0-9._/-]+(:[A-Za-z0-9._-]+)?(,[A-Za-z0-9._/-]+(:[A-Za-z0-9._-]+)?)*$", var.ollama_models))
    error_message = "Modelnamen zoals Ollama ze kent, gescheiden door komma's en zonder spaties, zoals qwen2.5:3b,llama3.2:3b."
  }
}

# De benchmark heeft GRFICS niet nodig: de cases zijn nagemaakt verkeer. Uit spaart een grote VM.
variable "enable_grfics" {
  description = "true zet ook een VM met GRFICSv3 neer, voor echt verkeer en demo's."
  type        = bool
  default     = false
}

variable "grfics_service_offering" {
  description = "De grootte van de VM met GRFICSv3."
  type        = string
  default     = "Large Instance"
}

variable "grfics_siem" {
  description = "'yes' start ook wazuh en zeek (--profile siem); fors zwaarder."
  type        = string
  default     = "no"

  validation {
    condition     = contains(["yes", "no"], var.grfics_siem)
    error_message = "Kies yes of no."
  }
}
