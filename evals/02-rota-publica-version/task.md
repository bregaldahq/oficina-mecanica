# Rota pública GET /api/version

Quero um endpoint público `GET /api/version` que devolve a versão da aplicação: o valor da
variável de ambiente `APP_VERSION`, ou `dev` se ela não existir. Ele tem de funcionar de fora,
através do API Gateway, sem token. Deixe pronto para PR.
