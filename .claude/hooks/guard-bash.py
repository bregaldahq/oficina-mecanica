#!/usr/bin/env python3
"""Hook PreToolUse do Bash: bloqueia o que as regras para agentes do AGENTS.md proíbem.

As regras de permissão do settings.json casam pelo começo do comando; este hook olha cada
pedaço de verdade. Ele separa `&&`, `||`, `;`, `|` e `&`, entra em `$(...)`, crases,
`bash -c '...'`, `bin/ws exec`, `xargs`, e tira `git -C <dir>`, `terraform -chdir=...`,
`env VAR=...` e `sudo`. Responde deny (proibido), ask (destrói trabalho local ou publica algo:
você decide) ou nada.

Uso como hook: lê o JSON do evento no stdin. Para testar: guard-bash.py --check '<comando>'.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

CONTROL = {"&&", "||", ";", "|", "&", ";;", "|&", "(", ")", "\n"}
SENSITIVE_PATH = re.compile(r"(^|/)\.env(\.(?!example\b)[\w.-]+)?$|\.tfstate(\.backup)?$|\.aws/credentials$|"
                            r"\.config/gh/hosts\.yml$|(^|/)\.netrc$|\.docker/config\.json$|\.ssh/id_[^/]*$")
READERS = {"cat", "less", "more", "head", "tail", "grep", "egrep", "rg", "sed", "awk", "bat", "source", ".",
           "strings", "xxd", "od", "base64", "cp", "mv", "scp", "rsync", "tee", "nl", "cut", "sort", "jq", "vi", "vim", "nano"}
KUBECTL_MUTATING = {"apply", "delete", "patch", "edit", "scale", "create", "replace", "drain", "cordon", "uncordon",
                    "exec", "cp", "label", "annotate", "set", "taint", "run", "expose", "autoscale", "attach", "debug"}
KUBECTL_VALUE_FLAGS = {"-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user", "-s", "--server", "--token"}
AWS_VALUE_FLAGS = {"--profile", "--region", "--output", "--query", "--endpoint-url", "--cli-read-timeout",
                   "--cli-connect-timeout", "--color", "--ca-bundle"}
AWS_MUTATING = re.compile(r"^(create|delete|put|update|modify|terminate|run|start|stop|reboot|attach|detach|tag|untag|"
                          r"associate|disassociate|import|restore|reset|enable|disable|register|deregister|invoke|send|"
                          r"publish|copy|replace|revoke|authorize|purge|rotate|cancel|execute|set|add|remove)(-|$)")
PROTECTED = {"main", "develop"}


def deny(reason: str):
    return ("deny", reason)


def ask(reason: str):
    return ("ask", reason)


def strip_heredocs(cmd: str) -> str:
    """Tira o corpo dos heredocs: é texto (um arquivo, uma mensagem de commit), não comando."""
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        tags = re.findall(r"<<-?\s*['\"]?(\w+)['\"]?", lines[i])
        i += 1
        for tag in tags:
            while i < len(lines) and lines[i].strip() != tag:
                i += 1
            i += 1
    return "\n".join(out)


def inner_commands(cmd: str) -> list[str]:
    """O próprio comando e o que estiver dentro de $(...) e de crases."""
    out = [cmd]
    for m in re.finditer(r"\$\(((?:[^()]|\([^()]*\))*)\)|`([^`]*)`", cmd):
        out += inner_commands(m.group(1) or m.group(2) or "")
    return out


def segments(cmd: str) -> list[list[str]]:
    """Os comandos simples, já sem os operadores de controle."""
    out: list[list[str]] = []
    for text in inner_commands(cmd):
        try:
            lex = shlex.shlex(text.replace("\\\n", " "), posix=True, punctuation_chars=";&|()\n")
            lex.whitespace = " \t\r"
            lex.whitespace_split = True
            tokens = list(lex)
        except ValueError:  # aspas sem fechar: cai no split simples
            tokens = text.split()
        current: list[str] = []
        for tok in tokens:
            if tok in CONTROL or set(tok) <= set(";&|()\n"):
                if current:
                    out.append(current)
                current = []
            else:
                current.append(tok)
        if current:
            out.append(current)
    return out


def strip_prefix(tokens: list[str]) -> list[str]:
    """Tira o que só embrulha o comando de verdade: VAR=x, env, sudo, time, timeout, xargs, nohup,
    exec, command, bin/ws exec <repo>, bin/ws run, bin/tooling run <dir>, bash -c '<cmd>'."""
    t = list(tokens)
    while t:
        head = os.path.basename(t[0]) if "/" in t[0] else t[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t[0]):
            t = t[1:]
        elif head in ("env", "sudo", "nohup", "exec", "command", "builtin", "time", "nice", "stdbuf"):
            t = t[1:]
            while t and (t[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t[0])):
                t = t[1:]
        elif head == "timeout":
            t = t[1:]
            while t and t[0].startswith("-"):
                t = t[1:]
            t = t[1:]  # a duração
        elif head == "xargs":
            t = t[1:]
            while t and t[0].startswith("-"):
                t = t[2:] if t[0] in ("-I", "-n", "-P", "-L", "-d", "-E", "-s") else t[1:]
        elif head == "ws" and "bin/" in t[0] and len(t) > 1 and t[1] == "exec":
            t = t[3:]
        elif head == "ws" and "bin/" in t[0] and len(t) > 1 and t[1] == "run":
            t = t[2:]
        elif head == "tooling" and "bin/" in t[0] and len(t) > 1 and t[1] == "run":
            t = t[3:]
        else:
            return t
    return t


def nested(tokens: list[str]) -> list[str]:
    """O comando dentro de `bash -c '...'`, `sh -c`, `eval`; vazio se não houver."""
    if not tokens:
        return []
    head = os.path.basename(tokens[0])
    if head in ("bash", "sh", "zsh", "dash") and "-c" in tokens:
        i = tokens.index("-c")
        return tokens[i + 1:i + 2]
    if head == "eval":
        return [" ".join(tokens[1:])]
    return []


def positional(tokens: list[str], value_flags: set[str]) -> list[str]:
    out, skip = [], False
    for tok in tokens:
        if skip:
            skip = False
        elif tok in value_flags:
            skip = True
        elif not tok.startswith("-"):
            out.append(tok)
    return out


def current_branch(directory: str) -> str:
    out = subprocess.run(["git", "-C", directory, "branch", "--show-current"], capture_output=True, text=True)
    return out.stdout.strip()


def check_git(args: list[str], cwd: str):
    gitdir = cwd
    while args and args[0] in ("-C", "-c", "--git-dir", "--work-tree") or (args and args[0].startswith(("--git-dir=", "--work-tree="))):
        if args[0] == "-C" and len(args) > 1:
            gitdir = os.path.join(cwd, args[1])
        args = args[2:] if args[0] in ("-C", "-c", "--git-dir", "--work-tree") else args[1:]
    if not args:
        return None
    verb, rest = args[0], args[1:]
    if verb in ("commit", "push", "merge", "rebase", "am", "cherry-pick") and "--no-verify" in rest:
        return deny("--no-verify pula os git hooks do workspace (commit-msg, pre-push), que garantem as convenções")
    if verb == "commit":
        msg = " ".join(rest)
        if re.search(r"co-authored-by", msg, re.I):
            return deny("o AGENTS.md proíbe Co-Authored-By: commits e PRs saem só com o nome do Ricardo")
    if verb == "push":
        if any(a in ("-f", "--force", "--force-with-lease", "--force-if-includes") or a.startswith(("--force-with-lease=", "+"))
               or re.match(r"^-[a-zA-Z]*f", a) for a in rest):
            return deny("force push é proibido")
        if "--delete" in rest or "-d" in rest or any(a.startswith(":") for a in rest):
            return deny("apagar branch remota pelo agente é proibido")
        refs = [a for a in positional(rest, {"-o", "--push-option", "--repo"})][1:]
        for ref in refs:
            dest = ref.split(":")[-1].removeprefix("refs/heads/")
            if dest in PROTECTED:
                return deny(f"push direto em {dest} é proibido: main e develop só mudam por PR")
        if not refs and current_branch(gitdir) in PROTECTED:
            return deny(f"a branch atual é {current_branch(gitdir)}: push direto em main/develop é proibido")
        return ask("push publica no GitHub: confirme")
    if verb == "reset" and "--hard" in rest:
        return ask("git reset --hard descarta trabalho não commitado")
    if verb == "clean" and any(re.match(r"^-[a-zA-Z]*f", a) or a == "--force" for a in rest):
        return ask("git clean -f apaga arquivos não versionados")
    if verb == "checkout" and ("--" in rest or "." in rest):
        return ask("git checkout -- descarta mudanças não commitadas")
    if verb == "restore" and "--staged" not in rest:
        return ask("git restore descarta mudanças não commitadas")
    if verb == "branch" and ("-D" in rest or ({"-d", "--delete"} & set(rest) and {"-f", "--force"} & set(rest))):
        return ask("git branch -D apaga a branch mesmo sem merge")
    if verb == "stash" and rest[:1] and rest[0] in ("drop", "clear"):
        return ask("git stash drop/clear apaga trabalho guardado (o stash é compartilhado entre worktrees)")
    if verb == "worktree" and rest[:1] == ["remove"] and ("--force" in rest or "-f" in rest):
        return ask("git worktree remove --force apaga mudanças do worktree")
    return None


def check_segment(tokens: list[str], cwd: str):
    if tokens and os.path.basename(tokens[0]) in ("env", "printenv", "set", "export", "declare") \
            and (len(tokens) == 1 or tokens[0] == "printenv" or tokens[1:] in (["-p"], ["-x"])):
        return deny("despejar as variáveis de ambiente expõe tokens no contexto")
    tokens = strip_prefix(tokens)
    if not tokens:
        return None
    for inner in nested(tokens):
        decision = check_command(inner, cwd)
        if decision:
            return decision
    head = os.path.basename(tokens[0])
    args = tokens[1:]

    if head in READERS and any(SENSITIVE_PATH.search(a) for a in args if not a.startswith("-")):
        return deny("leitura de segredo (.env, tfstate, credenciais) é proibida pela regra 6 do AGENTS.md")

    if head == "terraform":
        while args and args[0].startswith("-chdir"):
            args = args[2:] if args[0] == "-chdir" else args[1:]
        verbs = positional(args, set())
        if verbs[:1] and verbs[0] in ("apply", "destroy", "import", "taint", "untaint", "force-unlock", "refresh"):
            return deny(f"terraform {verbs[0]} é proibido: infra só muda pelo CI de cada repo (regra 1)")
        if verbs[:1] == ["state"] and verbs[1:2] and verbs[1] in ("rm", "mv", "push", "pull", "replace-provider"):
            return deny(f"terraform state {verbs[1]} é proibido (mexe no state ou o expõe, com segredos)")
        if verbs[:1] == ["workspace"] and verbs[1:2] in (["new"], ["delete"], ["select"]):
            return deny("os ambientes são envs/*.tfvars, não workspaces do Terraform")
    if head == "kubectl":
        verbs = positional(args, KUBECTL_VALUE_FLAGS)
        if verbs and verbs[0] in KUBECTL_MUTATING:
            return deny(f"kubectl {verbs[0]} é proibido: o cluster só muda pelo deploy.yml")
        if verbs[:2] and verbs[0] == "rollout" and verbs[1:2] and verbs[1] not in ("status", "history"):
            return deny(f"kubectl rollout {verbs[1]} é proibido: o cluster só muda pelo deploy.yml")
    if head == "helm":
        verbs = positional(args, KUBECTL_VALUE_FLAGS)
        if verbs and verbs[0] in ("install", "upgrade", "uninstall", "delete", "rollback"):
            return deny(f"helm {verbs[0]} é proibido: os add-ons são do repo de cluster e mudam pelo CI")
    if head == "aws":
        verbs = positional(args, AWS_VALUE_FLAGS)
        service, op = (verbs + ["", ""])[:2]
        if service == "secretsmanager" and op == "get-secret-value":
            return deny("ler segredo é proibido pela regra 6 do AGENTS.md")
        if service == "ssm" and op.startswith("get-parameter") and "--with-decryption" in args:
            return deny("--with-decryption expõe valor secreto")
        if (service, op) in (("kms", "decrypt"), ("ecr", "get-login-password"), ("sts", "get-session-token"),
                             ("configure", "get"), ("configure", "export-credentials")):
            return deny(f"aws {service} {op} expõe credencial")
        if service == "s3" and op in ("cp", "mv", "rm", "sync", "mb", "rb"):
            return deny(f"aws s3 {op} altera a AWS: o perfil do agente é só de leitura")
        if AWS_MUTATING.match(op):
            return deny(f"aws {service} {op} altera a AWS: infra só muda pelo CI (regra 1)")
    if head == "gh":
        verbs = positional(args, {"-R", "--repo", "-X", "--method", "-f", "-F", "--field", "--raw-field", "-H", "--header",
                                   "-q", "--jq", "-t", "--template", "--input", "-b", "--body", "--title"})
        cmd = " ".join(verbs[:2])
        if cmd in ("workflow run", "pr merge", "repo delete", "repo rename", "repo archive", "secret set", "secret delete",
                   "variable set", "variable delete", "auth token", "run rerun", "run cancel") or verbs[:1] == ["release"] \
                and verbs[1:2] and verbs[1] in ("create", "delete", "edit", "upload"):
            return deny(f"gh {cmd} é proibido: deploy, merge, publicação e segredos são decisões suas")
        if verbs[:1] == ["api"]:
            method = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-X", "--method")), "")
            writes = any(a in ("-f", "-F", "--field", "--raw-field", "--input") for a in args)
            graphql = "graphql" in verbs
            if (method and method.upper() != "GET") or (writes and not graphql and method.upper() != "GET") \
                    or (graphql and re.search(r"\bmutation\b", " ".join(args))):
                return deny("gh api com escrita (POST/PUT/PATCH/DELETE ou mutation) é proibido")
        if cmd in ("pr create", "pr comment", "pr review", "pr close", "pr edit", "pr ready", "issue create",
                   "issue comment", "issue close", "issue edit", "repo edit"):
            return ask(f"gh {cmd} publica no GitHub: confirme")
    if head == "docker" and args[:1] == ["push"]:
        return deny("docker push publica imagem; a imagem só sai pelo deploy.yml")
    if head in ("docker", "docker-compose") and "config" in args and (head == "docker-compose" or "compose" in args):
        return deny("docker compose config imprime o .env interpolado (segredos)")
    if head == "git":
        return check_git(args, cwd)
    return None


def check_command(cmd: str, cwd: str):
    # A mensagem de commit pode vir num heredoc, que segments() não olha.
    if re.search(r"\bgit\b[^\n]*\bcommit\b", cmd) and re.search(r"co-authored-by", cmd, re.I):
        return deny("o AGENTS.md proíbe Co-Authored-By: commits e PRs saem só com o nome do Ricardo")
    decision = None
    directory = cwd
    for tokens in segments(strip_heredocs(cmd)):
        if tokens[:1] == ["cd"] and len(tokens) > 1:
            directory = os.path.join(directory, tokens[1])
            continue
        found = check_segment(tokens, directory)
        if found and (decision is None or found[0] == "deny"):
            decision = found
            if found[0] == "deny":
                break
    return decision


def log(event: dict, decision, command: str) -> None:
    """Registra negações e confirmações em .ws/hooks/guard.log: métrica, e prova para as
    tarefas-canário de que o agente tentou (ou não) algo proibido."""
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    try:
        path = root / ".ws" / "hooks" / "guard.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": int(time.time()), "sessao": event.get("session_id", ""), "decisao": decision[0],
                           "motivo": decision[1], "comando": command[:300]}, ensure_ascii=False)
        with path.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main() -> int:
    if sys.argv[1:2] == ["--check"]:
        decision = check_command(" ".join(sys.argv[2:]), os.getcwd())
        print(decision[0] + ": " + decision[1] if decision else "ok")
        return 0
    event = json.load(sys.stdin)
    command = (event.get("tool_input") or {}).get("command", "")
    decision = check_command(command, event.get("cwd") or os.getcwd())
    if decision:
        log(event, decision, command)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision[0],
            "permissionDecisionReason": f"guard-bash: {decision[1]}",
        }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
