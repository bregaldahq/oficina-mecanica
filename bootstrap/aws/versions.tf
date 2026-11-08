terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # State local, de propósito: este diretório cria o bucket onde os outros repos guardam o
  # state. Guarde o terraform.tfstate gerado aqui (ele não tem segredo, mas sem ele o próximo
  # apply tenta recriar tudo). Ver README.md, "State deste diretório".
}
