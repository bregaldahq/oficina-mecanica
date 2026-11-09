# Oficina Mecânica — repositório principal

Este é o repositório principal do projeto, `oficina-mecanica`, mas ele não tem código de produto.
Ele junta os quatro repositórios do sistema da Oficina Mecânica (Tech Challenge SOAT, Fase 3)
para que um agente, ou uma pessoa, enxergue e mude o sistema inteiro de um lugar só. Os
repositórios ficam em `repos/`, que não é versionado aqui: cada um continua com o próprio Git, as
próprias branches e o próprio CI.

Os repositórios foram renomeados em novembro de 2026; o `README.md` tem a tabela de nomes antigos.
PRs antigos, a chave do state do Terraform, os roles de CI (`oficina-gha-<nome-antigo>`) e a tag
`Repo` ainda usam os nomes antigos, de propósito. Não "corrija" esses três.

## Mapa

| Repositório | Papel | Stack | Muda |
|---|---|---|---|
| `repos/oficina-infra-fundacao` | **Fundação**: VPC, subnets, RDS MySQL, *todos* os segredos, migrations SQL | Terraform | raríssimo |
| `repos/oficina-infra-cluster` | **Cluster**: EKS, node group, add-ons Helm, ECR, NLB interno + target group, `ClusterSecretStore` | Terraform | ocasional |
| `repos/oficina-gateway-auth` | **Borda**: Lambdas `auth-cpf` e `jwt-authorizer` (PHP/Bref), API Gateway, VPC Link | PHP 8.2 + Terraform | ocasional |
| `repos/oficina-api` | **Aplicação**: API REST em PHP puro (DDD, Clean Architecture), `deploy/` em kustomize, Job de migration | PHP 8.2 | diário |

Ordem de `apply`: **fundação → cluster → gateway → api**. Ordem de `destroy`: inversa.

## Fonte da verdade

O documento normativo entre os repositórios é
`repos/oficina-api/docs/fase-3/CONTRATOS.md`. Leia antes de qualquer mudança
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

- **Rede, banco e segredos** nascem em `oficina-infra-fundacao` e sobrevivem a tudo.
- **Cluster, ECR e NLB** nascem em `oficina-infra-cluster` e são descartáveis.
- **Porta de entrada e autenticação do cliente final** ficam em `oficina-gateway-auth`.
- **Regra de negócio** fica só na aplicação, `oficina-api`.

Dois papéis no JWT: `customer` (token vem do `POST /auth/cpf` da Lambda) e `admin` (token vem
do `POST /api/auth/login` da aplicação). Há um `JwtProvider` em cada repo. Namespace, comentários
e imports diferem, mas a montagem do token é idêntica, e o teste de contrato dos dois lados trava
isso.

## Como funciona cada repo

Cada repo tem o próprio `AGENTS.md` (`repos/<nome>/AGENTS.md`): o que cria, os contratos que
publica e consome, como validar sem AWS, armadilhas e convenções. O hook `repo-context.py` o põe
no contexto na primeira vez que a sessão mexe no repo. Leia antes de mudar algo lá. Em resumo:

- **`oficina-infra-fundacao`** (Terraform):
  - VPC `10.20.0.0/16` **sem NAT** (ADR-010): subnets públicas para os nodes, privadas para RDS e
    Lambda;
  - SG crachá `db-client` e RDS MySQL 8.0;
  - os segredos `oficina/<env>/db` e `oficina/<env>/auth`, gerados por `random_password`;
  - os 10 parâmetros SSM e o endpoint do Secrets Manager;
  - as migrations `migrations/NNN_<slug>.sql`: idempotentes, sem `DELIMITER`/`USE`/`CREATE
    DATABASE`, executadas pelo Job da aplicação.
- **`oficina-infra-cluster`** (Terraform):
  - EKS com nodes nas subnets públicas;
  - ECR;
  - NLB interno e target group criados pelo Terraform;
  - add-ons: LB Controller, metrics-server, External Secrets com o `ClusterSecretStore`
    `oficina-secretsmanager`, New Relic;
  - RBAC das CRDs da app (`rbac-app-deployer.tf`).

  O `destroy.yml` é manual: agente não dispara.
- **`oficina-gateway-auth`** (PHP 8.2/Bref + Terraform):
  - Lambdas `auth-cpf` (na VPC, emite o JWT `customer`) e `jwt-authorizer` (fora da VPC), com o
    mesmo zip;
  - HTTP API com rota dedicada sem authorizer para cada rota pública, e `ANY /api/{proxy+}` com
    authorizer via VPC Link → NLB.

  O teste mais importante é o `tests/Contract/JwtContractTest.php`.
- **`oficina-api`** (PHP 8.2 puro, DDD e Clean Architecture):
  - máquina de estados da OS no agregado `ServiceOrder` (métodos nomeados, nunca `setStatus`);
  - um use case por ação e repositórios PDO;
  - `public/index.php` com todas as rotas e a matriz de autorização;
  - `deploy/` em kustomize, com o Job de migration;
  - a documentação da Fase 3 (`docs/fase-3/`: `CONTRATOS.md`, ADRs, RFCs).

  Os testes de integração usam SQLite com `CREATE TABLE` escritos à mão.

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
| conta AWS: bucket e lock do state, OIDC, roles de CI, role só-leitura do agente | este repo (`bootstrap/aws/`), aplicado à mão pelo usuário, nunca pelo agente |

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

`bin/check-contracts.py` confere todos esses pontos, e mais o `ClusterSecretStore`, o RBAC das
CRDs da app, os placeholders do deploy, as migrations, os nomes antigos, as tags e o OIDC. Ele
compara com o `CONTRATOS.md` e o `swagger.yaml` (o código fica em `tools/contratos/`, os testes em
`tests/test_contratos.py`).

- `erro`: as implementações discordam e algo quebra.
- `aviso`: o documento está desatualizado.
- `conhecido`: erro aceito, com motivo, em `tools/contratos/conhecidos.txt`. Não acrescente
  linha ali sem o usuário decidir.

## Ferramentas do workspace

```bash
make setup                         # baixa os repos que faltam em repos/
bin/ws status                      # branch, arquivos sujos e divergência de cada repo
bin/ws context                     # o mesmo, mais PRs abertos e CI de develop, em 4 linhas
bin/ws pull                        # fast-forward em todos
bin/ws prs [--branch <b>]          # PRs abertos; com --branch, os PRs irmãos de uma mudança
bin/ws ci [<branch>]               # último run de cada workflow; log do que falhou em .ws/ci/
bin/ws diff [--patch]              # o que mudou contra origin/develop
bin/ws grep -E 'padrão'            # busca nos quatro repos (só arquivos versionados ou novos)
bin/ws verify [--changed] [--fast] # o que o pr.yml roda, local e sem AWS (ver "Validação local")
bin/ws e2e                         # ponta a ponta entre os repos, sem AWS: migrations, app, Lambdas, JWT
bin/ws exec <repo> <cmd...>        # comando na imagem de ferramentas (PHP, Composer, Terraform...)
bin/ws branch <nome> <repo...>     # mesma branch nos repos indicados, a partir de origin/develop
bin/ws isolate <b> <repo...>       # worktrees próprios desta sessão (sessões paralelas)
bin/ws doctor                      # confere Docker, ferramentas, clones e proteções de branch
bin/ws hooks install               # git hooks de convenção (commit-msg, pre-push) nos cinco repos
bin/ws statusline                  # a linha da status line (branch de cada repo, último verify)
bin/ws eval [list|setup|grade|clean] <n>   # tarefas-canário (evals/README.md)
bin/ws run git log -3 --oneline
bin/check-contracts.py [--json]    # os contratos entre os repos (SSM, JWT, rotas, segredos...)
```

Onde um comando pede `<repo>`, vale o nome curto: `fundacao`, `cluster`, `gateway`, `api`.

### Como buscar

Com clones de verdade em `repos/` (o layout do `make setup`), o Grep e o Glob a partir da raiz
encontram os quatro repos: o `.ignore` devolve `repos/` às buscas, e dentro de cada repo vale o
`.gitignore` dele. Se `repos/<nome>` for symlink (`bin/ws link`; o `bin/ws doctor` avisa), o
ripgrep não entra nele.

- `bin/ws grep` busca nos quatro repos só em arquivos versionados ou novos, em qualquer layout.
- Numa sessão em worktree, `repos/` é um symlink para o checkout principal: no Grep ou Glob,
  passe `path: repos/<nome>`.
- Nunca conclua que algo não existe a partir de uma busca que não entrou nos repos.

### Sessões em worktree

O app desktop abre cada sessão num worktree em `.claude/worktrees/<nome>`, onde `repos/` não
existe. O hook `SessionStart` (`.claude/hooks/ensure-repos.sh`) liga `repos/` ao do checkout
principal, e `bin/ws` e `bin/check-contracts.py` fazem a mesma resolução sozinhos. Os clones são
os mesmos do checkout principal: duas sessões abertas ao mesmo tempo mexem nos mesmos arquivos.
Para isolar, use `bin/ws isolate <branch> <repo...>`.

### Guardrails executados

As regras para agentes, mais abaixo, não dependem só de você lembrar delas.

- **`.claude/hooks/guard-bash.py`** (antes de todo Bash): analisa o comando inteiro, inclusive
  `&&`, `bash -c`, `$(...)`, `git -C`, `cd x &&` e `bin/ws exec`.
  - **Nega:** `apply`/`destroy`/`state`, `kubectl`/`helm`/`aws` que alteram algo, leitura de
    segredo, `gh pr merge`, `gh workflow run`, `gh api` com escrita, force push, push em
    `main`/`develop`, `--no-verify` e `Co-Authored-By`.
  - **Pede confirmação:** push, `gh pr create`/`comment`, `reset --hard`, `clean -f`,
    `restore`, `branch -D`, `stash drop`.
  - Uma negação vem com o motivo. Não tente outra forma do mesmo comando: explique ao usuário.
- **`.claude/hooks/guard-edit.py`**: nega edição em `.env`, tfstate, `vendor/`, `.terraform/`,
  nas cópias aninhadas dos repos e no worktree de outra sessão.
- **`.claude/hooks/after-edit.py`**: formata `.tf` com `terraform fmt`. Quando o arquivo toca um
  contrato (migration, JWT, rotas, SSM, segredos, `deploy/`, nomes antigos, domínio,
  `CONTRATOS.md`), lembra uma vez por sessão o que mais precisa mudar junto.
- **`.claude/hooks/verify-on-stop.py`** (ao fim de cada resposta): se o estado dos repos mudou
  desde o início da sessão e desde o último `verify` verde, roda `bin/ws verify --changed
  --fast`. Vermelho devolve o trabalho para você uma vez. Corrija, ou diga ao usuário o que está
  vermelho e por quê.
- **`.claude/hooks/repo-context.py`**: na primeira vez que a sessão lê, busca ou edita algo em
  `repos/<nome>/`, põe no contexto o `AGENTS.md` daquele repo, se ele existir.
- **`.claude/hooks/session-start.py`**: liga `repos/` nos worktrees e põe o `bin/ws context` no
  começo da sessão.
- **`githooks/`** (`commit-msg` e `pre-push`, instalados com `bin/ws hooks install`): valem para
  qualquer pessoa ou agente, no Git dos cinco repos.
  - `commit-msg`: Conventional Commits com escopo, sem acento no assunto, sem `Co-Authored-By`.
  - `pre-push`: bloqueia push em `main`/`develop` e roda `bin/ws verify --fast` do repo.

## Validação local

Não há PHP, Composer, kubectl nem tflint na máquina de desenvolvimento: tudo roda na imagem
`tooling/Dockerfile`, com as versões do CI. Sem conta AWS, o teto de verificação dos repos de
IaC é `fmt` + `validate` sem backend.

**Use `bin/ws verify`.** Ele roda, em paralelo e sem AWS, o mesmo que o `pr.yml` de cada repo:

- **fundação:** `terraform fmt` e `validate`, checagem de SQL proibido e as migrations aplicadas
  duas vezes num MySQL 8.0 com a conferência do seed;
- **cluster:** `fmt`, `validate` e `tflint` (não bloqueante, como no CI);
- **gateway:** composer, contrato do JWT, phpunit, phpstan, `fmt` e `validate`;
- **aplicação:** composer, php-cs-fixer, phpstan, phpunit e `kustomize build` dos dois overlays,
  e o build da imagem de produção com `--image`;
- **workspace:** shellcheck, Python, os testes de `tests/` e `check-contracts`.

O passo `workflows` (actionlint) confere a sintaxe dos workflows de todos os repos e bloqueia. Leva cerca de 30 s com tudo; `--changed` olha
só os repos com mudança, e `--fast` pula as migrations. O resultado vai para
`.ws/verify/latest.json` e os logs para `.ws/verify/logs/`.

Em comando encadeado com pipe, use `set -o pipefail`: sem ele, `cmd | head && próximo` segue
mesmo com `cmd` falhando.

**`bin/ws e2e`** sobe um MySQL, aplica as migrations da fundação pelo runner da aplicação, sobe
a aplicação e usa as Lambdas do gateway como classes para conferir o caminho inteiro: o token
da `auth-cpf` aceito pela aplicação, o `jwt-authorizer`, a matriz de autorização e o webhook.
Leva cerca de 30 s e usa a branch em disco de cada repo. Ele pega quebras entre repos que os
testes de cada repo não pegam.

Para um comando avulso, use `bin/ws exec <repo> <cmd>`, por exemplo
`bin/ws exec gateway vendor/bin/phpunit --filter Jwt`. Nos repos, o `make install/test/stan` do
gateway e o `scripts/php.sh` da aplicação também rodam em container. O `make test` da aplicação
usa o docker compose (`make up` antes) e o `make k8s-render` precisa de kubectl.

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

## Comandos

O que o usuário digita no Claude Code, e o que acontece. As skills ficam em `.claude/skills/`.

| Comando | Quando |
|---|---|
| `/status-geral` | "como está tudo": branch, sujeira, PRs e CI dos quatro repos, só o que pede ação |
| `/verificar [repo]` | "isso está ok?": o que o CI roda, local e sem AWS, só com as falhas |
| `/checar-contratos` | antes de PR de infra, depois de um pull, ou quando algo "funciona num repo e quebra no outro" |
| `/mudanca-cross-repo <descrição>` | qualquer mudança que toca mais de um repo; começa em plan mode |
| `/nova-migration <descrição>` | coluna, tabela ou índice novo |
| `/novo-endpoint <descrição>` | rota nova na API (e no gateway, se for pública) |
| `/mudar-jwt <descrição>` | claim, expiração ou validação do token |
| `/novo-parametro-ssm <descrição>` | expor, renomear ou remover um valor entre repos |
| `/novo-segredo <descrição>` | segredo ou chave de segredo nova |
| `/corrigir-ci [branch ou link]` | "o CI quebrou" |
| `/abrir-prs` | publicar uma mudança pronta: PRs draft, na ordem de apply, ligados entre si |
| `/revisar-pr <repo> <número>` | revisar um PR (ou os irmãos dele) antes de mergear |
| `/release` | preparar `develop` → `main` |
| `/atualizar-dependencias [repo]` | Composer, providers, actions, layers e EKS desatualizados |
| `/registrar-licao` | logo depois de corrigir o agente: a correção vira teste, checagem, hook ou regra |

Comandos do próprio Claude Code que encaixam no fluxo:

- **plan mode** (Shift+Tab): para mudança cross-repo;
- `/code-review` e `/security-review`: antes de `/abrir-prs`;
- `/simplify`: depois de uma mudança grande;
- `/loop 5m /status-geral`: para acompanhar o CI dos PRs enquanto a sessão está aberta;
- `/fewer-permission-prompts`: depois de umas semanas de uso, para liberar os comandos de
  leitura que mais pedem confirmação.

## Definição de Pronto

Uma mudança só está pronta, e só sai em PR, quando:

1. `bin/ws verify --changed` termina em `OK`. Use `--image` se mexeu em `Dockerfile` ou
   `docker/` da app. Se a mudança atravessa repos (JWT, rotas, autenticação, migrations,
   segredos), `bin/ws e2e` também termina sem falha.
2. `bin/check-contracts.py` não tem `erro`. `aviso` novo de documento pede adendo no
   `CONTRATOS.md`.
3. O subagente `guardiao-de-contratos` não tem achado grave sobre o diff (`bin/ws diff --patch`).
4. Se o contrato mudou, o `CONTRATOS.md` mudou no mesmo conjunto de PRs, como adendo.
5. O usuário recebeu um resumo:
   - o que mudou em cada repo e em que ordem fazer o merge;
   - o que foi verificado aqui;
   - o que só o CI consegue verificar (`terraform plan`, deploy, smoke).

Os PRs saem com `/abrir-prs`, e só quando o usuário pedir.

## Como evoluir este harness

- **Correção do usuário vira prevenção** (`/registrar-licao`), nesta ordem de preferência: teste
  > checagem em `tools/contratos/` > hook > `AGENTS.md` do repo > este `AGENTS.md` > memória.
  Cada registro ganha uma linha em `docs/LICOES.md`.
- **Mudou `AGENTS.md`, skill, hook ou checker?** Rode antes e depois as tarefas-canário afetadas
  (`bin/ws eval`, `evals/README.md`). Se a nota piorar, a mudança volta.
- **Tudo em `bin/`, `tools/`, `.claude/hooks/` e `githooks/` tem teste em `tests/`**, rodado
  pelo `bin/ws verify --repo workspace`. O plano e o histórico das decisões estão em
  `docs/PLANO-HARNESS-IA.md`.

## Regras para agentes

1. **Nunca** rode `terraform apply`/`destroy`, `kubectl apply`/`delete` nem dispare
   `workflow_dispatch` de deploy a partir daqui. Infra só muda pelo CI de cada repo.
2. Mudança que atravessa repositórios segue a ordem de apply: o **produtor** do contrato muda e é
   mergeado antes do **consumidor**. Remoção é o contrário: primeiro o consumidor deixa de ler,
   depois o produtor deixa de publicar.
3. Uma branch com o **mesmo nome** em cada repo afetado (`bin/ws branch`, ou `bin/ws isolate`
   numa sessão em worktree), e PRs que se referenciam (`bin/ws prs --branch`).
4. Antes de dar uma mudança por pronta, rode `bin/ws verify --changed`. Ele inclui o
   `bin/check-contracts.py` e os testes de cada repo tocado, e precisa terminar em `OK`.
5. Não commite nada dentro de `repos/` a partir de comandos do workspace sem conferir em qual repo
   e em qual branch está — cada um é um Git separado.
6. Não leia nem imprima `.env` nem saída de `get-secret-value`. Os `envs/*.tfvars` são
   configuração versionada, sem segredo, e podem ser lidos.
7. Na AWS, as sessões do Claude Code usam o perfil `oficina-readonly` (`AWS_PROFILE` no
   `.claude/settings.json`; o role vem de `bootstrap/aws/`). Ele lê a conta, mas não lê segredo,
   `kms:Decrypt` nem o bucket de state. Se precisar de mais, peça ao usuário; não troque de
   perfil.
