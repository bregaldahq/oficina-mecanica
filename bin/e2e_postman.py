#!/usr/bin/env python3
"""A coleção Postman da Fase 4 contra os três serviços de verdade, local e sem AWS.

Sobe o mesmo ambiente do e2e da Fase 4 (LocalStack com SNS, SQS e DynamoDB, o MySQL de cada
serviço, as três APIs) e acrescenta o que o e2e não tem: os três workers em laço, como os
Deployments, e um gateway local (tools/e2e/gateway.php) que roteia por prefixo e roda a Lambda
auth-cpf. Então roda oficina-api/docs/fase-4/postman/ com tools/e2e/postman-runner.js (Node, sem
newman). O pagamento que em hml o cliente faz no sandbox é feito pelo webhook assinado do Mercado
Pago falso, logo depois da requisição que mostra o link.

Uso: bin/ws e2e --postman [--keep]
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_fase4 import TOOLING, Fase4E2E  # noqa: E402
from wslib import ROOT, repos_dir  # noqa: E402

COLLECTION = Path("docs/fase-4/postman/oficina-fase4.postman_collection.json")
ENVIRONMENT = Path("docs/fase-4/postman/hml.postman_environment.json")
SERVICES = ("os", "faturamento", "execucao")
PAY_AFTER = "link de pagamento"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def runner_command(collection: Path, environment: Path, base_url: str, admin_password: str, webhook_token: str) -> list[str]:
    return ["node", str(ROOT / "tools" / "e2e" / "postman-runner.js"), str(collection), str(environment),
            "--set", f"baseUrl={base_url}", "--set", f"adminPassword={admin_password}",
            "--set", f"webhookToken={webhook_token}", "--pay-after", PAY_AFTER, "--retries", "20", "--delay", "1500"]


class PostmanE2E:
    def __init__(self):
        self.passed = self.failed = 0
        self.fase4 = Fase4E2E(self.check)
        self.gateway = f"{self.fase4.net}-gateway"
        self.workers = [f"{self.fase4.net}-worker-{s}" for s in SERVICES]
        self.port = free_port()

    def check(self, desc: str, ok: bool, detail: str = "") -> bool:
        print(f"  {'ok   ' if ok else 'FALHA'}  {desc}" + ("" if ok or not detail else f"  ({detail[:200]})"), flush=True)
        self.passed += ok
        self.failed += not ok
        return ok

    def start_workers(self) -> None:
        for service, container in zip(SERVICES, self.workers):
            self.fase4.php("sh", "-c", "while :; do php bin/worker.php >/dev/null 2>&1; sleep 0.5; done",
                           detach=True, service=service, container=container)

    def start_gateway(self) -> bool:
        f4 = self.fase4
        image = subprocess.run([str(TOOLING), "image"], capture_output=True, text=True, check=True).stdout.strip()
        env = {"JWT_SECRET": f4.env["JWT_SECRET"], "JWT_EXPIRATION": f4.env["JWT_EXPIRATION"],
               "INTERNAL_TOKEN": f4.os_env["INTERNAL_TOKEN"], "MP_WEBHOOK_SECRET": f4.billing_env["MP_WEBHOOK_SECRET"],
               "OS_URL": f"http://{f4.os_app}:8080", "BILLING_URL": f"http://{f4.billing_app}:8080",
               "EXECUTION_URL": f"http://{f4.app}:8080"}
        cmd = ["docker", "run", "-d", "--rm", "--name", self.gateway, "--network", f4.net, "-p", f"127.0.0.1:{self.port}:8080",
               "-u", f"{os.getuid()}:{os.getgid()}", "-v", f"{(repos_dir() / 'oficina-gateway-auth').resolve()}:/gateway:ro",
               "-v", f"{(ROOT / 'tools' / 'e2e').resolve()}:/e2e:ro", "-w", "/e2e"]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        started = subprocess.run(cmd + [image, "php", "-S", "0.0.0.0:8080", "gateway.php"], capture_output=True, text=True)
        if started.returncode != 0:
            return self.check("gateway local de pé", False, started.stderr[-200:])
        for _ in range(30):
            probe = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"http://127.0.0.1:{self.port}/api/health"],
                                   capture_output=True, text=True)
            if probe.stdout == "200":
                return self.check("gateway local de pé, roteando para os três serviços", True)
            time.sleep(1)
        return self.check("gateway local de pé", False, "GET /api/health pelo gateway não respondeu")

    def run(self) -> int:
        f4 = self.fase4
        print("Postman da Fase 4: a coleção inteira contra os três serviços, por um gateway local", flush=True)
        if not (f4.saga_available() and f4.up() and f4.billing_up() and f4.os_up()):
            return 1
        self.start_workers()
        if not self.start_gateway():
            return 1
        api = repos_dir() / "oficina-api"
        print("\ncoleção oficina-api/" + str(COLLECTION), flush=True)
        out = subprocess.run(runner_command(api / COLLECTION, api / ENVIRONMENT, f"http://127.0.0.1:{self.port}",
                                            f4.os_env["ADMIN_PASSWORD"], f4.billing_env["WEBHOOK_TOKEN"]))
        self.check("coleção Postman da Fase 4 inteira", out.returncode == 0)
        print(f"\n{self.passed} ok, {self.failed} falha(s)")
        return 1 if self.failed else 0

    def down(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.gateway, *self.workers], capture_output=True)
        self.fase4.down()


def main() -> int:
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("o Docker não está rodando")
        return 1
    e2e = PostmanE2E()
    try:
        return e2e.run()
    finally:
        if "--keep" in sys.argv:
            print(f"containers de pé na rede {e2e.fase4.net}; gateway em http://127.0.0.1:{e2e.port}")
        else:
            e2e.down()


if __name__ == "__main__":
    sys.exit(main())
