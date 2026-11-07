---
name: checar-contratos
description: Confere se os quatro repositórios da Oficina ainda obedecem ao CONTRATOS.md — parâmetros SSM, segredos, JWT, rotas públicas e migrations. Use antes de PRs de infra, depois de puxar mudanças ou quando algo "funciona num repo e quebra no outro".
---

# Checar contratos

1. `bin/ws status` — avise se algum repo não está em `develop`/`main` atualizado, porque a
   checagem vale para a branch que estiver em disco.
2. `bin/check-contracts.py --verbose` — erro aqui é bloqueante.
3. Compare a lista de parâmetros publicados com a seção 2 de `CONTRATOS.md`: parâmetro no código
   e fora do documento (ou o contrário) é divergência.
4. Confira à mão o que o script não cobre:
   - nomes dos segredos `oficina/<env>/db` e `oficina/<env>/auth` e suas chaves (seção 3);
   - `ClusterSecretStore` `oficina-secretsmanager` igual no repo k8s e no `ExternalSecret` da app;
   - teste de contrato do JWT: o token literal é o mesmo na Lambda e na aplicação;
   - rotas sem authorizer no `apigateway.tf` da Lambda batem com as rotas públicas da matriz de
     autorização da aplicação (seção 5).

Relate só divergências, cada uma com arquivo e linha dos dois lados. Se estiver tudo coerente,
diga em uma frase.
