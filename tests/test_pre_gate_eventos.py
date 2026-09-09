"""Pré-gate em `session_start.py` (evento `SubagentStart`) e `pre_compact.py`.

Os dois entraram em `hooks.json` (lote 10, onda 4) sem o pré-gate do lote 2, que os três
hooks quentes (`guardar`, `reafirmar`, `formatar`) já tinham (`test_hooks_quentes.py`).
Medido, projeto sem `.claude/harness.json`, p25 de n=25 intercaladas: `session_start.py`
como `SubagentStart` 150,0 → 68,2 ms; `pre_compact.py` 104,9 → 52,9 ms (piso de
interpretador nu: 52,9 ms — fica NO piso). `SubagentStart` é o caso caro: dispara uma vez
por Task, então numa sessão de orquestração com várias Tasks o import pago se multiplica —
exatamente a categoria de desperdício que o lote 2 existe para eliminar. O cenário COM
config não regride: 126,9 → 120,5 ms e 106,3 → 107,5 ms, dentro do ruído de máquina.

Mesma família de teste de `test_hooks_quentes.py`: SUBPROCESSO, porque o pré-gate roda em
tempo de import, e a única forma de exercitar `sys.path` + `__main__` é rodar o script de
verdade — testar `avaliar()`/`montar()` direto não passaria pelo bootstrap.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
HOOKS = SRC / "harness_memoria" / "hooks"

#: Os dois hooks desta ressalva, cada um com o EVENTO exato que dispara o caminho quente:
#: `session_start.py` é o script do `SubagentStart` (o caro — uma vez por Task), e
#: `pre_compact.py` só tem um evento.
_EVENTOS = {
    "session_start.py": lambda raiz: json.dumps(
        {
            "hook_event_name": "SubagentStart",
            "cwd": str(raiz),
            "agent_id": "a-1",
            "agent_type": "general-purpose",
        }
    ),
    "pre_compact.py": lambda raiz: json.dumps(
        {"hook_event_name": "PreCompact", "trigger": "auto", "cwd": str(raiz)}
    ),
}


@pytest.fixture
def alheio(tmp_path: Path) -> Path:
    """Projeto que NÃO adotou o harness. O cenário que pagava o import inteiro à toa."""
    raiz = tmp_path / "alheio"
    raiz.mkdir()
    (raiz / "CLAUDE.md").write_text("# Projeto que não usa o harness\n", encoding="utf-8")
    return raiz


def _rodar_importtime(hook: str, evento: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "importtime", str(HOOKS / hook)],
        input=evento,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
        timeout=120,
    )


@pytest.mark.parametrize("hook", sorted(_EVENTOS))
def test_pre_gate_nao_importa_o_pacote_em_projeto_sem_config(alheio: Path, hook: str):
    """A prova direta desta ressalva: em projeto sem config, nenhum dos dois importa `config`.

    Antes desta correção os dois hooks importavam o pacote inteiro incondicionalmente —
    `harness_memoria.config` aparecia sempre em `-X importtime`, mesmo para um evento (o
    arranque de um subagente, ou uma compactação) que não tem nada a fazer num projeto que
    nunca pediu o harness. Este teste falha na árvore anterior à correção — ver a medição no
    docstring do módulo.
    """
    r = _rodar_importtime(hook, _EVENTOS[hook](alheio), alheio)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"{hook} produziu saída em projeto sem config"
    carregados = r.stderr
    assert "harness_memoria.hooks._leve" in carregados, f"{hook}: o pré-gate não rodou"
    for modulo in ("harness_memoria.config", "harness_memoria.diario", "dataclasses", "tempfile"):
        assert modulo not in carregados, f"{hook} importou {modulo} para não fazer nada"


@pytest.mark.parametrize("hook", sorted(_EVENTOS))
def test_com_config_o_hook_importa_o_pacote_inteiro(projeto: Path, hook: str):
    """O outro lado, obrigatório: o pré-gate não pode ter matado o caminho normal.

    Um hook silenciosamente inerte também devolve rc=0 e stdout vazio — é o modo de falha
    próprio desta mudança, e o único jeito de distingui-lo de sucesso é exigir que o
    trabalho tenha de fato acontecido.
    """
    r = _rodar_importtime(hook, _EVENTOS[hook](projeto), projeto)
    assert r.returncode == 0, r.stderr
    assert "harness_memoria.config" in r.stderr, f"{hook} ficou inerte em projeto COM config"


@pytest.mark.parametrize("hook", sorted(_EVENTOS))
def test_importar_o_modulo_do_hook_nao_encerra_o_processo(alheio: Path, hook: str, monkeypatch):
    """A mesma guarda que os três hooks quentes já tinham: import não pode `sys.exit`.

    O pré-gate roda em tempo de import. Sem a guarda `__name__ == "__main__"`, um `pytest`
    lançado de um diretório com `CLAUDE.md` e sem `.claude/harness.json` mataria a própria
    coleta — e a suíte importa este módulo (`test_session_start.py` faz `import
    harness_memoria.hooks.session_start as SS`).
    """
    monkeypatch.chdir(alheio)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    modulo = f"harness_memoria.hooks.{hook[:-3]}"
    for nome in [m for m in list(sys.modules) if m.startswith("harness_memoria.hooks")]:
        del sys.modules[nome]
    __import__(modulo)  # não deve levantar SystemExit


@pytest.mark.parametrize("hook", sorted(_EVENTOS))
def test_pre_gate_nao_mata_o_autoteste(alheio: Path, projeto: Path, hook: str):
    """`--autoteste` recebe o projeto por argumento; o cwd do processo não é ele.

    Sem a guarda `--autoteste`, `session_start.py --autoteste --projeto <com-config>` rodado
    de um diretório sem `harness.json` devolvia saída VAZIA com rc=0 — o autoteste do CI
    ficaria verde tendo conferido zero casos.
    """
    r = subprocess.run(
        [sys.executable, str(HOOKS / hook), "--autoteste", "--projeto", str(projeto)],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(alheio),
        env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "inerte por desenho" not in r.stderr, "conferiu o cwd, não o `--projeto`"
