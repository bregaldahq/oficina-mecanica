"""O que os scripts Python de bin/ compartilham: onde ficam os repositórios e quais são.

Mesmas regras do bin/ws (que é bash e repete a resolução do diretório).
"""
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


def resolve_repo(arg: str, names: list[str]) -> str:
    """Aceita o nome inteiro ou uma parte dele: api, gateway, cluster, fundacao."""
    if arg in names:
        return arg
    found = [n for n in names if arg in n.split("-")[1:]]
    if len(found) != 1:
        raise SystemExit(f"repositório {'ambíguo' if found else 'desconhecido'}: {arg} (opções: {', '.join(names)})")
    return found[0]
