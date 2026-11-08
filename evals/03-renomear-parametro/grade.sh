#!/usr/bin/env bash
# shellcheck source=evals/lib.sh
source "$WS/evals/lib.sh"
C="$REPOS/oficina-infra-cluster"
published() { python3 -c '
import re, sys; t = open(sys.argv[1]).read()
blocks = re.findall(r"resource\s+\"aws_ssm_parameter\".*?\n}", t, re.S)
sys.exit(0 if any("/nlb/" + sys.argv[2] + "\"" in b for b in blocks) else 1)' "$C/ssm.tf" "$1"; }
check "o nome novo é publicado" published http_listener_arn
check "o nome antigo continua publicado (o consumidor ainda não migrou)" published listener_arn
check "nenhum parâmetro consumido sem dono (SSM-1)" no_finding SSM-1
verify oficina-infra-cluster
for step in tf-fmt tf-validate; do check "cluster: $step" step_ok oficina-infra-cluster "$step"; done
finish
