"""Seção 2: parâmetros SSM. Quem publica (resource "aws_ssm_parameter") e quem consome."""
import re
from collections import defaultdict

from . import CONTRATOS, REPOS, Finding, Local, Repos, find_line, line_of, md_section

EXTENSIONS = {".tf", ".yml", ".yaml", ".sh", ".php", ".py", ".json"}

# As três formas de escrever o ambiente que aparecem nos repos: ${var.environment},
# ${ENVIRONMENT} / $ENVIRONMENT e <env>.
ENV = r"(?:\$\{[^}]+\}|\$[A-Za-z_]+|<env>|hml|prod)"
PARAM = re.compile(r"/oficina/" + ENV + r"/([a-z_]+/[a-z_]+)")
RESOURCE = re.compile(r'resource\s+"aws_ssm_parameter"\s+"[^"]+"\s*\{(.*?)\n\}', re.S)
OLD_TO_SHORT = {old: short for short, (_, old) in REPOS.items()}


def inventory(repos: Repos):
    """{parâmetro: {repo curto: primeiro Local}} para quem publica e para quem consome."""
    producers: dict[str, dict[str, Local]] = defaultdict(dict)
    consumers: dict[str, dict[str, Local]] = defaultdict(dict)
    for short in REPOS:
        if not repos.has(short):
            continue
        for rel in repos.tracked(short):
            if not any(rel.endswith(ext) for ext in EXTENSIONS):
                continue
            text = repos.read(short, rel)
            published = set()
            if rel.endswith(".tf"):
                for block in RESOURCE.finditer(text):
                    for m in PARAM.finditer(block.group(1)):
                        published.add(m.group(1))
                        producers[m.group(1)].setdefault(short, repos.at(short, rel, line_of(text, block.start())))
            for m in PARAM.finditer(text):
                if m.group(1) not in published:
                    consumers[m.group(1)].setdefault(short, repos.at(short, rel, line_of(text, m.start())))
    return producers, consumers


def documented(repos: Repos) -> dict[str, tuple[str, int]]:
    """{parâmetro: (repo curto dono, linha)} segundo as tabelas da seção 2 do CONTRATOS.md."""
    text = repos.read("api", CONTRATOS)
    section = md_section(text, 2)
    offset = text.find(section)
    owner, out = None, {}
    for m in re.finditer(r"^### Publicados por `([^`]+)`|^\| `/oficina/<env>/([a-z_]+/[a-z_]+)`", section, re.M):
        if m.group(1):
            owner = OLD_TO_SHORT.get(m.group(1)) or next((s for s, (new, _) in REPOS.items() if new == m.group(1)), None)
        elif owner:
            out[m.group(2)] = (owner, line_of(text, offset + m.start()))
    return out


def check(repos: Repos) -> list[Finding]:
    producers, consumers = inventory(repos)
    out = []
    for name in sorted(consumers):
        if name not in producers:
            who = consumers[name]
            out.append(Finding("SSM-1", "erro", "§2", f"/oficina/<env>/{name} é consumido por "
                               f"{', '.join(repos.name(s) for s in who)}, mas ninguém publica: o apply quebra",
                               name, list(who.values())))
    for name in sorted(producers):
        who = producers[name]
        if len(who) > 1:
            out.append(Finding("SSM-2", "erro", "§2", f"/oficina/<env>/{name} é publicado por mais de um repo",
                               name, list(who.values())))
        elif not set(consumers.get(name, {})) - set(who):
            out.append(Finding("SSM-3", "aviso", "§2", f"/oficina/<env>/{name} é publicado e nenhum outro repo lê",
                               name, list(who.values())))

    if repos.has("api"):
        doc = documented(repos)
        for name in sorted(set(doc) | set(producers)):
            in_doc = doc.get(name)
            in_code = producers.get(name, {})
            if in_doc and not in_code:
                out.append(Finding("SSM-4", "aviso", "§2", f"/oficina/<env>/{name} está no CONTRATOS.md, mas nenhum repo publica",
                                   name, [repos.at("api", CONTRATOS, in_doc[1])]))
            elif in_code and not in_doc:
                out.append(Finding("SSM-4", "aviso", "§2", f"/oficina/<env>/{name} é publicado, mas não está no CONTRATOS.md",
                                   name, list(in_code.values()) + [repos.at("api", CONTRATOS, find_line(repos.read("api", CONTRATOS), "## 2."))]))
            elif in_doc and in_doc[0] not in in_code:
                out.append(Finding("SSM-4", "aviso", "§2", f"/oficina/<env>/{name}: o CONTRATOS.md diz que o dono é "
                                   f"{repos.name(in_doc[0])}, mas quem publica é {', '.join(repos.name(s) for s in in_code)}",
                                   name, [repos.at("api", CONTRATOS, in_doc[1])] + list(in_code.values())))
    return out
