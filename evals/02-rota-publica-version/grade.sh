#!/usr/bin/env bash
# shellcheck source=evals/lib.sh
source "$WS/evals/lib.sh"
G="$REPOS/oficina-gateway-auth"; A="$REPOS/oficina-api"
check "app: rota GET /api/version com requireAuth: false" grep -qE "get\('/api/version'.*requireAuth: false" "$A/public/index.php"
check "gateway: rota dedicada GET /api/version sem authorizer" python3 -c '
import re, sys; t = open(sys.argv[1]).read()
b = re.search(r"route_key\s*=\s*\"GET /api/version\"(.*?)\n}", t, re.S)
sys.exit(0 if b and "\"NONE\"" in b.group(1) else 1)' "$G/apigateway.tf"
check "rotas coerentes entre gateway e app (ROTA-1)" no_finding ROTA-1 /version
check "swagger.yaml: /version com security: [] (ROTA-4)" no_finding ROTA-4 /version
check "swagger.yaml documenta /version" grep -q "^  /version:" "$A/swagger.yaml"
check "CONTRATOS.md, seção 5, cita a rota (ROTA-2/3)" no_finding ROTA-2 /api/version
check "CONTRATOS.md cita /api/version" grep -q "/api/version" "$A/docs/fase-3/CONTRATOS.md"
verify oficina-api
for step in cs-fixer phpstan phpunit; do check "app: $step" step_ok oficina-api "$step"; done
verify oficina-gateway-auth
for step in tf-fmt tf-validate; do check "gateway: $step" step_ok oficina-gateway-auth "$step"; done
finish
