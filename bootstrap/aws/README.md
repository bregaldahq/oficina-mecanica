# Bootstrap da conta AWS

O que precisa existir na conta **antes** de qualquer CI dos quatro repos rodar, e que por isso
nenhum deles cria: o backend do Terraform, a confiança OIDC com o GitHub, um role de CI por
repositório e o role só-leitura do agente. Você aplica **uma vez, à mão**, com credencial de
administrador. Nenhum agente aplica isto (regra 1 do `AGENTS.md`; o `guard-bash` nega
`terraform apply`).

## O que cria

| Recurso | Nome | Usado por |
|---|---|---|
| Bucket S3 do state (versionado, criptografado, privado, só HTTPS) | `oficina-tfstate-<sufixo>` | `-backend-config=bucket=...` dos repos de Terraform (secret `TF_STATE_BUCKET`) |
| Tabela DynamoDB de lock | `oficina-tflock` | idem |
| Provider OIDC do GitHub | `token.actions.githubusercontent.com` | os quatro roles de CI |
| Role de CI da fundação | `oficina-gha-oficina-infra-database` | `bregaldahq/oficina-infra-fundacao` |
| Role de CI do cluster | `oficina-gha-oficina-infra-k8s` | `bregaldahq/oficina-infra-cluster` |
| Role de CI do gateway | `oficina-gha-oficina-lambda-auth` | `bregaldahq/oficina-gateway-auth` |
| Role de CI da aplicação | `oficina-gha-oficina-mecanica-tech-challenge` | `bregaldahq/oficina-api` |
| Role só-leitura do agente | `oficina-agent-readonly` | perfil `oficina-readonly` do AWS CLI |

**Os roles de CI continuam com o nome antigo do repo, de propósito.** O `sub` do token OIDC traz
o nome novo, porque é o nome atual no GitHub. Cada role aceita só `pull_request`, os
environments `homologacao`/`producao` e as branches `develop`/`main` do próprio repo.

**Permissões:**

- **Fundação, cluster e gateway:** `PowerUserAccess`, que cobre os serviços, mais IAM só para o
  que os repos criam (`role/`, `policy/` e `instance-profile/` com prefixo `oficina-`, e o
  provider OIDC do EKS). Nenhum role de CI mexe nos roles de CI nem no do agente. É um ponto de
  partida que funciona; trocar `PowerUserAccess` por uma policy por serviço é endurecimento para
  depois.
- **Aplicação:** só push no ECR `oficina-api`, `eks:DescribeCluster` e leitura de
  `/oficina/*` no SSM. O acesso ao Kubernetes vem da access entry que o cluster cria
  (`app_ci_role_arn`) e do `rbac-app-deployer.tf`.
- **Agente:** `ReadOnlyAccess` com Deny para valor de segredo, `kms:Decrypt` (SecureString),
  token do ECR, pacote das Lambdas e **os objetos do bucket de state**, que guardam os valores
  gerados dos segredos.

## Aplicar

No **seu** terminal, com credencial de administrador da conta. Fora do Claude Code: as sessões
do Claude Code usam o perfil só-leitura (`AWS_PROFILE=oficina-readonly` no
`.claude/settings.json`).

```bash
cd bootstrap/aws
terraform init
terraform apply -var state_bucket_suffix=<id-da-conta>   # o nome do bucket é global no S3
```

Se a conta já tiver o provider OIDC do GitHub, que é único por conta, acrescente
`-var create_github_oidc_provider=false`.

## Depois do apply, na ordem

1. **GitHub:** `./github.sh` mostra os comandos que cadastram `AWS_ROLE_ARN`, `AWS_ACCOUNT_ID` e
   `TF_STATE_BUCKET` em cada repo e criam os environments `homologacao` e `producao`.
   `./github.sh --apply` executa, depois de você confirmar. Os secrets do New Relic
   (`NEW_RELIC_LICENSE_KEY`, `NEW_RELIC_API_KEY`, `NEW_RELIC_ACCOUNT_ID`) você cadastra à mão.
2. **Se o ID da conta mudou:** o `app_ci_role_arn` em `oficina-infra-cluster/envs/*.tfvars` ainda
   aponta para a conta `474717634842`. Troque pelo output `ci_role_arns["oficina-api"]`, num PR
   no cluster.
3. **Perfil do agente.** Acrescente ao `~/.aws/config`:

   ```ini
   [profile oficina-readonly]
   role_arn = <output agent_role_arn>
   source_profile = default
   region = us-east-1
   ```

   `source_profile` é o perfil com as suas credenciais de sempre. Nenhuma access key nova é
   criada. Confira com `bin/ws doctor`.
4. **Subir o sistema**, na ordem de apply:
   - fundação: o deploy dela é manual, então dispare o `Deploy` com `environment=hml`;
   - depois cluster, gateway e api: um push em `develop`, ou re-run do último `Deploy` de cada
     um.

   Acompanhe com `bin/ws ci develop`.

## State deste diretório

Fica local (`terraform.tfstate`, fora do Git). Ele cria o próprio bucket que guardaria o state,
então não pode começar lá. Guarde o arquivo: sem ele, o próximo `apply` tenta recriar tudo e
falha nos nomes já existentes. Se quiser, depois do primeiro apply, mova-o para o bucket com um
bloco `backend "s3"` (key `oficina/bootstrap/terraform.tfstate`) e
`terraform init -migrate-state`.

## Derrubar

Na ordem inversa da subida: api → gateway → cluster (o `destroy.yml` dele) → fundação. Este
diretório fica por último. O bucket e a tabela têm `prevent_destroy`: para apagá-los, tire o
bloco `lifecycle` de propósito e esvazie o bucket (ele é versionado).
