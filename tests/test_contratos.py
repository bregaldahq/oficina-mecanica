"""Testes do checker de contratos (tools/contratos/).

Cada teste monta quatro mini-repos (com git, porque o checker só olha arquivos versionados) a
partir de um cenário que cumpre todos os contratos, planta uma violação e confere que a
checagem certa a pega. Rodar: python3 -m unittest discover -s tests
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import contratos  # noqa: E402

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJh"

PROVIDER = """<?php
namespace {ns};

final class JwtProvider
{{
    {const}
    public function generate(array $payload): string
    {{
        $claims = array_merge($payload, ['iss' => {iss}, 'iat' => 1, 'exp' => 2]);
        // comentário que só existe de um lado
        $header = $this->base64urlEncode(json_encode(['alg' => 'HS256', 'typ' => 'JWT']));
        $body   = $this->base64urlEncode(json_encode($claims));
        return "{{$header}}.{{$body}}";
    }}

    private function base64urlEncode(string $data): string
    {{
        return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
    }}
}}
"""

CONTRACT_TEST = """<?php
final class JwtContractTest
{{
    private const EXPECTED_TOKEN = '{a}'
        . '{b}';
}}
"""

GREEN = {
    "fundacao": {
        "ssm.tf": 'resource "aws_ssm_parameter" "db_secret" {\n  name  = "/oficina/${var.environment}/db/secret_arn"\n  type  = "String"\n}\n',
        "secrets.tf": """resource "aws_secretsmanager_secret" "db" {
  name = "oficina/${var.environment}/db"
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({
    host     = "h"
    password = random_password.db.result
  })
}

resource "aws_secretsmanager_secret" "auth" {
  name = "oficina/${var.environment}/auth"
}

resource "aws_secretsmanager_secret_version" "auth" {
  secret_id = aws_secretsmanager_secret.auth.id
  secret_string = jsonencode({
    JWT_SECRET = random_password.jwt.result
  })
}
""",
        "locals.tf": 'locals {\n  tags = {\n    Project     = "oficina-mecanica"\n    Environment = var.environment\n'
                     '    ManagedBy   = "terraform"\n    Repo        = "oficina-infra-database"\n  }\n}\n',
        ".github/workflows/deploy.yml": """permissions:
  id-token: write
env:
  TF_VERSION: "1.9.8"
jobs:
  apply:
    steps:
      - run: terraform init -backend-config="key=oficina/oficina-infra-database/${TF_ENV}/terraform.tfstate"
      - run: |
          aws secretsmanager get-secret-value --secret-id "oficina/${TF_ENV}/db" \\
            --query SecretString --output text \\
            | jq -e 'has("host") and has("password")' > /dev/null
""",
        "migrations/001_initial_schema.sql": "CREATE TABLE IF NOT EXISTS customers (\n  id CHAR(36) PRIMARY KEY,\n"
                                             "  name VARCHAR(100) NOT NULL,\n  email VARCHAR(255) NULL\n);\n",
        "migrations/002_seed_demo.sql": "INSERT INTO customers (id, name) VALUES ('1', 'Maria');\n",
    },
    "cluster": {
        "ssm.tf": 'resource "aws_ssm_parameter" "tg" {\n  name  = "/oficina/${var.environment}/nlb/target_group_arn"\n}\n',
        "data.tf": 'data "aws_ssm_parameter" "db_secret" {\n  name = "/oficina/${var.environment}/db/secret_arn"\n}\n',
        "addons-external-secrets.tf": 'resource "kubectl_manifest" "store" {\n  yaml_body = yamlencode({\n'
                                      '    kind       = "ClusterSecretStore"\n    metadata = {\n'
                                      '      name = "oficina-secretsmanager"\n    }\n  })\n}\n',
        "rbac-app-deployer.tf": 'resource "kubernetes_role" "app" {\n  rule {\n    api_groups = ["elbv2.k8s.aws"]\n'
                                '    resources  = ["targetgroupbindings"]\n  }\n  rule {\n'
                                '    api_groups = ["external-secrets.io"]\n    resources  = ["externalsecrets"]\n  }\n}\n',
        "locals.tf": 'locals {\n  repo_name = "oficina-infra-k8s"\n  tags = {\n    Project     = "oficina-mecanica"\n'
                     '    Environment = var.environment\n    ManagedBy   = "terraform"\n    Repo        = local.repo_name\n  }\n}\n',
        "envs/hml.tfvars": 'app_ci_role_arn = "arn:aws:iam::1:role/oficina-gha-oficina-mecanica-tech-challenge"\n',
        ".github/workflows/pr.yml": 'env:\n  TF_VERSION: 1.9.8\njobs:\n  plan:\n    steps:\n'
                                    '      - run: terraform init -backend-config="key=oficina/oficina-infra-k8s/hml/terraform.tfstate"\n',
    },
    "gateway": {
        "apigateway.tf": """resource "aws_apigatewayv2_integration" "auth_cpf" {
  integration_type = "AWS_PROXY"
}

resource "aws_apigatewayv2_integration" "app_proxy" {
  integration_type = "HTTP_PROXY"
}

resource "aws_apigatewayv2_route" "auth_cpf" {
  route_key          = "POST /auth/cpf"
  target             = "integrations/${aws_apigatewayv2_integration.auth_cpf.id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_route" "health" {
  route_key          = "GET /api/health"
  target             = "integrations/${aws_apigatewayv2_integration.app_proxy.id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_route" "app_proxy" {
  route_key          = "ANY /api/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.app_proxy.id}"
  authorization_type = "CUSTOM"
}
""",
        "src/Handler/JwtAuthorizerHandler.php": "<?php\nprivate const PUBLIC_ROUTES = [\n"
                                                "    ['method' => 'GET', 'path' => '/api/health'],\n];\n",
        "src/Security/JwtProvider.php": PROVIDER.format(ns="Oficina\\Auth\\Security", const="", iss="'oficina-mecanica-api'"),
        "tests/Contract/JwtContractTest.php": CONTRACT_TEST.format(a=TOKEN[:20], b=TOKEN[20:]),
        "handler-auth.php": "<?php\n$db = $secrets->get($dbSecretId);\n$host = $db['host'];\n",
        "src/Handler/AuthCpfHandler.php": "<?php\n$secret = $this->secrets->get($this->authSecretId);\n$jwt = $secret['JWT_SECRET'];\n",
        "locals.tf": 'locals {\n  tags = {\n    Project     = "oficina-mecanica"\n    Environment = var.environment\n'
                     '    ManagedBy   = "terraform"\n    Repo        = "oficina-lambda-auth"\n  }\n}\n',
        ".github/workflows/deploy.yml": 'jobs:\n  d:\n    steps:\n      - uses: hashicorp/setup-terraform@v3\n'
                                        '        with:\n          terraform_version: 1.9.8\n'
                                        '      - run: terraform init -backend-config="key=oficina/oficina-lambda-auth/${TF_ENV}/terraform.tfstate"\n',
    },
    "api": {
        "public/index.php": """<?php
$router->get('/api/health', fn() => $h->live(), requireAuth: false);
$router->get('/api/customers', fn() => $c->index())->requireRole('admin');
""",
        "nginx.conf": "server {\n    location /docs {\n    }\n    location /api {\n    }\n}\n",
        "swagger.yaml": "openapi: 3.0.3\npaths:\n  /health:\n    get:\n      security: []\n"
                        "  /auth/cpf:\n    post:\n      security: []\n  /customers:\n    get:\n      summary: x\n",
        "src/Infrastructure/Security/JwtProvider.php": PROVIDER.format(
            ns="App\\Infrastructure\\Security", const="private const ISSUER = 'oficina-mecanica-api';", iss="self::ISSUER"),
        "tests/Unit/Infrastructure/Security/JwtContractTest.php": CONTRACT_TEST.format(a=TOKEN[:10], b=TOKEN[10:]),
        "docs/fase-3/contract-token.md": f"# Token\n\n```\n{TOKEN}\n```\n",
        "docs/fase-3/CONTRATOS.md": """# Contratos

## 2. SSM Parameter Store — nomes exatos

### Publicados por `oficina-infra-database`

| Parâmetro | Tipo | Conteúdo |
|---|---|---|
| `/oficina/<env>/db/secret_arn` | String | ARN |

### Publicados por `oficina-infra-k8s`

| Parâmetro | Tipo | Conteúdo |
|---|---|---|
| `/oficina/<env>/nlb/target_group_arn` | String | ARN |

## 3. Segredos no Secrets Manager

**`oficina/<env>/db`** — JSON:

```json
{ "host": "...", "password": "..." }
```

**`oficina/<env>/auth`** — JSON:

```json
{ "JWT_SECRET": "..." }
```

## 5. Rotas e autorização

### API Gateway (`oficina-lambda-auth`)

| Rota | Integração | Authorizer |
|---|---|---|
| `POST /auth/cpf` | Lambda | nenhum |
| `GET /api/health` | NLB | nenhum |
| `ANY /api/{proxy+}` | NLB | Lambda `jwt-authorizer` |

### Aplicação — matriz de autorização

| Rota | Acesso |
|---|---|
| `GET /api/health` | público |
| todo o resto de `/api/**` | `admin` |

## 6. Banco de dados
""",
        "deploy/base/external-secret.yaml": """apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
spec:
  secretStoreRef:
    name: oficina-secretsmanager
    kind: ClusterSecretStore
  data:
    - secretKey: DB_HOST
      remoteRef: { key: oficina/hml/db, property: host }
    - secretKey: JWT_SECRET
      remoteRef: { key: oficina/hml/auth, property: JWT_SECRET }
""",
        "deploy/base/targetgroupbinding.yaml": "apiVersion: elbv2.k8s.aws/v1beta1\nkind: TargetGroupBinding\n"
                                               "spec:\n  targetGroupARN: TARGET_GROUP_ARN_PLACEHOLDER\n",
        ".github/workflows/deploy.yml": """jobs:
  deploy:
    steps:
      - run: |
          TG_ARN=$(get "/oficina/${ENVIRONMENT}/nlb/target_group_arn")
          sed -i "s#TARGET_GROUP_ARN_PLACEHOLDER#${{ steps.ssm.outputs.target_group_arn }}#" \\
            deploy/base/targetgroupbinding.yaml
""",
        "tests/Integration/PdoCustomerRepositoryTest.php": "<?php\n$pdo->exec('\n    CREATE TABLE customers (\n"
                                                           "        id TEXT PRIMARY KEY,\n        name TEXT NOT NULL,\n"
                                                           "        email TEXT\n    )\n');\n",
        "src/Infrastructure/Repository/PdoCustomerRepository.php": "<?php\n// SELECT id, name, email FROM customers\n",
    },
    "workspace": {
        "AGENTS.md": "Use `bin/ws` e `repos/oficina-api/public/index.php`.\n",
        "bin/ws": "#!/bin/sh\n",
    },
}


class Cenario:
    """Os quatro mini-repos e o workspace, num diretório temporário."""

    def __init__(self, changes: dict[str, dict[str, str | None]] | None = None):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        paths = {}
        for short, files in GREEN.items():
            files = {**files, **(changes or {}).get(short, {})}
            root = base / (short if short == "workspace" else contratos.REPOS[short][0])
            for rel, content in files.items():
                if content is not None:
                    (root / rel).parent.mkdir(parents=True, exist_ok=True)
                    (root / rel).write_text(content)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            if short != "workspace":
                paths[short] = root
        self.repos = contratos.Repos(paths, base / "workspace")

    def run(self, known: set[str] | None = None):
        return contratos.run(self.repos, known=known or set())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


def edit(short: str, rel: str, old: str, new: str) -> dict:
    content = GREEN[short][rel]
    assert old in content, f"'{old}' não está em {short}/{rel}"
    return {short: {rel: content.replace(old, new)}}


class ContratosTest(unittest.TestCase):
    def assertFinds(self, changes: dict, id_: str, severidade: str = "erro"):
        with Cenario(changes) as c:
            found = [f for f in c.run() if f.id == id_ and f.severidade == severidade]
            self.assertTrue(found, f"esperava {severidade} {id_}; achados: {[(f.id, f.severidade, f.mensagem) for f in c.run()]}")
            return found

    def test_cenario_verde_nao_tem_achados(self):
        with Cenario() as c:
            self.assertEqual([(f.id, f.mensagem) for f in c.run()], [])

    # §2 SSM
    def test_consumido_sem_dono(self):
        self.assertFinds({"cluster": {"ssm.tf": None}}, "SSM-1")

    def test_dois_donos(self):
        self.assertFinds({"gateway": {"ssm.tf": GREEN["cluster"]["ssm.tf"]}}, "SSM-2")

    def test_publicado_fora_do_documento(self):
        self.assertFinds(edit("cluster", "ssm.tf", "target_group_arn", "listener_arn"), "SSM-4", "aviso")

    # §4 JWT
    def test_token_literal_diferente(self):
        self.assertFinds(edit("api", "tests/Unit/Infrastructure/Security/JwtContractTest.php", "c2lnbmF0dXJh", "outra"), "JWT-1")

    def test_teste_de_contrato_ausente(self):
        self.assertFinds({"gateway": {"tests/Contract/JwtContractTest.php": None}}, "JWT-1")

    def test_montagem_do_token_diferente(self):
        self.assertFinds(edit("gateway", "src/Security/JwtProvider.php", "'+/', '-_'", "'+/', '__'"), "JWT-2")

    def test_emissor_diferente_da_constante(self):
        self.assertFinds(edit("gateway", "src/Security/JwtProvider.php", "'oficina-mecanica-api'", "'outro'"), "JWT-2")

    # §5 rotas
    def test_rota_publica_da_app_sem_rota_no_gateway(self):
        self.assertFinds(edit("api", "public/index.php", "$router->get('/api/customers', fn() => $c->index())->requireRole('admin');",
                              "$router->post('/api/x/{id}/approval', fn($p) => $o->r($p), requireAuth: false);"), "ROTA-1")

    def test_rota_publica_no_gateway_mas_protegida_na_app(self):
        self.assertFinds(edit("api", "public/index.php", "requireAuth: false", "requireAuth: true"), "ROTA-1")

    def test_gateway_encaminha_o_que_o_nginx_nao_serve(self):
        self.assertFinds(edit("gateway", "apigateway.tf", '"GET /api/health"', '"GET /swagger.yaml"'), "ROTA-1")

    def test_tabela_do_gateway_desatualizada(self):
        self.assertFinds(edit("api", "docs/fase-3/CONTRATOS.md", "| `GET /api/health` | NLB | nenhum |\n", ""), "ROTA-2", "aviso")

    def test_swagger_sem_security_vazio(self):
        self.assertFinds(edit("api", "swagger.yaml", "    get:\n      security: []\n", "    get:\n      summary: y\n"), "ROTA-4", "aviso")

    # §3 segredos
    def test_external_secret_le_chave_inexistente(self):
        self.assertFinds(edit("api", "deploy/base/external-secret.yaml", "property: host", "property: hostname"), "SEG-1")

    def test_lambda_le_chave_inexistente(self):
        self.assertFinds(edit("gateway", "src/Handler/AuthCpfHandler.php", "['JWT_SECRET']", "['JWT_KEY']"), "SEG-1")

    def test_smoke_da_fundacao_le_chave_inexistente(self):
        self.assertFinds(edit("fundacao", ".github/workflows/deploy.yml", 'has("password")', 'has("pass")'), "SEG-1")

    def test_documento_dos_segredos_desatualizado(self):
        self.assertFinds(edit("api", "docs/fase-3/CONTRATOS.md", '{ "JWT_SECRET": "..." }', '{ "JWT_SECRET": "...", "X": 1 }'),
                         "SEG-2", "aviso")

    # cluster e deploy
    def test_cluster_secret_store_com_outro_nome(self):
        self.assertFinds(edit("api", "deploy/base/external-secret.yaml", "name: oficina-secretsmanager", "name: outro"), "ESO-1")

    def test_cluster_secret_store_com_kind_antes_do_name(self):
        self.assertFinds(edit("api", "deploy/base/external-secret.yaml",
                              "    name: oficina-secretsmanager\n    kind: ClusterSecretStore",
                              "    kind: ClusterSecretStore\n    name: outro"), "ESO-1")

    def test_crd_com_kind_antes_do_apiversion(self):
        self.assertFinds({"api": {"deploy/base/extra.yaml": "kind: SecretStore\nmetadata: {}\napiVersion: external-secrets.io/v1beta1\n"}},
                         "RBAC-1")

    def test_crd_sem_rbac(self):
        self.assertFinds(edit("cluster", "rbac-app-deployer.tf", '"targetgroupbindings"', '"outros"'), "RBAC-1")

    def test_placeholder_removido(self):
        self.assertFinds(edit("api", "deploy/base/targetgroupbinding.yaml", "TARGET_GROUP_ARN_PLACEHOLDER", "arn:aws:..."), "DEPLOY-1")

    # §6 migrations
    def test_migration_com_delimiter(self):
        self.assertFinds({"fundacao": {"migrations/003_proc.sql": "DELIMITER $$\nSELECT 1;\n"}}, "MIG-1")

    def test_buraco_na_sequencia(self):
        self.assertFinds({"fundacao": {"migrations/004_x.sql": "SELECT 1;\n"}}, "MIG-1")

    def test_seed_que_rodaria_em_producao(self):
        self.assertFinds({"fundacao": {"migrations/002_seed_demo.sql": None, "migrations/002_seed.sql": "SELECT 1;\n"}}, "MIG-1")

    def test_coluna_faltando_no_schema_dos_testes(self):
        self.assertFinds({"fundacao": {"migrations/003_phone.sql":
                                       "SET @s = 'ALTER TABLE customers ADD COLUMN phone VARCHAR(20) NULL';\n"},
                          "api": {"src/Infrastructure/Repository/PdoCustomerRepository.php": "<?php // phone\n"}},
                         "MIG-2", "aviso")

    # nomes, tags e CI
    def test_chave_do_state_com_nome_novo(self):
        self.assertFinds(edit("cluster", ".github/workflows/pr.yml", "oficina/oficina-infra-k8s/", "oficina/oficina-infra-cluster/"),
                         "NOME-1")

    def test_tag_repo_com_nome_novo(self):
        self.assertFinds(edit("cluster", "locals.tf", 'repo_name = "oficina-infra-k8s"', 'repo_name = "oficina-infra-cluster"'),
                         "NOME-1")

    def test_role_de_ci_com_nome_novo(self):
        self.assertFinds(edit("cluster", "envs/hml.tfvars", "oficina-gha-oficina-mecanica-tech-challenge", "oficina-gha-oficina-api"),
                         "NOME-1")

    def test_tag_repo_com_comentario_no_fim_da_linha(self):
        with Cenario(edit("gateway", "locals.tf", 'Repo        = "oficina-lambda-auth"',
                          'Repo        = "oficina-lambda-auth" # nome antigo, de propósito')) as c:
            self.assertEqual([f.mensagem for f in c.run() if f.id == "NOME-1"], [])
        self.assertFinds(edit("gateway", "locals.tf", 'Repo        = "oficina-lambda-auth"',
                              'Repo        = "oficina-gateway-auth" # novo'), "NOME-1")

    def test_tag_obrigatoria_ausente(self):
        self.assertFinds(edit("gateway", "locals.tf", '    ManagedBy   = "terraform"\n', ""), "TAG-1")

    def test_access_key_estatica(self):
        self.assertFinds(edit("gateway", ".github/workflows/deploy.yml", "      - uses: hashicorp/setup-terraform@v3\n",
                              "      - env:\n          AWS_ACCESS_KEY_ID: x\n      - uses: hashicorp/setup-terraform@v3\n"), "CI-1")

    def test_versoes_diferentes_do_terraform(self):
        self.assertFinds(edit("gateway", ".github/workflows/deploy.yml", "terraform_version: 1.9.8", "terraform_version: 1.9.5"),
                         "CI-1", "aviso")

    # contexto dos agentes
    def test_caminho_citado_que_nao_existe(self):
        self.assertFinds({"workspace": {"AGENTS.md": "Veja `bin/nao-existe.sh`.\n"}}, "DOC-1", "aviso")

    # conhecidos.txt
    def test_erro_conhecido_nao_derruba(self):
        changes = {"cluster": {"ssm.tf": None}}
        with Cenario(changes) as c:
            known = {f"{f.id} {f.chave}" for f in c.run() if f.severidade == "erro"}
            self.assertTrue(known)
            self.assertFalse([f for f in c.run(known) if f.severidade == "erro"])
            self.assertTrue([f for f in c.run(known) if f.severidade == "conhecido"])

    def test_conhecido_que_sumiu_vira_aviso(self):
        with Cenario() as c:
            found = [f for f in c.run({"SSM-1 db/nada"}) if f.id == "CONHECIDO"]
            self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
