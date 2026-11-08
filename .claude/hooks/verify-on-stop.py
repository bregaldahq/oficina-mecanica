#!/usr/bin/env python3
"""Hook Stop: antes de o agente devolver a vez, o que mudou precisa passar no bin/ws verify.

O Stop dispara ao fim de toda resposta, então o verify só roda quando o estado dos repos
(bin/wslib.py: fingerprint) é diferente do estado no início da sessão e do último estado que
o verify aprovou. Vermelho: devolve o trabalho para o agente uma vez; se continuar vermelho,
deixa encerrar e avisa o usuário.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "bin"))
from wslib import fingerprint  # noqa: E402


def read(path: Path) -> str:
    return path.read_text().strip() if path.is_file() else ""


def summary(report: dict) -> str:
    failed = [f"{r['repo'].removeprefix('oficina-')}/{s['id']}"
              for r in report.get("repos", []) for s in r["steps"] if s["status"] == "falhou"]
    missing = report.get("missing") or []
    return ", ".join(failed + [f"{m} ausente" for m in missing]) or "veja .ws/verify/latest.json"


def main() -> int:
    event = json.load(sys.stdin)
    state = fingerprint()
    start = read(ROOT / ".ws" / "hooks" / f"{event.get('session_id', '')}.inicio")
    if state in (start, read(ROOT / ".ws" / "verify" / "ok-fingerprint")):
        return 0
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print(json.dumps({"systemMessage": "verify-on-stop: Docker parado, a verificação desta sessão não rodou."}))
        return 0

    try:
        run = subprocess.run([str(ROOT / "bin" / "ws"), "verify", "--changed", "--fast", "--json"],
                             capture_output=True, text=True, timeout=110)
    except subprocess.TimeoutExpired:
        print(json.dumps({"systemMessage": "verify-on-stop: bin/ws verify passou de 110 s e foi interrompido; "
                          "rode à mão antes de dar a mudança por pronta."}, ensure_ascii=False))
        return 0
    if run.returncode == 0:
        return 0
    try:
        what = summary(json.loads(run.stdout))
    except json.JSONDecodeError:
        what = (run.stdout + run.stderr).strip().splitlines()[-1:] or ["erro ao rodar o verify"]
        what = what[0]
    if event.get("stop_hook_active"):
        print(json.dumps({"systemMessage": f"bin/ws verify continua vermelho: {what}. Logs em .ws/verify/logs/."},
                         ensure_ascii=False))
        return 0
    print(json.dumps({"decision": "block", "reason":
                      f"bin/ws verify --changed falhou: {what}. Leia os logs em .ws/verify/logs/ e corrija antes de "
                      "encerrar. Se a mudança ainda está pela metade de propósito (vai perguntar algo ao usuário), "
                      "diga na resposta o que está vermelho e por quê."}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
