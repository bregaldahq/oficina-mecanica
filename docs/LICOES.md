# Lições

Cada correção do agente que virou prevenção (`/registrar-licao`). A mesma lição duas vezes quer
dizer que o primeiro registro não funcionou.

| Data | O que houve | Onde foi registrado |
|---|---|---|
| 2026-11-07 | O `verify` reescrevia o `.php-cs-fixer.cache`, que é versionado na app, e deixava o repo sujo | `bin/verify.py` (`--using-cache=no`); o teste é o `git status` limpo depois do verify |
| 2026-11-07 | O `NOME-1` acusou erro numa tag `Repo` com comentário no fim da linha (falso positivo em `develop`) | `tools/contratos/nomes.py` + `test_tag_repo_com_comentario_no_fim_da_linha` |
| 2026-11-07 | O `deploy.yml` da fundação em `develop` era YAML inválido e nada acusava | passo `workflows` do `bin/ws verify`, agora bloqueante |
| 2026-11-08 | Um `cmd \| head && próximo` seguiu com `cmd` falhando (o `php.sh` sem permissão de execução) e só a saída mostrou | `AGENTS.md`, "Validação local": `set -o pipefail` em comandos encadeados com pipe |
| 2026-11-07 | A skill `status-geral` usava `gh run list --branch`, que o `gh` 2.4 da máquina não tem | `bin/ws ci`/`context` usam a API REST; o `doctor` avisa o `gh` velho |
