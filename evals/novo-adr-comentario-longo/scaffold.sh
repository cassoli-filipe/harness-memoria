#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../_comum/base.sh"
cat > scripts/fornecedor.py <<'PY'
def buscar_pedido(id_: int) -> dict:
    return {"id": id_}


def buscar_pedidos(ids: list[int]) -> list[dict]:
    return [{"id": i} for i in ids]
PY
cat > scripts/sincronizar.py <<'PY'
from fornecedor import buscar_pedido


def sincronizar(ids: list[int]) -> list[dict]:
    return [buscar_pedido(i) for i in ids]
PY
commitar
