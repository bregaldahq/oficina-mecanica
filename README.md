# oficina-workspace

Workspace que reúne os quatro repositórios do sistema da **Oficina Mecânica** (Tech Challenge
SOAT, Fase 3) para trabalhar com agentes de IA — Claude Code, Codex ou qualquer ferramenta que
leia `AGENTS.md` — enxergando o sistema inteiro de uma vez.

Não há código de produto aqui: só o mapa, as regras e as ferramentas para operar os repos juntos.

| Repositório | Papel |
|---|---|
| [`oficina-infra-database`](https://github.com/bregaldahq/oficina-infra-database) | fundação: VPC, RDS, segredos, migrations |
| [`oficina-infra-k8s`](https://github.com/bregaldahq/oficina-infra-k8s) | cluster: EKS, add-ons, ECR, NLB interno |
| [`oficina-lambda-auth`](https://github.com/bregaldahq/oficina-lambda-auth) | borda: Lambdas de autenticação e API Gateway |
| [`oficina-mecanica-tech-challenge`](https://github.com/bregaldahq/oficina-mecanica-tech-challenge) | aplicação, deploy, contratos e ADRs |

## Começando

```bash
git clone https://github.com/bregaldahq/oficina-workspace.git
cd oficina-workspace
make setup          # baixa os quatro em repos/
claude              # ou o agente de sua preferência, a partir da raiz
```

Já tem os repos clonados em outro lugar? Em vez de clonar de novo:

```bash
bin/ws link ~/caminho/onde/estao/os/clones
```

## O que tem aqui

| Caminho | Para quê |
|---|---|
| `AGENTS.md` | contexto para qualquer agente: mapa, acoplamento, convenções, regras |
| `CLAUDE.md` | importa o `AGENTS.md` e lista o que é específico do Claude Code |
| `Makefile` | atalhos: `make setup`, `make pull`, `make status`, `make prs`, `make contratos` |
| `repos.txt` | lista de repositórios, na ordem de apply — para incluir um repo, adicione uma linha |
| `bin/ws` | `clone`, `link`, `pull`, `status`, `prs`, `run <cmd>` em todos os repos |
| `bin/check-contracts.py` | confere o acoplamento por SSM: consumidor sem dono, dono duplicado, parâmetro órfão |
| `.claude/skills/` | `status-geral`, `mudanca-cross-repo`, `checar-contratos` |
| `.claude/agents/` | `guardiao-de-contratos`, revisor de diffs contra o `CONTRATOS.md` |
| `.claude/settings.json` | libera comandos de leitura e bloqueia `apply`, `destroy`, deploy manual e leitura de segredos |

## Princípios

- **`repos/` não é versionado.** Cada repositório mantém o próprio Git, CI e proteção de branch;
  o workspace só os enxerga. Nada de submodule.
- **Uma fonte da verdade.** O contrato entre os repos continua em
  `oficina-mecanica-tech-challenge/docs/fase-3/CONTRATOS.md`. O workspace aponta para ele, não
  copia.
- **Agente não muda infra.** Infra muda pelo CI de cada repo; daqui, o agente lê, edita, testa e
  abre PR.
