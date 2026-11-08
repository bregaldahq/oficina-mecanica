---
name: nova-migration
description: Cria uma coluna, tabela ou índice no banco da Oficina do jeito certo — migration idempotente no oficina-infra-fundacao e as mudanças correspondentes na aplicação (entidade, repositório PDO, schema SQLite dos testes de integração). Use para "nova coluna", "nova tabela", "adicionar campo X em Y", "índice em Z".
---

# Nova migration

Mudança cross-repo: **fundação → aplicação**, nessa ordem de merge. Siga também a skill
`mudanca-cross-repo` para branches e PRs.

## 1. Planejar (plan mode)

Leia `repos/oficina-infra-fundacao/docs/MODELO-DE-DADOS.md` e a migration mais recente. Liste:

- o SQL;
- a entidade e o repositório PDO afetados em `repos/oficina-api/src/`;
- os testes de integração que criam a tabela (`grep -rl "CREATE TABLE <tabela>"
  repos/oficina-api/tests/Integration`).

Mostre o plano e espere o ok.

## 2. A migration (`repos/oficina-infra-fundacao/migrations/`)

- Nome: o próximo número livre, no formato `NNN_<slug_em_snake_case>.sql`. Seed só com sufixo
  `_demo`.
- Idempotente. O `pr.yml` aplica tudo duas vezes. Para `ADD COLUMN`, `ADD INDEX` e o que mais
  não aceita `IF NOT EXISTS` no MySQL 8.0, use o padrão do `002_fase3_ajustes.sql`:

  ```sql
  SET @stmt = (SELECT IF(COUNT(*) = 0,
      'ALTER TABLE <tabela> ADD COLUMN <coluna> <tipo> NULL AFTER <outra>',
      'SELECT 1')
    FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = '<tabela>' AND column_name = '<coluna>');
  PREPARE s FROM @stmt;
  EXECUTE s;
  DEALLOCATE PREPARE s;
  ```

  Para tabela nova, use `CREATE TABLE IF NOT EXISTS`.
- Proibido: `DELIMITER`, `CREATE DATABASE`, `USE`. Um statement por `;` no fim da linha.
- Atualize o `docs/MODELO-DE-DADOS.md`.

## 3. A aplicação (`repos/oficina-api/`)

- Entidade ou agregado em `src/Domain/`, com hidratação por `reconstitute()` (ADR-005).
- Repositório PDO em `src/Infrastructure/Repository/`, com a transação dentro dele (ADR-004).
- **Schema SQLite dos testes de integração:** os `CREATE TABLE` em `tests/Integration/*.php` são
  escritos à mão, sem `ENUM` nem `CHECK`. A coluna nova entra ali, senão os testes passam e a
  produção quebra.
- Se a coluna aparece na API: DTO, controller e `swagger.yaml`.

## 4. Verificar

`bin/ws verify --repo fundacao` (as migrations rodam duas vezes num MySQL 8.0) e
`bin/ws verify --repo api`. `bin/check-contracts.py --only migrations` aponta coluna usada pelo
PDO e ausente no schema dos testes. Termine na Definição de Pronto do `AGENTS.md`.
