# Imagem de ferramentas da Oficina: tudo o que o pr.yml dos quatro repositórios usa, nas mesmas
# versões, para que a máquina de desenvolvimento só precise de Docker. Construída e usada por
# bin/tooling; a tag é o hash deste arquivo, então mudar uma versão aqui gera imagem nova.
#
# Versões e de onde vêm:
#   PHP 8.2 + pdo_mysql   pr.yml da aplicação e do gateway (shivammathur/setup-php, "8.2")
#   Composer 2.7          scripts/composer.sh da aplicação
#   Terraform 1.9.8       pr.yml da fundação e do cluster (o gateway ainda está em 1.9.5)
#   tflint                pr.yml do cluster (setup-tflint@v4, sem versão fixa lá)
#   kustomize 5.4.3       deploy.yml da aplicação
#   actionlint            não está no CI; lint extra e não bloqueante dos workflows
FROM php:8.2-cli-bookworm

ARG TARGETARCH=amd64
ARG TERRAFORM_VERSION=1.9.8
ARG TFLINT_VERSION=0.53.0
ARG KUSTOMIZE_VERSION=5.4.3
ARG ACTIONLINT_VERSION=1.7.1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git unzip curl ca-certificates jq shellcheck \
 && docker-php-ext-install pdo_mysql \
 && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2.7 /usr/bin/composer /usr/local/bin/composer

RUN set -eux; cd /tmp; \
    curl -fsSLo tf.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip"; \
    unzip -q tf.zip terraform -d /usr/local/bin; \
    curl -fsSLo tflint.zip "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_${TARGETARCH}.zip"; \
    unzip -q tflint.zip tflint -d /usr/local/bin; \
    curl -fsSL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv${KUSTOMIZE_VERSION}/kustomize_v${KUSTOMIZE_VERSION}_linux_${TARGETARCH}.tar.gz" \
      | tar xz -C /usr/local/bin kustomize; \
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_${TARGETARCH}.tar.gz" \
      | tar xz -C /usr/local/bin actionlint; \
    rm -f /tmp/*.zip

# Os repositórios são montados em /w com o uid de quem chama; o Git dentro do container não pode
# recusá-los por "dubious ownership".
RUN git config --system --add safe.directory '*'

WORKDIR /w
