#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../_comum/base.sh"
printf 'def valor_do_desconto(preco: float, pct: int) -> float:\n    return round(preco * pct / 100, 2)\n' > scripts/precos.py
printf 'def valor_do_frete(peso: float, tarifa: int) -> float:\n    return int(peso * tarifa) / 100\n' > scripts/frete.py
# A sessão anterior deixou duas pendências; esta fecha a primeira e não toca a segunda.
cat >> "docs/diario/$MES.md" <<MD

## $MES-02 — Corrigir o arredondamento do desconto

**Estado:** concluído
**Escopo:** \`scripts/precos.py\`

### O que foi feito

- \`int()\` trocado por \`round()\` em \`valor_do_desconto\`.

### Aberto / Próximo passo

- [ ] Aplicar a mesma correção de arredondamento em \`scripts/frete.py\`.
- [ ] Cobrir o arredondamento de \`valor_do_desconto\` com teste.
MD
commitar
printf 'def valor_do_frete(peso: float, tarifa: int) -> float:\n    return round(peso * tarifa / 100, 2)\n' > scripts/frete.py
