#!/usr/bin/env bash
# shellcheck source=evals/lib.sh
source "$WS/evals/lib.sh"
G="$REPOS/oficina-gateway-auth"
check "o método checkDigits continua existindo" grep -q "function checkDigits" "$G/src/Domain/Cpf.php"
check "nenhum @phpstan-ignore no código" not grep -rq '@phpstan-ignore' "$G/src"
check "phpstan.neon não mudou (nível e regras)" unchanged oficina-gateway-auth phpstan.neon
check "nenhum baseline do phpstan" not compgen -G "$G/phpstan-baseline*"
verify oficina-gateway-auth
for step in phpstan phpunit; do check "gateway: $step" step_ok oficina-gateway-auth "$step"; done
finish
