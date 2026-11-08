@AGENTS.md

## Claude Code

- Abra o Claude Code na raiz deste workspace: os quatro repos ficam visíveis em `repos/` e o
  `CLAUDE.md` de cada um (se existir) é carregado quando você trabalha dentro dele.
- Skills do workspace em `.claude/skills/`, chamadas como comandos (`/<nome>`). O catálogo, com o
  que digitar em cada situação, está em "Comandos" no `AGENTS.md`.
- Hooks em `.claude/hooks/` (configurados em `.claude/settings.json`): guarda de Bash e de edição,
  lembretes de contrato depois de editar, `bin/ws verify` ao encerrar e o retrato dos repos no
  início da sessão. Veja "Guardrails executados" no `AGENTS.md`.
- Subagentes em `.claude/agents/`:
  - `guardiao-de-contratos`: diff contra o `CONTRATOS.md`;
  - `revisor-ddd`: aplicação contra as ADRs 001 a 005;
  - `revisor-terraform`: Terraform contra a propriedade de recursos e a rede;
  - `verificador`: roda o `bin/ws verify` e devolve só as falhas.

  As skills os chamam; use-os antes de abrir PRs.
