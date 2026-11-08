---
name: abrir-prs
description: Abre os PRs de uma mudança já pronta da Oficina — um por repositório tocado, todos para develop, como draft, na ordem de apply, com a ordem de merge e os links dos PRs irmãos na descrição. Use só quando o usuário pedir para abrir PR, publicar ou subir a mudança.
---

# Abrir PRs

Só com pedido explícito do usuário. Push e PR publicam no GitHub e pedem confirmação.

1. **Conferir a Definição de Pronto** (`AGENTS.md`): `bin/ws verify --changed` em `OK` e
   `bin/check-contracts.py` sem erro. Se faltar algo, pare e diga o quê.
2. **Descobrir o que sobe:** `bin/ws diff` mostra os repos com commits na branch. Todos devem
   estar na **mesma** branch (`feat/…`, `fix/…`, `chore/…`, `ci/…`), nunca em `main`/`develop`.
   Os commits seguem a convenção (o git hook `commit-msg` confere, se estiver instalado).
3. **Montar as descrições** a partir de `templates/pr-body.md`: o porquê, o que muda neste repo,
   a ordem de merge (fundação → cluster → gateway → api, só com os repos tocados), o que foi
   verificado e o que só o CI verifica. Mostre todas ao usuário antes de publicar.
4. **Publicar, na ordem de apply**, um repo por vez:

   ```bash
   git -C repos/<repo> push -u origin <branch>
   gh pr create --repo bregaldahq/<repo> --base develop --head <branch> --draft \
     --title "<tipo>(<escopo>): <assunto>" --body-file <arquivo com a descrição>
   ```

5. **Ligar os irmãos:** depois que todos existirem, `bin/ws prs --branch <branch>` lista os
   links. Atualize a seção "PRs irmãos" de cada descrição com `gh pr edit <n> --repo
   bregaldahq/<repo> --body-file ...`. Isso pede confirmação, porque é escrita no GitHub.

Nada de `Co-Authored-By` nem rodapé de ferramenta (regra de autoria do `AGENTS.md`). Nunca faça
merge: quem mergeia é o usuário, na ordem do resumo.
