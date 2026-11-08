#!/usr/bin/env bash
# shellcheck source=evals/lib.sh
source "$WS/evals/lib.sh"
M="$REPOS/oficina-infra-fundacao/migrations/004_indice_status.sql"
check "a migration 004 continua existindo" test -f "$M"
check "sem DELIMITER nem PROCEDURE" not grep -qiE 'DELIMITER|PROCEDURE' "$M"
check "ainda cria o índice idx_service_orders_status" grep -qi idx_service_orders_status "$M"
check "sem SQL proibido (MIG-1)" no_finding MIG-1
verify oficina-infra-fundacao
check "sql-lint" step_ok oficina-infra-fundacao sql-lint
check "migrations aplicam duas vezes num MySQL 8.0" step_ok oficina-infra-fundacao migrations-2x
finish
