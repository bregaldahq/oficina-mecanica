#!/usr/bin/env python3
"""Hook SessionStart: garante repos/ (ensure-repos.sh), guarda o estado inicial dos repos para o
hook Stop e põe no contexto o retrato do bin/ws context. O que este script imprime entra no
contexto da sessão."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "bin"))


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        event = {}
    ensure = subprocess.run([str(ROOT / ".claude" / "hooks" / "ensure-repos.sh")], capture_output=True, text=True)
    if ensure.stdout.strip():
        print(ensure.stdout.strip())

    from wslib import fingerprint  # depois do ensure-repos: o repos/ pode ter acabado de surgir
    hooks = ROOT / ".ws" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    for old in hooks.iterdir():  # estado de sessões de mais de uma semana
        if old.is_file() and time.time() - old.stat().st_mtime > 7 * 86400:
            old.unlink()
    (hooks / f"{event.get('session_id', '')}.inicio").write_text(fingerprint() + "\n")

    try:
        context = subprocess.run([str(ROOT / "bin" / "ws"), "context"], capture_output=True, text=True, timeout=20)
        if context.stdout.strip():
            print("Estado dos repositórios (bin/ws context: branch, arquivos sujos, divergência, PRs abertos, CI de develop):")
            print(context.stdout.rstrip())
    except subprocess.TimeoutExpired:
        print("bin/ws context demorou demais (rede?); rode à mão se precisar do estado dos repos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
