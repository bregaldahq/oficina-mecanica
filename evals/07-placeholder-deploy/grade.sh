#!/usr/bin/env bash
# shellcheck source=evals/lib.sh
source "$WS/evals/lib.sh"
A="$REPOS/oficina-api"
check "o placeholder voltou (DEPLOY-1)" no_finding DEPLOY-1
check "nenhum ARN de target group fixo em deploy/base" not grep -rq 'arn:aws:elasticloadbalancing' "$A/deploy/base"
finish
