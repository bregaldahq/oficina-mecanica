# Role só-leitura para o agente (Claude Code) investigar sem poder mudar nada nem ver segredo.
# Ninguém ganha access key nova: o perfil oficina-readonly do AWS CLI assume este role a partir
# das suas credenciais de sempre (README.md, "Perfil do agente"). O .claude/settings.json do
# workspace fixa AWS_PROFILE=oficina-readonly nas sessões do Claude Code.

data "aws_iam_policy_document" "agent_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = length(var.agent_trusted_principal_arns) > 0 ? var.agent_trusted_principal_arns : ["arn:aws:iam::${local.account_id}:root"]
    }
  }
}

resource "aws_iam_role" "agent" {
  name                 = "oficina-agent-readonly"
  description          = "Leitura para o agente de IA do workspace oficina-mecanica, sem segredos"
  assume_role_policy   = data.aws_iam_policy_document.agent_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "agent_read_only" {
  role       = aws_iam_role.agent.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# A ReadOnlyAccess ainda deixa ler coisas que são segredo; o Deny vence qualquer Allow.
data "aws_iam_policy_document" "agent_no_secrets" {
  statement {
    sid    = "SemSegredos"
    effect = "Deny"
    actions = [
      "secretsmanager:GetSecretValue", # valores de oficina/<env>/db e /auth
      "kms:Decrypt",                   # SecureString do SSM e tudo o que é criptografado com KMS
      "ecr:GetAuthorizationToken",     # credencial de docker login
      "lambda:GetFunction",            # URL do pacote com o código
      "rds:DownloadDBLogFilePortion",
      "sts:GetSessionToken",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "SemOStateDoTerraform"
    effect    = "Deny"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.state.arn}/*"] # o state guarda os valores gerados dos segredos
  }
}

resource "aws_iam_role_policy" "agent_no_secrets" {
  name   = "sem-segredos"
  role   = aws_iam_role.agent.id
  policy = data.aws_iam_policy_document.agent_no_secrets.json
}
