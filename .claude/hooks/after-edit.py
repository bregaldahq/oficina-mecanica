#!/usr/bin/env python3
"""Hook PostToolUse de Edit, Write e MultiEdit.

1. Formata o .tf editado com terraform fmt, se houver terraform na máquina.
2. Quando o arquivo editado toca um contrato entre repos, lembra o agente do que mais precisa
   mudar junto. Cada lembrete aparece uma vez por sessão.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])

REMINDERS = [
    ("migrations", r"/migrations/[^/]+\.sql$",
     "Migration: tem de ser idempotente (o pr.yml aplica duas vezes). Onde o MySQL não aceita IF NOT EXISTS, "
     "consulte o information_schema e use PREPARE/EXECUTE; nada de DELIMITER, CREATE DATABASE ou USE. Coluna "
     "nova usada por repositório PDO entra também no CREATE TABLE dos testes de integração da app "
     "(tests/Integration) e no docs/MODELO-DE-DADOS.md. Valide com bin/ws verify --repo fundacao."),
    ("jwt", r"(JwtProvider\.php|JwtContractTest\.php|contract-token\.md)$",
     "JWT (§4 do CONTRATOS.md): a Lambda e a app precisam gerar o mesmo token. Mude os dois JwtProvider, os dois "
     "testes de contrato com o MESMO token literal e o docs/fase-3/contract-token.md, ou nenhum. Nunca troque "
     "o literal só para o teste passar. bin/check-contracts.py --only jwt confere."),
    ("rotas", r"(/apigateway\.tf|/public/index\.php|JwtAuthorizerHandler\.php|/swagger\.yaml)$",
     "Rotas (§5): rota pública existe nos dois lados, com rota dedicada sem authorizer no apigateway.tf e "
     "requireAuth: false em public/index.php, e o swagger.yaml marca security: []. Atualize a seção 5 do "
     "CONTRATOS.md. bin/check-contracts.py --only rotas confere."),
    ("ssm", r"/(ssm|data)\.tf$",
     "SSM (§2): cada parâmetro tem um dono. Quem publica é mergeado antes de quem consome; remoção é ao "
     "contrário; renomear são três etapas. Atualize a seção 2 do CONTRATOS.md. bin/check-contracts.py --only ssm."),
    ("segredos", r"(/secrets\.tf|external-secret[^/]*\.ya?ml|/iam\.tf|addons-external-secrets\.tf)$",
     "Segredos (§3): a fundação é a dona; segredo novo pede policy IRSA do ESO no cluster e ExternalSecret na "
     "app e/ou IAM na Lambda. Nunca leia nem imprima valores. bin/check-contracts.py --only segredos."),
    ("deploy", r"/deploy/(base|overlays)/",
     "deploy/: não troque TARGET_GROUP_ARN_PLACEHOLDER nem APP_IMAGE_PLACEHOLDER por valores, porque o deploy.yml "
     "os substitui por sed. CRD nova precisa de permissão no rbac-app-deployer.tf do cluster. Valide com "
     "bin/ws verify --repo api (kustomize build)."),
    ("nomes", r"(/locals\.tf|/\.github/workflows/[^/]+)$",
     "Nomes antigos: a chave do state (oficina/<nome-antigo>/...), os roles oficina-gha-<nome-antigo> e a tag "
     "Repo continuam com o nome antigo, de propósito. Workflows: OIDC, nunca access key."),
    ("dominio", r"/src/Domain/",
     "Domínio (ADR-003/005): nada de dependência externa em src/Domain; transição de status só por método "
     "nomeado (nunca setStatus), e transição inválida lança InvalidStatusTransitionException; hidratação via "
     "reconstitute()."),
    ("contratos-doc", r"/CONTRATOS\.md$",
     "CONTRATOS.md é normativo: mudança de contrato entra como adendo, no estilo dos existentes, no mesmo "
     "conjunto de PRs que muda a implementação."),
]


def seen_file(session: str) -> Path:
    return ROOT / ".ws" / "hooks" / f"{session or 'sem-sessao'}.lembretes"


def main() -> int:
    event = json.load(sys.stdin)
    path = (event.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return 0
    path = os.path.normpath(os.path.join(event.get("cwd") or os.getcwd(), path))
    notes = []

    if path.endswith(".tf") and shutil.which("terraform") and os.path.isfile(path):
        before = Path(path).read_bytes()
        subprocess.run(["terraform", "fmt", path], capture_output=True)
        if Path(path).read_bytes() != before:
            notes.append(f"terraform fmt reformatou {path}; releia o arquivo antes de editá-lo de novo.")

    seen_path = seen_file(event.get("session_id", ""))
    seen = set(seen_path.read_text().split()) if seen_path.is_file() else set()
    for key, pattern, text in REMINDERS:
        if key not in seen and re.search(pattern, path):
            notes.append(text)
            seen.add(key)
    if seen:
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text("\n".join(sorted(seen)) + "\n")

    if notes:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": "\n\n".join(notes)}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
