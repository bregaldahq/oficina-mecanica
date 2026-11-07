---
name: status-geral
description: Panorama dos quatro repositórios da Oficina — branch atual, trabalho não commitado, divergência com o remoto, PRs abertos e último CI. Use quando pedirem "como está tudo", "o que está pendente", "status dos repos" ou antes de começar uma mudança cross-repo.
---

# Status geral do workspace

1. Rode `bin/ws status`. Se algum repo aparecer como ausente, diga e sugira `bin/ws clone`
   (ou `bin/ws link <dir>` se já houver clones na máquina).
2. Rode `bin/ws prs`.
3. Para cada repo, veja o último run de CI nas branches `develop` e `main`:
   `gh run list --repo bregaldahq/<repo> --branch <branch> --limit 1`.
4. Rode `bin/check-contracts.py`.

Entregue uma tabela curta, uma linha por repo: branch, sujos, à frente/atrás, PRs abertos,
CI de `develop` e de `main`. Abaixo, só o que pede ação: repo atrás do remoto, branch esquecida
com trabalho não commitado, PR parado, CI vermelho, erro de contrato. Não repita o que está ok.
