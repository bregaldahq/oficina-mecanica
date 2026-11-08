#!/usr/bin/env python3
"""Roda localmente, sem AWS, o que o pr.yml de cada repositório roda.

Cada passo espelha um step do CI e roda na imagem de bin/tooling. As migrations (num MySQL 8.0
de verdade) e a imagem de produção rodam direto no Docker. Os repositórios rodam em paralelo.

Uso: bin/ws verify [--repo NOME]... [--changed] [--fast] [--image] [--json]

  --repo NOME  só esse repositório; aceita o nome curto (fundacao, cluster, gateway, api,
               workspace) e pode repetir
  --changed    só os repos com arquivo sujo, ou numa branch de trabalho com commits fora de
               origin/develop
  --fast       pula as migrations num MySQL de verdade, o passo mais lento
  --image      inclui o build da imagem de produção da aplicação (lento)
  --json       imprime o resultado em JSON

O resultado também vai para .ws/verify/latest.json, e o log de cada passo para
.ws/verify/logs/<repo>-<passo>.log. Sai com 1 se algum passo bloqueante falhar. Passo não
bloqueante (o tflint, que no CI tem continue-on-error, e o actionlint, que não está no CI) só
gera aviso.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

from wslib import ROOT, repo_names, repos_dir, resolve_repo

TOOLING = ROOT / "bin" / "tooling"
OUT = ROOT / ".ws" / "verify"
WORKSPACE = "workspace"


@dataclass
class Step:
    id: str
    run: Callable[[Path, TextIO], bool]
    mirrors: str
    blocking: bool = True
    slow: bool = False   # pulado com --fast
    image: bool = False  # só com --image


def sh(cmd: list[str], log: TextIO, **kwargs) -> bool:
    log.write("$ " + " ".join(cmd) + "\n")
    log.flush()
    return subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, **kwargs).returncode == 0


def tool(script: str) -> Callable[[Path, TextIO], bool]:
    """Roda um trecho de shell na imagem de ferramentas, com o repo montado em /w."""
    return lambda repo, log: sh([str(TOOLING), "run", str(repo), "sh", "-ec", script], log)


TF_FMT = tool("terraform fmt -check -recursive -diff")


def tf_validate(repo: Path, log: TextIO) -> bool:
    # Lock versionado (gateway): o init local não pode reescrevê-lo. Sem lock versionado (a
    # fundação e o cluster o ignoram), faz o mesmo que o CI e resolve os providers na hora.
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", ".terraform.lock.hcl"],
                             capture_output=True).returncode == 0
    lock = " -lockfile=readonly" if tracked else ""
    return tool(f"terraform init -backend=false -input=false{lock} -no-color >/dev/null"
                " && terraform validate -no-color")(repo, log)


TF_VALIDATE = tf_validate
COMPOSER = tool("composer install --no-interaction --prefer-dist --no-progress")
ACTIONLINT = tool("actionlint")

FORBIDDEN_SQL = re.compile(r"^\s*(CREATE DATABASE|USE |DELIMITER)", re.I | re.M)


def sql_lint(repo: Path, log: TextIO) -> bool:
    bad = []
    for path in sorted((repo / "migrations").glob("*.sql")):
        text = path.read_text(errors="ignore")
        for m in FORBIDDEN_SQL.finditer(text):
            bad.append(f"migrations/{path.name}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(0).strip()}")
    log.write("\n".join(bad) + "\n" if bad else "nenhum CREATE DATABASE, USE ou DELIMITER\n")
    return not bad


def migrations_twice(repo: Path, log: TextIO) -> bool:
    """Igual ao job sql-lint do pr.yml: aplica tudo, reaplica tudo e confere o seed."""
    name = f"oficina-verify-mysql-{os.getpid()}"
    files = sorted((repo / "migrations").glob("*.sql"))
    if not sh(["docker", "run", "-d", "--rm", "--name", name, "-e", "MYSQL_ROOT_PASSWORD=root",
               "-e", "MYSQL_DATABASE=oficina_mecanica", "mysql:8.0"], log):
        return False
    mysql = ["docker", "exec", "-i", name, "mysql", "-h127.0.0.1", "-uroot", "-proot", "oficina_mecanica"]
    try:
        # O entrypoint sobe um servidor temporário, sem rede, antes do definitivo: por TCP só o
        # definitivo responde.
        for _ in range(90):
            if subprocess.run(mysql + ["-e", "SELECT 1"], capture_output=True).returncode == 0:
                break
            time.sleep(2)
        else:
            log.write("o MySQL não ficou pronto em 180 s\n")
            return False
        for rodada in ("aplicando", "reaplicando"):
            for path in files:
                log.write(f"== {rodada} {path.name}\n")
                log.flush()
                with path.open("rb") as sql:
                    if subprocess.run(mysql, stdin=sql, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
                        log.write(f"falhou em {path.name} ({rodada}): a migration não é idempotente\n")
                        return False
        out = subprocess.run(mysql + ["-N", "-e", "SELECT COUNT(DISTINCT status) FROM service_orders"],
                             capture_output=True, text=True)
        log.write(f"status distintos no seed: {out.stdout.strip()}\n")
        if out.stdout.strip() != "7":
            log.write("o seed precisa cobrir os 7 status da máquina de estados\n")
            return False
        return True
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def app_image(repo: Path, log: TextIO) -> bool:
    # O PR só valida que a imagem constrói e que o agente do New Relic carrega (exige glibc).
    return (sh(["docker", "build", "--target", "production", "-t", "oficina-api:verify", str(repo)], log)
            and sh(["sh", "-c", "docker run --rm oficina-api:verify php -m | grep -qi newrelic"], log))


def python_compiles(repo: Path, log: TextIO) -> bool:
    files = sorted([*repo.glob("bin/*.py"), *repo.glob("tools/**/*.py"), *repo.glob("tests/*.py")])
    return sh([sys.executable, "-m", "py_compile", *map(str, files)], log)


def unittests(repo: Path, log: TextIO) -> bool:
    return sh([sys.executable, "-m", "unittest", "discover", "-s", str(repo / "tests")], log, cwd=repo)


def contracts(repo: Path, log: TextIO) -> bool:
    return sh([sys.executable, str(repo / "bin" / "check-contracts.py")], log)


STEPS: dict[str, list[Step]] = {
    "oficina-infra-fundacao": [
        Step("tf-fmt", TF_FMT, "pr.yml: terraform fmt"),
        Step("tf-validate", TF_VALIDATE, "pr.yml: terraform validate (aqui sem backend)"),
        Step("sql-lint", sql_lint, "pr.yml: sem CREATE DATABASE, USE nem DELIMITER"),
        Step("migrations-2x", migrations_twice, "pr.yml: migrations duas vezes num MySQL 8.0 e seed", slow=True),
        Step("actionlint", ACTIONLINT, "fora do CI", blocking=False),
    ],
    "oficina-infra-cluster": [
        Step("tf-fmt", TF_FMT, "pr.yml: terraform fmt"),
        Step("tf-validate", TF_VALIDATE, "pr.yml: terraform validate"),
        Step("tflint", tool("tflint --init >/dev/null && tflint --recursive"),
             "pr.yml: tflint (continue-on-error)", blocking=False),
        Step("actionlint", ACTIONLINT, "fora do CI", blocking=False),
    ],
    "oficina-gateway-auth": [
        Step("composer", COMPOSER, "pr.yml: composer install"),
        Step("phpunit-contract", tool("vendor/bin/phpunit --testsuite contract"), "pr.yml: contrato do JWT"),
        Step("phpunit", tool("vendor/bin/phpunit"), "pr.yml: testes"),
        Step("phpstan", tool("vendor/bin/phpstan analyse --no-progress"), "pr.yml: PHPStan nível 8"),
        Step("tf-fmt", TF_FMT, "pr.yml: terraform fmt"),
        Step("tf-validate", TF_VALIDATE, "pr.yml: terraform validate"),
        Step("actionlint", ACTIONLINT, "fora do CI", blocking=False),
    ],
    "oficina-api": [
        Step("composer", COMPOSER, "pr.yml: composer install"),
        # --using-cache=no: o .php-cs-fixer.cache da aplicação é versionado e o dry-run o reescreve.
        Step("cs-fixer", tool("PHP_CS_FIXER_IGNORE_ENV=1 vendor/bin/php-cs-fixer fix --dry-run --diff --using-cache=no"),
             "pr.yml: estilo (PSR-12)"),
        Step("phpstan", tool("vendor/bin/phpstan analyse --no-progress --memory-limit=512M"), "pr.yml: PHPStan"),
        Step("phpunit", tool("vendor/bin/phpunit --no-coverage"), "pr.yml: testes unitários e de integração"),
        Step("kustomize", tool("kustomize build deploy/overlays/hml >/dev/null"
                               " && kustomize build deploy/overlays/prod >/dev/null"), "pr.yml: manifests"),
        Step("image", app_image, "pr.yml: build da imagem e extensão New Relic", image=True),
        Step("actionlint", ACTIONLINT, "fora do CI", blocking=False),
    ],
    WORKSPACE: [
        Step("shellcheck", tool("shellcheck bin/ws bin/tooling .claude/hooks/*.sh"), "-"),
        Step("python", python_compiles, "-"),
        Step("testes", unittests, "tests/ (checker de contratos)"),
        Step("contratos", contracts, "bin/check-contracts.py"),
    ],
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout.strip()


def changed(repo: Path) -> bool:
    if git(repo, "status", "--porcelain"):
        return True
    if git(repo, "branch", "--show-current") in ("", "main", "develop"):
        return False
    for base in ("origin/develop", "origin/main"):  # este repo só tem main
        if git(repo, "rev-parse", "--verify", "-q", base):
            return int(git(repo, "rev-list", "--count", f"{base}..HEAD") or 0) > 0
    return True


def tail(path: Path, n: int) -> list[str]:
    lines = [ln for ln in path.read_text(errors="ignore").splitlines() if ln.strip()]
    return lines[-n:]


class Printer:
    def __init__(self, stream: TextIO):
        self.stream = stream
        self.lock = threading.Lock()

    def line(self, text: str) -> None:
        with self.lock:
            print(text, file=self.stream, flush=True)


def run_repo(name: str, path: Path, args, out: Printer) -> dict:
    short = name.removeprefix("oficina-").removeprefix("infra-").split("-")[0]
    result = {"repo": name, "branch": git(path, "branch", "--show-current"), "steps": []}
    for step in STEPS[name]:
        entry = {"id": step.id, "mirrors": step.mirrors, "blocking": step.blocking}
        if (step.slow and args.fast) or (step.image and not args.image):
            entry["status"] = "pulado"
        else:
            log_path = OUT / "logs" / f"{name}-{step.id}.log"
            start = time.monotonic()
            with log_path.open("w") as log:
                try:
                    ok = step.run(path, log)
                except Exception as exc:  # um passo quebrado não derruba os outros repos
                    log.write(f"erro ao rodar o passo: {exc!r}\n")
                    ok = False
            entry.update({
                "status": "ok" if ok else ("falhou" if step.blocking else "aviso"),
                "duration_s": round(time.monotonic() - start),
                "log": str(log_path.relative_to(ROOT)),
            })
            if not ok:
                entry["summary"] = " | ".join(tail(log_path, 3))
        result["steps"].append(entry)
        dur = f"{entry['duration_s']:>3}s" if "duration_s" in entry else "    "
        out.line(f"{short:<10} {step.id:<17} {entry['status']:<7} {dur}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--changed", action="store_true")
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--image", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()
    if args.help:
        print(__doc__.strip())
        return 0

    names = repo_names()
    base = repos_dir()
    paths = {n: base / n for n in names} | {WORKSPACE: ROOT}
    selected = [resolve_repo(r, names + [WORKSPACE]) for r in args.repo] or names + [WORKSPACE]
    missing = [n for n in selected if not paths[n].is_dir()]
    selected = [n for n in selected if n not in missing]
    if args.changed:
        selected = [n for n in selected if changed(paths[n])]

    out = Printer(sys.stderr if args.json else sys.stdout)
    for n in missing:
        out.line(f"{n}: ausente em {base} (rode bin/ws clone)")
    if not selected:
        out.line("nada para verificar" + (" (nenhum repo com mudanças)" if args.changed else ""))
        return 1 if missing else 0

    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        out.line("o Docker não está rodando")
        return 1
    # Constrói a imagem uma vez só, antes de os repos rodarem em paralelo.
    if subprocess.run([str(TOOLING), "image"], stdout=subprocess.DEVNULL).returncode != 0:
        return 1

    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    started = datetime.now().astimezone()
    with ThreadPoolExecutor(max_workers=len(selected)) as pool:
        results = list(pool.map(lambda n: run_repo(n, paths[n], args, out), selected))

    failed = [(r["repo"], s) for r in results for s in r["steps"] if s["status"] in ("falhou", "aviso")]
    ok = not missing and not any(s["status"] == "falhou" for _, s in failed)
    report = {
        "started_at": started.isoformat(timespec="seconds"),
        "duration_s": round((datetime.now().astimezone() - started).total_seconds()),
        "ok": ok,
        "mode": {"changed": args.changed, "fast": args.fast, "image": args.image},
        "missing": missing,
        "repos": results,
    }
    (OUT / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for repo, step in failed:
            print(f"\n── {repo} / {step['id']} ({step['status']}) — {step['log']}")
            print("\n".join(tail(ROOT / step["log"], 40)))
        print(f"\n{'OK' if ok else 'FALHOU'} em {report['duration_s']}s. Resultado em .ws/verify/latest.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
