#!/usr/bin/env bash
#
# Configura o lado do GitHub a partir dos outputs deste diretório: os secrets AWS_ROLE_ARN,
# AWS_ACCOUNT_ID e TF_STATE_BUCKET de cada repo e os environments homologacao e producao.
#
# Uso (no seu terminal, depois do terraform apply):
#   ./github.sh            mostra os comandos, sem executar nada
#   ./github.sh --apply    executa, depois de você digitar "sim" (exige terminal interativo:
#                          um agente não consegue rodar esta forma)
#
# Os secrets do New Relic (NEW_RELIC_LICENSE_KEY, NEW_RELIC_API_KEY, NEW_RELIC_ACCOUNT_ID) não
# saem daqui: cadastre à mão, a partir da sua conta do New Relic.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
OWNER="${OFICINA_OWNER:-bregaldahq}"
APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

outputs="$(terraform output -json)"
out() { jq -r "$1" <<< "$outputs"; }
account="$(out .account_id.value)"
bucket="$(out .state_bucket.value)"

commands=()
for repo in oficina-infra-fundacao oficina-infra-cluster oficina-gateway-auth oficina-api; do
  role="$(out ".ci_role_arns.value[\"$repo\"]")"
  commands+=("gh secret set AWS_ROLE_ARN --repo $OWNER/$repo --body $role")
  commands+=("gh secret set AWS_ACCOUNT_ID --repo $OWNER/$repo --body $account")
  # A api não usa Terraform, mas o README dela lista o TF_STATE_BUCKET entre os esperados.
  commands+=("gh secret set TF_STATE_BUCKET --repo $OWNER/$repo --body $bucket")
  for env in homologacao producao; do
    commands+=("gh api -X PUT repos/$OWNER/$repo/environments/$env --silent")
  done
done

printf '%s\n' "${commands[@]}"
echo
echo "O role da api também precisa estar em app_ci_role_arn, nos envs/*.tfvars do cluster:"
echo "  $(out '.ci_role_arns.value["oficina-api"]')"

if ! $APPLY; then
  echo
  echo "Nada foi executado. Para executar: ./github.sh --apply"
  exit 0
fi

[[ -t 0 ]] || { echo "--apply só roda num terminal interativo." >&2; exit 1; }
read -r -p "Executar os ${#commands[@]} comandos acima no GitHub? Digite sim: " answer
[[ "$answer" == sim ]] || { echo "Cancelado."; exit 1; }
for cmd in "${commands[@]}"; do
  echo "+ ${cmd%% --body *}"
  eval "$cmd"
done
