"""O que os scripts Python de bin/ e os hooks compartilham: onde ficam os repositórios, quais
são e uma impressão digital do estado deles.

Mesmas regras do bin/ws (que é bash e repete a resolução do diretório).
"""
import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def repos_dir() -> Path:
    # Num worktree deste repo não existe repos/ (não é versionado): usa o do checkout principal.
    if os.environ.get("OFICINA_REPOS_DIR"):
        return Path(os.environ["OFICINA_REPOS_DIR"])
    local = ROOT / "repos"
    if local.exists():
        return local
    common = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True,
    )
    return Path(common.stdout.strip()).parent / "repos" if common.returncode == 0 else local


def repo_names() -> list[str]:
    """Os repositórios de repos.txt, na ordem de apply."""
    names = []
    for line in (ROOT / "repos.txt").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line.split()[0])
    return names


def fingerprint() -> str:
    """Hash do estado de trabalho do workspace e dos repos: HEAD, arquivos alterados e o conteúdo
    deles. Muda quando alguém edita, cria, apaga ou commita; não muda com o que o .gitignore
    ignora (vendor/, .terraform/, .ws/)."""
    h = hashlib.sha256()
    base = repos_dir()
    for path in [ROOT, *(base / n for n in repo_names())]:
        if not path.is_dir():
            continue
        git = lambda *a: subprocess.run(["git", "-C", str(path), *a], capture_output=True).stdout  # noqa: E731
        status = git("status", "--porcelain", "-uall")
        h.update(str(path).encode() + git("rev-parse", "HEAD") + status + git("diff", "HEAD"))
        for line in status.decode(errors="ignore").splitlines():
            if line.startswith("??"):
                f = path / line[3:]
                h.update(f.read_bytes() if f.is_file() else b"")
    return h.hexdigest()


def resolve_repo(arg: str, names: list[str]) -> str:
    """Aceita o nome inteiro ou uma parte dele: api, gateway, cluster, fundacao."""
    if arg in names:
        return arg
    found = [n for n in names if arg in n.split("-")[1:]]
    if len(found) != 1:
        raise SystemExit(f"repositório {'ambíguo' if found else 'desconhecido'}: {arg} (opções: {', '.join(names)})")
    return found[0]
