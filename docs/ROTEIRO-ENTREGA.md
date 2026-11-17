# Roteiro de entrega da Fase 4

O que falta para a entrega depende de você: o agente não aplica infraestrutura, não grava segredo,
não mexe em proteção de branch e não faz merge. Este roteiro põe esses passos na ordem certa, com
os comandos prontos. O vídeo fica de fora.

Estado em 2026-11-16: os seis repositórios estão implementados e verificados sem AWS
(`bin/ws verify`, `bin/ws e2e`: 20 + 87 checagens). O PDF de entrega está em
[`entrega/ENTREGA-FASE-4.pdf`](entrega/ENTREGA-FASE-4.pdf); para mudar, edite o
[`entrega/ENTREGA-FASE-4.md`](entrega/ENTREGA-FASE-4.md) e gere de novo
(`python3 docs/entrega/gerar.py`).

## 1. GitHub: branch padrão e proteção (R10)

Os dois repositórios novos estão com a branch padrão `chore/esqueleto` e **sem proteção**. Nos
quatro antigos, `main` e `develop` exigem PR com revisão, mas **nenhuma checagem do CI**.

Branch padrão `develop` nos novos:

```bash
for r in oficina-faturamento oficina-execucao; do gh api -X PATCH repos/bregaldahq/$r -f default_branch=develop; done
```

Proteção de `main` e `develop`: PR obrigatório e as checagens do `pr.yml` obrigatórias. O job de
qualidade dos serviços inclui o SonarCloud com `qualitygate.wait`, então exigir o job exige o
quality gate (depois do passo 2; sem o `SONAR_TOKEN` o passo só avisa).

```bash
protect() { # repo branch check...
  local repo=$1 branch=$2; shift 2
  local checks; checks=$(printf '"%s",' "$@"); checks="[${checks%,}]"
  gh api -X PUT "repos/bregaldahq/$repo/branches/$branch/protection" --input - <<JSON
{"required_status_checks":{"strict":false,"contexts":$checks},
 "enforce_admins":false,
 "required_pull_request_reviews":{"required_approving_review_count":0},
 "restrictions":null}
JSON
}
for b in main develop; do
  for r in oficina-api; do
    protect $r $b "Lint, testes e análise estática" "Build da imagem de produção" "Validação dos manifests kustomize" "Terraform fmt e validate (infra/)"
  done
  for r in oficina-faturamento oficina-execucao; do
    protect $r $b "Lint, testes, cobertura e qualidade" "Build da imagem de produção" "Validação dos manifests kustomize" "Terraform fmt e validate (infra/)"
  done
  protect oficina-gateway-auth $b "Testes e análise estática" "Terraform fmt e validate"
  protect oficina-infra-cluster $b "fmt + validate"
  protect oficina-infra-fundacao $b "Sanidade das migrations"
done
```

`required_approving_review_count: 0` exige PR sem exigir outra pessoa aprovando (o projeto tem um
autor só). Os jobs de `plan` dos repos de infra ficam de fora: dependem da conta AWS de pé. Depois,
`bin/ws doctor` confere as proteções.

## 2. Contas e segredos

| O quê | Onde | Como |
|---|---|---|
| SonarCloud | sonarcloud.io, organização `bregaldahq` | importar `oficina-api`, `oficina-faturamento` e `oficina-execucao` (chaves `bregaldahq_<repo>`, já nos `sonar-project.properties`) e desligar a *Automatic Analysis* (a análise é a do CI) |
| `SONAR_TOKEN` | secret dos três serviços | `gh secret set SONAR_TOKEN --repo bregaldahq/<repo>` |
| `NEW_RELIC_LICENSE_KEY`, `NEW_RELIC_API_KEY`, `NEW_RELIC_ACCOUNT_ID` | secret dos seis repos que fazem deploy | como na Fase 3 |
| Integração AWS no New Relic | *Infrastructure → AWS → Link account*, com o SQS | para o painel e o alerta de DLQ |
| Mercado Pago (sandbox) | segredo `oficina/hml/faturamento/mercadopago`, criado pelo `infra/` do Faturamento com `PREENCHER` | depois do primeiro deploy do Faturamento: `aws secretsmanager put-secret-value --secret-id oficina/hml/faturamento/mercadopago --secret-string '{"MP_ACCESS_TOKEN":"TEST-...","MP_WEBHOOK_SECRET":"..."}'` e reiniciar o Deployment `oficina-faturamento` |
| Webhook do Mercado Pago | painel do Mercado Pago, na aplicação de teste | URL `<apigw>/api/billing/payments/webhook/mercadopago`, evento *Pagamentos*; o segredo exibido ali é o `MP_WEBHOOK_SECRET` |

## 3. Conta AWS

1. `bootstrap/aws/`: `terraform apply` e depois `./github.sh --apply` (`bootstrap/aws/README.md`).
   Ele cria os roles de CI dos seis repos (o da api agora tem Terraform: state, SQS, IAM) e grava
   `AWS_ROLE_ARN`, `AWS_ACCOUNT_ID` e `TF_STATE_BUCKET` em cada um.
2. O role da api em `app_ci_role_arn`, nos `envs/*.tfvars` do cluster (o `github.sh` imprime o
   valor).

## 4. Deploy em hml, na ordem

Os merges da Fase 4 já estão na `develop` de cada repositório (em 2026-11-17), menos a migration
005 ([fundação #17](https://github.com/bregaldahq/oficina-infra-fundacao/pull/17), rascunho de
propósito). Os deploys que esses merges dispararam falharam porque a conta AWS estava desligada;
com o passo 3 feito, rode-os de novo nesta ordem. Na fundação, no cluster e no gateway o deploy é
**sempre manual**; nos três serviços, merge em `develop` dispara o de hml, e *Run workflow* na
`develop` refaz.

| # | Repositório | Como | Antes, confirme |
|---|---|---|---|
| 1 | fundação | *Actions → Deploy → Run workflow*, `develop`, ambiente `hml` (tópico SNS, `INTERNAL_TOKEN`, endpoint do Secrets Manager aberto à VPC) | passo 3 |
| 2 | cluster | *Actions → Deploy → Run workflow*, `develop`, `hml` (listeners e target groups dos três serviços, RBAC, policy do External Secrets) | fundação aplicada |
| 3 | faturamento e execucao | *Actions → Deploy → Run workflow* na `develop` | cluster aplicado; logo depois do Faturamento, o segredo do Mercado Pago (passo 2) e um rollout do Deployment |
| 4 | api | *Actions → Deploy → Run workflow* na `develop` (roda a migration 004) | Faturamento e Execução no ar |
| 5 | gateway | *Actions → Deploy → Run workflow*, `develop` (prefixos por serviço e a `auth-cpf` pela rota interna da OS) | a OS da Fase 4 no ar: a `auth-cpf` nova chama a rota interna dela |
| 6 | fundação | merge do [#17](https://github.com/bregaldahq/oficina-infra-fundacao/pull/17) (migration 005) e de novo o deploy da api, que aplica a migration | a OS da Fase 4 no ar e estável: depois da 005, voltar a imagem da OS para a da Fase 3 não funciona mais |

Nos repositórios antigos a `develop` exige uma aprovação: como dono, `gh pr merge <n> --merge --admin`.

**PRs antigos da Fase 3, revisados em 2026-11-17: feche sem merge.**

- Fundação [#6](https://github.com/bregaldahq/oficina-infra-fundacao/pull/6) e
  [#7](https://github.com/bregaldahq/oficina-infra-fundacao/pull/7), cluster
  [#10](https://github.com/bregaldahq/oficina-infra-cluster/pull/10) e
  [#11](https://github.com/bregaldahq/oficina-infra-cluster/pull/11): a correção do `deploy.yml`
  já está na `develop`, e tirar o `terraform plan` do PR jogaria fora o plan do cluster, que já é
  melhor que o de setembro. Substituídos pelos PRs `ci/fase-4-workflows`: o plan fica, e é
  pulado com aviso quando a conta AWS está fora do ar.
- api [#20](https://github.com/bregaldahq/oficina-api/pull/20): é de antes da Fase 4, tem
  conflito e reverteria boa parte dela. A ideia dele (produção só por disparo manual) entrou nos
  PRs `ci/fase-4-workflows` da api, do Faturamento e da Execução.
- Os `develop → main` (api #23, gateway #10, fundação #9, cluster #13) ficam para o passo 6.

## 5. Conferir em hml

1. O `deploy.yml` de cada serviço terminou verde (testes, `infra/`, imagem, rollout, smoke).
2. **Postman** (a coleção já roda inteira sem AWS: `bin/ws e2e --postman`, 40 de 40): importe `oficina-api/docs/fase-4/postman/` (coleção e ambiente), preencha
   `baseUrl` (`/oficina/hml/apigw/endpoint`), `adminPassword` e `webhookToken` (chave
   `WEBHOOK_TOKEN` do segredo `oficina/hml/auth`), e rode as pastas em ordem, com delay de
   3000 ms no runner. A pasta 6 pede o pagamento no sandbox, pelo `payment_url`.
3. **New Relic:** `NEW_RELIC_API_KEY=... python3 scripts/newrelic-import.py --env hml --endpoint <apigw>`
   no `oficina-api` importa os dashboards e alertas das Fases 3 e 4. Com a coleção rodada, o
   dashboard "Saga" mostra o funil, e o *distributed tracing* mostra uma OS passando pelos três
   serviços.
4. **Evidências:** o resumo do run do `pr.yml` (cobertura), o SonarCloud (quality gate) e o
   deploy marcado no New Relic, que são os links da seção "Evidências" de cada README.

## 6. Produção e encerramento

1. `develop → main` em cada repo, na ordem de apply (`/release` no Claude Code prepara o
   changelog e os riscos de cada um). O merge em `main` **não** aplica nada: produção sobe só por
   *Actions → Deploy → Run workflow* com a ref `main`, em todos os repositórios, na mesma ordem
   do passo 4. A migration 005 só entra em `main` com a OS da Fase 4 já em produção.
2. **Custo:** o ambiente cobra por hora (EKS, nodes, os dois RDS). Terminada a avaliação,
   destrua na ordem inversa à de apply, **serviços → gateway → cluster → fundação**:
   1. os três serviços: *Actions → Destroy* em `oficina-faturamento`, `oficina-execucao` e
      `oficina-api` (manual, digitando `hml`). Tira o `infra/` de cada um (filas, roles, o RDS do
      Faturamento, a tabela da Execução) e preserva o ECR, que é da conta. Roda antes do cluster e
      da fundação, porque o `infra/` lê parâmetros deles;
   2. o gateway: `terraform destroy` na sua máquina, como na Fase 3 (ele não tem workflow de
      destroy);
   3. o cluster: *Actions → Destroy* do `oficina-infra-cluster`;
   4. a fundação: `terraform destroy` na sua máquina, por último (VPC e RDS ficam presos enquanto
      houver node ou NLB).

   Confira no console que não sobrou NLB, RDS, node nem fila.

   - **Subir o hml de novo depois:** o ECR de cada serviço ficou na conta e fora do state; o
     primeiro apply falharia com `RepositoryAlreadyExists`. Antes dele, no `infra/` do serviço:
     `terraform import -var-file=envs/hml.tfvars 'aws_ecr_repository.service[0]' oficina-<serviço>`
     (ou apague o repositório no console, se as imagens não importam).
   - **Prod:** o RDS do Faturamento tem `deletion_protection` e snapshot final, então o destroy de
     prod falha de propósito até alguém desligar a proteção (`deletion_protection = false` num
     apply antes). O snapshot final tem nome fixo: um segundo destroy de prod exige apagar o
     snapshot anterior. Os segredos de prod ficam 7 dias agendados para exclusão; recriar prod
     nesse prazo falha até restaurar ou forçar a exclusão deles.
