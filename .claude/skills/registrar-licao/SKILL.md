---
name: registrar-licao
description: Transforma uma correção do usuário (ou um erro que o agente cometeu e percebeu) em algo que impede a repetição — teste, regra do checker de contratos, hook, AGENTS.md de um repo ou do workspace, ou memória. Use logo depois de o usuário corrigir o agente, ou quando ele disser "anota isso", "não faça mais isso", "lembra disso".
---

# Registrar lição

Uma lição só vale se o próximo agente não puder repetir o erro. Escolha o **primeiro** destes
lugares que resolve:

| Ordem | Onde | Quando serve |
|---|---|---|
| 1 | **teste** no repo de produto | a regra é sobre o comportamento do código |
| 2 | **checagem** em `tools/contratos/` + teste em `tests/test_contratos.py` | é uma invariante entre repos ou entre código e documento |
| 3 | **hook** em `.claude/hooks/` (`guard-bash.py`, `guard-edit.py`, lembrete em `after-edit.py`) + teste em `tests/test_hooks.py` | é um comando ou arquivo que o agente nunca deve tocar, ou um lembrete na hora certa |
| 4 | **`AGENTS.md` do repo** (seção Armadilhas: sintoma → causa → o que pega) | é conhecimento sobre um repo |
| 5 | **`AGENTS.md` do workspace** | vale para os quatro repos |
| 6 | **memória** do Claude | é preferência pessoal do usuário, não regra do projeto |

Passos:

1. Diga em uma frase qual foi o erro e qual é a regra.
2. Proponha o lugar (a tabela acima) e o texto ou código. Espere o ok.
3. Faça, rode `bin/ws verify --repo <repo>` (ou `--repo workspace`) e confira que a regra nova
   pegaria o erro original. Para teste e checagem: planta o erro, vê falhar, tira.
4. Acrescente uma linha a `docs/LICOES.md`, criando o arquivo se não existir:
   `| aaaa-mm-dd | o que houve | onde foi registrado |`.

O `docs/LICOES.md` serve de métrica: a mesma lição duas vezes quer dizer que o primeiro
registro não funcionou.
