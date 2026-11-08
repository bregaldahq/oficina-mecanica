#!/usr/bin/env python3
"""Hook PostToolUse de Read, Edit, Write, MultiEdit, Grep e Glob: na primeira vez que a sessão
mexe num repo de repos/, põe no contexto o AGENTS.md dele (o que o repo cria, contratos, como
validar, armadilhas). Assim o AGENTS.md do workspace fica curto e o detalhe de cada repo chega
só quando é preciso, sem depender do carregamento automático de CLAUDE.md aninhado.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
REPO = re.compile(r"(?:^|[/\s])repos/(oficina-[\w-]+)")


def main() -> int:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input") or {}
    target = " ".join(str(tool_input.get(k) or "") for k in ("file_path", "path", "notebook_path"))
    m = REPO.search(target)
    if not m:
        return 0
    name = m.group(1)
    agents = ROOT / "repos" / name / "AGENTS.md"
    seen_path = ROOT / ".ws" / "hooks" / f"{event.get('session_id') or 'sem-sessao'}.repos"
    seen = set(seen_path.read_text().split()) if seen_path.is_file() else set()
    if name in seen or not agents.is_file():
        return 0
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text("\n".join(sorted(seen | {name})) + "\n")
    text = f"Contexto do repositório {name} (repos/{name}/AGENTS.md, carregado uma vez por sessão):\n\n{agents.read_text()}"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
