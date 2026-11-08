provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "oficina-mecanica"
      Environment = "shared"
      ManagedBy   = "terraform"
      Repo        = "oficina-mecanica"
    }
  }
}

data "aws_caller_identity" "current" {}
