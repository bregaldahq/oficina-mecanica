---
name: novo-segredo
description: Adiciona uma chave a um segredo da Oficina (oficina/<env>/db ou oficina/<env>/auth) ou um segredo novo, com o gerador no Terraform da fundação e o consumo pela aplicação (ExternalSecret) e/ou pela Lambda (IAM e leitura) — sem nunca ver o valor. Use para "novo segredo", "nova variável sensível", "token novo para X".
---

# Novo segredo

**Nunca** leia, imprima nem peça o valor de um segredo. Os valores são gerados por
`random_password` na fundação e ninguém os digita.

## 1. Chave nova num segredo que já existe

Ordem de merge: **fundação → app e/ou gateway**.

1. `repos/oficina-infra-fundacao/secrets.tf`: um `random_password` novo, se for gerado, e a chave
   no `jsonencode` do `aws_secretsmanager_secret_version`. No smoke test do `deploy.yml` da
   fundação, acrescente o `has("<CHAVE>")`.
2. Aplicação: uma entrada em `repos/oficina-api/deploy/base/external-secret.yaml`
   (`secretKey` + `remoteRef { key, property }`) **e** no patch do overlay de prod
   (`deploy/overlays/prod/external-secret-patch.yaml`), que troca `oficina/hml` por
   `oficina/prod`. Depois, use como variável de ambiente.
3. Lambda, se ler: `$secret['<CHAVE>']` no handler. O IAM já dá acesso ao segredo inteiro.

## 2. Segredo novo (`oficina/<env>/<nome>`)

Tudo do item 1, mais:

- o `aws_secretsmanager_secret` e o ARN publicado em `ssm.tf` (skill `novo-parametro-ssm`);
- **cluster:** a policy IRSA do External Secrets (`addons-external-secrets.tf`) é restrita aos
  segredos atuais, e o novo precisa entrar ali (é o terceiro repo, entre a fundação e a app);
- **Lambda:** a permissão em `iam.tf`, só para a função que precisa. O authorizer não tem acesso
  ao segredo de banco, de propósito.

## 3. Verificar

`bin/check-contracts.py --only segredos`: chave lida que o `secrets.tf` não cria é erro
(`SEG-1`), e o `CONTRATOS.md` desatualizado é aviso (`SEG-2`). A seção 3 do `CONTRATOS.md`
recebe a chave como adendo. Termine na Definição de Pronto do `AGENTS.md`.
