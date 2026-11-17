"""bin/verify.py: a checagem de pipe que esconde a falha num workflow.

Rodar: python3 -m unittest discover -s tests
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import verify  # noqa: E402


def repo_with(workflow: str) -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".github" / "workflows").mkdir(parents=True)
    (tmp / ".github" / "workflows" / "pr.yml").write_text(textwrap.dedent(workflow))
    return tmp


class UnsafePipesTest(unittest.TestCase):
    def test_tee_sem_pipefail_esconde_a_falha(self):
        repo = repo_with("""
            jobs:
              quality:
                steps:
                  - name: Cobertura
                    run: php bin/check-coverage.php coverage.xml 80 | tee -a "$GITHUB_STEP_SUMMARY"
        """)
        found = verify.unsafe_pipes(repo)
        self.assertEqual(len(found), 1)
        self.assertIn("Cobertura", found[0])

    def test_shell_bash_ou_pipefail_resolvem(self):
        com_shell = repo_with("""
            jobs:
              quality:
                steps:
                  - name: Cobertura
                    shell: bash
                    run: php x | tee y
        """)
        com_pipefail = repo_with("""
            jobs:
              quality:
                steps:
                  - name: Cobertura
                    run: set -o pipefail; php x | tee y
        """)
        sem_nada = repo_with("""
            jobs:
              quality:
                steps:
                  - name: Cobertura
                    run: php x | tee y
        """)
        self.assertEqual(verify.unsafe_pipes(com_shell), [])
        self.assertEqual(verify.unsafe_pipes(com_pipefail), [])
        self.assertEqual(len(verify.unsafe_pipes(sem_nada)), 1, "o controle precisa acusar")

    def test_default_do_job_vale(self):
        repo = repo_with("""
            jobs:
              terraform:
                defaults:
                  run:
                    shell: bash
                steps:
                  - run: terraform plan | tee plan.txt
        """)
        self.assertEqual(verify.unsafe_pipes(repo), [])

    def test_pipe_que_falha_sozinho_ou_ou_logico_nao_conta(self):
        repo = repo_with("""
            jobs:
              image:
                steps:
                  - run: docker run --rm img php -m | grep -qi newrelic
                  - run: curl -fsS x || true
                  - run: echo "h=$(printf '%s' "$K" | sha256sum | cut -c1-16)" >> "$GITHUB_OUTPUT"
                  - run: |
                      case "$S" in
                        200|404) echo ok ;;
                      esac
        """)
        self.assertEqual(verify.unsafe_pipes(repo), [])


if __name__ == "__main__":
    unittest.main()
