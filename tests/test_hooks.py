"""Testes dos hooks do Claude Code (.claude/hooks/) e dos git hooks (githooks/).

Rodar: python3 -m unittest discover -s tests
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".claude" / "hooks"
sys.path.insert(0, str(ROOT / "bin"))


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HOOKS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard_bash = load("guard-bash")
guard_edit = load("guard-edit")

DENY = [
    "terraform apply",
    "terraform -chdir=repos/oficina-infra-cluster apply -auto-approve",
    "cd repos/oficina-infra-cluster && terraform destroy",
    "bin/ws exec cluster terraform apply",
    "bin/tooling run repos/x terraform state pull",
    "bash -c 'kubectl delete pod x'",
    "kubectl -n oficina-hml delete pod x",
    "kubectl get pods -o name | xargs kubectl delete",
    "kubectl rollout restart deployment/oficina-api",
    "echo ok; helm upgrade x y",
    "aws secretsmanager get-secret-value --secret-id oficina/hml/db",
    "aws --profile p ssm get-parameter --name x --with-decryption",
    "aws ssm put-parameter --name x --value y",
    "aws s3 rm s3://b/k",
    "aws lambda invoke --function-name f out.json",
    "gh workflow run deploy.yml",
    "gh pr merge 3 --squash",
    "gh api -X DELETE repos/o/r/git/refs/heads/x",
    "gh api repos/o/r/issues -f title=x",
    "gh api graphql -f query='mutation { addStar(input: {}) { clientMutationId } }'",
    "gh auth token",
    "git push --force origin feat/x",
    "git -C repos/oficina-api push -f",
    "git push origin HEAD:develop",
    "git -C repos/x push origin main",
    "git push origin +feat/x",
    "git commit -m 'feat(x): y' -m 'Co-Authored-By: Claude <noreply@anthropic.com>'",
    "git commit -F - <<'EOF'\nfeat(x): y\n\nCo-Authored-By: Claude\nEOF",
    "git commit --no-verify -m 'x'",
    "cat repos/oficina-api/.env",
    "grep JWT .env.local",
    "echo $(cat .env)",
    'echo "$(cat .env)"',
    "x=`kubectl delete pod y`",
    'VERSAO="$(terraform destroy -auto-approve)"',
    "cat ~/.aws/credentials",
    "docker compose config",
    "printenv",
    "env",
    "docker push 123.dkr.ecr.us-east-1.amazonaws.com/oficina-api:x",
]
ASK = [
    "git push -u origin feat/x",
    "git reset --hard HEAD~1",
    "git -C repos/x clean -fdx",
    "git checkout -- .",
    "git restore src/x.php",
    "git branch -D feat/x",
    "git stash drop",
    "gh pr create --draft --base develop --title t --body b",
    "gh pr comment 3 -b ok",
]
OK = [
    "terraform fmt -check -recursive",
    "terraform init -backend=false && terraform validate",
    "bin/ws exec gateway terraform validate",
    "bin/ws verify --changed",
    "kubectl get pods -n oficina-hml",
    "kubectl rollout status deploy/x",
    "aws ssm get-parameter --name /oficina/hml/eks/namespace",
    "aws sts get-caller-identity",
    "aws configure list-profiles",
    "gh pr list --repo o/r",
    "gh api 'repos/o/r/actions/runs?branch=develop' --jq '.workflow_runs[0].name'",
    "gh api graphql -f query='query { viewer { login } }'",
    "git status && git diff",
    "git restore --staged x",
    "git branch -d feat/x",
    "git commit -m 'feat(x): y'",
    "cat repos/oficina-api/.env.example",
    "echo 'terraform apply'",
    "grep -rn 'kubectl delete' docs/",
    "cat > /tmp/x.md <<'EOF'\nterraform apply\nkubectl delete pod x\nEOF",
    "env FOO=1 bin/ws verify",
    "export FOO=bar",
    "docker run --rm x",
]


class GuardBashTest(unittest.TestCase):
    def decision(self, cmd: str, cwd: str = "/tmp"):
        found = guard_bash.check_command(cmd, cwd)
        return found[0] if found else None

    def test_proibidos(self):
        for cmd in DENY:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.decision(cmd), "deny")

    def test_pedem_confirmacao(self):
        for cmd in ASK:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.decision(cmd), "ask")

    def test_liberados(self):
        for cmd in OK:
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.decision(cmd))

    def test_push_sem_refspec_olha_a_branch_atual(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", "-b", "develop", tmp], check=True)
            self.assertEqual(self.decision("git push", tmp), "deny")
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "-b", "feat/x"], check=True)
            self.assertEqual(self.decision("git push", tmp), "ask")

    def test_saida_do_hook(self):
        event = {"tool_input": {"command": "terraform apply"}, "cwd": "/tmp"}
        out = subprocess.run([str(HOOKS / "guard-bash.py")], input=json.dumps(event), capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        event["tool_input"]["command"] = "ls"
        out = subprocess.run([str(HOOKS / "guard-bash.py")], input=json.dumps(event), capture_output=True, text=True)
        self.assertEqual(out.stdout, "")


class GuardEditTest(unittest.TestCase):
    PROJECT = "/root/ws/.claude/worktrees/sessao-a"

    def test_negados(self):
        for path in ["/root/ws/repos/oficina-api/.env", "/x/.env.local", "/x/terraform.tfstate",
                     "/root/ws/repos/oficina-api/vendor/a/b.php", "/root/ws/repos/oficina-infra-cluster/.terraform/x",
                     "/root/ws/repos/oficina-api/repos/oficina-lambda-auth/src/x.php",
                     "/root/ws/repos/oficina-api/.claude/worktrees/velho/src/x.php",
                     "/root/.aws/credentials", "/root/ws/.claude/worktrees/sessao-b/AGENTS.md"]:
            with self.subTest(path=path):
                self.assertIsNotNone(guard_edit.decide(path, self.PROJECT))

    def test_liberados(self):
        for path in ["/root/ws/repos/oficina-api/src/Domain/Entity/Customer.php", "/x/.env.example",
                     "/root/ws/.claude/worktrees/sessao-a/AGENTS.md", "/root/ws/.claude/worktrees/sessao-a/repos/oficina-api/x.php"]:
            with self.subTest(path=path):
                self.assertIsNone(guard_edit.decide(path, self.PROJECT))


class AfterEditTest(unittest.TestCase):
    def run_hook(self, project: Path, path: str, session: str) -> str:
        event = {"tool_input": {"file_path": path}, "cwd": str(project), "session_id": session}
        out = subprocess.run([str(HOOKS / "after-edit.py")], input=json.dumps(event), capture_output=True, text=True,
                             env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)})
        return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] if out.stdout else ""

    def test_lembrete_uma_vez_por_sessao(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            path = str(project / "repos/oficina-infra-fundacao/migrations/004_x.sql")
            self.assertIn("idempotente", self.run_hook(project, path, "s1"))
            self.assertEqual(self.run_hook(project, path, "s1"), "")
            self.assertIn("idempotente", self.run_hook(project, path, "s2"))
            self.assertEqual(self.run_hook(project, str(project / "README.md"), "s3"), "")

    @unittest.skipUnless(shutil.which("terraform"), "sem terraform na máquina")
    def test_formata_tf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tf = Path(tmp) / "x.tf"
            tf.write_text('locals {\n  a    =   1\n}\n')
            self.assertIn("terraform fmt", self.run_hook(Path(tmp), str(tf), "s1"))
            self.assertEqual(tf.read_text(), "locals {\n  a = 1\n}\n")


class RepoContextTest(unittest.TestCase):
    def run_hook(self, project: Path, tool_input: dict, session: str) -> str:
        event = {"tool_input": tool_input, "session_id": session}
        out = subprocess.run([str(HOOKS / "repo-context.py")], input=json.dumps(event), capture_output=True, text=True,
                             env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)})
        return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] if out.stdout else ""

    def test_agents_md_do_repo_uma_vez_por_sessao(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for name in ("oficina-api", "oficina-infra-cluster"):
                (project / "repos" / name).mkdir(parents=True)
                (project / "repos" / name / "AGENTS.md").write_text(f"guia do {name}\n")
            self.assertIn("guia do oficina-api", self.run_hook(project, {"file_path": f"{tmp}/repos/oficina-api/src/x.php"}, "s1"))
            self.assertEqual(self.run_hook(project, {"file_path": f"{tmp}/repos/oficina-api/y.php"}, "s1"), "")
            self.assertIn("guia do oficina-infra-cluster", self.run_hook(project, {"path": "repos/oficina-infra-cluster"}, "s1"))
            self.assertEqual(self.run_hook(project, {"file_path": f"{tmp}/AGENTS.md"}, "s1"), "")


class GitHooksTest(unittest.TestCase):
    def commit_msg(self, message: str) -> int:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(message)
        try:
            return subprocess.run([str(ROOT / "githooks" / "commit-msg"), f.name], capture_output=True).returncode
        finally:
            os.unlink(f.name)

    def test_commit_msg(self):
        self.assertEqual(self.commit_msg("fix(gateway): rota dedicada para o webhook\n\ncorpo com acentuação\n"), 0)
        self.assertEqual(self.commit_msg("Merge pull request #3 from x/y\n"), 0)
        self.assertNotEqual(self.commit_msg("fix: sem escopo\n"), 0)
        self.assertNotEqual(self.commit_msg("fix(gateway): correção com acento\n"), 0)
        self.assertNotEqual(self.commit_msg("arrumei umas coisas\n"), 0)
        self.assertNotEqual(self.commit_msg("fix(x): y\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"), 0)
        self.assertNotEqual(self.commit_msg("fix(x): y\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n"), 0)

    def pre_push(self, remote_ref: str) -> int:
        line = f"refs/heads/x 1111 {remote_ref} 0000\n"
        return subprocess.run([str(ROOT / "githooks" / "pre-push"), "origin", "url"], input=line, text=True,
                              capture_output=True, env={**os.environ, "OFICINA_PRE_PUSH_VERIFY": "0"}).returncode

    def test_pre_push(self):
        self.assertNotEqual(self.pre_push("refs/heads/main"), 0)
        self.assertNotEqual(self.pre_push("refs/heads/develop"), 0)
        self.assertEqual(self.pre_push("refs/heads/feat/x"), 0)


class VerifyOnStopTest(unittest.TestCase):
    def test_nao_roda_quando_nada_mudou_na_sessao(self):
        from wslib import fingerprint
        session = f"teste-{uuid.uuid4().hex}"
        start = ROOT / ".ws" / "hooks" / f"{session}.inicio"
        start.parent.mkdir(parents=True, exist_ok=True)
        start.write_text(fingerprint() + "\n")
        try:
            out = subprocess.run([str(HOOKS / "verify-on-stop.py")], input=json.dumps({"session_id": session}),
                                 capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)}, timeout=30)
            self.assertEqual((out.returncode, out.stdout), (0, ""))
        finally:
            start.unlink()


if __name__ == "__main__":
    unittest.main()
