# Plano: Fase 4 — microsserviços, Saga e CI/CD por serviço

> Escrito em 2026-11-10 a partir do enunciado (`SOAT - Fase 4 - Tech challenge.pdf`) e do estado
> de `develop` nos quatro repos. As escolhas marcadas **(decisão N)** estão na seção 9 e foram
> **aceitas em 2026-11-10**, com a diretriz de menor custo possível (seção 10). O desenho
> detalhado e normativo está em `repos/oficina-api/docs/fase-4/`; este arquivo é o plano de
> execução e o registro do andamento.

## Andamento

| Data | Etapa | O que foi feito |
|---|---|---|
| 2026-11-10 | 0 | Decisões 1 a 7 aceitas. `guard-edit.py` corrigido (negava o worktree da própria sessão no app desktop), com dois testes. Pendente com você: prazo de entrega, PRs antigos, conta AWS, contas do Mercado Pago (teste) e do SonarCloud. |
| 2026-11-10 | 1 | `docs/fase-4/` no `oficina-api` (branch `chore/fase-4-desenho`): `CONTRATOS.md` da fase, ADRs 011 a 017, diagramas de arquitetura e da saga. Cobertura medida: **59,2%** das linhas de `src/` (862 de 1456); `Domain` e `Application` acima de 95%, o que falta está em controllers e repositórios PDO. |

## 1. O que o enunciado exige

| # | Requisito | Onde o sistema está hoje |
|---|---|---|
| R1 | No mínimo 3 microsserviços, cada um com repositório, infraestrutura e banco próprios | 1 aplicação (`oficina-api`), 1 banco (RDS MySQL da fundação) |
| R2 | Pelo menos um banco SQL e um NoSQL | só MySQL |
| R3 | REST síncrono quando necessário e mensageria para eventos | só REST; a ADR-006 deixou mensageria fora de escopo "até haver caso de uso" |
| R4 | Nenhum serviço acessa o banco de outro | a Lambda `auth-cpf` lê `customers` direto no RDS |
| R5 | Saga com rollback e compensação em qualquer etapa; escolha justificada no README | transações locais no repositório PDO (ADR-004) |
| R6 | Pagamento integrado ao Mercado Pago | não existe pagamento |
| R7 | Testes unitários em todos, 1 fluxo completo em BDD, cobertura ≥ 80% por serviço | PHPUnit sem medição de cobertura (`coverage: none` no `pr.yml`); sem BDD |
| R8 | SonarQube ou similar no CI | php-cs-fixer + PHPStan |
| R9 | Pipeline independente por serviço: build, testes, qualidade, deploy em Kubernetes | já é assim no `oficina-api`; falta replicar |
| R10 | `main` protegida, com PR e checagens obrigatórias | já existe nos 4 repos (`bin/ws doctor` confere) |
| R11 | Observabilidade da Fase 3, com rastreamento dos fluxos distribuídos | New Relic APM + dashboards; trace só HTTP |
| R12 | Por repo: Dockerfile, manifestos, pipeline, evidência de cobertura, doc de arquitetura, Swagger/Postman | existe no `oficina-api` |
| R13 | Vídeo ≤ 15 min e PDF de entrega | — |

## 2. Arquitetura alvo

### 2.1 Os três serviços

| Serviço | Repositório | Dono de | Banco |
|---|---|---|---|
| **OS** (atendimento) | `oficina-api` — o repo atual vira o OS Service **(decisão 1)** | clientes, veículos, ordem de serviço, histórico de status, login admin, **orquestrador da saga** | MySQL, o RDS que já existe na fundação |
| **Faturamento** (orçamento e pagamento) | `oficina-faturamento` (novo) | catálogo de serviços, peças e estoque, orçamento, aprovação do cliente, pagamento Mercado Pago, estorno | SQL próprio **(decisão 3)** |
| **Execução** (diagnóstico e reparo) | `oficina-execucao` (novo) | fila de trabalho da oficina, diagnóstico (itens levantados), reparo, linha do tempo da execução | DynamoDB (NoSQL) |

Por que esse corte:

- Segue as quatro áreas do enunciado (atendimento, diagnóstico, execução, cobrança) e o exemplo
  sugerido, o que facilita a justificativa no PDF.
- **Catálogo e estoque vão para o Faturamento**: é ele quem precifica o orçamento, e reservar
  estoque na mesma transação SQL do orçamento dá uma compensação real para a saga (liberar a
  reserva).
- **Execução em DynamoDB**: a tarefa de oficina é um documento (itens, mecânico, eventos da
  linha do tempo) lido por chave e por status, sem junção. Atende o R2 sem pod nem instância
  para manter, e custa zero parado.
- A OS deixa de guardar itens e preços: guarda status, histórico, `budget_id` e o total, que
  chegam por evento.

Os três continuam em PHP 8.2 sem framework (ADR-001): o roteador, o `JwtProvider`, o logger
JSON e o Dockerfile com o agente do New Relic são copiados na criação de cada repo, sem
biblioteca compartilhada. Uma lib comum criaria um quinto ciclo de release e acoplamento de
versão; a divergência do que importa (JWT, envelope das mensagens) fica travada por teste de
contrato, como já é hoje entre o gateway e a aplicação.

### 2.2 Comunicação

```
                        API Gateway (oficina-gateway-auth)
   /auth/cpf ─► Lambda auth-cpf ──REST interno──► OS            (deixa de ler o RDS: R4)
   /api/**  (o que não casar com os dois abaixo) ► NLB :80 ─► OS          ─► MySQL (RDS fundação)
   /api/billing/** ──────────────────────────────► NLB :81 ─► Faturamento ─► MySQL próprio ─► Mercado Pago
   /api/execution/** ────────────────────────────► NLB :82 ─► Execução    ─► DynamoDB

   OS ◄──────────────── SNS oficina-<env>-mensagens ────────────────► Faturamento, Execução
        (uma fila SQS + DLQ por serviço, assinatura filtrada por tipo de mensagem)
```

- **Mensageria: SNS + SQS (decisão 2).** Um tópico, uma fila com DLQ por serviço, filtro por
  atributo `type`. Sem broker para operar nem pods a mais (o cluster já esteve no limite de
  pods por node), em Terraform, com IRSA. Local e no e2e: LocalStack.
- **REST síncrono só em dois pontos**: cliente → serviço pelo gateway, e `auth-cpf` → OS
  (`GET /internal/customers/by-document/{cpf}`), porque o login precisa de resposta imediata.
  Entre os três serviços não há chamada síncrona: o que um precisa do outro vai no payload da
  mensagem (por exemplo, o email do cliente para o envio do orçamento).
- **Roteamento**: o NLB é L4, então cada serviço ganha um listener e um target group no repo do
  cluster (que já é dono do NLB), publicados em SSM; o gateway troca o `ANY /api/{proxy+}` por
  uma rota por prefixo. `/internal/*` não é roteado pelo gateway e exige um token de serviço.
- **Envelope das mensagens**: `id`, `type`, `saga_id`, `os_id`, `occurred_at`, `correlation_id`,
  cabeçalhos de trace e `payload`. O catálogo (tipo, produtor, consumidores, schema) entra no
  documento de contratos e vira checagem do `check-contracts`.
- **Entrega**: SQS padrão é "pelo menos uma vez". Cada serviço tem outbox (mensagem gravada na
  mesma transação do estado e publicada pelo worker) e inbox (id já processado é ignorado).
  Cada serviço roda dois Deployments da mesma imagem: `api` (nginx + php-fpm) e `worker`
  (consumidor em CLI).

### 2.3 Saga orquestrada (decisão 4)

O orquestrador fica no OS Service: a OS é o agregado cujo status o fluxo altera, e o estado da
saga (`sagas`: passo atual, prazo, histórico) fica no MySQL ao lado dela. Orquestração e não
coreografia porque o fluxo é linear e longo, com espera humana (aprovação, pagamento) e prazos;
com um orquestrador a ordem, os prazos e as compensações ficam num lugar só, o que é testável
em BDD e demonstrável no vídeo. O custo é o OS Service conhecer os comandos dos outros dois.

| Passo | Comando do orquestrador | Sucesso → status da OS | Falha → compensação |
|---|---|---|---|
| 1. Abrir OS | (local) | `RECEIVED` | — |
| 2. Diagnóstico | `execution.request-diagnosis` | `diagnosis.started` → `DIAGNOSIS`; `diagnosis.completed` (itens) | `diagnosis.failed` → OS `CANCELLED` |
| 3. Orçamento | `billing.generate-budget` (reserva estoque) | `budget.generated` → `AWAITING_APPROVAL` | `budget.failed` (sem estoque, item inexistente) → cancela a tarefa na Execução → `CANCELLED` |
| 4. Aprovação | (espera, com prazo) | `budget.approved` | `budget.rejected` ou prazo → cancela o orçamento (libera estoque) e a tarefa → `REJECTED` |
| 5. Pagamento | `billing.charge` (cria a cobrança no Mercado Pago) | `payment.confirmed` (webhook) | `payment.failed` ou prazo → cancela o orçamento e a tarefa → `CANCELLED` |
| 6. Reparo | `execution.start-repair` | `EXECUTING`; `repair.completed` → `FINISHED` | `repair.failed` → **estorno** no Mercado Pago + libera estoque → `CANCELLED` |

- Status novos na OS: `AWAITING_PAYMENT` e `CANCELLED`, com métodos nomeados (ADR-003).
  `DELIVERED` continua manual e fora da saga.
- O pagamento vem **antes** do reparo **(decisão 5)**. É o que dá à saga uma compensação de
  verdade para mostrar: reparo falha → estorno.
- Prazos de aprovação e de pagamento configuráveis por ambiente (curtos em hml, para o vídeo).
- Toda compensação é idempotente e repetida até confirmar; o que esgota as tentativas vai para
  a DLQ, com alerta.

### 2.4 Mercado Pago

- Porta `PaymentGateway` no domínio do Faturamento, com dois adaptadores: Mercado Pago e um
  falso, para testes, BDD e e2e.
- Checkout Pro **(decisão 6)**: preferência com `external_reference` = id do orçamento e
  `notification_url` apontando para o gateway. Dá para pagar com cartão de teste no vídeo.
- Webhook `POST /api/billing/payments/webhook/mercadopago`: rota pública dedicada no gateway, validada
  pela assinatura `x-signature`; o serviço consulta o pagamento na API antes de confirmar
  (nunca confia no corpo do webhook). Chamadas com `X-Idempotency-Key`.
- Os pods saem para a internet pelos nodes em subnet pública (ADR-010), então não precisa NAT.
- Segredo `oficina/<env>/faturamento/mercadopago` (`MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`): o Terraform cria
  o segredo com valor provisório e `ignore_changes`; **você** grava o valor real. O agente não vê.
- Os detalhes da API (endpoint de estorno, formato da assinatura) serão conferidos na
  documentação oficial na Etapa 4, não de memória.

### 2.5 Infraestrutura por serviço

Cada repo de serviço ganha `infra/` (Terraform, mesmo padrão do gateway, que já junta código e
Terraform): ECR, role IRSA, fila + DLQ + assinatura, banco próprio, segredo próprio, parâmetros
SSM. O acoplamento continua só por SSM (ADR-008).

- **Fundação**: ganha o tópico SNS e seus parâmetros. Continua dona do RDS do OS e das
  migrations dele (ADR-009 vale para o OS; os outros dois têm migrations no próprio repo).
- **Cluster**: listeners e target groups novos, RBAC de deploy para os serviços novos, ARN do
  OIDC em SSM para os roles IRSA. Capacidade: 3 serviços × (api + worker) não cabem com folga
  em 2 × t3.medium (17 pods cada, boa parte ocupada pelos add-ons); ligar *prefix delegation*
  no vpc-cni ou subir para 3 nodes.
- **Ordem de apply**: fundação → cluster → gateway → `infra/` de cada serviço → deploy de cada
  serviço.
- **Conta** (`bootstrap/aws/`, aplicado por você): roles de CI dos dois repos novos e permissão
  de Terraform para o role do `oficina-api`.

## 3. Mudanças de contrato

Tudo abaixo entra num `docs/fase-4/CONTRATOS.md` (no `oficina-api`, que continua sendo a casa
dos documentos normativos), como adendos ao da Fase 3, mais as ADRs novas.

| Contrato | Mudança |
|---|---|
| Rotas | Um prefixo por serviço: `/api/billing/**` (Faturamento) e `/api/execution/**` (Execução); o resto de `/api/**` é do OS. `/api/parts*` e `/api/service-items*` passam para `/api/billing/`. `POST /api/service-orders/{id}/approval` vira `POST /api/billing/budgets/{id}/approval`. `POST /api/service-orders/{id}/items` e o `PATCH .../status` manual saem: quem move a OS é a saga. Rotas novas de orçamento, pagamento e execução. |
| JWT | mesmo token e mesmo segredo nos três serviços; o teste de contrato com o token literal é copiado para os dois repos novos. Sem claim nova. |
| Banco | `service_catalog`, `parts_inventory`, `service_order_services` e `service_order_parts` saem do banco do OS (migration de remoção só **depois** de o OS parar de ler). Tabelas novas no OS: `sagas`, `outbox`, `inbox`. Dados: só seed de demonstração, sem migração de dados. |
| `auth-cpf` | deixa de usar o segredo `oficina/<env>/db` e o SG `db-client`; passa a ler o endpoint interno do OS em SSM. |
| SSM | novos: tópico SNS, listeners/target groups por serviço, OIDC do cluster, URL e ARN das filas. |
| Segredos | novos: `oficina/<env>/faturamento/db`, `oficina/<env>/faturamento/mercadopago` e a chave `INTERNAL_TOKEN` em `oficina/<env>/auth`. |
| Mensagens | contrato novo: catálogo de tipos, envelope e schemas. |
| ADRs | 011 divisão em microsserviços; 012 saga orquestrada; 013 SNS+SQS (substitui a decisão de escopo da ADR-006); 014 banco por serviço (ajusta a 009); 015 Mercado Pago; 016 seis repositórios (ajusta a 008); 017 outbox/inbox e idempotência. |

## 4. Qualidade e CI/CD (igual nos três serviços)

- **Cobertura**: PHPUnit com pcov; o `pr.yml` falha abaixo de 80% de linhas. O `oficina-api`
  nunca mediu cobertura: medir é a primeira tarefa da Etapa 1, porque define quanto teste falta.
- **BDD**: Behat com features em português. No OS, o fluxo completo da saga (caminho feliz e as
  compensações de orçamento rejeitado, pagamento recusado e reparo que falha) contra um
  barramento em memória. Nos outros dois, ao menos uma feature do fluxo próprio.
- **Qualidade**: SonarCloud (gratuito para repo público) no `pr.yml`, com quality gate
  obrigatório **(decisão 7)**. php-cs-fixer e PHPStan continuam.
- **Pipeline**: `pr.yml` (estilo, PHPStan, PHPUnit com cobertura, Behat, Sonar, build da imagem,
  `kustomize build`, `terraform plan` do `infra/`) e `deploy.yml` (OIDC → `infra/` apply → push
  no ECR → migration → `kubectl apply -k` → smoke), por repo, sem depender dos outros.
- **Evidências no README** de cada repo: badge do Sonar e da cobertura, link do último run,
  diagrama do serviço, justificativa da saga (no OS), Swagger próprio.

## 5. Observabilidade

- `NEW_RELIC_APP_NAME` por serviço; o worker abre uma transação de background por mensagem.
- O trace atravessa a fila: quem publica grava os cabeçalhos de trace distribuído no envelope,
  quem consome os aceita. `correlation_id`, `saga_id` e `os_id` em todo log JSON.
- Eventos customizados `SagaStarted`, `SagaStepCompleted`, `SagaCompensated`, `SagaFailed`.
- Dashboard novo "Saga" (funil por passo, tempo por passo, compensações por motivo) e alertas:
  mensagem na DLQ, saga parada além do prazo, taxa de compensação, erro no webhook de pagamento.

## 6. O harness acompanha

O workspace conhece quatro repos; precisa conhecer seis antes de o agente trabalhar neles.

- `bin/ws`, `verify`, `doctor`, `statusline`, `Makefile` e os hooks: dois repos novos
  (`faturamento`, `execucao`), com os passos de cobertura, Behat e `infra/`.
- `tooling/Dockerfile`: pcov e Behat.
- `tools/contratos/`: família nova `mensagens` (todo tipo publicado tem consumidor e está no
  catálogo; envelope igual nos três), rotas por prefixo no gateway, JWT nos três serviços e a
  regra "nenhum serviço referencia o banco de outro".
- `bin/ws e2e`: LocalStack (SNS, SQS, DynamoDB), os três serviços e seus workers, Mercado Pago
  falso; percorre a saga feliz e as três compensações.
- `AGENTS.md` de cada repo novo, o mapa e a tabela "Onde mexer para…" do workspace, a skill
  `/novo-evento` e as tarefas-canário afetadas (antes e depois, como manda o `AGENTS.md`).
- `guard-edit.py`: recusava edição no worktree da própria sessão do app desktop (comparava com
  `CLAUDE_PROJECT_DIR`, que aponta para o checkout principal). **Corrigido em 2026-11-10.**

## 7. Etapas

Cada etapa termina com `bin/ws verify`, `check-contracts` e `e2e` verdes, uma revisão completa
do que foi feito e os PRs na ordem de apply. A próxima só começa depois disso. Em todas, o
sistema continua funcionando: o `oficina-api` só perde uma responsabilidade depois que o
serviço novo a assumiu (produtor antes do consumidor; remoção na ordem inversa).

| Etapa | Entrega | Repos | Esforço |
|---|---|---|---|
| **0. Base** | Decisões da seção 9 fechadas. PRs abertos antigos resolvidos (fundação #9 #7 #6, cluster #13 #11 #10, gateway #10, api #23 #20). `develop` verde: o CI do cluster e o deploy da api estão vermelhos (a conta AWS foi derrubada; reerguer com `bootstrap/aws/` é com você). Contas: Mercado Pago de teste e SonarCloud. | todos | 1 dia |
| **1. Desenho e medição** | `docs/fase-4/`: ADRs 011–017, `CONTRATOS.md` da Fase 4 com o catálogo de mensagens e as rotas, diagrama da arquitetura e da saga. Cobertura atual do `oficina-api` medida. | api | 2 dias |
| **2. Fundação da mensageria e do harness** | SNS na fundação; listeners, target groups, RBAC e OIDC no cluster; roles novos no `bootstrap/aws/`; os dois repos criados a partir do esqueleto (roteador, JWT, logger, Dockerfile, kustomize, `infra/`, `pr.yml`, `deploy.yml`, proteção de branch) respondendo `/health`; harness com seis repos e LocalStack no e2e. | fundação, cluster, workspace, 2 novos | 4 dias |
| **3. Execução** | Serviço completo em DynamoDB: fila de tarefas, diagnóstico, reparo, API, worker, outbox/inbox, testes ≥ 80%, Behat, Swagger. Ainda sem ninguém chamando. | execucao | 4 dias |
| **4. Faturamento** | Catálogo e estoque (migrations e seed próprios), orçamento com reserva, aprovação, Mercado Pago (cobrança, webhook, estorno) com adaptador falso, API, worker, testes ≥ 80%, Behat, Swagger. | faturamento | 6 dias |
| **5. OS e saga** | Orquestrador, `sagas`/`outbox`/`inbox`, status novos, worker, prazos, compensações; BDD do fluxo completo; `/internal/customers/by-document`. O OS para de usar catálogo, itens e mudança manual de status. | fundação (migration), api | 6 dias |
| **6. Borda** | Rotas por prefixo e webhook do Mercado Pago no gateway; `auth-cpf` chamando o OS em vez do RDS; migration que remove as tabelas movidas; e2e com a saga e as compensações. | gateway, fundação, api | 3 dias |
| **7. Qualidade e observabilidade** | Sonar com gate nos três; cobertura ≥ 80% conferida no CI; trace pela fila; dashboard e alertas da saga; READMEs com evidências. | 3 serviços | 3 dias |
| **8. Entrega** | Deploy em hml pelo CI, roteiro e gravação do vídeo (fluxo feliz, uma compensação ao vivo, um deploy com testes, trace no New Relic), PDF, release `develop` → `main`. | todos | 3 dias |

Total: cerca de 32 dias de trabalho de uma pessoa com o agente. As etapas 3 e 4 não dependem
uma da outra e podem correr em sessões paralelas (`bin/ws isolate`).

## 8. Riscos

| Risco | Como o plano trata |
|---|---|
| Cobertura de 80% no `oficina-api` estar longe | medir na Etapa 1; controllers e repositórios PDO são os candidatos a descoberto |
| Saga com estados presos (mensagem perdida, worker caído) | outbox/inbox, prazo em todo passo de espera, DLQ com alerta, e2e com falha injetada |
| Webhook do Mercado Pago só funciona com URL pública | usar o hml real para o vídeo; adaptador falso em teste e e2e |
| Limite de pods no cluster | prefix delegation ou terceiro node, na Etapa 2 |
| Custo: segundo RDS, mais pods | hml efêmero (sobe para testar e gravar, depois `destroy`); réplica única em hml |
| `auth-cpf` passa a depender do cluster estar no ar | aceito e registrado em ADR; é o preço do R4 |
| Agente do New Relic em processo CLI de longa duração | validar no esqueleto da Etapa 2, antes de três serviços dependerem disso |
| Três cópias do roteador/JWT/envelope divergirem | testes de contrato e a família `mensagens` do `check-contracts` |

## 9. Decisões

As decisões 1 a 7 foram aceitas em 2026-11-10 como recomendadas. A 8 (prazo) continua aberta.

| # | Decisão | Recomendo | Alternativa |
|---|---|---|---|
| 1 | O que vira o OS Service | manter o repo `oficina-api` com esse nome (state, roles, ECR e PRs já apontam para ele; os repos acabaram de ser renomeados) | renomear para `oficina-os`, mais claro para a banca |
| 2 | Mensageria | SNS + SQS | RabbitMQ no cluster: mais didático no vídeo (painel), mas é um pod com estado para operar |
| 3 | Banco do Faturamento | instância RDS MySQL própria (`db.t4g.micro`), criada pelo `infra/` do serviço: isolamento sem ressalva | banco lógico e usuário separados na instância da fundação: sem custo, mas "banco próprio" fica discutível e exige provisionar usuário por dentro da VPC |
| 4 | Saga | orquestrada, com o orquestrador no OS Service | coreografada: menos acoplamento, mas fluxo e compensações espalhados em três repos |
| 5 | Momento do pagamento | depois da aprovação e antes do reparo | na entrega do veículo: mais fiel a uma oficina, mas a saga perde a compensação por estorno |
| 6 | Produto do Mercado Pago | Checkout Pro (link de pagamento) | Pix pela API de pagamentos: mais simples, porém difícil de "pagar" no sandbox |
| 7 | Qualidade | SonarCloud | SonarQube próprio: precisa de servidor |
| 8 | Prazo de entrega | não está no PDF; diga a data para eu ajustar o corte das etapas | — |

Se o prazo apertar, o que sai primeiro, nesta ordem: a compensação por prazo expirado (ficam
as por evento de falha), o dashboard da saga (ficam os eventos e o trace), e a remoção das
tabelas movidas do banco do OS (ficam sem uso, registradas como pendência).

## 10. Custo

Diretriz: o menor custo possível, sem abrir mão dos requisitos.

- **Desenvolver e verificar tudo localmente.** LocalStack (SNS, SQS, DynamoDB), MySQL em
  container e o adaptador falso do Mercado Pago cobrem as Etapas 2 a 7 sem a conta AWS.
- **AWS só no fim, e só em `hml`.** O ambiente sobe na Etapa 8 para o teste de integração e a
  gravação do vídeo, e é destruído em seguida. O que custa de verdade já existia na Fase 3: o
  control plane do EKS (US$ 0,10 por hora) e os nodes.
- **O que a Fase 4 acrescenta enquanto o ambiente está de pé:** a segunda instância RDS
  (`db.t4g.micro`, single-AZ, sem backup, cerca de US$ 0,02 por hora) e centavos de SNS, SQS e
  DynamoDB. Os listeners novos usam o NLB que já existe.
- **Sem terceiro node:** *prefix delegation* no vpc-cni e uma réplica por Deployment em `hml`.
- **Gratuitos:** SonarCloud (repos públicos), sandbox do Mercado Pago, GitHub Actions em repo
  público.
- Um risco de custo: esquecer o ambiente ligado. O roteiro da Etapa 8 termina com o `destroy`
  (disparado por você) e a conferência de que nada ficou de pé.

