"""Fixtures: projetos sintéticos mínimos, montados em tmp_path.

Sintéticos de propósito. Um teste que depende de um repositório real passa a falhar quando
aquele repositório muda por razões que nada têm a ver com o harness — e a suíte que falha
por motivo alheio é a suíte que se aprende a ignorar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

CLAUDE_MD = """\
# Projeto de Teste

## Comandos

```bash
python scripts/checar.py
```

## Regras invioláveis

**NUNCA**

- Escrever segredo no repositório. O `.env` está no .gitignore e o hook bloqueia.
- Tratar identificador como número. Zero à esquerda é significativo.

**SEMPRE**

- Rodar os testes antes de declarar trabalho concluído.

## Memória do projeto

- [diário](docs/diario/{mes}.md) — mês corrente.

### Qual ADR ler — por caminho que você vai tocar

| Caminho     | ADRs |
| ----------- | ---- |
| `scripts/`  | 0001 |
"""

ADR_0001 = """\
---
status: accepted
data: 2026-01-15
---

# ADR-0001 — Primeira decisão do projeto

## Plano de Implementação

- feito
"""

DIARIO_README = "# Diário\n\nRegras: uma entrada por sessão.\n"


def _entrada(data: str, becos: str | None = None) -> str:
    corpo = f"""
## {data} — Entrada de teste

**Estado:** concluído
**Escopo:** `scripts/`

### O que foi feito

- algo verificável

### Verificação

- 1 teste passou
"""
    if becos:
        corpo += f"\n### Tentativas descartadas\n\n- {becos}\n"
    return corpo


@pytest.fixture
def projeto(tmp_path: Path):
    """Projeto válido e completo: a auditoria passa nele sem falha nem aviso."""
    from datetime import datetime

    mes = datetime.now().strftime("%Y-%m")
    raiz = tmp_path / "proj"
    (raiz / ".claude").mkdir(parents=True)
    (raiz / "docs" / "adr").mkdir(parents=True)
    (raiz / "docs" / "diario").mkdir(parents=True)
    (raiz / "scripts").mkdir()

    (raiz / "CLAUDE.md").write_text(CLAUDE_MD.replace("{mes}", mes), encoding="utf-8")
    (raiz / "scripts" / "checar.py").write_text("# stub\n", encoding="utf-8")
    (raiz / "docs" / "adr" / "0001-primeira.md").write_text(ADR_0001, encoding="utf-8")
    (raiz / "docs" / "adr" / "README.md").write_text(
        "# ADRs\n\n| ADR | Título | Status |\n|---|---|---|\n"
        "| [0001](0001-primeira.md) | Primeira decisão | accepted |\n",
        encoding="utf-8",
    )
    (raiz / "docs" / "diario" / "README.md").write_text(DIARIO_README, encoding="utf-8")
    (raiz / "docs" / "diario" / f"{mes}.md").write_text(
        f"# Diário · {mes}\n\n---\n"
        + _entrada(f"{mes}-01", "abordagem X → falhou. **Não repetir.**"),
        encoding="utf-8",
    )
    escrever_config(raiz, {})
    return raiz


def escrever_config(raiz: Path, dados: dict) -> Path:
    p = raiz / ".claude" / "harness.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def entrada_de_diario():
    return _entrada
