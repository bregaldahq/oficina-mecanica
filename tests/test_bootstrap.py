"""bootstrap/aws contra os nomes do projeto: role de CI com o nome antigo do repo (README, "Nomes
antigos"), sub do OIDC com o nome novo, e o backend que os workflows esperam.

Rodar: python3 -m unittest discover -s tests
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "bootstrap" / "aws"
sys.path.insert(0, str(ROOT / "tools"))

from contratos import REPOS  # noqa: E402


class BootstrapTest(unittest.TestCase):
    def test_roles_de_ci_com_nome_antigo_e_sub_com_nome_novo(self):
        text = (BOOTSTRAP / "github-oidc.tf").read_text()
        roles = dict(re.findall(r'(\w+)\s*=\s*\{\s*repo\s*=\s*"[^"]+",\s*role\s*=\s*"([^"]+)"', text))
        repos = dict(re.findall(r'(\w+)\s*=\s*\{\s*repo\s*=\s*"([^"]+)"', text))
        self.assertEqual(set(roles), set(REPOS))
        for short, (new, old) in REPOS.items():
            with self.subTest(repo=short):
                self.assertEqual(roles[short], f"oficina-gha-{old}")
                self.assertEqual(repos[short], new)

    def test_backend_igual_ao_dos_workflows(self):
        state = (BOOTSTRAP / "state.tf").read_text()
        self.assertIn('bucket = "oficina-tfstate-${var.state_bucket_suffix}"', state)
        self.assertIn('name         = "oficina-tflock"', state)
        for short in ("fundacao", "cluster", "gateway"):
            deploy = ROOT / "repos" / REPOS[short][0] / ".github" / "workflows" / "deploy.yml"
            if deploy.is_file():
                with self.subTest(repo=short):
                    self.assertIn("dynamodb_table=oficina-tflock", deploy.read_text())

    def test_agente_nao_le_segredo_nem_state(self):
        agent = (BOOTSTRAP / "agent.tf").read_text()
        for action in ("secretsmanager:GetSecretValue", "kms:Decrypt", "s3:GetObject"):
            with self.subTest(acao=action):
                self.assertIn(f'"{action}"', agent)
        self.assertIn('effect = "Deny"', agent)

    def test_github_sh_nao_executa_sem_apply_e_terminal(self):
        script = (BOOTSTRAP / "github.sh").read_text()
        self.assertIn('[[ -t 0 ]]', script)
        self.assertIn("--apply", script)


if __name__ == "__main__":
    unittest.main()
