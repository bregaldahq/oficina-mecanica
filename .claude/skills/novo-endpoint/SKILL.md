---
name: novo-endpoint
description: Cria uma rota nova na API da Oficina — use case, DTO, controller, rota com a matriz de autorização em public/index.php, swagger.yaml e testes; se a rota for pública, também a rota dedicada no API Gateway e o CONTRATOS.md. Use para "endpoint novo", "rota nova", "expor X na API".
---

# Novo endpoint

## 1. Decidir o acesso (pergunte se não estiver claro)

| Acesso | Em `public/index.php` | Gateway (`oficina-gateway-auth`) |
|---|---|---|
| `admin` (padrão) | `->requireRole('admin')` | nada: passa pelo `ANY /api/{proxy+}` com authorizer |
| `customer` ou `admin` | `->requireRole('customer', 'admin')`; o customer só vê o que é dele | nada |
| público | `requireAuth: false` | **rota dedicada sem authorizer** em `apigateway.tf`. Sem `Authorization`, o gateway devolve 401 antes do authorizer |

Rota pública é mudança cross-repo (**gateway e app no mesmo conjunto de PRs**, seção 5 do
`CONTRATOS.md`): use também a skill `mudanca-cross-repo`.

## 2. A aplicação (`repos/oficina-api/`)

Siga uma rota parecida que já existe (por exemplo `GET /api/service-orders/me`):

- **regra de negócio** em `src/Domain/`; nada de `setStatus` (ADR-003);
- **use case** em `src/Application/UseCase/<Contexto>/`, um por ação, com DTO de entrada em
  `src/Application/DTO/<Contexto>/`;
- **controller** em `src/Presentation/Controller/`, validando a entrada com o `RequestValidator`;
- **rota** em `public/index.php`, junto das do mesmo recurso, com a autorização da tabela acima;
- **`swagger.yaml`**: o caminho sem o `/api` (os `servers` já o incluem); rota pública leva
  `security: []`;
- **testes** em `tests/Unit/Application/UseCase/` e `tests/Unit/Presentation/` e, se tocar o
  banco, em `tests/Integration/`.

## 3. Se for pública: o gateway (`repos/oficina-gateway-auth/apigateway.tf`)

- Uma `aws_apigatewayv2_route` com `authorization_type = "NONE"` e
  `target = "integrations/${aws_apigatewayv2_integration.app_proxy.id}"`, como as de
  `GET /api/health`.
- Seção 5 do `CONTRATOS.md`: a rota entra na tabela do API Gateway e na matriz da aplicação,
  como adendo.

## 4. Verificar

`bin/ws verify --changed` e `bin/check-contracts.py --only rotas` (`ROTA-1` a `ROTA-4`). Para
rota pública ou mudança de autorização, `bin/ws e2e` também. Termine
na Definição de Pronto do `AGENTS.md`.
