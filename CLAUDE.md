@AGENTS.md

## Claude Code

- Abra o Claude Code na raiz deste workspace: os quatro repos ficam visíveis em `repos/` e o
  `CLAUDE.md` de cada um (se existir) é carregado quando você trabalha dentro dele.
- Skills do workspace em `.claude/skills/`: `status-geral`, `mudanca-cross-repo`,
  `checar-contratos`.
- Subagente `guardiao-de-contratos` (`.claude/agents/`): revisa um diff, ou um conjunto de PRs,
  contra `CONTRATOS.md`. Use antes de abrir PRs que mexem em SSM, segredos, JWT, rotas ou
  migrations.
