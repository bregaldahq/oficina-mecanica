#!/usr/bin/env bash
# Planta um erro de tipo que só o phpstan pega: o teste unitário não usa o método novo.
set -euo pipefail
G="$REPOS/oficina-gateway-auth"
python3 - "$G/src/Domain/Cpf.php" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read().rstrip()
assert s.endswith("}")
s = s[:-1].rstrip() + '''

    public function checkDigits(): int
    {
        return substr($this->value, 9, 2);
    }
}
'''
open(p, "w").write(s)
PY
git -C "$G" add src/Domain/Cpf.php
git -C "$G" -c core.hooksPath=/dev/null commit -q -m "feat(cpf): digitos verificadores do cpf"
