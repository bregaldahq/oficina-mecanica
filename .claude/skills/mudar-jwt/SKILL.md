---
name: mudar-jwt
description: Muda o token JWT da Oficina (claim nova, expiração, emissor, algoritmo) nos dois lados ao mesmo tempo — JwtProvider da Lambda e da aplicação, os dois testes de contrato com o mesmo token literal e o contract-token.md. Use para qualquer pedido que mexa no formato, nas claims ou na validação do token.
---

# Mudar o JWT

O token é emitido pela Lambda `auth-cpf` (cliente) e pela aplicação (admin) e validado pelo
`jwt-authorizer` **e** pela aplicação. Header, ordem das claims e base64url precisam sair byte a
byte iguais (seção 4 do `CONTRATOS.md`).

## 1. Antes de editar (plan mode)

- Leia a seção 4 do `CONTRATOS.md` e o ADR-002.
- Pergunte, se o pedido não disser:
  - **Os tokens já emitidos continuam válidos?** Claim nova obrigatória, emissor novo ou
    algoritmo novo invalidam a sessão de quem está logado, por até `JWT_EXPIRATION` (3600 s).
  - **A ordem de deploy importa?** Se o validador passa a exigir algo, ele sobe depois do
    emissor.
- Mostre o plano e espere o ok.

## 2. Os dois lados, no mesmo conjunto de PRs

| Onde | Arquivo |
|---|---|
| Lambda | `repos/oficina-gateway-auth/src/Security/JwtProvider.php` |
| Aplicação | `repos/oficina-api/src/Infrastructure/Security/JwtProvider.php` |
| Teste de contrato da Lambda | `repos/oficina-gateway-auth/tests/Contract/JwtContractTest.php` |
| Teste de contrato da aplicação | `repos/oficina-api/tests/Unit/Infrastructure/Security/JwtContractTest.php` |
| Token documentado | `repos/oficina-api/docs/fase-3/contract-token.md` |

- Mude a montagem do token igual nos dois `JwtProvider`. Os arquivos não são idênticos
  (namespace, comentários), mas `generate()` e `base64urlEncode()` precisam ser equivalentes.
- Gere o token novo **uma vez**, com a entrada fixa do teste:
  `bin/ws exec gateway vendor/bin/phpunit --testsuite contract`. O teste falha e mostra o token
  obtido. Ponha o **mesmo** literal nos dois testes e no `contract-token.md`.
- Nunca atualize o literal de um lado só para o teste passar.
- Seção 4 do `CONTRATOS.md`: tabela de claims e ordem de montagem, como adendo.

## 3. Verificar

`bin/check-contracts.py --only jwt` (`JWT-1`: o mesmo literal nos três lugares; `JWT-2`:
montagem equivalente), `bin/ws verify --repo gateway --repo api` e `bin/ws e2e`, que confere o
token da Lambda sendo aceito pela aplicação de verdade. Termine na Definição de
Pronto do `AGENTS.md`, com a ordem de deploy no resumo.
