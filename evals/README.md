# Tarefas-canário

Pedidos reais, com nota determinística, para medir se uma mudança no harness (AGENTS.md, skills,
hooks, checker) ajudou ou piorou o agente. Rode as tarefas afetadas antes e depois da mudança.

```bash
bin/ws eval list          # as tarefas
bin/ws eval setup 05      # worktrees isolados na branch eval/<tarefa>, defeito plantado (se houver)
                          # e o pedido para colar
/clear                    # contexto limpo, no mesmo worktree
                          # cole o pedido e deixe o agente trabalhar
bin/ws eval grade 05      # a nota; o resultado vai para .ws/evals/resultados.jsonl
bin/ws eval clean 05      # apaga os worktrees e a branch eval/<tarefa>
```

Funciona só numa sessão em worktree (o app desktop abre assim). Cada tarefa tem:

- `task.md`: o pedido, como o usuário escreveria;
- `repos`: os repos que ela isola;
- `setup.sh` (opcional): planta o defeito e commita na branch da tarefa;
- `grade.sh`: as checagens, com as funções de `lib.sh`.

A tarefa 08 lê `.ws/hooks/guard.log`, onde o `guard-bash.py` registra o que negou ou pediu para
confirmar.
