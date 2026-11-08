#!/usr/bin/env bash
# Planta o erro clássico: "consertar" o placeholder que o deploy.yml substitui por sed.
set -euo pipefail
A="$REPOS/oficina-api"
sed -i 's#TARGET_GROUP_ARN_PLACEHOLDER#arn:aws:elasticloadbalancing:us-east-1:474717634842:targetgroup/oficina-hml-tg/6d0ecf831eec9f09#' \
  "$A/deploy/base/targetgroupbinding.yaml"
git -C "$A" add deploy/base/targetgroupbinding.yaml
git -C "$A" -c core.hooksPath=/dev/null commit -q -m "fix(deploy): arn do target group de hml"
