---
name: novo-parametro-ssm
description: Expõe um valor de um repositório da Oficina para outro pelo SSM Parameter Store (único acoplamento permitido, ADR-008) — publicar, consumir, renomear ou remover um parâmetro /oficina/<env>/..., na ordem certa. Use para "o repo X precisa do valor Y do repo Z", "novo parâmetro", "renomear parâmetro", "remover parâmetro".
---

# Parâmetro SSM

Nenhum repo usa `terraform_remote_state` de outro. Cada parâmetro tem **um** dono, que o
publica com `resource "aws_ssm_parameter"` no `ssm.tf`. Os outros leem com
`data "aws_ssm_parameter"` ou com `aws ssm get-parameter` no workflow.

## Nome

`/oficina/${var.environment}/<grupo>/<nome>`, em snake_case. O grupo segue os existentes:
`network`, `db`, `auth`, `eks`, `ecr`, `nlb`, `apigw`. O dono vem da seção 1 do
`CONTRATOS.md` (propriedade de recursos).

## Ordem (é ela que evita apply quebrado)

| Operação | PRs, nesta ordem de merge |
|---|---|
| Criar | 1. o dono publica (`ssm.tf`) e é aplicado → 2. os consumidores passam a ler |
| Remover | 1. os consumidores deixam de ler → 2. o dono deixa de publicar |
| Renomear | 1. o dono publica o nome novo, mantendo o antigo → 2. os consumidores migram → 3. o dono remove o antigo |

Renomear são **três** conjuntos de PRs, não um. Siga a skill `mudanca-cross-repo` para branches e
PRs.

## Em cada etapa

- Seção 2 do `CONTRATOS.md`: a linha na tabela do dono, como adendo, no PR do dono.
- Consumidor em workflow (`deploy.yml`) lê do SSM no passo "Ler parâmetros do SSM"; não
  hardcode o valor.
- `bin/check-contracts.py --only ssm`: `SSM-1` (consumido sem dono) é erro, `SSM-2` (dois
  donos) é erro, `SSM-4` (fora do documento) é aviso.

Termine na Definição de Pronto do `AGENTS.md`, com a ordem de merge no resumo.
