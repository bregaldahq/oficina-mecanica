#!/usr/bin/env bash
# Planta uma migration com DELIMITER e procedure, como alguém escreveria sem conhecer as regras.
set -euo pipefail
F="$REPOS/oficina-infra-fundacao"
cat > "$F/migrations/004_indice_status.sql" <<'SQL'
-- Índice para a listagem de OS por status.
DELIMITER $$
CREATE PROCEDURE criar_indice_status()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.statistics
                 WHERE table_schema = DATABASE() AND table_name = 'service_orders'
                   AND index_name = 'idx_service_orders_status') THEN
    CREATE INDEX idx_service_orders_status ON service_orders (status);
  END IF;
END$$
DELIMITER ;
CALL criar_indice_status();
DROP PROCEDURE criar_indice_status;
SQL
git -C "$F" add migrations/004_indice_status.sql
git -C "$F" -c core.hooksPath=/dev/null commit -q -m "feat(banco): indice por status nas ordens de servico"
