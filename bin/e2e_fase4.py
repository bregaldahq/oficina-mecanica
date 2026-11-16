"""Ponta a ponta da Fase 4, local e sem AWS: os microsserviços contra o LocalStack.

Sobe um LocalStack (SNS, SQS e DynamoDB), cria os recursos com o script do próprio serviço
(scripts/localstack-init.sh) e faz o papel do orquestrador da saga: publica os comandos no
tópico, age como o mecânico pela API e lê, numa fila de sonda, o que o serviço publicou.

Cobre o que os testes do repo, com adaptadores em memória, não alcançam: o desenho da tabela
num DynamoDB de verdade, a transação com inbox e outbox, o filtro da assinatura e o worker.

Serviços cobertos: Execução (DynamoDB) e, se estiver em disco, Faturamento (MySQL próprio,
com as migrations do repo e o meio de pagamento falso, mas o webhook assinado de verdade).
"""
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import time

from wslib import ROOT, repos_dir

TOOLING = ROOT / "bin" / "tooling"
# Fixada: é a última linha que roda sem conta nem token.
LOCALSTACK_IMAGE = "localstack/localstack:3.8"
# O que o serviço de OS consome da Execução (docs/fase-4/CONTRATOS.md §5.3): o filtro da sonda.
EXECUTION_EVENTS = ["diagnosis.started", "diagnosis.completed", "diagnosis.failed", "repair.started",
                    "repair.completed", "repair.failed", "execution.cancelled"]
BILLING_EVENTS = ["budget.generated", "budget.failed", "budget.approved", "budget.rejected", "budget.cancelled",
                  "payment.created", "payment.confirmed", "payment.failed", "payment.refunded"]
# Do seed 002_catalogo_demo.sql do Faturamento (os mesmos ids da Fase 3).
SEED_SERVICE = ("c597dc97-5a51-497c-acdb-3ae16aab815e", 180.00)  # troca de óleo e filtro
SEED_PART = ("b4e35f65-d29c-5474-b009-21263ff5c64f", 189.00, 60)  # pastilha de freio, 60 em estoque


class Fase4E2E:
    def __init__(self, check):
        self.check = check
        self.repo = repos_dir() / "oficina-execucao"
        self.billing = repos_dir() / "oficina-faturamento"
        self.os_repo = repos_dir() / "oficina-api"
        self.fundacao = repos_dir() / "oficina-infra-fundacao"
        self.net = f"oficina-e2e4-{os.getpid()}"
        self.ls, self.app = f"{self.net}-aws", f"{self.net}-execucao"
        self.db, self.billing_app = f"{self.net}-db", f"{self.net}-faturamento"
        self.os_db, self.os_app = f"{self.net}-os-db", f"{self.net}-os"
        self.env = {"JWT_SECRET": secrets.token_hex(32), "JWT_EXPIRATION": "3600", "APP_ENV": "hml",
                    "AWS_REGION": "us-east-1", "AWS_ENDPOINT_URL": f"http://{self.ls}:4566",
                    "WORKER_MAX_TICKS": "1", "WORKER_WAIT_SECONDS": "2"}
        self.billing_env = {"DB_HOST": self.db, "DB_PORT": "3306", "DB_DATABASE": "oficina_faturamento",
                            "DB_USERNAME": "root", "DB_PASSWORD": "root", "WEBHOOK_TOKEN": secrets.token_hex(16),
                            "MP_WEBHOOK_SECRET": secrets.token_hex(16), "PAYMENT_GATEWAY": "fake"}
        self.os_env = {"DB_HOST": self.os_db, "DB_PORT": "3306", "DB_DATABASE": "oficina_mecanica", "DB_USERNAME": "root",
                       "DB_PASSWORD": "root", "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": secrets.token_hex(12),
                       "INTERNAL_TOKEN": secrets.token_hex(16), "MIGRATIONS_PATH": "/migrations",
                       "SAGA_APPROVAL_TIMEOUT_SECONDS": "600", "SAGA_PAYMENT_TIMEOUT_SECONDS": "600"}
        self.sequence = 0
        self.probe = ""

    def available(self) -> bool:
        return (self.repo / "bin" / "worker.php").is_file()

    def saga_available(self) -> bool:
        return self.billing_available() and (self.os_repo / "bin" / "worker.php").is_file() \
            and (self.fundacao / "migrations" / "004_fase4_saga.sql").is_file()

    def billing_available(self) -> bool:
        return (self.billing / "bin" / "worker.php").is_file() and (self.billing / "migrations").is_dir()

    # ── infraestrutura ──────────────────────────────────────────────────────────────────────
    def aws(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "exec", "-i", self.ls, *args], input=stdin, capture_output=True, text=True)

    def php(self, *args: str, detach: bool = False, billing: bool = False, service: str = "") -> subprocess.CompletedProcess:
        service = service or ("faturamento" if billing else "execucao")
        repo, name = {"execucao": (self.repo, self.app), "faturamento": (self.billing, self.billing_app),
                      "os": (self.os_repo, self.os_app)}[service]
        image = subprocess.run([str(TOOLING), "image"], capture_output=True, text=True, check=True).stdout.strip()
        cmd = ["docker", "run", "--rm", "--network", self.net, "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
               "-v", f"{repo.resolve()}:/w", "-w", "/w"]
        if (repo / ".env").exists():  # o serviço carrega o .env e ele sobrescreveria este ambiente
            cmd += ["-v", "/dev/null:/w/.env:ro"]
        extra = {"faturamento": self.billing_env, "os": self.os_env}.get(service, {})
        if service == "os":
            cmd += ["-v", f"{(self.fundacao / 'migrations').resolve()}:/migrations:ro"]
        for key, value in {**self.env, **extra}.items():
            cmd += ["-e", f"{key}={value}"]
        if detach:
            cmd[2:2] = ["-d", "--name", name]
        return subprocess.run(cmd + [image, *args], capture_output=True, text=True)

    def http(self, method: str, path: str, token: str = "", body: dict | None = None, billing: bool = False,
             headers: dict | None = None, service: str = ""):
        service = service or ("faturamento" if billing else "execucao")
        app, prefix = {"execucao": (self.app, "/api/execution"), "faturamento": (self.billing_app, "/api/billing"),
                       "os": (self.os_app, "")}[service]
        cmd = ["docker", "exec", app, "curl", "-s", "-X", method, "-w", "\n%{http_code}", f"http://127.0.0.1:8080{prefix}{path}"]
        if token:
            cmd += ["-H", f"Authorization: Bearer {token}"]
        for key, value in (headers or {}).items():
            cmd += ["-H", f"{key}: {value}"]
        if body is not None:
            cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
        text, _, status = subprocess.run(cmd, capture_output=True, text=True).stdout.rpartition("\n")
        try:
            return int(status or 0), json.loads(text or "{}")
        except json.JSONDecodeError:
            return int(status or 0), {"corpo": text[:200]}

    def up(self) -> bool:
        if not (self.repo / "vendor" / "autoload.php").is_file():
            print(f"composer install em {self.repo.name}...", flush=True)
            subprocess.run([str(TOOLING), "run", str(self.repo), "composer", "install", "--no-interaction", "--quiet"], check=True)
        subprocess.run(["docker", "network", "create", self.net], capture_output=True, check=True)
        started = subprocess.run(["docker", "run", "-d", "--rm", "--name", self.ls, "--network", self.net,
                                  "-e", "SERVICES=sns,sqs,dynamodb", LOCALSTACK_IMAGE], capture_output=True, text=True)
        if started.returncode != 0:
            return self.check("LocalStack de pé", False, started.stderr.strip()[-200:])
        for _ in range(60):
            if self.aws("awslocal", "sns", "list-topics").returncode == 0:
                break
            time.sleep(2)
        else:
            return self.check("LocalStack de pé", False, "não respondeu em 120 s")

        init = self.aws("env", "ENVIRONMENT=e2e", "sh", stdin=(self.repo / "scripts" / "localstack-init.sh").read_text())
        created = dict(line.split("=", 1) for line in init.stdout.splitlines() if "=" in line)
        if not self.check("scripts/localstack-init.sh cria tabela, fila e assinatura",
                          init.returncode == 0 and len(created) == 3, init.stderr.strip()[-300:]):
            return False
        self.env.update(created)
        if self.billing_available():
            init = self.aws("env", "ENVIRONMENT=e2e", "sh", stdin=(self.billing / "scripts" / "localstack-init.sh").read_text())
            created = dict(line.split("=", 1) for line in init.stdout.splitlines() if "=" in line)
            if not self.check("faturamento: localstack-init.sh cria a fila e assina o mesmo tópico",
                              init.returncode == 0 and created.get("MESSAGING_TOPIC_ARN") == self.env["MESSAGING_TOPIC_ARN"],
                              init.stderr.strip()[-300:]):
                return False
            self.billing_env["MESSAGING_QUEUE_URL"] = created["MESSAGING_QUEUE_URL"]
        if self.saga_available():
            init = self.aws("env", "ENVIRONMENT=e2e", "sh", stdin=(self.os_repo / "scripts" / "localstack-init.sh").read_text())
            created = dict(line.split("=", 1) for line in init.stdout.splitlines() if "=" in line)
            if not self.check("os: localstack-init.sh cria a fila da saga e assina o mesmo tópico",
                              init.returncode == 0 and created.get("MESSAGING_TOPIC_ARN") == self.env["MESSAGING_TOPIC_ARN"],
                              init.stderr.strip()[-300:]):
                return False
            self.os_env["MESSAGING_QUEUE_URL"] = created["MESSAGING_QUEUE_URL"]

        # A fila de sonda faz o papel da fila do serviço de OS: recebe o que a Execução publica.
        probe = self.aws("sh", "-ec", """
            url=$(awslocal sqs create-queue --queue-name sonda-os --query QueueUrl --output text)
            arn=$(awslocal sqs get-queue-attributes --queue-url "$url" --attribute-names QueueArn --query Attributes.QueueArn --output text)
            awslocal sns subscribe --topic-arn "$1" --protocol sqs --notification-endpoint "$arn" \\
              --attributes "{\\"RawMessageDelivery\\":\\"true\\",\\"FilterPolicy\\":$2}" >/dev/null
            echo "$url"
        """, "sh", self.env["MESSAGING_TOPIC_ARN"], json.dumps(json.dumps({"type": EXECUTION_EVENTS + BILLING_EVENTS})))
        self.probe = probe.stdout.strip()
        if not self.check("fila de sonda assinada no tópico", probe.returncode == 0 and bool(self.probe), probe.stderr[-200:]):
            return False

        self.php("php", "-S", "0.0.0.0:8080", "-t", "public", "public/index.php", detach=True)
        for _ in range(30):
            if self.http("GET", "/health")[0] == 200:
                return True
            time.sleep(1)
        return self.check("API da Execução de pé", False, "GET /api/execution/health não respondeu")

    def down(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.app, self.ls, self.db, self.billing_app, self.os_db, self.os_app], capture_output=True)
        subprocess.run(["docker", "network", "rm", self.net], capture_output=True)

    # ── papéis ──────────────────────────────────────────────────────────────────────────────
    def token(self, sub: str, role: str) -> str:
        return self.php("php", "-r", 'require "vendor/autoload.php"; echo (new App\\Infrastructure\\Security\\JwtProvider('
                        f'getenv("JWT_SECRET"), 3600))->generate(["sub" => "{sub}", "role" => "{role}"]);').stdout.strip()

    def command(self, type_: str, os_id: str, payload: dict, message_id: str = "") -> str:
        """O orquestrador publica um comando no tópico. Devolve o id da mensagem."""
        self.sequence += 1
        message_id = message_id or f"e2e-cmd-{self.sequence}"
        envelope = {"id": message_id, "type": type_, "version": 1, "producer": "os", "saga_id": f"saga-{os_id}",
                    "os_id": os_id, "occurred_at": "2026-11-15T10:00:00.000Z", "correlation_id": f"corr-{os_id}",
                    "payload": payload}
        out = self.aws("awslocal", "sns", "publish", "--topic-arn", self.env["MESSAGING_TOPIC_ARN"],
                       "--message", json.dumps(envelope),
                       "--message-attributes", json.dumps({"type": {"DataType": "String", "StringValue": type_}}))
        if out.returncode != 0:
            self.check(f"publicar {type_}", False, out.stderr[-200:])
        return message_id

    def worker(self, billing: bool = False, service: str = "") -> list[dict]:
        """Uma volta do worker (outbox + fila). Devolve as linhas de log estruturado."""
        out = self.php("php", "bin/worker.php", billing=billing, service=service)
        lines = []
        for line in out.stdout.splitlines():
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        if out.returncode != 0:
            self.check("worker roda sem erro", False, (out.stdout + out.stderr)[-300:])
        return lines

    def published(self) -> list[dict]:
        """O que chegou à sonda desde a última leitura."""
        messages = []
        for _ in range(3):
            out = self.aws("awslocal", "sqs", "receive-message", "--queue-url", self.probe,
                           "--max-number-of-messages", "10", "--wait-time-seconds", "1")
            batch = json.loads(out.stdout or "{}").get("Messages", [])
            for raw in batch:
                messages.append(json.loads(raw["Body"]))
                self.aws("awslocal", "sqs", "delete-message", "--queue-url", self.probe, "--receipt-handle", raw["ReceiptHandle"])
            if not batch and messages:
                break
        return sorted(messages, key=lambda m: m["occurred_at"])

    def outcomes(self, logs: list[dict]) -> list[str]:
        return [line.get("outcome", "") for line in logs if line.get("message") == "message.processed"]

    # ── o roteiro ───────────────────────────────────────────────────────────────────────────
    def run(self) -> None:
        print("\nFase 4: serviço de Execução contra o LocalStack (SNS, SQS, DynamoDB)", flush=True)
        if not self.up():
            return
        token = self.php("php", "-r", 'require "vendor/autoload.php"; echo (new App\\Infrastructure\\Security\\JwtProvider('
                         'getenv("JWT_SECRET"), 3600))->generate(["sub" => "admin", "role" => "admin"]);').stdout.strip()
        os_id = "os-e2e-1"

        status, body = self.http("GET", "/ready")
        self.check("GET /api/execution/ready 200 (toca o DynamoDB)", status == 200 and body.get("dynamodb") == "connected", str(body))
        self.check("GET /api/execution/tasks sem token: 401", self.http("GET", "/tasks")[0] == 401)

        diagnosis = {"customer_name": "Maria Silva", "description": "Barulho no freio",
                     "vehicle": {"license_plate": "ABC1D23", "brand": "Fiat", "model": "Uno"}}
        first = self.command("execution.request-diagnosis", os_id, diagnosis)
        self.command("os.tipo-que-ninguem-assina", os_id, {})  # o filtro da fila não deixa passar
        logs = self.worker()
        self.check("worker trata execution.request-diagnosis; o filtro da fila barra o tipo alheio",
                   self.outcomes(logs) == ["ok"], json.dumps(logs)[-300:])
        status, body = self.http("GET", "/tasks", token)
        queue = [t["os_id"] for t in body.get("data", [])]
        self.check("a tarefa aparece na fila de diagnóstico (índice por status)", status == 200 and queue == [os_id], str(body)[:200])

        self.command("execution.request-diagnosis", os_id, diagnosis, message_id=first)
        self.check("a mesma mensagem entregue de novo é duplicata (inbox)", self.outcomes(self.worker()) == ["duplicate"])

        self.check("mecânico inicia o diagnóstico: 200", self.http("POST", f"/tasks/{os_id}/diagnosis/start", token)[0] == 200)
        status, body = self.http("POST", f"/tasks/{os_id}/diagnosis/complete", token,
                                 {"items": [{"service_item_id": "svc-1"}, {"part_id": "part-9", "quantity": 2}]})
        self.check("mecânico conclui o diagnóstico com 2 itens: 200", status == 200 and body.get("status") == "DIAGNOSED", str(body)[:200])
        self.check("concluir o reparo fora de hora: 422", self.http("POST", f"/tasks/{os_id}/repair/complete", token)[0] == 422)
        events = self.published()  # sem volta do worker: a API publica a outbox logo depois de gravar
        self.check("a API publica diagnosis.started e diagnosis.completed no tópico sem esperar o worker",
                   [e["type"] for e in events] == ["diagnosis.started", "diagnosis.completed"], str([e["type"] for e in events]))
        done = events[-1] if events else {}
        self.check("o evento leva saga, OS, correlation id, produtor e os itens do diagnóstico",
                   done.get("saga_id") == f"saga-{os_id}" and done.get("os_id") == os_id and done.get("producer") == "execucao"
                   and done.get("correlation_id") == f"corr-{os_id}" and len(done.get("payload", {}).get("items", [])) == 2,
                   json.dumps(done)[:300])
        self.check("publicado sai da outbox: outra volta do worker não republica", self.worker() is not None and self.published() == [])

        self.command("execution.start-repair", os_id, {"items": [{"kind": "service", "id": "svc-1", "quantity": 1}]})
        self.check("worker trata execution.start-repair", self.outcomes(self.worker()) == ["ok"])
        status, body = self.http("GET", "/tasks?status=QUEUED_REPAIR", token)
        self.check("a tarefa passa para a fila de reparo", [t["os_id"] for t in body.get("data", [])] == [os_id], str(body)[:200])
        self.http("POST", f"/tasks/{os_id}/repair/start", token)
        status, body = self.http("POST", f"/tasks/{os_id}/repair/fail", token, {"reason": "peça com defeito"})
        self.check("mecânico registra a falha do reparo: 200", status == 200 and body.get("status") == "REPAIR_FAILED", str(body)[:200])
        events = self.published()
        self.check("repair.failed chega ao tópico com o motivo (é o que dispara a compensação da saga)",
                   [e["type"] for e in events] == ["repair.started", "repair.failed"]
                   and events[-1]["payload"].get("reason") == "peça com defeito", str(events)[:300])

        self.command("execution.cancel", "os-e2e-2", {"reason": "prazo de aprovação vencido"})
        self.check("worker trata execution.cancel de uma OS sem tarefa", self.outcomes(self.worker()) == ["ok"])
        events = self.published()
        self.check("a compensação é confirmada com execution.cancelled, mesmo sem tarefa",
                   [(e["type"], e["os_id"]) for e in events] == [("execution.cancelled", "os-e2e-2")], str(events)[:300])

        status, body = self.http("GET", f"/tasks/{os_id}", token)
        timeline = [e["type"] for e in body.get("timeline", [])]
        self.check("a linha do tempo da tarefa está completa e em ordem",
                   timeline == ["task.opened", "diagnosis.started", "diagnosis.completed", "repair.queued", "repair.started",
                                "repair.failed"], str(timeline))

        if self.billing_available():
            self.run_billing()
        if self.saga_available():
            self.run_saga()

    # ── Faturamento ─────────────────────────────────────────────────────────────────────────
    def sign(self, data_id: str, request_id: str, ts: str) -> str:
        """O x-signature como o Mercado Pago mandaria (o mesmo manifesto que o serviço confere)."""
        manifest = f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
        digest = hmac.new(self.billing_env["MP_WEBHOOK_SECRET"].encode(), manifest.encode(), hashlib.sha256).hexdigest()
        return f"ts={ts},v1={digest}"

    def billing_up(self) -> bool:
        if not (self.billing / "vendor" / "autoload.php").is_file():
            print(f"composer install em {self.billing.name}...", flush=True)
            subprocess.run([str(TOOLING), "run", str(self.billing), "composer", "install", "--no-interaction", "--quiet"], check=True)
        subprocess.run(["docker", "run", "-d", "--rm", "--name", self.db, "--network", self.net, "-e", "MYSQL_ROOT_PASSWORD=root",
                        "-e", "MYSQL_DATABASE=oficina_faturamento", "mysql:8.0"], capture_output=True, check=True)
        for _ in range(90):
            if subprocess.run(["docker", "exec", self.db, "mysql", "-h127.0.0.1", "-uroot", "-proot", "-e", "SELECT 1"],
                              capture_output=True).returncode == 0:
                break
            time.sleep(2)
        else:
            return self.check("faturamento: MySQL de pé", False, "não respondeu em 180 s")

        for rodada in ("1ª vez", "2ª vez, idempotente"):
            out = self.php("php", "bin/migrate.php", billing=True)
            if not self.check(f"faturamento: migrations do próprio repo, {rodada}", out.returncode == 0, (out.stdout + out.stderr)[-300:]):
                return False

        self.php("php", "-S", "0.0.0.0:8080", "-t", "public", "public/index.php", detach=True, billing=True)
        for _ in range(30):
            if self.http("GET", "/health", billing=True)[0] == 200:
                return True
            time.sleep(1)
        return self.check("faturamento: API de pé", False, "GET /api/billing/health não respondeu")

    def part_stock(self, admin: str) -> tuple[int, int]:
        body = self.http("GET", f"/parts/{SEED_PART[0]}", admin, billing=True)[1]
        return body.get("stock_quantity", -1), body.get("reserved_quantity", -1)

    def run_billing(self) -> None:
        print("\nFase 4: serviço de Faturamento (MySQL próprio, Mercado Pago falso, webhook assinado)", flush=True)
        if not self.billing_up():
            return
        admin, owner, other = self.token("admin", "admin"), self.token("cli-e2e", "customer"), self.token("outro", "customer")
        os_id = "os-e2e-fat"
        self.published()  # descarta o que sobrou da parte da Execução

        status, body = self.http("GET", "/ready", billing=True)
        self.check("GET /api/billing/ready 200 (toca o MySQL do serviço)", status == 200 and body.get("database") == "connected", str(body))
        status, body = self.http("GET", "/service-items", admin, billing=True)
        self.check("o catálogo veio do seed com os ids da Fase 3", status == 200 and SEED_SERVICE[0] in [i["id"] for i in body.get("data", [])],
                   str(body)[:200])
        self.check("catálogo sem token: 401; com token de cliente: 403",
                   self.http("GET", "/parts", billing=True)[0] == 401 and self.http("GET", "/parts", owner, billing=True)[0] == 403)

        generate = {"customer": {"id": "cli-e2e", "name": "Maria Silva", "email": "maria@example.com"},
                    "items": [{"kind": "service", "id": SEED_SERVICE[0], "quantity": 1}, {"kind": "part", "id": SEED_PART[0], "quantity": 2}]}
        self.command("billing.generate-budget", os_id, generate)
        self.check("worker trata billing.generate-budget", self.outcomes(self.worker(billing=True)) == ["ok"])
        events = self.published()
        total = SEED_SERVICE[1] + 2 * SEED_PART[1]
        self.check("budget.generated chega ao tópico com o total pelo preço do catálogo",
                   [e["type"] for e in events] == ["budget.generated"] and abs(events[0]["payload"]["total_amount"] - total) < 0.001,
                   str(events)[:300])
        self.check("as 2 pastilhas ficam reservadas no estoque", self.part_stock(admin) == (SEED_PART[2], 2), str(self.part_stock(admin)))
        status, body = self.http("GET", f"/budgets/by-order/{os_id}", owner, billing=True)
        budget_id = body.get("id", "")
        self.check("o cliente dono vê o orçamento; outro cliente recebe 404",
                   status == 200 and body.get("status") == "AWAITING_APPROVAL"
                   and self.http("GET", f"/budgets/{budget_id}", other, billing=True)[0] == 404, str(body)[:200])

        self.check("webhook de aprovação com X-Webhook-Token errado: 401",
                   self.http("POST", f"/budgets/{budget_id}/approval", body={"approved": True}, billing=True,
                             headers={"X-Webhook-Token": "errado"})[0] == 401)
        status, body = self.http("POST", f"/budgets/{budget_id}/approval", body={"approved": True}, billing=True,
                                 headers={"X-Webhook-Token": self.billing_env["WEBHOOK_TOKEN"]})
        events = self.published()
        self.check("cliente aprova: a API publica budget.approved sem esperar o worker",
                   status == 200 and [e["type"] for e in events] == ["budget.approved"], f"{status} {events}"[:300])

        self.command("billing.charge", os_id, {"budget_id": budget_id})
        self.check("worker trata billing.charge", self.outcomes(self.worker(billing=True)) == ["ok"])
        events = self.published()
        self.check("payment.created chega com o link de pagamento",
                   [e["type"] for e in events] == ["payment.created"] and events[0]["payload"].get("payment_url", "").startswith("https://"),
                   str(events)[:300])

        payment_id = f"fake-approved-{budget_id}-{round(total * 100)}"
        path = f"/payments/webhook/mercadopago?data.id={payment_id}&type=payment"
        self.check("notificação do Mercado Pago com assinatura falsa: 401",
                   self.http("POST", path, billing=True, headers={"x-request-id": "r1", "x-signature": "ts=1,v1=00"})[0] == 401)
        status, body = self.http("POST", path, billing=True, headers={"x-request-id": "r1", "x-signature": self.sign(payment_id, "r1", "1731751200")})
        events = self.published()
        self.check("notificação assinada confirma o pagamento e publica payment.confirmed na hora",
                   status == 200 and body.get("outcome") == "ok" and [e["type"] for e in events] == ["payment.confirmed"], f"{status} {body} {events}"[:300])
        status, body = self.http("POST", path, billing=True, headers={"x-request-id": "r2", "x-signature": self.sign(payment_id, "r2", "1731751300")})
        self.check("o Mercado Pago reenvia a notificação: duplicata, sem efeito", body.get("outcome") == "duplicate", str(body))
        self.check("pago: as peças saem do estoque", self.part_stock(admin) == (SEED_PART[2] - 2, 0), str(self.part_stock(admin)))

        self.command("billing.refund-payment", os_id, {"budget_id": budget_id, "reason": "reparo falhou"})
        self.command("billing.cancel-budget", os_id, {"budget_id": budget_id, "reason": "reparo falhou"})
        self.check("worker trata o estorno e o cancelamento (compensação do reparo que falhou)",
                   sorted(self.outcomes(self.worker(billing=True))) == ["ok", "ok"])
        events = self.published()
        self.check("payment.refunded e budget.cancelled chegam ao tópico",
                   sorted(e["type"] for e in events) == ["budget.cancelled", "payment.refunded"], str([e["type"] for e in events]))
        self.check("cancelado depois de pago: as peças voltam ao estoque", self.part_stock(admin) == (SEED_PART[2], 0), str(self.part_stock(admin)))
        status, body = self.http("GET", f"/budgets/{budget_id}", admin, billing=True)
        self.check("o orçamento termina CANCELLED com o pagamento REFUNDED",
                   body.get("status") == "CANCELLED" and (body.get("payment") or {}).get("status") == "REFUNDED", str(body)[:300])

        self.command("billing.generate-budget", "os-e2e-sem-estoque",
                     {**generate, "items": [{"kind": "part", "id": SEED_PART[0], "quantity": SEED_PART[2] + 1}]})
        self.worker(billing=True)
        events = self.published()
        self.check("estoque insuficiente: budget.failed com INSUFFICIENT_STOCK e nada reservado",
                   [(e["type"], e["payload"].get("reason")) for e in events] == [("budget.failed", "INSUFFICIENT_STOCK")]
                   and self.part_stock(admin) == (SEED_PART[2], 0), str(events)[:300])

    # ── A saga inteira, pelos três serviços ─────────────────────────────────────────────────
    @staticmethod
    def cpf() -> str:
        base = [int(d) for d in f"{secrets.randbelow(10 ** 9):09d}"]
        for _ in range(2):
            total = sum(d * w for d, w in zip(base, range(len(base) + 1, 1, -1)))
            base.append(0 if total % 11 < 2 else 11 - total % 11)
        return "".join(map(str, base))

    def os_up(self) -> bool:
        if not (self.os_repo / "vendor" / "autoload.php").is_file():
            subprocess.run([str(TOOLING), "run", str(self.os_repo), "composer", "install", "--no-interaction", "--quiet"], check=True)
        subprocess.run(["docker", "run", "-d", "--rm", "--name", self.os_db, "--network", self.net, "-e", "MYSQL_ROOT_PASSWORD=root",
                        "-e", "MYSQL_DATABASE=oficina_mecanica", "mysql:8.0"], capture_output=True, check=True)
        for _ in range(90):
            if subprocess.run(["docker", "exec", self.os_db, "mysql", "-h127.0.0.1", "-uroot", "-proot", "-e", "SELECT 1"],
                              capture_output=True).returncode == 0:
                break
            time.sleep(2)
        else:
            return self.check("os: MySQL de pé", False, "não respondeu em 180 s")
        out = self.php("php", "bin/migrate.php", service="os")
        if not self.check("os: migrations da fundação, com a 004 da saga", out.returncode == 0, (out.stdout + out.stderr)[-300:]):
            return False
        self.php("php", "-S", "0.0.0.0:8080", "-t", "public", "public/index.php", detach=True, service="os")
        for _ in range(30):
            if self.http("GET", "/api/health", service="os")[0] == 200:
                return True
            time.sleep(1)
        return self.check("os: API de pé", False, "GET /api/health não respondeu")

    def round(self) -> None:
        """Uma volta de cada worker: os comandos e eventos andam um passo pelos três serviços."""
        for service in ("os", "execucao", "faturamento", "os"):
            self.worker(service=service)

    def order(self, admin: str, os_id: str) -> dict:
        body = self.http("GET", f"/api/service-orders/{os_id}", admin, service="os")[1]
        return body if isinstance(body, dict) else {}

    def open_order(self, admin: str, description: str) -> str:
        cpf = self.cpf()
        status, body = self.http("POST", "/api/customers", admin, {"name": "Maria Silva", "document": cpf, "email": "maria@example.com"},
                                 service="os")
        customer = body.get("id", "") if isinstance(body, dict) else ""
        if not self.check("os: cadastra a cliente", status == 201 and bool(customer), f"{status} {body}"[:200]):
            return ""
        # placa Mercosul: três letras, um dígito, uma letra, dois dígitos
        letters = "".join(chr(65 + secrets.randbelow(26)) for _ in range(3))
        plate = f"{letters}{secrets.randbelow(10)}{chr(65 + secrets.randbelow(26))}{secrets.randbelow(100):02d}"
        status, body = self.http("POST", "/api/vehicles", admin, {"customer_id": customer, "license_plate": plate, "brand": "Fiat",
                                                                 "model": "Uno", "year": 2015}, service="os")
        vehicle = body.get("id", "") if isinstance(body, dict) else ""
        if not self.check("os: cadastra o veículo", status == 201 and bool(vehicle), f"{status} {body}"[:200]):
            return ""
        status, body = self.http("POST", "/api/service-orders", admin, {"customer_id": customer, "vehicle_id": vehicle,
                                                                       "description": description}, service="os")
        self.check("os: abrir a OS devolve 201 com a saga no passo DIAGNOSIS",
                   status == 201 and (body.get("saga") or {}).get("step") == "DIAGNOSIS", f"{status} {body}"[:300])
        return body.get("id", "")

    def to_payment(self, admin: str, os_id: str) -> dict:
        """Diagnóstico, orçamento, aprovação e cobrança, cada um pelo serviço dono."""
        self.round()
        self.http("POST", f"/tasks/{os_id}/diagnosis/start", admin)
        self.http("POST", f"/tasks/{os_id}/diagnosis/complete", admin,
                  {"items": [{"service_item_id": SEED_SERVICE[0]}, {"part_id": SEED_PART[0], "quantity": 2}]})
        self.round()
        order = self.order(admin, os_id)
        budget = order.get("budget_id") or ""
        self.http("POST", f"/budgets/{budget}/approval", body={"approved": True}, service="faturamento",
                  headers={"X-Webhook-Token": self.billing_env["WEBHOOK_TOKEN"]})
        self.round()
        self.round()
        return self.order(admin, os_id)

    def pay(self, os_id: str, admin: str) -> None:
        order = self.order(admin, os_id)
        payment_id = f"fake-approved-{order['budget_id']}-{round(order['total_amount'] * 100)}"
        self.http("POST", f"/payments/webhook/mercadopago?data.id={payment_id}&type=payment", service="faturamento",
                  headers={"x-request-id": "r", "x-signature": self.sign(payment_id, "r", "1731751200")})
        self.round()

    def run_saga(self) -> None:
        print("\nFase 4: a saga inteira, pelos três serviços (cada um com o próprio banco e worker)", flush=True)
        if not self.os_up():
            return
        status, body = self.http("POST", "/api/auth/login", body={"username": "admin", "password": self.os_env["ADMIN_PASSWORD"]}, service="os")
        admin = body.get("token", "")
        if not self.check("os: login do admin", status == 200 and bool(admin), f"{status} {body}"[:200]):
            return
        self.published()

        os_id = self.open_order(admin, "Barulho no freio")
        if not os_id:
            return
        order = self.to_payment(admin, os_id)
        total = SEED_SERVICE[1] + 2 * SEED_PART[1]
        self.check("orçamento do Faturamento chega à OS: total pelo catálogo e link de pagamento",
                   order.get("status") == "AWAITING_PAYMENT" and abs(order.get("total_amount", 0) - total) < 0.001
                   and str(order.get("payment_url", "")).startswith("https://"), str(order)[:300])

        self.pay(os_id, admin)
        order = self.order(admin, os_id)
        self.check("pagamento confirmado: a OS vai para EXECUTING e a saga para o passo REPAIR",
                   order.get("status") == "EXECUTING" and (order.get("saga") or {}).get("step") == "REPAIR", str(order)[:300])
        status, body = self.http("GET", f"/tasks/{os_id}", admin)
        self.check("a Execução recebeu a ordem de reparo: tarefa na fila de reparo", body.get("status") == "QUEUED_REPAIR", str(body)[:200])

        self.http("POST", f"/tasks/{os_id}/repair/start", admin)
        self.http("POST", f"/tasks/{os_id}/repair/complete", admin)
        self.round()
        order = self.order(admin, os_id)
        saga = order.get("saga") or {}
        self.check("reparo concluído: OS FINISHED e saga COMPLETED",
                   order.get("status") == "FINISHED" and saga.get("state") == "COMPLETED", str(order)[:300])
        self.check("a linha do tempo da saga registra todos os passos",
                   [h["step"] for h in saga.get("history", []) if h["event"] == "step.entered"] == ["BUDGET", "APPROVAL", "PAYMENT", "REPAIR"],
                   str(saga.get("history"))[:300])
        status, body = self.http("POST", f"/api/service-orders/{os_id}/delivery", admin, service="os")
        self.check("entrega manual: DELIVERED", status == 200 and body.get("status") == "DELIVERED", f"{status} {body}"[:200])
        before = self.part_stock(admin)

        # Compensação: o reparo falha depois do pagamento.
        os_id = self.open_order(admin, "Embreagem patinando")
        self.to_payment(admin, os_id)
        self.pay(os_id, admin)
        self.check("segunda OS paga: as 2 pastilhas saem do estoque", self.part_stock(admin) == (before[0] - 2, 0), str(self.part_stock(admin)))
        self.http("POST", f"/tasks/{os_id}/repair/start", admin)
        self.http("POST", f"/tasks/{os_id}/repair/fail", admin, {"reason": "peça com defeito"})
        self.round()
        order = self.order(admin, os_id)
        self.check("reparo falhou: a OS vai para CANCELLED na hora e a saga compensa",
                   order.get("status") == "CANCELLED" and (order.get("saga") or {}).get("state") in ("COMPENSATING", "COMPENSATED"), str(order)[:300])
        self.round()
        saga = self.order(admin, os_id).get("saga") or {}
        self.check("estorno e cancelamento do orçamento confirmados: saga COMPENSATED",
                   saga.get("state") == "COMPENSATED" and saga.get("pending_compensations") == [], str(saga)[:300])
        self.check("as pastilhas voltam ao estoque", self.part_stock(admin) == before, str(self.part_stock(admin)))
        status, body = self.http("GET", f"/budgets/by-order/{os_id}", admin, service="faturamento")
        self.check("no Faturamento: orçamento CANCELLED com o pagamento REFUNDED",
                   body.get("status") == "CANCELLED" and (body.get("payment") or {}).get("status") == "REFUNDED", str(body)[:300])

        # Cancelamento pelo admin no meio da saga.
        os_id = self.open_order(admin, "Revisão")
        self.round()
        status, body = self.http("POST", f"/api/service-orders/{os_id}/cancellation", admin, {"reason": "cliente desistiu"}, service="os")
        self.round()
        task = self.http("GET", f"/tasks/{os_id}", admin)[1]
        saga = self.order(admin, os_id).get("saga") or {}
        self.check("admin cancela no diagnóstico: a tarefa da Execução é cancelada e a saga COMPENSATED",
                   status == 200 and task.get("status") == "CANCELLED" and saga.get("state") == "COMPENSATED", f"{status} {task} {saga}"[:300])

