# Oficina Mecânica — workspace

Este repositório não tem código de produto. Ele junta os quatro repositórios do sistema da
Oficina Mecânica (Tech Challenge SOAT, Fase 3) para que um agente, ou uma pessoa, enxergue e
mude o sistema inteiro de um lugar só. Os repositórios ficam em `repos/`, que não é versionado
aqui: cada um continua com o próprio Git, as próprias branches e o próprio CI.

## Mapa

| Repositório | Papel | Stack | Muda |
|---|---|---|---|
| `repos/oficina-infra-database` | **Fundação**: VPC, subnets, RDS MySQL, *todos* os segredos, migrations SQL | Terraform | raríssimo |
| `repos/oficina-infra-k8s` | **Cluster**: EKS, node group, add-ons Helm, ECR, NLB interno + target group, `ClusterSecretStore` | Terraform | ocasional |
| `repos/oficina-lambda-auth` | **Borda**: Lambdas `auth-cpf` e `jwt-authorizer` (PHP/Bref), API Gateway, VPC Link | PHP 8.2 + Terraform | ocasional |
| `repos/oficina-mecanica-tech-challenge` | **Aplicação**: API REST em PHP puro (DDD, Clean Architecture), `deploy/` em kustomize, Job de migration | PHP 8.2 | diário |

Ordem de `apply`: **database → k8s → lambda → app**. Ordem de `destroy`: inversa.

## Fonte da verdade

O documento normativo entre os repositórios é
`repos/oficina-mecanica-tech-challenge/docs/fase-3/CONTRATOS.md`. Leia antes de qualquer mudança
que atravesse repositórios. Em caso de divergência entre ele e uma implementação, **o documento
vence** — corrija a implementação, ou altere o documento no mesmo conjunto de PRs.

Também na aplicação: ADRs em `docs/fase-3/adr/`, RFCs em `docs/fase-3/rfc/`, token de contrato
JWT em `docs/fase-3/contract-token.md`, dashboards e alertas em `docs/fase-3/newrelic/`.

Este workspace **não duplica** esses documentos. Se precisar citar um contrato, aponte o arquivo.

## Como os repositórios se acoplam

O acoplamento é **só** por SSM Parameter Store, sob `/oficina/<env>/...` (ADR-008). Nenhum repo
usa `terraform_remote_state` de outro. Cada parâmetro tem **um** repositório dono, que o publica
com `resource "aws_ssm_parameter"`; os demais leem com `data "aws_ssm_parameter"` ou com
`aws ssm get-parameter` no workflow.

Outros pontos de contato que quebram em silêncio se um lado mudar:

- **JWT HS256** gerado pela Lambda e validado pela aplicação: header, ordem das claims e
  base64url precisam ser byte a byte iguais. Os dois repos têm um teste de contrato com o mesmo
  token literal.
- **Segredos** `oficina/<env>/db` e `oficina/<env>/auth`: criados pelo repo de banco, lidos pela
  Lambda (SDK) e pela aplicação (External Secrets, `ClusterSecretStore` `oficina-secretsmanager`).
- **Migrations** vivem no repo de banco, mas quem as executa é o Job da aplicação
  (`bin/migrate.php`).
- **Rotas públicas** (`/auth/cpf`, `/api/auth/login`, `/api/health`, `/api/ready`) existem no
  gateway (repo da Lambda) **e** na matriz de autorização da aplicação.

`bin/check-contracts.py` confere o primeiro item automaticamente: parâmetro consumido sem dono,
parâmetro com dois donos e parâmetro publicado que ninguém lê.

## Ferramentas do workspace

```bash
make setup                 # baixa os repos que faltam em repos/
bin/ws status              # branch, arquivos sujos e divergência de cada repo
bin/ws pull                # fast-forward em todos
bin/ws prs                 # PRs abertos em todos
bin/ws run git log -3 --oneline
bin/check-contracts.py     # acoplamento SSM consistente?
```

## Validação local

Não há PHP nem Composer na máquina de desenvolvimento — PHP roda em Docker. Sem conta AWS, o
teto de verificação dos repos de IaC é `fmt` + `validate` sem backend.

| Repo | Comandos |
|---|---|
| aplicação | `make up`, `make test`, `make analyse`, `make lint`, `make k8s-render` (ou `scripts/php.sh vendor/bin/phpunit`) |
| lambda-auth | `make test`, `make stan`, `make fmt`, `make validate` |
| infra-database, infra-k8s | `terraform fmt -check -recursive` e `terraform init -backend=false && terraform validate` |

## Convenções (valem nos quatro repos)

- **Branches**: `main` = produção, `develop` = homologação. Trabalho em `feat/…`, `fix/…`,
  `chore/…`, `ci/…`, sempre com PR para `develop`; `develop` sobe para `main` por PR.
- **Commits** em português, sem acento no assunto, no formato Conventional Commits com escopo:
  `fix(observabilidade): …`, `feat(gateway): …`, `chore(docs): …`.
- **Autoria**: commits e PRs saem só com o nome do Ricardo. Não adicione `Co-Authored-By` nem
  rodapé de ferramenta.
- **CI**: `pr.yml` (lint, testes, análise estática, `terraform plan` nos repos de IaC) e
  `deploy.yml` (OIDC → apply/deploy → smoke test). Nenhuma access key estática.
- **Terraform**: ambientes em `envs/hml.tfvars` e `envs/prod.tfvars`, não em workspaces. Tags
  obrigatórias `Project`, `Environment`, `ManagedBy`, `Repo`.

## Regras para agentes

1. **Nunca** rode `terraform apply`/`destroy`, `kubectl apply`/`delete` nem dispare
   `workflow_dispatch` de deploy a partir daqui. Infra só muda pelo CI de cada repo.
2. Mudança que atravessa repositórios segue a ordem de apply: o **produtor** do contrato muda e é
   mergeado antes do **consumidor**. Remoção é o contrário: primeiro o consumidor deixa de ler,
   depois o produtor deixa de publicar.
3. Uma branch com o **mesmo nome** em cada repo afetado, e PRs que se referenciam.
4. Antes de abrir PR de mudança cross-repo, rode `bin/check-contracts.py` e os testes de cada repo
   tocado.
5. Não commite nada dentro de `repos/` a partir de comandos do workspace sem conferir em qual repo
   e em qual branch está — cada um é um Git separado.
6. Não leia nem imprima `.env` nem saída de `get-secret-value`. Os `envs/*.tfvars` são
   configuração versionada, sem segredo, e podem ser lidos.
