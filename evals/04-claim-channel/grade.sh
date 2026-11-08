#!/usr/bin/env bash
# shellcheck source=evals/lib.sh
source "$WS/evals/lib.sh"
G="$REPOS/oficina-gateway-auth"; A="$REPOS/oficina-api"
check "a Lambda emite a claim channel=cpf" grep -qE "'channel'\s*=>\s*'cpf'" "$G/src/Handler/AuthCpfHandler.php"
check "token literal igual nos dois testes e no contract-token.md (JWT-1)" no_finding JWT-1
check "montagem do token equivalente nos dois JwtProvider (JWT-2)" no_finding JWT-2
check "CONTRATOS.md, seção 4, documenta a claim" grep -q "channel" "$A/docs/fase-3/CONTRATOS.md"
verify oficina-gateway-auth
for step in phpunit-contract phpunit phpstan; do check "gateway: $step" step_ok oficina-gateway-auth "$step"; done
verify oficina-api
check "app: phpunit" step_ok oficina-api phpunit
finish
