#!/usr/bin/env python3
"""Ponta a ponta entre os repositórios, local e sem AWS.

Sobe um MySQL 8.0, aplica as migrations da fundação pelo runner da aplicação (bin/migrate.php,
duas vezes) e sobe a aplicação (php -S). Depois usa as Lambdas do gateway como classes
(tools/e2e/lambda.php) para conferir o caminho inteiro:

- login do admin;
- token do cliente emitido pela auth-cpf e aceito pela aplicação;
- o jwt-authorizer;
- a matriz de autorização;
- o webhook.

Usa a branch que estiver em disco em cada repo.

Uso: bin/ws e2e [--keep]     --keep deixa os containers de pé para investigar
"""
import json
import os
import secrets
import subprocess
import sys
import time

from wslib import ROOT, repos_dir

TOOLING = ROOT / "bin" / "tooling"


class E2E:
    def __init__(self):
        base = repos_dir()
        self.api, self.gateway, self.fundacao = (base / n for n in ("oficina-api", "oficina-gateway-auth", "oficina-infra-fundacao"))
        self.net = f"oficina-e2e-{os.getpid()}"
        self.db, self.app = f"{self.net}-db", f"{self.net}-app"
        self.env = {
            "DB_HOST": self.db, "DB_PORT": "3306", "DB_DATABASE": "oficina_mecanica", "DB_USERNAME": "root",
            "DB_PASSWORD": "root", "JWT_SECRET": secrets.token_hex(32), "JWT_EXPIRATION": "3600",
            "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": secrets.token_hex(12), "WEBHOOK_TOKEN": secrets.token_hex(16),
            "APP_ENV": "hml",  # o seed _demo só roda fora de produção
            "MIGRATIONS_PATH": "/migrations",  # as da fundação, como no Job oficina-migrate
        }
        self.passed = self.failed = 0

    def check(self, desc: str, ok: bool, detail: str = "") -> bool:
        print(f"  {'ok   ' if ok else 'FALHA'}  {desc}" + ("" if ok or not detail else f"  ({detail[:200]})"), flush=True)
        self.passed += ok
        self.failed += not ok
        return ok

    def php(self, *args: str, detach: bool = False, name: str = "") -> subprocess.CompletedProcess:
        """Roda na imagem de ferramentas, na rede do e2e, com a app em /w e o gateway em /gateway."""
        image = subprocess.run([str(TOOLING), "image"], capture_output=True, text=True, check=True).stdout.strip()
        cmd = ["docker", "run", "--rm", "--network", self.net, "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
               "-v", f"{self.api.resolve()}:/w", "-v", f"{self.gateway.resolve()}:/gateway:ro",
               "-v", f"{(self.fundacao / 'migrations').resolve()}:/migrations:ro",
               "-v", f"{(ROOT / 'tools' / 'e2e').resolve()}:/e2e:ro", "-w", "/w"]
        if (self.api / ".env").exists():  # a app carrega o .env e ele sobrescreveria este ambiente
            cmd += ["-v", "/dev/null:/w/.env:ro"]
        for key, value in self.env.items():
            cmd += ["-e", f"{key}={value}"]
        if detach:
            cmd[2:2] = ["-d", "--name", name]
        return subprocess.run(cmd + [image, *args], capture_output=True, text=True)

    def http(self, method: str, path: str, token: str = "", body: dict | None = None, headers: dict | None = None):
        cmd = ["docker", "exec", self.app, "curl", "-s", "-X", method, "-w", "\n%{http_code}", f"http://127.0.0.1:8080{path}"]
        if token:
            cmd += ["-H", f"Authorization: Bearer {token}"]
        for key, value in (headers or {}).items():
            cmd += ["-H", f"{key}: {value}"]
        if body is not None:
            cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        text, _, status = out.rpartition("\n")
        return int(status or 0), text

    def lambda_(self, *args: str) -> dict:
        out = self.php("php", "/e2e/lambda.php", *args)
        try:
            return json.loads(out.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return {"erro": (out.stdout + out.stderr).strip()[-300:]}

    def sql(self, query: str) -> str:
        return subprocess.run(["docker", "exec", self.db, "mysql", "-h127.0.0.1", "-uroot", "-proot", "-N", "-e", query,
                               "oficina_mecanica"], capture_output=True, text=True).stdout.strip()

    def up(self) -> bool:
        for repo in (self.api, self.gateway):
            if not (repo / "vendor" / "autoload.php").is_file():
                print(f"composer install em {repo.name}...", flush=True)
                subprocess.run([str(TOOLING), "run", str(repo), "composer", "install", "--no-interaction", "--quiet"], check=True)
        subprocess.run(["docker", "network", "create", self.net], capture_output=True, check=True)
        subprocess.run(["docker", "run", "-d", "--rm", "--name", self.db, "--network", self.net, "-e", "MYSQL_ROOT_PASSWORD=root",
                        "-e", "MYSQL_DATABASE=oficina_mecanica", "mysql:8.0"], capture_output=True, check=True)
        for _ in range(90):  # por TCP só responde o servidor definitivo, não o temporário do entrypoint
            if subprocess.run(["docker", "exec", self.db, "mysql", "-h127.0.0.1", "-uroot", "-proot", "-e", "SELECT 1"],
                              capture_output=True).returncode == 0:
                return True
            time.sleep(2)
        return self.check("MySQL de pé", False, "não respondeu em 180 s")

    def run(self) -> int:
        print(f"e2e: {self.api.name}, {self.gateway.name} e {self.fundacao.name}, na branch em disco de cada um", flush=True)
        if not self.up():
            return 1

        print("migrations (fundação, pelo runner da aplicação)")
        for rodada in ("1ª vez", "2ª vez, idempotente"):
            out = self.php("php", "bin/migrate.php")
            self.check(f"bin/migrate.php, {rodada}", out.returncode == 0, out.stdout[-200:] + out.stderr[-200:])
        self.php("php", "-S", "0.0.0.0:8080", "-t", "public", "public/index.php", detach=True, name=self.app)
        for _ in range(30):
            if self.http("GET", "/api/health")[0] == 200:
                break
            time.sleep(1)

        print("aplicação")
        self.check("GET /api/health 200", self.http("GET", "/api/health")[0] == 200)
        status, body = self.http("GET", "/api/ready")
        self.check("GET /api/ready 200 (toca o banco)", status == 200, body)
        status, body = self.http("POST", "/api/auth/login", body={"username": "admin", "password": self.env["ADMIN_PASSWORD"]})
        admin = json.loads(body).get("token", "") if status == 200 else ""
        self.check("POST /api/auth/login devolve o token do admin", bool(admin), f"{status} {body}")
        self.check("GET /api/customers com token de admin: 200", self.http("GET", "/api/customers", admin)[0] == 200)
        self.check("GET /api/customers sem token: 401", self.http("GET", "/api/customers")[0] == 401)

        print("gateway: Lambda auth-cpf e jwt-authorizer contra a aplicação")
        row = self.sql("SELECT document, id FROM customers WHERE status = 'ACTIVE' AND LENGTH(document) = 11 LIMIT 1").split()
        if not self.check("o seed tem cliente ACTIVE com CPF", len(row) == 2):
            return self.finish()
        cpf, customer_id = row
        resp = self.lambda_("auth", cpf)
        token = json.loads(resp.get("body", "{}")).get("token", "") if resp.get("statusCode") == 200 else ""
        self.check("auth-cpf: CPF de cliente ativo devolve 200 e token", bool(token), json.dumps(resp))
        self.check("auth-cpf: CPF com dígito inválido devolve 400", self.lambda_("auth", "12345678900").get("statusCode") == 400)
        self.check("auth-cpf: CPF válido não cadastrado devolve 404", self.lambda_("auth", "52998224725").get("statusCode") == 404)
        auth = self.lambda_("authorize", token, "GET", "/api/service-orders/me")
        self.check("jwt-authorizer aceita o token da auth-cpf (role=customer, customerId certo)",
                   auth.get("isAuthorized") is True and auth.get("context", {}).get("role") == "customer"
                   and auth.get("context", {}).get("customerId") == customer_id, json.dumps(auth))
        auth = self.lambda_("authorize", admin, "GET", "/api/customers")
        self.check("jwt-authorizer aceita o token de admin emitido pela aplicação",
                   auth.get("isAuthorized") is True and auth.get("context", {}).get("role") == "admin", json.dumps(auth))
        self.check("jwt-authorizer recusa token adulterado",
                   self.lambda_("authorize", token[:-2] + "xx", "GET", "/api/service-orders/me").get("isAuthorized") is False)
        status, body = self.http("GET", "/api/service-orders/me", token)
        self.check("a aplicação aceita o token emitido pela Lambda: GET /api/service-orders/me 200", status == 200, f"{status} {body}")
        self.check("token de cliente em rota de admin: 403", self.http("GET", "/api/customers", token)[0] == 403)

        order = self.sql("SELECT id FROM service_orders WHERE status = 'AWAITING_APPROVAL' LIMIT 1")
        if order:
            status = self.http("POST", f"/api/service-orders/{order}/approval", body={"approved": True},
                               headers={"X-Webhook-Token": "errado"})[0]
            self.check("webhook de aprovação com X-Webhook-Token errado: 401/403", status in (401, 403), str(status))
        return self.finish()

    def finish(self) -> int:
        print(f"\n{self.passed} ok, {self.failed} falha(s)")
        return 1 if self.failed else 0

    def down(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.app, self.db], capture_output=True)
        subprocess.run(["docker", "network", "rm", self.net], capture_output=True)


def main() -> int:
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__.strip())
        return 0
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("o Docker não está rodando")
        return 1
    e2e = E2E()
    try:
        return e2e.run()
    finally:
        if "--keep" in sys.argv:
            print(f"containers de pé: {e2e.db}, {e2e.app} (rede {e2e.net}); para tirar: "
                  f"docker rm -f {e2e.app} {e2e.db} && docker network rm {e2e.net}")
        else:
            e2e.down()


if __name__ == "__main__":
    sys.exit(main())
