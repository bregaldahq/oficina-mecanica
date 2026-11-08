---
name: atualizar-dependencias
description: Levanta e aplica atualizações de dependências nos repositórios da Oficina — Composer (patch/minor), providers do Terraform dentro do constraint, versões das GitHub Actions, layers Bref/New Relic da Lambda, versão do EKS e ferramentas da imagem tooling/Dockerfile. Use para "atualizar dependências", "tem algo desatualizado?", "bump de versões".
---

# Atualizar dependências

Primeiro levante e mostre; só aplique o que o usuário escolher, numa branch
`chore/deps-<aaaa-mm-dd>` por repo (`bin/ws branch` ou `bin/ws isolate`).

## Levantar

| O quê | Como |
|---|---|
| Composer (app e gateway) | `bin/ws exec <repo> composer outdated --direct --minor-only` (major só listar) |
| Providers Terraform | `required_providers` em `versions.tf` × registry: `bin/ws exec <repo> terraform init -backend=false -upgrade` num worktree isolado e veja o que mudaria no lock (o lock só é versionado no gateway) |
| GitHub Actions | `uses:` dos workflows (`bin/ws grep -n "uses:" -- '.github/workflows/*'`) × a última versão de cada action |
| Layers da Lambda | ARNs de Bref (`php-82`) e New Relic em `repos/oficina-gateway-auth/envs/*.tfvars`. Envelhecem: confira a versão publicada antes de trocar |
| EKS | `cluster_version` em `repos/oficina-infra-cluster/envs/*.tfvars` × a janela de suporte padrão da AWS. Upgrade é um minor por vez e mexe nos nodes: só planeje, não aplique |
| Ferramentas locais | os `ARG` do `tooling/Dockerfile` × o que o CI usa (`terraform_version`, kustomize) |

## Aplicar

- Patch e minor de Composer: `composer update <pacote>` com `bin/ws exec`, e commite o
  `composer.lock`.
- Provider ou action: só dentro do constraint e com o changelog lido; major vira plano, não PR.
- Depois de cada repo, `bin/ws verify --repo <repo>`. Atualização que quebra teste volta e entra
  como achado no resumo.

Responda com uma tabela (o quê, de → para, risco, aplicado ou não) e termine na Definição de
Pronto do `AGENTS.md`. PRs só com `/abrir-prs`.
