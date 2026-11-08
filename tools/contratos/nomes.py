"""Convenções que valem nos quatro repos.

NOME-1  os três nomes antigos ficam: chave do state, role de CI (oficina-gha-<antigo>) e tag Repo
TAG-1   tags obrigatórias Project, Environment, ManagedBy e Repo nos repos de Terraform
CI-1    OIDC em todo workflow (nenhuma access key) e a mesma versão do Terraform nos três repos
"""
import re

from . import REPOS, Finding, Repos, find_line, line_of

IAC = ("fundacao", "cluster", "gateway")
TAGS = ("Project", "Environment", "ManagedBy", "Repo")


def workflows(repos: Repos, short: str):
    for rel in repos.tracked(short):
        if rel.startswith(".github/workflows/") and rel.endswith((".yml", ".yaml")):
            yield rel, repos.read(short, rel)


def check(repos: Repos) -> list[Finding]:
    out = []
    new_names = {new: short for short, (new, _) in REPOS.items()}
    versions: dict[str, list] = {}
    for short in REPOS:
        if not repos.has(short):
            continue
        new, old = REPOS[short]
        for rel, text in workflows(repos, short):
            for m in re.finditer(r"key=oficina/([\w-]+)/", text):
                if m.group(1) != old:
                    out.append(Finding("NOME-1", "erro", "README", f"a chave do state usa '{m.group(1)}'; tem de continuar "
                                       f"'{old}', ou o Terraform não acha o state e recria tudo",
                                       f"{new} state", [repos.at(short, rel, line_of(text, m.start()))]))
            if re.search(r"aws-access-key-id|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY", text):
                out.append(Finding("CI-1", "erro", "§9", f"{rel} usa access key estática; o contrato exige OIDC",
                                   f"{new}:{rel} access-key", [repos.at(short, rel, find_line(text, "AWS_"))]))
            for m in re.finditer(r"(?:terraform_version|TF_VERSION):\s*['\"]?([\d.]+)", text):
                versions.setdefault(m.group(1), []).append(repos.at(short, rel, line_of(text, m.start())))
        for rel in repos.tracked(short):
            if not rel.endswith((".tf", ".tfvars", ".yml", ".yaml")):
                continue
            text = repos.read(short, rel)
            for m in re.finditer(r"oficina-gha-([\w-]+)", text):
                if m.group(1) in new_names:
                    out.append(Finding("NOME-1", "erro", "README", f"role 'oficina-gha-{m.group(1)}' não existe: os roles de CI "
                                       f"continuam com o nome antigo ('oficina-gha-{REPOS[new_names[m.group(1)]][1]}')",
                                       f"{new}:{rel} role", [repos.at(short, rel, line_of(text, m.start()))]))

    for short in IAC:
        if not repos.has(short):
            continue
        text = repos.read(short, "locals.tf")
        missing = [t for t in TAGS if not re.search(rf"^\s*{t}\s*=", text, re.M)]
        if missing:
            out.append(Finding("TAG-1", "erro", "AGENTS.md", f"locals.tf sem a(s) tag(s) obrigatória(s) {', '.join(missing)}",
                               repos.name(short), [repos.at(short, "locals.tf")]))
        m = re.search(r"^\s*Repo\s*=\s*(.+)$", text, re.M)
        if m:
            value = m.group(1).strip()
            if value.startswith("local."):
                ref = re.search(rf'^\s*{value.split(".", 1)[1]}\s*=\s*"([^"]+)"', text, re.M)
                value = ref.group(1) if ref else value
            value = value.strip('"')
            if value != REPOS[short][1]:
                out.append(Finding("NOME-1", "erro", "README", f"tag Repo = '{value}'; tem de continuar '{REPOS[short][1]}' "
                                   "(trocar dispara um apply que mexe em todos os recursos)",
                                   f"{repos.name(short)} tag", [repos.at(short, "locals.tf", line_of(text, m.start()))]))

    if len(versions) > 1:
        out.append(Finding("CI-1", "aviso", "§9", "versões diferentes do Terraform nos workflows: " + ", ".join(sorted(versions)),
                           "terraform-version", [loc for locs in versions.values() for loc in locs[:1]]))
    return out
