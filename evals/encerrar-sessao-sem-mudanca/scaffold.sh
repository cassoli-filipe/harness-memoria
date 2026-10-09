#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../_comum/base.sh"
printf 'def valor_do_desconto(preco: float, pct: int) -> float:\n    return int(preco * pct) / 100\n' > scripts/precos.py
commitar
