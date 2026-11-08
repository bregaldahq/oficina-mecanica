---
name: revisar-pr
description: Revisa um PR (ou o conjunto de PRs irmãos de uma mudança) de um repositório da Oficina — roda as verificações locais na branch do PR, os contratos entre repos e os revisores especializados, e entrega um relatório. Use para "revisa o PR X", "dá uma olhada no PR do gateway", antes de aprovar ou mergear.
---

# Revisar PR

Argumentos: `<repo> <número>`, ou só a branch, para pegar os irmãos.

1. **Contexto:** `gh pr view <n> --repo bregaldahq/<repo>` (título, descrição, base, branch) e
   `bin/ws prs --branch <branch>` (PRs irmãos nos outros repos). Avise se a base não for
   `develop` ou se a ordem de merge da descrição estiver errada.
2. **Checkout sem atrapalhar ninguém:** numa sessão em worktree, use
   `bin/ws isolate <branch> <repos dos PRs>`. A branch vem do remoto. Fora de worktree, use
   `bin/ws branch <branch> <repos>` só se os clones estiverem limpos. Se não estiverem, pergunte.
3. **Verificar:** `bin/ws verify --changed` (subagente `verificador`, se forem vários repos) e
   `bin/check-contracts.py --json`.
4. **Revisar o diff** (`bin/ws diff --patch`), em paralelo quando fizer sentido:
   - subagente `guardiao-de-contratos`: contrato entre repos e ordem de apply;
   - subagente `revisor-ddd`: se mexe em `oficina-api/src/`;
   - subagente `revisor-terraform`: se mexe em `.tf`;
   - a skill `/code-review` para bugs no diff e `/security-review` se toca autenticação,
     segredos, IAM ou rotas públicas.
5. **Relatório:**
   - um veredito (pode mergear / mergear depois de X / não mergear);
   - os achados, do mais grave ao menos grave, cada um com repo, arquivo:linha e o que quebra;
   - o que só o CI do PR mostra (`terraform plan` comentado, build da imagem): leia os
     comentários do PR com `gh pr view <n> --comments` se houver.

Comente no PR (`gh pr comment`, que pede confirmação) só se o usuário pedir. Nunca aprove nem
mergeie. No fim, numa sessão isolada, `bin/ws isolate --rm`.
