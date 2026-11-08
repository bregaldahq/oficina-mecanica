---
name: status-geral
description: Panorama dos quatro repositórios da Oficina — branch atual, trabalho não commitado, divergência com o remoto, PRs abertos e último CI. Use quando pedirem "como está tudo", "o que está pendente", "status dos repos" ou antes de começar uma mudança cross-repo.
---

# Status geral do workspace

1. Rode `bin/ws context`: uma linha por repo, com branch, sujeira, divergência com o upstream,
   PRs abertos e se o CI de `develop` está vermelho. Se algum repo aparecer como ausente, diga e
   sugira `bin/ws clone` (ou `bin/ws link <dir>` se já houver clones na máquina).
2. Se algum CI estiver vermelho, rode `bin/ws ci develop` (e `bin/ws ci main`, se fizer sentido)
   e leia o log das etapas que falharam, salvo em `.ws/ci/`, para dizer o motivo em uma linha.
   Não use `gh run list --branch`: o `gh` desta máquina é antigo e não tem essa opção.
3. Rode `bin/check-contracts.py`.

Entregue uma tabela curta, uma linha por repo: branch, sujos, à frente/atrás, PRs abertos e CI
de `develop`. Abaixo, só o que pede ação: repo atrás do remoto, branch esquecida com trabalho não
commitado, PR parado, CI vermelho (com o motivo), erro de contrato. Não repita o que está ok.
