"""DOC-1: todo caminho citado no contexto dos agentes existe. Contexto apontando para arquivo que
não existe mais leva o agente a procurar no lugar errado, ou a concluir que algo sumiu.
"""
import re

from . import REPOS, Finding, Local, Repos

CONTEXT = ["AGENTS.md", "CLAUDE.md", "README.md"]
PREFIXES = ("repos/", "bin/", ".claude/", "tools/", "tooling/", "docs/", "src/", "deploy/", "migrations/",
            "scripts/", "tests/", "envs/", "public/")


def candidates(text: str):
    for m in re.finditer(r"`([^`\s]+)`", text):
        path = m.group(1).rstrip(".,:;)")
        if path.startswith(PREFIXES) and not re.search(r"[<>*{}$]|\.\.\.|…", path):
            yield path, text.count("\n", 0, m.start()) + 1


def exists(repos: Repos, path: str) -> bool:
    if (repos.workspace / path).exists():
        return True
    if path.startswith("repos/"):
        parts = path.split("/", 2)
        short = next((s for s, (new, _) in REPOS.items() if new == parts[1]), None)
        return bool(short and repos.has(short) and (len(parts) < 3 or (repos.path(short) / parts[2]).exists()))
    # Caminho relativo a um repo de produto (ex.: src/Domain/, migrations/NNN...).
    return any(repos.has(s) and (repos.path(s) / path).exists() for s in REPOS)


def check(repos: Repos) -> list[Finding]:
    files = CONTEXT + [str(p.relative_to(repos.workspace)) for p in sorted((repos.workspace / ".claude").glob("*/**/*.md"))
                       if "worktrees" not in p.parts]
    out = []
    for rel in files:
        path = repos.workspace / rel
        if not path.is_file():
            continue
        for cited, line in candidates(path.read_text(errors="ignore")):
            if not exists(repos, cited):
                out.append(Finding("DOC-1", "aviso", "contexto", f"{rel} cita `{cited}`, que não existe em nenhum repo",
                                   f"{rel} {cited}", [Local("workspace", rel, line)]))
    return out
