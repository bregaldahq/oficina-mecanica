---
name: verificar
description: Roda localmente, sem AWS, o que o CI de cada repositório da Oficina roda (testes, phpstan, terraform fmt/validate, migrations duas vezes, kustomize, contratos) e resume só o que falhou. Use quando perguntarem "isso está ok?", "roda os testes", "verifica", antes de commitar ou antes de abrir PR.
---

# Verificar

1. Escolha o escopo:
   - pedido genérico ("verifica"): `bin/ws verify --changed`, ou seja, só os repos com mudança;
   - um repo citado: `bin/ws verify --repo <fundacao|cluster|gateway|api|workspace>`;
   - mudança em `Dockerfile` ou `docker/` da app: acrescente `--image`;
   - "rápido": `--fast` pula as migrations num MySQL de verdade.
2. Com mais de um repo, ou quando o log tende a ser grande, delegue ao subagente `verificador`:
   ele roda e devolve só as falhas, sem encher o contexto. Para um repo, rode você mesmo.
3. Se algo falhar, leia `.ws/verify/logs/<repo>-<passo>.log` (o caminho está no
   `.ws/verify/latest.json`) e aponte arquivo:linha. Para reproduzir um teste só, use
   `bin/ws exec <repo> vendor/bin/phpunit --filter <Teste>` ou
   `bin/ws exec <repo> terraform validate`.

Responda com uma linha por repo (ok, ou o que falhou) e, para cada falha, a causa provável em
uma frase. Aviso não bloqueante (tflint no cluster) só se for novo. Não corrija nada sem o
usuário pedir; se ele pediu "verifica e corrige", corrija e rode de novo até `OK`.
