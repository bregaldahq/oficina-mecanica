variable "region" {
  description = "Região AWS do projeto (seção 1 do CONTRATOS.md)."
  type        = string
  default     = "us-east-1"
}

variable "github_owner" {
  description = "Dono dos quatro repositórios no GitHub."
  type        = string
  default     = "bregaldahq"
}

variable "state_bucket_suffix" {
  description = "Sufixo do bucket de state: oficina-tfstate-<sufixo>. Precisa ser único no S3 inteiro (ex.: o id da conta)."
  type        = string
}

variable "create_github_oidc_provider" {
  description = "false se a conta já tem o provider OIDC token.actions.githubusercontent.com (só pode haver um)."
  type        = bool
  default     = true
}

variable "agent_trusted_principal_arns" {
  description = "Quem pode assumir o role só-leitura do agente. Vazio = qualquer principal da conta com permissão de sts:AssumeRole (os administradores)."
  type        = list(string)
  default     = []
}
