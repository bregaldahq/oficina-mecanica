---
name: checar-contratos
description: Confere se os quatro repositórios da Oficina ainda obedecem ao CONTRATOS.md — parâmetros SSM, segredos, JWT, rotas públicas, migrations, nomes antigos e RBAC. Use antes de PRs de infra, depois de puxar mudanças ou quando algo "funciona num repo e quebra no outro".
---

# Checar contratos

1. `bin/ws status`: avise se algum repo não está em `develop`/`main` atualizado, porque a
   checagem vale para a branch que estiver em disco.
2. `bin/check-contracts.py --json`. Ele cobre SSM (§2), segredos (§3), JWT (§4), rotas (§5),
   migrations (§6), `ClusterSecretStore`, RBAC das CRDs, placeholders do deploy, nomes antigos,
   tags, OIDC e caminhos citados no contexto dos agentes. `bin/check-contracts.py --help` lista
   tudo.
   - `erro`: as implementações discordam e algo quebra em runtime. É bloqueante.
   - `conhecido`: erro aceito, com motivo, em `tools/contratos/conhecidos.txt`. Relate, sem
     bloquear.
   - `aviso`: o `CONTRATOS.md` ou o `swagger.yaml` estão desatualizados em relação ao código.
     Pela regra do `AGENTS.md`, o documento vence: diga se o certo é corrigir o código ou
     escrever um adendo.
3. Olhe à mão só o que o script não cobre: ordem de apply de uma mudança em andamento (produtor
   antes do consumidor) e a semântica do que mudou (um valor de parâmetro trocado, por exemplo).

Relate os erros e os conhecidos, cada um com arquivo e linha dos dois lados, e resuma os avisos
por tipo. Se não houver erro, diga em uma frase e liste os avisos que pedem adendo no
`CONTRATOS.md`.

Ao achar uma divergência que o script deveria ter pego e não pegou, proponha a checagem nova em
`tools/contratos/`, com teste em `tests/test_contratos.py`.
