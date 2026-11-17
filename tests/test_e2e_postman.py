"""bin/e2e_postman.py e tools/e2e/postman-runner.js, sem containers: o runner contra um servidor
HTTP de mentira.

Rodar: python3 -m unittest discover -s tests
"""
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import e2e_postman  # noqa: E402

RUNNER = ROOT / "tools" / "e2e" / "postman-runner.js"


class Fake(BaseHTTPRequestHandler):
    calls: list = []
    pending = 0  # quantas vezes /status responde "ainda não"

    def log_message(self, *args):
        pass

    def reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        Fake.calls.append(("POST", self.path, self.headers.get("Authorization"), body))
        if self.path == "/login":
            self.reply(200, {"token": "tok-" + body.get("user", "")})
        else:
            self.reply(200, {"ok": True})

    def do_GET(self):
        Fake.calls.append(("GET", self.path, self.headers.get("Authorization"), None))
        if Fake.pending > 0:
            Fake.pending -= 1
            self.reply(200, {"status": "PENDING"})
        else:
            self.reply(200, {"status": "DONE"})


def item(name, method, path, tests, body=None, auth=None):
    headers = [{"key": "Authorization", "value": auth}] if auth else []
    req = {"method": method, "header": headers, "url": {"raw": "{{baseUrl}}" + path}}
    if body is not None:
        req["body"] = {"mode": "raw", "raw": json.dumps(body)}
    return {"name": name, "event": [{"listen": "test", "script": {"exec": tests}}], "request": req}


@unittest.skipUnless(shutil.which("node"), "sem node")
class RunnerTest(unittest.TestCase):
    def setUp(self):
        Fake.calls, Fake.pending = [], 0
        self.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        self.server.shutdown()

    def run_collection(self, items, *extra):
        (self.tmp / "c.json").write_text(json.dumps({"item": [{"name": "pasta", "item": items}],
                                                     "variable": [{"key": "token", "value": ""}]}))
        (self.tmp / "e.json").write_text(json.dumps({"values": [{"key": "user", "value": "maria"}]}))
        return subprocess.run(["node", str(RUNNER), str(self.tmp / "c.json"), str(self.tmp / "e.json"),
                               "--set", f"baseUrl={self.base}", "--delay", "10", *extra], capture_output=True, text=True)

    def test_variaveis_testes_e_repeticao_do_get(self):
        Fake.pending = 2
        out = self.run_collection([
            item("login", "POST", "/login", ["pm.test('200', () => pm.response.to.have.status(200));",
                                             "pm.collectionVariables.set('token', pm.response.json().token);"],
                 body={"user": "{{user}}"}),
            item("espera", "GET", "/status", ["pm.test('pronto', () => pm.expect(pm.response.json().status).to.eql('DONE'));",
                                              "pm.test('lista', () => pm.expect([1, 2, 3]).to.include(2));",
                                              "pm.test('número', () => pm.expect(5).to.be.at.least(3));"],
                 auth="Bearer {{token}}"),
        ])
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("(3 tentativas)", out.stdout)
        self.assertEqual(Fake.calls[0][3], {"user": "maria"}, "variável de ambiente no corpo")
        self.assertEqual(Fake.calls[-1][2], "Bearer tok-maria", "variável de coleção salva pelo teste")

    def test_falha_aparece_e_post_nao_repete(self):
        out = self.run_collection([item("criar", "POST", "/x", ["pm.test('201', () => pm.response.to.have.status(201));"])])
        self.assertEqual(out.returncode, 1)
        self.assertIn("FALHA", out.stdout)
        self.assertEqual(len(Fake.calls), 1)

    def test_pagamento_depois_da_requisicao_indicada(self):
        out = self.run_collection([item("link de pagamento", "GET", "/status", [])], "--pay-after", "link de pagamento",
                                  "--set", "serviceOrderId=os-1")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(Fake.calls[-1][:2], ("POST", "/__e2e/pay/os-1"))


class OrquestradorTest(unittest.TestCase):
    def test_comando_do_runner_passa_credenciais_e_pagamento(self):
        cmd = e2e_postman.runner_command(Path("c.json"), Path("e.json"), "http://127.0.0.1:1", "senha", "tok")
        self.assertEqual(cmd[0], "node")
        self.assertIn("baseUrl=http://127.0.0.1:1", cmd)
        self.assertIn("adminPassword=senha", cmd)
        self.assertIn("webhookToken=tok", cmd)
        self.assertEqual(cmd[cmd.index("--pay-after") + 1], e2e_postman.PAY_AFTER)

    def test_a_colecao_tem_a_requisicao_depois_da_qual_se_paga(self):
        from wslib import repos_dir

        path = repos_dir() / "oficina-api" / e2e_postman.COLLECTION
        if not path.is_file():
            self.skipTest("oficina-api fora do disco")
        names = [i["name"] for f in json.loads(path.read_text())["item"] for i in f["item"]]
        self.assertEqual(sum(e2e_postman.PAY_AFTER in n for n in names), 1)


if __name__ == "__main__":
    unittest.main()
