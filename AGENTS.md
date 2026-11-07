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

## O sistema de ponta a ponta

Uma requisição atravessa os quatro repositórios assim:

```
Cliente ── POST /auth/cpf ──► API Gateway ──► Lambda auth-cpf ──► RDS (busca cliente por CPF)
                              (lambda-auth)    (lambda-auth)       (infra-database)
                                                   └─► devolve JWT HS256 assinado com JWT_SECRET

Cliente ── GET /api/... + Bearer ──► API Gateway ──► Lambda jwt-authorizer (valida o JWT, cache 300s)
                                         │
                                         └─ VPC Link ──► NLB interno :80 ──► Pods oficina-api no EKS
                                            (lambda-auth)  (infra-k8s)        (app, revalida o JWT)
                                                                                 └─► RDS MySQL
```

- **Rede, banco e segredos** nascem em `oficina-infra-database` e sobrevivem a tudo.
- **Cluster, ECR e NLB** nascem em `oficina-infra-k8s` e são descartáveis.
- **Porta de entrada e autenticação do cliente final** ficam em `oficina-lambda-auth`.
- **Regra de negócio** fica só na aplicação, `oficina-mecanica-tech-challenge`.

Dois papéis no JWT: `customer` (token vem do `POST /auth/cpf` da Lambda) e `admin` (token vem
do `POST /api/auth/login` da aplicação). O mesmo `JwtProvider` existe nos dois repos, copiado byte
a byte.

## Como funciona cada repo

### `oficina-infra-database` — fundação

**O que é.** Terraform puro (>= 1.6, AWS provider ~> 5.60) mais as migrations SQL. Primeiro a
ser aplicado, último a ser destruído (ADR-009).

**O que cria.**
- `network.tf`: VPC `10.20.0.0/16` com 2 subnets públicas (rota `0.0.0.0/0` → IGW, onde moram os
  nodes do EKS) e 2 privadas (sem rota para a internet, onde ficam RDS e Lambda). **Não há NAT**
  (ADR-010, custo). Remover a rota pública impede os nodes de entrar no cluster.
- `security_groups.tf`: SG `db` (ingress 3306) e SG `db-client`, que fica **vazio** e funciona
  como **crachá**: quem anexa o `db-client` alcança o banco. Isso mantém a dependência numa
  direção só (database → k8s/lambda). Não troque por referência direta ao SG dos nodes.
- `rds.tf`: MySQL 8.0 `db.t4g.micro`, criptografado. Em `prod`, `deletion_protection = true` e
  snapshot final obrigatório.
- `secrets.tf`: `random_password` gera os valores dos segredos `oficina/<env>/db` e
  `oficina/<env>/auth`. Ninguém digita nem commita esses valores.
- `ssm.tf`: os 10 parâmetros `network/*`, `db/*` e `auth/secret_arn` que os outros repos leem.
- `vpc_endpoints.tf`: interface endpoint do **Secrets Manager**. Sem NAT, a Lambda `auth-cpf`
  (subnet privada) não alcança o endpoint público do serviço e trava até o timeout, sem erro.
  Serviço AWS novo chamado de dentro da subnet privada precisa de endpoint próprio.

**Migrations.** Ficam em `migrations/NNN_<slug>.sql`:
- `001` é o schema inicial;
- `002` traz os ajustes da Fase 3;
- `003_seed_demo` tem 120 OS de demonstração e só roda em hml.

Quem executa é o Job da aplicação, não este repo. Toda migration precisa ser idempotente:
- onde o MySQL não aceita `IF NOT EXISTS`, consulte o `information_schema` e monte o comando com
  `PREPARE`/`EXECUTE`;
- não use `DELIMITER`, `CREATE DATABASE` nem `USE`.

O `pr.yml` aplica todas as migrations **duas vezes** num MySQL real, para provar a idempotência.
O modelo de dados está documentado em `docs/MODELO-DE-DADOS.md`.

**Validar.** `terraform fmt -check -recursive` e `terraform init -backend=false && terraform validate`.
Para as migrations, suba um container `mysql:8.0` e aplique os arquivos em ordem, duas vezes.

### `oficina-infra-k8s` — cluster

**O que é.** Terraform com os providers `aws`, `kubernetes`, `helm` e `kubectl`. Os três
últimos se autenticam via `aws eks get-token`. Lê do SSM a rede, o `db/client_sg_id` e os ARNs
dos segredos.

**O que cria.**
- `eks.tf`: cluster EKS (versão em `envs/*.tfvars`, hoje `1.31`) e um managed node group de
  `t3.small`, de 2 a 4 nodes, nas **subnets públicas** com IP público. Cada node recebe o SG do
  node, o SG do cluster e o SG crachá do banco. `capacity_type` é `SPOT` em hml e `ON_DEMAND`
  em prod.
- `ecr.tf`: repositório `oficina-api`, com scan on push e retenção das últimas 10 imagens.
- `nlb.tf`: NLB **interno**, target group `target_type = ip` e listener `:80`, todos criados
  **pelo Terraform**, não pelo Load Balancer Controller. Motivo: a Lambda aplica antes da app e
  precisa dos ARNs já existentes. Os Pods entram no target group pelo `TargetGroupBinding`
  declarado na aplicação.
- `addons-*.tf`: add-ons Helm.
  - `aws-load-balancer-controller` (IRSA): só registra os targets.
  - `metrics-server`: pré-requisito do HPA.
  - `external-secrets` (IRSA restrita aos 2 segredos): cria o `ClusterSecretStore`
    **`oficina-secretsmanager`**.
  - `nri-bundle`: New Relic, com kube-state-metrics, eventos e logs via Fluent Bit.
- `namespaces.tf`: `oficina-hml` e `oficina-prod`.
- `rbac-app-deployer.tf`: dá ao role de CI da aplicação permissão sobre as CRDs
  `TargetGroupBinding` e `ExternalSecret` no namespace. Sem isso, o deploy da app volta
  `forbidden`. CRD nova usada pela app precisa entrar aqui.
- `ssm.tf`: publica `eks/*`, `ecr/repository_url` e `nlb/*`.

**Cuidados.**
- Antes de destruir o cluster, remova os workloads da aplicação. Um `TargetGroupBinding` órfão
  trava a exclusão do target group.
- Há um `destroy.yml` que só roda por disparo manual e pede que você digite o nome do ambiente.
  Agente não dispara.

**Validar.** `terraform fmt`, `terraform init -backend=false`, `terraform validate` (o CI também
roda `tflint`).

### `oficina-lambda-auth` — borda e autenticação

**O que é.** PHP 8.2 no runtime **Bref** (layer `php-82`) mais o Terraform do API Gateway. As
duas Lambdas recebem o **mesmo zip** (`scripts/build-package.sh` → `build/lambda.zip`). O que muda
entre elas é o `handler`. Assim, quem emite e quem valida o token rodam o mesmo `JwtProvider`.

**Código (`src/`).**
- `Handler/AuthCpfHandler.php` implementa o `POST /auth/cpf`:
  - valida o CPF com dígito verificador antes de tocar o banco;
  - busca o cliente em `customers`;
  - decide entre 200, 400, 403, 404 e 500 (tabela na seção 5 do `CONTRATOS.md`);
  - emite o JWT com `role=customer`.
- `Handler/JwtAuthorizerHandler.php` é o authorizer REQUEST com *simple response*. Ele valida
  assinatura e `exp` e devolve `context.customerId` e `context.role`.
- `Security/JwtProvider.php`: cópia byte a byte do `JwtProvider` da aplicação.
- `Secrets/SecretsManagerProvider.php`: guarda o segredo em cache estático entre invocações. Uma
  rotação só é percebida quando um container novo sobe.
- `Domain/Cpf.php` replica o value object `Document` da aplicação, e
  `Repository/PdoCustomerRepository.php` faz o acesso ao banco.
- `handler-auth.php` e `handler-authorizer.php` só montam as dependências e delegam. Os handlers
  são classes puras, que recebem um array e devolvem um array, testáveis sem AWS.

**Infra (`*.tf`).**
- `lambda.tf`: a `auth-cpf` roda **dentro** da VPC (subnets privadas + SG crachá) porque fala
  com o RDS. O `jwt-authorizer` roda **fora** da VPC, sem ENI e sem cold start extra no caminho
  de toda requisição.
- `iam.tf`: um role por função. O authorizer não recebe acesso ao segredo de banco nem
  permissão de VPC.
- `apigateway.tf`: HTTP API com as rotas abaixo e o VPC Link, que usa as mesmas subnets privadas
  do NLB.
  - Rotas dedicadas, sem authorizer: `POST /auth/cpf` (vai para a Lambda), `GET /api/health`,
    `GET /api/ready`, `POST /api/auth/login`, `GET /docs`, `GET /docs/{proxy+}` e
    `GET /swagger.yaml` (essas seguem para o NLB).
  - `ANY /api/{proxy+}` passa pelo `jwt-authorizer` e segue via VPC Link para o listener do NLB.
- `newrelic-logs.tf`: logs das Lambdas e o access log do gateway vão para o New Relic por
  **Kinesis Firehose** (subscription filter do CloudWatch). Não se usa a extensão de Lambda: a
  `auth-cpf` está numa VPC sem NAT e a extensão falharia em silêncio.
- `ssm.tf`: publica `apigw/endpoint` e `apigw/api_id`.

**O teste mais importante.** `tests/Contract/JwtContractTest.php` compara um token gerado com
entrada fixa contra uma string literal. A aplicação tem o teste espelho. Se ele quebrar,
descubra o que mudou no `JwtProvider` e reverta. Não atualize a string sem mudar os dois lados.

**Validar.** Veja a tabela de validação local mais abaixo. Os ARNs dos layers (Bref, New Relic)
em `envs/*.tfvars` envelhecem: confira a versão antes de mudar.

### `oficina-mecanica-tech-challenge` — aplicação

**O que é.** API REST em **PHP 8.2 puro**, sem framework (ADR-001), em Clean Architecture e
DDD. Tem Nginx + PHP-FPM numa imagem `php:8.2-fpm-bookworm` (não Alpine, porque o agente New
Relic exige glibc), MySQL via PDO, PHPUnit 11 e PHPStan nível 8. É o repo de mudança diária e o
dono da documentação da Fase 3.

**Camadas (`src/`).** A dependência aponta sempre para dentro:
- `Domain/`, sem nenhuma dependência externa.
  - O agregado `Aggregate/ServiceOrder.php` é a máquina de estados da OS:
    `RECEIVED → DIAGNOSIS → AWAITING_APPROVAL → EXECUTING → FINISHED → DELIVERED`, com
    `AWAITING_APPROVAL → REJECTED`. Cada transição é um método nomeado (`changeToDiagnosis`,
    `sendForApproval`, `approve`, `reject`, `finish`, `deliver`). Nunca existe `setStatus`
    (ADR-003). Transição inválida lança `InvalidStatusTransitionException`.
  - Entidades, value objects (`Document` para CPF/CNPJ, `LicensePlate`, `CustomerStatus`),
    eventos de domínio e interfaces de repositório.
- `Application/`: um use case por ação (`CreateServiceOrder`, `ChangeServiceOrderStatus`,
  `ReviewBudget`, `AddItems`, `ListServiceOrdersByCustomer`…) com DTOs de entrada.
- `Infrastructure/`:
  - repositórios PDO; a transação fica dentro do repositório (ADR-004) e a hidratação usa
    `reconstitute()` (ADR-005);
  - `Security/JwtProvider.php` (o par do da Lambda) e `Logging/JsonLogger.php`, com log JSON e
    `correlation_id`;
  - `Database/MigrationRunner.php`;
  - `Event/InMemoryEventDispatcher.php` e três subscribers que reagem a toda mudança de status:
    `StatusHistorySubscriber` grava `service_order_status_history`, `NewRelicSubscriber` emite
    os custom events `ServiceOrderCreated` e `ServiceOrderStatusChanged`, e
    `StatusChangeEmailNotifier` manda email via cliente SMTP próprio.
- `Presentation/`: `Router` com regex e `requireRole()`, `AuthMiddleware` (revalida o JWT
  localmente; nunca confia no contexto do gateway), `CorrelationIdMiddleware`, controllers e
  `RequestValidator`.

**Composition root.** `public/index.php` monta todas as dependências à mão e declara **todas as
rotas com a matriz de autorização**. Rota nova entra aqui. Se for pública, também precisa de rota
dedicada no `apigateway.tf` da Lambda.

**Rotas.**
- Públicas: `GET /api/health` (liveness, não toca o banco), `GET /api/ready` (readiness) e
  `POST /api/auth/login`.
- Com `X-Webhook-Token`: `POST /api/service-orders/{id}/approval`.
- `customer` ou `admin`: `GET /api/service-orders/me` e `GET /api/service-orders/{id}` (o
  customer só vê a própria OS).
- Só `admin`: o resto do CRUD de OS, clientes, veículos, peças e serviços.

O contrato HTTP completo está em `swagger.yaml`.

**Deploy (`deploy/`, kustomize).**
- `base/` tem: Deployment (Nginx + PHP-FPM, probes em `/api/health` e `/api/ready`), Service,
  HPA (2 a 10 réplicas, CPU 70% e memória 80%), `ExternalSecret` (gera o `Secret`
  `oficina-secret` a partir do `ClusterSecretStore` `oficina-secretsmanager`),
  `TargetGroupBinding`, ConfigMaps e o **Job `oficina-migrate`**.
- `overlays/hml` e `overlays/prod` definem namespace, réplicas, recursos e tag da imagem. O prod
  tem também um PDB.
- O Job clona `oficina-infra-database` na ref de `deploy/base/migrations-configmap.yaml`, que o
  pipeline fixa, e roda `bin/migrate.php`. O runner controla o que já rodou pela tabela
  `schema_migrations` e pula os arquivos `_demo` em produção.

**Pipeline (`deploy.yml`).**
1. Autentica por OIDC e lê do SSM o ECR, o cluster, o namespace e o target group.
2. Faz build e push da imagem com tag = git sha.
3. Fixa no overlay a imagem e o ARN do target group, e roda `kubectl apply -k`.
4. Roda o Job de migration e espera o rollout.
5. Faz smoke test em `/api/ready` e um smoke de observabilidade.
6. Marca o deployment no New Relic.

**Documentação.** Fica em `docs/fase-3/`:
- `CONTRATOS.md` (normativo);
- 10 ADRs e 3 RFCs;
- diagramas;
- dashboards e alertas do New Relic em `newrelic/`, importados por `scripts/newrelic-import.py`;
- coleção Postman.

`docs/DOMAIN-STORYTELLING.md` descreve os fluxos de negócio.

**Cuidados.**
- Os testes de integração (`tests/Integration/`) rodam em SQLite in-memory com `CREATE TABLE`
  escritos dentro dos próprios testes, sem `ENUM` nem `CHECK`. Coluna nova usada por um
  repositório PDO precisa entrar ali também.
- `src/Infrastructure/Database/schema.sql` é legado das fases anteriores e nada o referencia. O
  schema de verdade são as migrations do repo de banco.
- Não há PHP na máquina: use `scripts/php.sh` ou `make` (docker compose).

## Onde mexer para…

| Quero… | Repos, na ordem |
|---|---|
| nova regra de negócio ou endpoint admin | app (`src/` + `public/index.php` + `swagger.yaml`) |
| novo endpoint **público** | app (rota com `requireAuth: false`) e lambda-auth (rota dedicada em `apigateway.tf`) |
| nova coluna ou tabela | infra-database (`migrations/NNN_*.sql`) → app (entidade, repositório PDO, schema SQLite dos testes de integração) |
| nova claim ou mudança no JWT | lambda-auth **e** app juntos, com os dois testes de contrato e `contract-token.md` |
| novo segredo | infra-database (`secrets.tf`) → infra-k8s (policy IRSA do ESO, se for segredo novo) → app (`ExternalSecret`) e/ou lambda-auth (IAM) |
| novo parâmetro compartilhado | repo produtor (`ssm.tf`) → consumidores (`data "aws_ssm_parameter"` ou workflow) → `CONTRATOS.md` |
| escala, recursos ou réplicas | app (`deploy/overlays/<env>`) |
| tamanho ou tipo de node, versão do EKS | infra-k8s (`envs/<env>.tfvars`) |
| dashboards e alertas | app (`docs/fase-3/newrelic/`) |

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
- **Rotas públicas** (`/auth/cpf`, `/api/auth/login`, `/api/health`, `/api/ready`, `/docs`,
  `/swagger.yaml`) existem como rota dedicada no gateway (repo da Lambda) **e** na matriz de
  autorização da aplicação.

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
