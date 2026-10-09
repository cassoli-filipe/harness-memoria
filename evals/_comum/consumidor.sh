#!/usr/bin/env bash
# Monta um projeto consumidor sintético a partir do `template/` do harness em DESTINO.
#
# Um montador só, para os dois lugares que precisam de um consumidor de verdade: o job
# `autotestes` do CI (`bash evals/_comum/consumidor.sh /tmp/proj`) e os scaffolds das evals
# (`bash "$(dirname "$0")/../_comum/consumidor.sh" .`). Duas cópias deste passo divergiriam
# na primeira mudança do template — e foi assim que o ADR de exemplo do CI ficou fora do
# formato do template uma vez (ver o comentário do ADR derivado, abaixo).
#
# Ambiente mínimo de propósito: o scaffold das evals recebe só PATH, HOME e TMPDIR.
set -euo pipefail

DESTINO="${1:?uso: consumidor.sh DESTINO}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$DESTINO/.claude" "$DESTINO/scripts"
cp -r "$RAIZ/template/docs" "$DESTINO/docs"
rm -f "$DESTINO/docs/diario/AAAA-MM.md"
cp "$RAIZ/template/harness.json" "$DESTINO/.claude/harness.json"
MES=$(date +%Y-%m)
printf '# Diário · %s\n\n---\n\n## %s-01 — Entrada de exemplo\n\n**Estado:** concluído\n\n### Tentativas descartadas\n\n- abordagem X → falhou. **Não repetir.**\n' "$MES" "$MES" \
  > "$DESTINO/docs/diario/$MES.md"

# O ADR de exemplo é DERIVADO do próprio `template.md`, não escrito à mão: o cheque de
# conformidade exige que todo ADR tenha os campos e as seções do template, então um exemplo
# escrito à parte divergiria dele na primeira vez que o template mudasse.
python3 - "$DESTINO" <<'PY'
import re
import sys
from pathlib import Path

destino = Path(sys.argv[1])
tpl = (destino / "docs/adr/template.md").read_text(encoding="utf-8")
corpo = tpl.split("\n---\n", 2)[-1]
corpo = re.sub(
    r"^# ADR-NNNN —.*$",
    "# ADR-0001 — Exemplo de problema com a solução escolhida",
    corpo,
    count=1,
    flags=re.MULTILINE,
)
campos = "\n".join(
    f"{c}: {v}" for c, v in re.findall(r"^([a-z-]+):\s*(.*)$", tpl.split("\n---")[0], re.MULTILINE)
)
campos = campos.replace("status: proposed", "status: accepted").replace(
    "data: AAAA-MM-DD", "data: 2026-01-01"
)
(destino / "docs/adr/0001-exemplo.md").write_text(f"---\n{campos}\n---\n{corpo}", encoding="utf-8")
PY

cat > "$DESTINO/CLAUDE.md" <<MD
# Projeto Consumidor

## Regras invioláveis

**NUNCA**

- Escrever segredo no repositório. O hook bloqueia e o .gitignore cobre.

## Memória

- [diário](docs/diario/$MES.md)

### Qual ADR ler — por caminho que você vai tocar

| Caminho    | ADRs |
| ---------- | ---- |
| \`scripts/\` | 0001 |
MD
