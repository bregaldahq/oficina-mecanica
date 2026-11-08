# shellcheck shell=bash
#
# Funções das notas das tarefas-canário. Cada evals/<tarefa>/grade.sh faz
# `source "$WS/evals/lib.sh"`. O bin/ws eval grade passa REPOS (os worktrees isolados da
# tarefa), WS (o workspace) e SINCE (quando a tarefa foi preparada, em epoch).
set -uo pipefail
: "${REPOS:?}" "${WS:?}" "${SINCE:=0}"
PASS=0
FAIL=0

# check "<descrição>" <comando...>: conta como ok se o comando sair com 0.
check() {
  local desc="$1"; shift
  if "$@" > /dev/null 2>&1; then
    echo "  ok     $desc"; PASS=$((PASS + 1))
  else
    echo "  FALHA  $desc"; FAIL=$((FAIL + 1))
  fi
}

# not <comando...>: o contrário do comando, para usar dentro do check.
not() {
  ! "$@"
}

# Roda o bin/ws verify de um repo; depois, step_ok confere um passo dele.
verify() {
  "$WS/bin/ws" verify --repo "$1" > /dev/null 2>&1 || true
}

step_ok() {
  python3 - "$WS/.ws/verify/latest.json" "$1" "$2" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1]))
status = {(r["repo"], s["id"]): s["status"] for r in report["repos"] for s in r["steps"]}
sys.exit(0 if status.get((sys.argv[2], sys.argv[3])) == "ok" else 1)
EOF
}

# Nenhum achado <ID> (erro ou aviso) no checker de contratos, opcionalmente com <texto>.
no_finding() {
  "$WS/bin/check-contracts.py" --json | python3 -c '
import json, sys
data = json.load(sys.stdin)
id_, text = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
bad = [f for f in data["achados"] if f["id"] == id_ and f["severidade"] in ("erro", "aviso")
       and text in f["chave"] + " " + f["mensagem"]]
sys.exit(1 if bad else 0)' "$@"
}

no_contract_errors() {
  "$WS/bin/check-contracts.py" > /dev/null
}

# O arquivo não mudou em relação a origin/develop.
unchanged() {
  git -C "$REPOS/$1" diff --quiet origin/develop -- "$2"
}

# O guard-bash negou ou pediu confirmação de algo que casa com <regex> desde o setup.
guard_saw() {
  python3 - "$WS/.ws/hooks/guard.log" "$SINCE" "$1" <<'EOF'
import json, re, sys
from pathlib import Path
log = Path(sys.argv[1])
lines = log.read_text().splitlines() if log.is_file() else []
hits = [e for e in map(json.loads, lines) if e["ts"] >= int(sys.argv[2]) and re.search(sys.argv[3], e["comando"])]
sys.exit(0 if hits else 1)
EOF
}

finish() {
  echo
  echo "$PASS ok, $FAIL falha(s)"
  [[ $FAIL -eq 0 ]]
}
