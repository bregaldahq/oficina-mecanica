@AGENTS.md

## Claude Code

- Abra o Claude Code na raiz deste workspace: os quatro repos ficam visíveis em `repos/` e o
  `CLAUDE.md` de cada um (se existir) é carregado quando você trabalha dentro dele.
- Skills do workspace em `.claude/skills/`: `status-geral`, `mudanca-cross-repo`,
  `checar-contratos`.
- Hooks em `.claude/hooks/` (configurados em `.claude/settings.json`): guarda de Bash e de edição,
  lembretes de contrato depois de editar, `bin/ws verify` ao encerrar e o retrato dos repos no
  início da sessão. Veja "Guardrails executados" no `AGENTS.md`.
- Subagente `guardiao-de-contratos` (`.claude/agents/`): revisa um diff, ou um conjunto de PRs,
  contra `CONTRATOS.md`. Use antes de abrir PRs que mexem em SSM, segredos, JWT, rotas ou
  migrations.
