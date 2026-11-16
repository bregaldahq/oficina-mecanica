"""Ponta a ponta da Fase 4, local e sem AWS: os microsserviços contra o LocalStack.

Sobe um LocalStack (SNS, SQS e DynamoDB), cria os recursos com o script do próprio serviço
(scripts/localstack-init.sh) e faz o papel do orquestrador da saga: publica os comandos no
tópico, age como o mecânico pela API e lê, numa fila de sonda, o que o serviço publicou.

Cobre o que os testes do repo, com adaptadores em memória, não alcançam: o desenho da tabela
num DynamoDB de verdade, a transação com inbox e outbox, o filtro da assinatura e o worker.

Por enquanto só o serviço de Execução; os outros entram conforme forem implementados.
"""
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


class Fase4E2E:
    def __init__(self, check):
        self.check = check
        self.repo = repos_dir() / "oficina-execucao"
        self.net = f"oficina-e2e4-{os.getpid()}"
        self.ls, self.app = f"{self.net}-aws", f"{self.net}-execucao"
        self.env = {"JWT_SECRET": secrets.token_hex(32), "JWT_EXPIRATION": "3600", "APP_ENV": "hml",
                    "AWS_REGION": "us-east-1", "AWS_ENDPOINT_URL": f"http://{self.ls}:4566",
                    "WORKER_MAX_TICKS": "1", "WORKER_WAIT_SECONDS": "2"}
        self.sequence = 0

    def available(self) -> bool:
        return (self.repo / "bin" / "worker.php").is_file()

    # ── infraestrutura ──────────────────────────────────────────────────────────────────────
    def aws(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "exec", "-i", self.ls, *args], input=stdin, capture_output=True, text=True)

    def php(self, *args: str, detach: bool = False) -> subprocess.CompletedProcess:
        image = subprocess.run([str(TOOLING), "image"], capture_output=True, text=True, check=True).stdout.strip()
        cmd = ["docker", "run", "--rm", "--network", self.net, "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
               "-v", f"{self.repo.resolve()}:/w", "-w", "/w"]
        if (self.repo / ".env").exists():  # o serviço carrega o .env e ele sobrescreveria este ambiente
            cmd += ["-v", "/dev/null:/w/.env:ro"]
        for key, value in self.env.items():
            cmd += ["-e", f"{key}={value}"]
        if detach:
            cmd[2:2] = ["-d", "--name", self.app]
        return subprocess.run(cmd + [image, *args], capture_output=True, text=True)

    def http(self, method: str, path: str, token: str = "", body: dict | None = None):
        cmd = ["docker", "exec", self.app, "curl", "-s", "-X", method, "-w", "\n%{http_code}",
               f"http://127.0.0.1:8080/api/execution{path}"]
        if token:
            cmd += ["-H", f"Authorization: Bearer {token}"]
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

        # A fila de sonda faz o papel da fila do serviço de OS: recebe o que a Execução publica.
        probe = self.aws("sh", "-ec", """
            url=$(awslocal sqs create-queue --queue-name sonda-os --query QueueUrl --output text)
            arn=$(awslocal sqs get-queue-attributes --queue-url "$url" --attribute-names QueueArn --query Attributes.QueueArn --output text)
            awslocal sns subscribe --topic-arn "$1" --protocol sqs --notification-endpoint "$arn" \\
              --attributes "{\\"RawMessageDelivery\\":\\"true\\",\\"FilterPolicy\\":$2}" >/dev/null
            echo "$url"
        """, "sh", self.env["MESSAGING_TOPIC_ARN"], json.dumps(json.dumps({"type": EXECUTION_EVENTS})))
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
        subprocess.run(["docker", "rm", "-f", self.app, self.ls], capture_output=True)
        subprocess.run(["docker", "network", "rm", self.net], capture_output=True)

    # ── papéis ──────────────────────────────────────────────────────────────────────────────
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

    def worker(self) -> list[dict]:
        """Uma volta do worker (outbox + fila). Devolve as linhas de log estruturado."""
        out = self.php("php", "bin/worker.php")
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
        self.command("budget.generated", os_id, {})  # tipo de outro serviço: o filtro da fila não deixa passar
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
