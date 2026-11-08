"""Seção 4: o token emitido pela Lambda tem de ser aceito pela aplicação, e vice-versa.

O que precisa ser igual é o token, não o arquivo: os dois JwtProvider diferem em namespace,
comentários e na forma de escrever o emissor (constante de um lado, literal do outro).
"""
import re

from . import Finding, Repos, find_line

TOKEN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
DOC = "docs/fase-3/contract-token.md"
PROVIDER = {"gateway": "src/Security/JwtProvider.php", "api": "src/Infrastructure/Security/JwtProvider.php"}
# Os métodos que decidem os bytes do token.
TOKEN_METHODS = ("generate", "base64urlEncode")


def contract_test(repos: Repos, short: str) -> tuple[str, str, int]:
    """(arquivo, token literal, linha) do teste de contrato do repo; token vazio se não houver."""
    for rel in repos.tracked(short):
        if rel.startswith("tests/") and rel.endswith("JwtContractTest.php"):
            text = repos.read(short, rel)
            m = re.search(r"EXPECTED_TOKEN\s*=\s*(.*?);", text, re.S)
            if m:
                return rel, "".join(re.findall(r"'([^']*)'", m.group(1))), find_line(text, "EXPECTED_TOKEN =")
            return rel, "", 0
    return "", "", 0


def method_body(text: str, name: str) -> str:
    m = re.search(rf"function\s+{name}\s*\([^)]*\)[^{{]*\{{", text)
    if not m:
        return ""
    depth, i = 1, m.end()
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.end():i - 1]


def normalized(text: str, name: str) -> str:
    body = method_body(text, name)
    consts = dict(re.findall(r"const\s+(\w+)\s*=\s*('[^']*'|\"[^\"]*\"|\d+)\s*;", text))
    body = re.sub(r"self::(\w+)", lambda m: consts.get(m.group(1), m.group(0)), body)
    body = re.sub(r"/\*.*?\*/|//[^\n]*|#[^\n]*", "", body, flags=re.S)
    return re.sub(r"\s+", "", body).replace('"', "'")


def check(repos: Repos) -> list[Finding]:
    if not repos.has("gateway", "api"):
        return []
    out = []
    tests = {s: contract_test(repos, s) for s in ("gateway", "api")}
    for short, (rel, token, _) in tests.items():
        if not token:
            out.append(Finding("JWT-1", "erro", "§4", f"{repos.name(short)} não tem o teste de contrato do JWT com "
                               "EXPECTED_TOKEN (obrigatório pela seção 4)", f"teste-ausente {short}",
                               [repos.at(short, rel or "tests/")]))
    doc_text = repos.read("api", DOC)
    doc_token = (TOKEN.search(doc_text) or [""])[0] if doc_text else ""
    tokens = {f"{repos.name(s)}/{rel}": (tok, repos.at(s, rel, line)) for s, (rel, tok, line) in tests.items() if tok}
    if doc_token:
        tokens[f"oficina-api/{DOC}"] = (doc_token, repos.at("api", DOC, find_line(doc_text, doc_token[:20])))
    if len({tok for tok, _ in tokens.values()}) > 1:
        out.append(Finding("JWT-1", "erro", "§4", "o token literal do contrato difere entre "
                           + ", ".join(tokens) + ": um lado mudou o JwtProvider ou o teste sem o outro",
                           "token-diferente", [loc for _, loc in tokens.values()]))

    texts = {s: repos.read(s, rel) for s, rel in PROVIDER.items()}
    for short, text in texts.items():
        if not text:
            out.append(Finding("JWT-2", "erro", "§4", f"{repos.name(short)}: {PROVIDER[short]} não existe",
                               f"provider-ausente {short}", [repos.at(short, PROVIDER[short])]))
    if all(texts.values()):
        for name in TOKEN_METHODS:
            a, b = (normalized(texts[s], name) for s in ("gateway", "api"))
            if a != b:
                out.append(Finding("JWT-2", "erro", "§4", f"{name}() dos dois JwtProvider não é equivalente: os tokens "
                                   "deixam de ser aceitos do outro lado", name,
                                   [repos.at(s, PROVIDER[s], find_line(texts[s], f"function {name}")) for s in ("gateway", "api")]))
    return out
