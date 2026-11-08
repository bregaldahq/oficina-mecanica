---
name: mudanca-cross-repo
description: Planeja e executa uma mudança que toca mais de um repositório da Oficina (novo parâmetro SSM, segredo, claim do JWT, rota, coluna de banco, variável de ambiente). Use sempre que a mudança pedida não couber em um repo só.
---

# Mudança cross-repo

## 1. Entender o contrato atingido

Leia `repos/oficina-api/docs/fase-3/CONTRATOS.md` e identifique a seção
afetada (propriedade de recursos, SSM, segredos, JWT, rotas, banco, observabilidade, imagem, CI).
Se a mudança contradiz uma ADR em `docs/fase-3/adr/`, pare e pergunte antes de seguir.

## 2. Montar o plano

Liste, na ordem de apply (**fundação → cluster → gateway → api**), cada repo tocado e o que muda nele.
Regras:

- Quem **publica** muda antes de quem **consome**.
- Remoção é ao contrário: o consumidor para de ler primeiro, o produtor para de publicar depois.
- Renomear = adicionar o novo, migrar consumidores, remover o antigo (três etapas, não uma).
- Migration nova vai no repo de banco; quem executa é o Job da aplicação. Ela precisa ser
  idempotente, sem `DELIMITER`, sem `CREATE DATABASE`/`USE`.
- Mudou o JWT? O teste de contrato da Lambda **e** o da aplicação mudam juntos, com o mesmo
  token literal, e `docs/fase-3/contract-token.md` é atualizado.
- Se o contrato muda, `CONTRATOS.md` muda no mesmo conjunto de PRs (como adendo, seguindo o
  estilo dos adendos existentes).

Mostre o plano e espere confirmação antes de editar.

## 3. Executar

- Em cada repo afetado: `git -C repos/<repo> switch develop && git -C repos/<repo> pull --ff-only`,
  depois crie a **mesma** branch (`feat/<slug>` ou `fix/<slug>`) em todos.
- Faça a mudança e rode a validação local do repo (tabela em `AGENTS.md`).
- Rode `bin/check-contracts.py`.
- Peça ao subagente `guardiao-de-contratos` uma revisão do diff conjunto.

## 4. PRs

Commits e PRs seguem as convenções de `AGENTS.md` (português, Conventional Commits, sem
coautoria de ferramenta). Abra os PRs para `develop` **só depois de o usuário pedir**. Na
descrição de cada PR, inclua a ordem de merge e os links dos PRs irmãos.
