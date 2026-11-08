"""Seção 3: os segredos oficina/<env>/db e oficina/<env>/auth e as chaves de cada um.

O dono é a fundação (secrets.tf). Quem lê: o ExternalSecret da aplicação (base e overlays), a
Lambda (SDK) e o smoke test do deploy da fundação.
"""
import re

from . import CONTRATOS, Finding, Repos, find_line, line_of, md_section, tf_blocks

SECRETS_TF = "secrets.tf"


def defined(repos: Repos) -> dict[str, set[str]]:
    """{db|auth: chaves} do jsonencode de cada aws_secretsmanager_secret_version."""
    text = repos.read("fundacao", SECRETS_TF)
    names = {}
    for name, body, _ in tf_blocks(text, "resource", "aws_secretsmanager_secret"):
        m = re.search(r'name\s*=\s*"oficina/\$\{var\.environment\}/(\w+)"', body)
        if m:
            names[name] = m.group(1)
    out = {}
    for _, body, _ in tf_blocks(text, "resource", "aws_secretsmanager_secret_version"):
        ref = re.search(r"aws_secretsmanager_secret\.(\w+)\.id", body)
        enc = re.search(r"jsonencode\(\{(.*?)\}\)", body, re.S)
        if ref and enc and ref.group(1) in names:
            out[names[ref.group(1)]] = set(re.findall(r"^\s*(\w+)\s*=", enc.group(1), re.M))
    return out


def check(repos: Repos) -> list[Finding]:
    if not repos.has("fundacao"):
        return []
    keys = defined(repos)
    tf_line = lambda key: repos.at("fundacao", SECRETS_TF, find_line(repos.read("fundacao", SECRETS_TF), f"{key} "))
    out = []

    def missing(where: int, secret: str, key: str, rel: str, short: str, what: str):
        if secret not in keys:
            out.append(Finding("SEG-1", "erro", "§3", f"{what} lê o segredo oficina/<env>/{secret}, que a fundação não cria",
                               f"{short}:{rel} {secret}", [repos.at(short, rel, where)]))
        elif key not in keys[secret]:
            out.append(Finding("SEG-1", "erro", "§3", f"{what} lê a chave {key} de oficina/<env>/{secret}, que não existe "
                               f"(o segredo tem: {', '.join(sorted(keys[secret]))})", f"{short}:{rel} {secret}.{key}",
                               [repos.at(short, rel, where), repos.at("fundacao", SECRETS_TF)]))

    if repos.has("api"):
        for rel in repos.tracked("api"):
            if rel.startswith("deploy/") and rel.endswith((".yaml", ".yml")):
                text = repos.read("api", rel)
                if "remoteRef" not in text:
                    continue
                for m in re.finditer(r"key:\s*oficina/\w+/(\w+),\s*property:\s*(\w+)", text):
                    missing(line_of(text, m.start()), m.group(1), m.group(2), rel, "api", "O ExternalSecret")

    if repos.has("gateway"):
        for rel in repos.tracked("gateway"):
            if not rel.endswith(".php") or rel.startswith(("tests/", "vendor/")):
                continue
            text = repos.read("gateway", rel)
            for var, sid in re.findall(r"\$(\w+)\s*=\s*\$(?:this->)?secrets->get\(\$(?:this->)?(\w+)\)", text):
                secret = "db" if "db" in sid.lower() else "auth" if "auth" in sid.lower() else sid
                for m in re.finditer(rf"\${var}\['(\w+)'\]", text):
                    missing(line_of(text, m.start()), secret, m.group(1), rel, "gateway", "A Lambda")

    deploy = repos.read("fundacao", ".github/workflows/deploy.yml")
    for m in re.finditer(r'--secret-id\s+"oficina/\$\{\w+\}/(\w+)"(.{0,400}?)>\s*/dev/null', deploy, re.S):
        for key in re.findall(r'has\("(\w+)"\)', m.group(2)):
            missing(line_of(deploy, m.start()), m.group(1), key, ".github/workflows/deploy.yml", "fundacao",
                    "O smoke test do deploy da fundação")

    if repos.has("api"):
        doc = repos.read("api", CONTRATOS)
        section = md_section(doc, 3)
        base = doc.find(section)
        for m in re.finditer(r"\*\*`oficina/<env>/(\w+)`\*\*.*?```json(.*?)```", section, re.S):
            secret, documented = m.group(1), set(re.findall(r'"(\w+)"\s*:', m.group(2)))
            if secret in keys and documented != keys[secret]:
                diff = sorted(documented ^ keys[secret])
                out.append(Finding("SEG-2", "aviso", "§3", f"as chaves de oficina/<env>/{secret} no CONTRATOS.md e no secrets.tf "
                                   f"diferem em: {', '.join(diff)}", secret,
                                   [repos.at("api", CONTRATOS, line_of(doc, base + m.start())), tf_line("jsonencode")]))
    return out
