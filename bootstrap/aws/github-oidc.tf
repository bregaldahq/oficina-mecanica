# Um role de CI por repositório, assumido pelo GitHub Actions via OIDC (seção 9 do
# CONTRATOS.md: nenhuma access key estática).
#
# O NOME do role continua com o nome antigo do repo, de propósito (README, "Nomes antigos"); o
# `sub` do token OIDC traz o nome NOVO, porque é o nome atual do repo no GitHub. Os jobs que usam
# AWS rodam em pull_request (plan) ou nos environments homologacao/producao (deploy).

locals {
  account_id = data.aws_caller_identity.current.account_id

  ci_roles = {
    fundacao = { repo = "oficina-infra-fundacao", role = "oficina-gha-oficina-infra-database", terraform = true }
    cluster  = { repo = "oficina-infra-cluster", role = "oficina-gha-oficina-infra-k8s", terraform = true }
    gateway  = { repo = "oficina-gateway-auth", role = "oficina-gha-oficina-lambda-auth", terraform = true }
    api      = { repo = "oficina-api", role = "oficina-gha-oficina-mecanica-tech-challenge", terraform = false }
  }

  github_subjects = ["pull_request", "environment:homologacao", "environment:producao",
  "ref:refs/heads/develop", "ref:refs/heads/main"]

  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # A AWS valida o certificado do GitHub pela própria cadeia de confiança; o thumbprint só é
  # exigido pela API.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1", "1c58a3a8518e8759bf075b76b750d4f2df264fcd"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "ci_trust" {
  for_each = local.ci_roles

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [for s in local.github_subjects : "repo:${var.github_owner}/${each.value.repo}:${s}"]
    }
  }
}

resource "aws_iam_role" "ci" {
  for_each = local.ci_roles

  name                 = each.value.role
  description          = "GitHub Actions de ${var.github_owner}/${each.value.repo} (OIDC)"
  assume_role_policy   = data.aws_iam_policy_document.ci_trust[each.key].json
  max_session_duration = 3600
}

# ── Repos de Terraform (fundação, cluster, gateway) ─────────────────────────────────────────
# PowerUserAccess cobre os serviços (VPC, RDS, Secrets Manager, SSM, EKS, ECR, ELB, Lambda, API
# Gateway, Firehose, S3, DynamoDB do lock, KMS, logs). IAM fica de fora dela e entra só para o
# que os repos criam, tudo com prefixo oficina- (roles do EKS, node group, IRSA, Lambdas,
# Firehose), e o provider OIDC do EKS. Nenhum role de CI mexe nos roles de CI nem no do agente.

resource "aws_iam_role_policy_attachment" "ci_power_user" {
  for_each = { for k, v in local.ci_roles : k => v if v.terraform }

  role       = aws_iam_role.ci[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "ci_iam" {
  statement {
    sid     = "IamDoProjeto"
    actions = ["iam:*"]
    resources = [
      "arn:aws:iam::${local.account_id}:role/oficina-*",
      "arn:aws:iam::${local.account_id}:policy/oficina-*",
      # O módulo iam-role-for-service-accounts-eks cria a policy do ALB controller com o prefixo
      # padrão AmazonEKS_ (addons-alb-controller.tf, attach_load_balancer_controller_policy).
      "arn:aws:iam::${local.account_id}:policy/AmazonEKS_*",
      "arn:aws:iam::${local.account_id}:instance-profile/oficina-*",
      "arn:aws:iam::${local.account_id}:oidc-provider/oidc.eks.${var.region}.amazonaws.com/*",
    ]
  }

  statement {
    sid       = "LeituraDeIam"
    actions   = ["iam:Get*", "iam:List*"]
    resources = ["*"]
  }

  statement {
    sid    = "NadaNosRolesDeCiNemNoDoAgente"
    effect = "Deny"
    actions = ["iam:Attach*", "iam:Create*", "iam:Delete*", "iam:Detach*", "iam:Put*", "iam:Update*",
    "iam:Tag*", "iam:Untag*", "iam:PassRole"]
    resources = [
      "arn:aws:iam::${local.account_id}:role/oficina-gha-*",
      "arn:aws:iam::${local.account_id}:role/oficina-agent-*",
    ]
  }
}

resource "aws_iam_role_policy" "ci_iam" {
  for_each = { for k, v in local.ci_roles : k => v if v.terraform }

  name   = "iam-do-projeto"
  role   = aws_iam_role.ci[each.key].id
  policy = data.aws_iam_policy_document.ci_iam.json
}

# ── Aplicação: só publica a imagem e aplica os manifests ────────────────────────────────────
# O acesso ao Kubernetes vem da access entry que o cluster cria para este role
# (app_ci_role_arn em oficina-infra-cluster/envs/*.tfvars) e do rbac-app-deployer.tf.

data "aws_iam_policy_document" "ci_api" {
  statement {
    sid       = "LoginNoEcr"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "PushDaImagem"
    actions = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload",
      "ecr:DescribeImages", "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload", "ecr:PutImage",
    "ecr:UploadLayerPart"]
    resources = ["arn:aws:ecr:${var.region}:${local.account_id}:repository/oficina-api"]
  }

  statement {
    sid       = "Kubeconfig"
    actions   = ["eks:DescribeCluster"]
    resources = ["arn:aws:eks:${var.region}:${local.account_id}:cluster/oficina-*"]
  }

  statement {
    sid       = "ParametrosDoContrato"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:aws:ssm:${var.region}:${local.account_id}:parameter/oficina/*"]
  }
}

resource "aws_iam_role_policy" "ci_api" {
  name   = "deploy-da-aplicacao"
  role   = aws_iam_role.ci["api"].id
  policy = data.aws_iam_policy_document.ci_api.json
}
