"""Checagem dos contratos entre os quatro repositórios (docs/fase-3/CONTRATOS.md da aplicação).

Cada família de checagem fica num módulo e devolve uma lista de `Finding`. Severidade:

  erro   as implementações discordam entre si e algo quebra em runtime (ou no apply)
  aviso  o documento (CONTRATOS.md, swagger) discorda da implementação: ele precisa de adendo

Um erro já conhecido e aceito, com motivo, fica em conhecidos.txt e é relatado como
"conhecido", sem derrubar a checagem.
"""
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Nome curto -> nome do repositório (repos.txt) e nome antigo, que continua na chave do state, no
# role de CI e na tag Repo (README, "Nomes antigos").
REPOS = {
    "fundacao": ("oficina-infra-fundacao", "oficina-infra-database"),
    "cluster": ("oficina-infra-cluster", "oficina-infra-k8s"),
    "gateway": ("oficina-gateway-auth", "oficina-lambda-auth"),
    "api": ("oficina-api", "oficina-mecanica-tech-challenge"),
}
CONTRATOS = "docs/fase-3/CONTRATOS.md"
FAMILIES = ("ssm", "jwt", "rotas", "segredos", "k8s", "migrations", "nomes", "docs")


@dataclass
class Local:
    repo: str
    arquivo: str
    linha: int = 0

    def __str__(self) -> str:
        return f"{self.repo}/{self.arquivo}" + (f":{self.linha}" if self.linha else "")


@dataclass
class Finding:
    id: str
    severidade: str  # erro | aviso | conhecido
    secao: str
    mensagem: str
    chave: str  # estável: é o que conhecidos.txt cita
    locais: list[Local] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"id": self.id, "severidade": self.severidade, "secao": self.secao, "mensagem": self.mensagem,
                "chave": self.chave, "locais": [str(x) for x in self.locais]}


class Repos:
    """Os clones, por nome curto. Um repo ausente faz as checagens que dependem dele serem puladas."""

    def __init__(self, paths: dict[str, Path], workspace: Path):
        self.paths = paths
        self.workspace = workspace

    def has(self, *shorts: str) -> bool:
        return all(s in self.paths and self.paths[s].is_dir() for s in shorts)

    def path(self, short: str) -> Path:
        return self.paths[short]

    def name(self, short: str) -> str:
        return REPOS[short][0]

    def read(self, short: str, rel: str) -> str:
        p = self.paths[short] / rel
        return p.read_text(errors="ignore") if p.is_file() else ""

    def tracked(self, short: str) -> list[str]:
        out = subprocess.run(["git", "-C", str(self.paths[short]), "ls-files"], capture_output=True, text=True)
        return out.stdout.splitlines()

    def at(self, short: str, rel: str, line: int = 0) -> Local:
        return Local(self.name(short), rel, line)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def find_line(text: str, needle: str) -> int:
    pos = text.find(needle)
    return line_of(text, pos) if pos >= 0 else 0


def tf_blocks(text: str, kind: str, type_: str):
    """(nome, corpo, posição) de cada `<kind> "<type>" "<nome>" { ... }` de um arquivo HCL."""
    for m in re.finditer(rf'^{kind}\s+"{re.escape(type_)}"\s+"([^"]+)"\s*\{{', text, re.M):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        yield m.group(1), text[m.end():i - 1], m.start()


def md_section(text: str, number: int) -> str:
    """O corpo da seção `## <number>.` de um markdown."""
    m = re.search(rf"^## {number}\.[^\n]*\n(.*?)(?=^## \d+\.|\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def load_known(path: Path = HERE / "conhecidos.txt") -> set[str]:
    known = set()
    if path.is_file():
        for line in path.read_text().splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry:
                known.add(" ".join(entry.split()))
    return known


def run(repos: Repos, only: set[str] | None = None, known: set[str] | None = None) -> list[Finding]:
    from . import docs, jwt, k8s, migrations, nomes, rotas, segredos, ssm

    modules = {"ssm": ssm, "jwt": jwt, "rotas": rotas, "segredos": segredos, "k8s": k8s,
               "migrations": migrations, "nomes": nomes, "docs": docs}
    findings: list[Finding] = []
    for name in FAMILIES:
        if not only or name in only:
            findings += modules[name].check(repos)

    known = load_known() if known is None else known
    seen = set()
    for f in findings:
        key = f"{f.id} {f.chave}"
        if key in known:
            seen.add(key)
            if f.severidade == "erro":
                f.severidade = "conhecido"
    if not only:
        for key in sorted(known - seen):
            findings.append(Finding("CONHECIDO", "aviso", "-", f"'{key}' está em conhecidos.txt mas não aparece mais: remova a linha",
                                    key, [Local("workspace", "tools/contratos/conhecidos.txt")]))
    order = {"erro": 0, "conhecido": 1, "aviso": 2}
    return sorted(findings, key=lambda f: (order[f.severidade], f.id, f.chave))
