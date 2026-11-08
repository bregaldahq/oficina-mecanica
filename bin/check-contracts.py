#!/usr/bin/env python3
"""Confere o acoplamento por SSM entre os repositórios.

Varre repos/ atrás de nomes de parâmetro /oficina/<env>/..., separa quem
publica (resource "aws_ssm_parameter") de quem consome (qualquer outra menção)
e aponta:

  - parâmetro consumido que ninguém publica  -> erro (apply quebra)
  - parâmetro publicado por mais de um repo  -> erro (dois donos)
  - parâmetro publicado que ninguém consome  -> aviso

Sai com código 1 se houver erro. Uso: bin/check-contracts.py [--verbose]
"""
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def repos_dir() -> Path:
    # Mesma regra do bin/ws: num worktree sem repos/, usa o do checkout principal.
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


REPOS = repos_dir()
EXTENSIONS = {".tf", ".yml", ".yaml", ".sh", ".php", ".py", ".json"}

# Aceita as três formas de escrever o ambiente que aparecem nos repos:
# ${var.environment}, ${ENVIRONMENT} / $ENVIRONMENT e <env>.
ENV = r"(?:\$\{[^}]+\}|\$[A-Za-z_]+|<env>|hml|prod)"
PARAM = re.compile(r"/oficina/" + ENV + r"/([a-z_]+/[a-z_]+)")
RESOURCE = re.compile(r'resource\s+"aws_ssm_parameter"\s+"[^"]+"\s*\{(.*?)\n\}', re.S)


def files(repo: Path):
    # Só arquivos versionados: ignora vendor/, .terraform/ e clones aninhados.
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True)
    for rel in tracked.stdout.splitlines():
        path = repo / rel
        if path.suffix in EXTENSIONS and path.is_file():
            yield path


def main() -> int:
    verbose = "--verbose" in sys.argv
    repos = sorted(p for p in REPOS.iterdir() if p.is_dir()) if REPOS.exists() else []
    if not repos:
        print("Nenhum repositório em repos/. Rode bin/ws clone primeiro.")
        return 1

    producers = defaultdict(set)
    consumers = defaultdict(set)
    for repo in repos:
        for path in files(repo):
            text = path.read_text(errors="ignore")
            published = set()
            if path.suffix == ".tf":
                for block in RESOURCE.findall(text):
                    published |= set(PARAM.findall(block))
            for name in published:
                producers[name].add(repo.name)
            for name in set(PARAM.findall(text)) - published:
                consumers[name].add(repo.name)

    errors = 0
    for name in sorted(consumers):
        if name not in producers:
            errors += 1
            print(f"ERRO  /oficina/<env>/{name} consumido por {', '.join(sorted(consumers[name]))}, mas ninguém publica")
    for name in sorted(producers):
        if len(producers[name]) > 1:
            errors += 1
            print(f"ERRO  /oficina/<env>/{name} publicado por mais de um repo: {', '.join(sorted(producers[name]))}")
        elif not consumers.get(name, set()) - producers[name]:
            print(f"aviso /oficina/<env>/{name} publicado por {next(iter(producers[name]))}, sem consumidor em outro repo")

    if verbose:
        print()
        for name in sorted(set(producers) | set(consumers)):
            print(f"/oficina/<env>/{name}")
            print(f"   publica: {', '.join(sorted(producers.get(name, []))) or '-'}")
            print(f"   consome: {', '.join(sorted(consumers.get(name, []))) or '-'}")

    print(f"\n{len(producers)} publicados, {len(consumers)} consumidos, {errors} erro(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
