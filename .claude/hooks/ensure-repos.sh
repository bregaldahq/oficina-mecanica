#!/usr/bin/env bash
#
# Hook SessionStart. Num worktree deste repo (o app desktop abre sessões assim) não existe
# repos/, porque ele não é versionado: liga repos/ ao do checkout principal, para que os
# caminhos repos/<nome>/... do AGENTS.md e das skills funcionem. Os clones são os mesmos do
# checkout principal, não cópias.
#
# O que este script imprime entra no contexto da sessão.
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

[[ -e "$ROOT/repos" ]] && exit 0

common="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
main="$(dirname "$common")"

if [[ "$main" == "$ROOT" ]]; then
  echo "repos/ não existe. Rode bin/ws clone (ou bin/ws link <dir>) antes de mexer nos repositórios."
elif [[ -d "$main/repos" ]]; then
  ln -s "$main/repos" "$ROOT/repos"
  echo "Sessão em worktree: repos/ aponta para $main/repos. São os mesmos clones do checkout principal; outra sessão aberta neles vê as mesmas mudanças."
else
  echo "Sessão em worktree e o checkout principal ($main) também não tem repos/. Rode bin/ws clone."
fi
