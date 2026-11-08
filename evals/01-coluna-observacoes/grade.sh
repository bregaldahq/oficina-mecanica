#!/usr/bin/env bash
# shellcheck source=evals/lib.sh
source "$WS/evals/lib.sh"
F="$REPOS/oficina-infra-fundacao"; A="$REPOS/oficina-api"
new_migration() { git -C "$F" diff --name-only --diff-filter=A origin/develop -- migrations | xargs -r grep -li "observacoes"; }
check "migration nova adiciona a coluna observacoes" test -n "$(new_migration)"
check "migration no formato NNN_slug, sem SQL proibido" no_finding MIG-1
verify oficina-infra-fundacao
check "migrations aplicam duas vezes num MySQL 8.0" step_ok oficina-infra-fundacao migrations-2x
check "MODELO-DE-DADOS.md documenta a coluna" grep -qi observacoes "$F/docs/MODELO-DE-DADOS.md"
check "repositório PDO grava e lê a coluna" grep -rqi observacoes "$A/src/Infrastructure/Repository"
check "schema SQLite dos testes de integração tem a coluna" grep -rqi observacoes "$A/tests/Integration"
check "swagger.yaml documenta o campo" grep -qi observacoes "$A/swagger.yaml"
check "nenhuma coluna usada pelo PDO falta nos testes (MIG-2)" no_finding MIG-2 observacoes
verify oficina-api
for step in cs-fixer phpstan phpunit; do check "app: $step" step_ok oficina-api "$step"; done
finish
