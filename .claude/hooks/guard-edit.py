#!/usr/bin/env python3
"""Hook PreToolUse de Edit, Write, MultiEdit e NotebookEdit: nega escrita onde o agente não deve
escrever (segredos, arquivos gerados, cópias velhas dos repos, o worktree de outra sessão)."""
import json
import os
import re
import sys

RULES = [
    (re.compile(r"(^|/)\.env(\.(?!example\b)[\w.-]+)?$"), "é segredo local (.env); a regra 6 do AGENTS.md proíbe"),
    (re.compile(r"\.tfstate(\.backup)?$"), "é state do Terraform, que só o CI mexe"),
    (re.compile(r"/vendor/"), "vendor/ é gerado pelo Composer: mude o composer.json e rode composer (bin/ws exec <repo> composer ...)"),
    (re.compile(r"/\.terraform/"), ".terraform/ é gerado pelo terraform init"),
    (re.compile(r"/repos/[^/]+/(repos|\.claude/worktrees)/"),
     "é uma cópia aninhada ou um worktree velho de um repo, não o clone de trabalho: edite em repos/<nome>/"),
    (re.compile(r"/(\.aws|\.ssh|\.config/gh)/|/\.netrc$|/\.docker/config\.json$"), "guarda credenciais"),
]


def decide(path: str, project: str) -> str | None:
    for pattern, reason in RULES:
        if pattern.search(path):
            return reason
    # O worktree de outra sessão do app desktop: outra conversa está trabalhando nele.
    m = re.search(r"^(.*/\.claude/worktrees/[^/]+)/", path)
    if m and not (project + "/").startswith(m.group(1) + "/"):
        return "é o worktree de outra sessão do Claude Code; edite só dentro desta sessão"
    return None


def session_root(project: str, cwd: str) -> str:
    """A raiz desta sessão. No app desktop, CLAUDE_PROJECT_DIR aponta para o checkout principal
    mesmo quando a sessão roda num worktree: aí quem diz qual é o worktree da sessão é o cwd."""
    project, cwd = os.path.normpath(project), os.path.normpath(cwd)
    m = re.search(r"^(.*/\.claude/worktrees/[^/]+)(/|$)", cwd)
    if m and (m.group(1) + "/").startswith(project + "/"):
        return m.group(1)
    return project


def main() -> int:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not path:
        return 0
    cwd = event.get("cwd") or os.getcwd()
    path = os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))
    reason = decide(path, session_root(os.environ.get("CLAUDE_PROJECT_DIR") or cwd, cwd))
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"guard-edit: {path} {reason}",
        }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
