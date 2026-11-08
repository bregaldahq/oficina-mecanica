"""O que a aplicação aplica no cluster e o que o repo do cluster precisa oferecer.

ESO-1     o ExternalSecret aponta para o ClusterSecretStore que o cluster cria (adendo 2 da §2)
RBAC-1    toda CRD usada em deploy/ tem permissão para o role de CI da aplicação
DEPLOY-1  os placeholders que o deploy.yml substitui por sed continuam nos manifests
"""
import re

from . import Finding, Repos, find_line, line_of

ESO_TF = "addons-external-secrets.tf"
RBAC_TF = "rbac-app-deployer.tf"
DEPLOY_YML = ".github/workflows/deploy.yml"
# Grupos que o Kubernetes já traz: não são CRDs e não passam pelo rbac-app-deployer.
BUILTIN_GROUPS = {"", "v1", "apps", "batch", "autoscaling", "policy", "networking.k8s.io",
                  "rbac.authorization.k8s.io", "storage.k8s.io", "kustomize.config.k8s.io"}


def manifests(repos: Repos):
    for rel in repos.tracked("api"):
        if rel.startswith("deploy/") and rel.endswith((".yaml", ".yml")):
            yield rel, repos.read("api", rel)


def check(repos: Repos) -> list[Finding]:
    out = []
    if repos.has("cluster", "api"):
        eso = repos.read("cluster", ESO_TF)
        m = re.search(r'kind\s*=\s*"ClusterSecretStore".*?name\s*=\s*"([^"]+)"', eso, re.S)
        store = m.group(1) if m else None
        for rel, text in manifests(repos):
            # Só as linhas mais indentadas que o secretStoreRef; name e kind em qualquer ordem.
            for ref in re.finditer(r"^([ \t]*)secretStoreRef:[ \t]*\n((?:\1[ \t]+\S.*\n?)+)", text, re.M):
                name = re.search(r"name:\s*(\S+)", ref.group(2))
                if "ClusterSecretStore" not in ref.group(2) or not name or name.group(1) == store:
                    continue
                out.append(Finding("ESO-1", "erro", "§2 adendo 2", f"o ExternalSecret usa o ClusterSecretStore "
                                   f"'{name.group(1)}', mas o cluster cria '{store}': o Secret oficina-secret não é gerado",
                                   f"{rel} {name.group(1)}",
                                   [repos.at("api", rel, line_of(text, ref.start())),
                                    repos.at("cluster", ESO_TF, find_line(eso, "ClusterSecretStore"))]))

        rbac = repos.read("cluster", RBAC_TF)
        allowed = set()
        for groups, resources in re.findall(r"api_groups\s*=\s*\[([^\]]*)\]\s*resources\s*=\s*\[([^\]]*)\]", rbac):
            for g in re.findall(r'"([^"]*)"', groups):
                allowed |= {(g, r) for r in re.findall(r'"([^"]*)"', resources)}
        for rel, text in manifests(repos):
            # Um documento YAML por vez; apiVersion e kind no nível de cima, em qualquer ordem.
            pos = 0
            for doc in re.split(r"^---[ \t]*$", text, flags=re.M):
                api = re.search(r"^apiVersion:\s*(\S+)", doc, re.M)
                kind = re.search(r"^kind:\s*(\w+)", doc, re.M)
                start, pos = pos, pos + len(doc) + 3
                if not api or not kind:
                    continue
                group = api.group(1).rsplit("/", 1)[0] if "/" in api.group(1) else ""
                if group in BUILTIN_GROUPS:
                    continue
                plural = kind.group(1).lower() + ("es" if kind.group(1).lower().endswith("s") else "s")
                if (group, plural) not in allowed:
                    out.append(Finding("RBAC-1", "erro", "§9", f"{rel} usa {kind.group(1)} ({group}), mas o rbac-app-deployer.tf "
                                       "não dá permissão ao role de CI da aplicação: o deploy volta forbidden",
                                       f"{group}/{plural}", [repos.at("api", rel, line_of(text, start + kind.start())),
                                                             repos.at("cluster", RBAC_TF)]))

    if repos.has("api"):
        deploy = repos.read("api", DEPLOY_YML)
        for m in re.finditer(r'sed -i "s#(\^?[^#]*?)#[^"]*"\s*\\?\s*\n?\s*(deploy/\S+)', deploy):
            placeholder, rel = m.group(1), m.group(2)
            if placeholder.startswith("^") or not placeholder.isupper():
                continue  # o MIGRATIONS_REF é uma regex de linha, não um placeholder
            if placeholder not in repos.read("api", rel):
                out.append(Finding("DEPLOY-1", "erro", "§8", f"o deploy.yml substitui {placeholder} em {rel}, mas o "
                                   "placeholder sumiu do manifesto: o valor do ambiente não é aplicado",
                                   f"{rel} {placeholder}", [repos.at("api", DEPLOY_YML, line_of(deploy, m.start())),
                                                            repos.at("api", rel)]))
    return out
