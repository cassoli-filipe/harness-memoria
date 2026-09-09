"""Testes do lote 10 — eventos que a plataforma tem e o harness não registrava.

Dois assuntos, um arquivo:

* `pre_compact.py` (hook novo) — a instrução ANTES da compactação. `montar_instrucao` é
  testada em processo; o `main()` via subprocesso, porque é lá que vivem o bootstrap de
  `sys.path` e o `except` que garante rc=0 mesmo com `src/` quebrado.
* `hooks/hooks.json` — os quatro fatos que o registro precisa cumprir e que nenhum teste
  de outro arquivo confere: `PreCompact` aponta para `pre_compact.py` com o matcher certo
  (`trigger`, não `source` — confirmado lendo o binário instalado, não a doc), `SubagentStart`
  aponta para `session_start.py` (o bloco reduzido já é testado em `test_session_start.py`;
  aqui só se confere a FIAÇÃO), `reafirmar` ganhou `async: true`, e o número de alvos que
  `ci.yml` (job `manifestos`) conta bateu com o que a mudança soma: 5 → 7.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import escrever_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_memoria.config import carregar, invioaveis
from harness_memoria.hooks import pre_compact as PC

RAIZ_DO_REPO = Path(__file__).resolve().parents[1]
SRC = RAIZ_DO_REPO / "src"
HOOK = SRC / "harness_memoria" / "hooks" / "pre_compact.py"
HOOKS_JSON = RAIZ_DO_REPO / "hooks" / "hooks.json"

#: Mesma defesa de `test_session_start.py`/`test_session_end.py`: `CLAUDE_PROJECT_DIR` tem
#: prioridade sobre o `cwd` do evento em `config.raiz_projeto`, e depois da auto-hospedagem
#: (lote 12) o projeto "errado" é este próprio repositório.
_VARS_A_LIMPAR = ("CLAUDE_PROJECT_DIR", "HARNESS_MEMORIA_NARRANDO")


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch: pytest.MonkeyPatch):
    for v in _VARS_A_LIMPAR:
        monkeypatch.delenv(v, raising=False)


def _rodar(evento: str, cwd: Path, env_extra: dict | None = None, args=()):
    """O hook como o Claude Code o roda: subprocesso, evento no stdin, cwd no projeto."""
    env = {k: v for k, v in os.environ.items() if k not in _VARS_A_LIMPAR}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(HOOK), *args],
        input=evento,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        env=env,
        timeout=60,
    )


def _evento(raiz: Path, trigger: str = "auto") -> str:
    return json.dumps({"hook_event_name": "PreCompact", "trigger": trigger, "cwd": str(raiz)})


# --------------------------------------------------------------------------- #
# montar_instrucao — em processo
# --------------------------------------------------------------------------- #


def test_instrucao_leva_cada_inviolavel_em_uma_linha_e_pede_ids_de_adr(projeto: Path):
    cfg = carregar(projeto)
    regras = invioaveis(projeto, cfg.reafirmacao)
    assert regras, "fixture `projeto` não tem invioláveis — teste não testa nada"

    texto = PC.montar_instrucao(projeto, cfg)
    assert texto
    for r in regras:
        assert r in texto
    assert "ADR-NNNN" in texto
    assert "abordagem descartada" in texto


def test_instrucao_vazia_sem_secao_de_invioaveis(tmp_path: Path):
    """Projeto sem `## Regras invioláveis` não gera parágrafo vazio de propósito nenhum.

    Mesma política de `reafirmar.montar_mensagem`: inventar regra genérica gastaria a
    instrução do sumarizador para não dizer nada, e a ausência da seção já é reprovada pela
    auditoria — não é responsabilidade deste hook cobrir isso.
    """
    raiz = tmp_path / "proj"
    (raiz / ".claude").mkdir(parents=True)
    (raiz / "CLAUDE.md").write_text("# Projeto sem invioláveis\n\nSó prosa.\n", encoding="utf-8")
    escrever_config(raiz, {})
    cfg = carregar(raiz)
    assert PC.montar_instrucao(raiz, cfg) == ""


# --------------------------------------------------------------------------- #
# main() — subprocesso, como o Claude Code invoca
# --------------------------------------------------------------------------- #


def test_stdout_e_texto_cru_no_e_json(projeto: Path):
    """Não é `emitir_contexto`: sem `hookSpecificOutput`, sem chave nenhuma — texto puro.

    É o que faz este hook ter custo de contexto zero: a saída vira `customInstructions` do
    sumarizador (confirmado lendo o binário instalado, função `AJ` — `newCustomInstructions`
    é o `join` das saídas STDOUT triviais dos hooks de `PreCompact` bem-sucedidos), não um
    bloco de `additionalContext` novo.
    """
    r = _rodar(_evento(projeto), cwd=projeto)
    assert r.returncode == 0, r.stderr
    saida = r.stdout.strip()
    assert saida, "projeto com invioláveis não pode sair vazio"
    assert not saida.startswith("{"), "saída parece JSON — devia ser texto cru"
    assert "hookSpecificOutput" not in saida
    cfg = carregar(projeto)
    for reg in invioaveis(projeto, cfg.reafirmacao):
        assert reg in saida


def test_gate_projeto_sem_harness_json_fica_em_silencio(tmp_path: Path):
    alheio = tmp_path / "alheio"
    alheio.mkdir()
    (alheio / "CLAUDE.md").write_text("# Outro projeto\n", encoding="utf-8")
    r = _rodar(_evento(alheio), cwd=alheio)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_pacote_quebrado_sai_0_com_stdout_vazio_nunca_exit_2(tmp_path: Path, projeto: Path):
    """O ramo que este hook tem e os outros quatro não: `exit 2` aqui BLOQUEIA a
    compactação inteira (`Reactive compact blocked by PreCompact hook:`, confirmado no
    binário instalado). Com `config.py` quebrado, o hook tem de sair 0 — nunca 2, nunca 1 —
    e sem imprimir nada em stdout, senão o texto de erro viraria instrução do sumarizador.
    """
    src = tmp_path / "src"
    shutil.copytree(SRC, src, ignore=shutil.ignore_patterns("__pycache__"))
    alvo = src / "harness_memoria" / "config.py"
    alvo.write_text(alvo.read_text(encoding="utf-8") + "\ndef quebrado(:\n", encoding="utf-8")

    hook_quebrado = src / "harness_memoria" / "hooks" / "pre_compact.py"
    r = subprocess.run(
        [sys.executable, str(hook_quebrado)],
        input=_evento(projeto),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(projeto),
        env={k: v for k, v in os.environ.items() if k not in _VARS_A_LIMPAR},
        timeout=60,
    )
    assert r.returncode == 0, f"saiu com {r.returncode}, nunca pode ser 2 aqui"
    assert r.stdout.strip() == ""
    assert "Traceback" not in r.stderr, r.stderr
    assert "pre_compact" in r.stderr


def test_autoteste_com_config(projeto: Path):
    r = _rodar("", cwd=projeto, args=("--autoteste", "--projeto", str(projeto)))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "todos os casos corretos" in r.stdout


def test_autoteste_sem_config_e_inerte(tmp_path: Path):
    alheio = tmp_path / "alheio"
    alheio.mkdir()
    (alheio / "CLAUDE.md").write_text("# Outro projeto\n", encoding="utf-8")
    r = _rodar("", cwd=alheio, args=("--autoteste", "--projeto", str(alheio)))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "hook inerte por desenho" in r.stdout


# --------------------------------------------------------------------------- #
# `hooks/hooks.json` — a fiação que este lote muda
# --------------------------------------------------------------------------- #


def _hooks_json() -> dict:
    return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))


def _alvos(hk: dict) -> list[tuple[str, str, dict]]:
    """`(evento, caminho_relativo, objeto_do_hook)` de toda entrada que aponta pro plugin."""
    saida = []
    for evento, entradas in hk["hooks"].items():
        for entrada in entradas:
            for h in entrada["hooks"]:
                for arg in h.get("args", []):
                    if "${CLAUDE_PLUGIN_ROOT}" in arg:
                        rel = arg.replace("${CLAUDE_PLUGIN_ROOT}/", "")
                        saida.append((evento, rel, h))
    return saida


def test_numero_de_alvos_bate_com_o_que_o_ci_espera():
    """Mesma conta do job `manifestos` (`.github/workflows/ci.yml`, `if alvos != 7`).

    5 (linha de base) + 1 (`PreCompact`, mudança 10.1) + 1 (`SubagentStart`, mudança 10.2,
    reusa `session_start.py` — não é arquivo novo) = 7. `ci.yml` não é meu: o número novo
    vai reportado, não editado aqui.
    """
    alvos = _alvos(_hooks_json())
    assert len(alvos) == 7, alvos


def test_precompact_aponta_para_o_script_novo_com_o_matcher_de_trigger():
    hk = _hooks_json()
    entradas = hk["hooks"].get("PreCompact")
    assert entradas, "PreCompact não registrado"
    assert entradas[0]["matcher"] == "manual|auto"
    caminhos = [
        arg.replace("${CLAUDE_PLUGIN_ROOT}/", "")
        for h in entradas[0]["hooks"]
        for arg in h.get("args", [])
    ]
    assert "src/harness_memoria/hooks/pre_compact.py" in caminhos


def test_subagent_start_aponta_para_session_start_sem_arquivo_novo():
    """A decisão 3 do usuário: bloco REDUZIDO, mesma montagem de `session_start.py`
    (`reduzido=True`), sem script próprio — ver `test_session_start.py` para o contrato do
    bloco em si. Aqui só a fiação: o evento tem de existir e apontar pro arquivo certo.
    """
    hk = _hooks_json()
    entradas = hk["hooks"].get("SubagentStart")
    assert entradas, "SubagentStart não registrado"
    caminhos = [
        arg.replace("${CLAUDE_PLUGIN_ROOT}/", "")
        for h in entradas[0]["hooks"]
        for arg in h.get("args", [])
    ]
    assert "src/harness_memoria/hooks/session_start.py" in caminhos


def test_reafirmar_e_async_decisao_2_do_usuario():
    """`async: true` — a economia é ~15s numa sessão de 120 escritas (ver docstring de
    `reafirmar.py`, já corrigido para descrever o mecanismo real: o binário instalado colhe
    o resultado do hook assíncrono e entrega no turno seguinte, não descarta."""
    hk = _hooks_json()
    for entrada in hk["hooks"]["PostToolUse"]:
        for h in entrada["hooks"]:
            if any("reafirmar.py" in a for a in h.get("args", [])):
                assert h.get("async") is True
                return
    pytest.fail("entrada de reafirmar não encontrada em PostToolUse")


def test_session_start_matcher_inclui_fork():
    """Sem `fork` no matcher, uma sessão bifurcada herda o bloco velho do transcript do pai
    — `montar()` já trata os cinco `source` (`test_montar_atende_os_cinco_source_e_so_compact_avisa`
    em `test_session_start.py`); esta é só a fiação que faltava no lado da plataforma.
    """
    hk = _hooks_json()
    matcher = hk["hooks"]["SessionStart"][0]["matcher"]
    assert set(matcher.split("|")) == {"startup", "resume", "clear", "compact", "fork"}


def test_todo_alvo_referenciado_existe_no_disco():
    for _evento_nome, rel, _h in _alvos(_hooks_json()):
        assert (RAIZ_DO_REPO / rel).exists(), f"hooks.json aponta pra `{rel}`, que não existe"
