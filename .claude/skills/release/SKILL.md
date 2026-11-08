---
name: release
description: Prepara a subida de develop para main (produção) nos repositórios da Oficina — changelog por repo, riscos (migration, plan destrutivo, mudança de contrato, deploy manual da fundação) e, com o ok do usuário, os PRs develop → main na ordem de apply. Use para "subir para produção", "release", "o que vai para main".
---

# Release (develop → main)

`main` é produção: merge em `main` faz deploy em prod (a fundação, só por disparo manual).

1. **O que sobe:** para cada repo, `git -C repos/<repo> fetch origin` e
   `git -C repos/<repo> log --oneline origin/main..origin/develop`. Repo sem commits fica fora.
2. **Riscos**, por repo:
   - **fundação:** migration nova (o Job da app roda na subida da app; a ref vem do
     `migrations-configmap.yaml`), mudança em rede, RDS ou segredos. O deploy é manual
     (`workflow_dispatch`): quem dispara é o usuário, nunca o agente;
   - **cluster:** versão do EKS, tipo ou quantidade de nodes, add-ons. Leia o `terraform plan`
     de prod comentado no último PR e procure `destroy` ou `replace`;
   - **gateway:** rotas, authorizer, layers;
   - **api:** mudança de contrato (`bin/check-contracts.py` em `develop`) e o CI de `develop`
     verde (`bin/ws ci develop`).
3. **Changelog e ordem:** uma seção por repo, com os commits agrupados por tipo
   (`feat`/`fix`/…), e a ordem de merge e deploy: fundação → cluster → gateway → api.
   Mostre ao usuário.
4. **PRs `develop → main`**, só com o ok do usuário e na ordem de apply:
   `gh pr create --repo bregaldahq/<repo> --base main --head develop --title "chore(release): ..." --body-file ...`.
   Isso pede confirmação. A fundação vai junto, lembrando que o apply dela é manual.

Nunca faça merge nem dispare workflow. O usuário mergeia um repo por vez e espera o deploy
anterior terminar.
