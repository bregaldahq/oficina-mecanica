---
name: corrigir-ci
description: Descobre por que o CI (GitHub Actions) de um repositório da Oficina falhou, reproduz localmente e corrige na branch de trabalho. Use quando disserem "o CI quebrou", "o PR está vermelho", "o deploy falhou", ou colarem um link de run do GitHub Actions.
---

# Corrigir o CI

1. **Achar a falha.** `bin/ws ci <branch>` mostra o último run de cada workflow nos 4 repos e
   salva o log das etapas que falharam em `.ws/ci/<repo>-<branch>-<workflow>.log`. Com um link
   de run, use `gh run view <id> --repo bregaldahq/<repo> --log-failed`. Leia só as linhas em
   volta do erro.
2. **Classificar:**

   | Falha | O que fazer |
   |---|---|
   | Teste, phpstan, cs-fixer, `terraform fmt`/`validate`, kustomize, migrations, workflow inválido | reproduza com `bin/ws verify --repo <repo>` e corrija (passo 3) |
   | `Could not assume role with OIDC` | não é código: é a policy de confiança do role `oficina-gha-*` (achado 16 do `docs/PLANO-HARNESS-IA.md`). Diga ao usuário; não há o que corrigir aqui |
   | `terraform plan`/`apply`, deploy, smoke test, New Relic | depende da AWS: diagnostique pelo log e proponha a correção, sem tentar reproduzir |

3. **Corrigir** na branch do PR (nunca em `develop`/`main`), até `bin/ws verify --repo <repo>`
   ficar `OK`. Não silencie o erro: nada de `@phpstan-ignore`, `continue-on-error` ou teste
   desligado sem o usuário concordar.
4. **Commitar** com Conventional Commits em português, sem acento no assunto (`fix(ci): ...`).
   O push pede confirmação do usuário; diga o que vai subir antes.

Responda com a causa em uma frase, o que mudou e se o CI deve ficar verde só com isso, ou se
depende de algo fora do código.
