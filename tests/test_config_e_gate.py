"""Testes do gate e da extração de invioláveis.

O gate é a invariante que permite habilitar o plugin no nível do usuário: sem
`.claude/harness.json`, todo hook é inerte. Um furo aqui significa o harness de um projeto
agindo dentro de outro — que é o defeito exato que motivou tirar a política do código.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import escrever_config

from harness_memoria.config import (
    ConfigReafirmacao,
    ErroDeConfig,
    carregar,
    invioaveis,
)

HOOKS = Path(__file__).resolve().parents[1] / "src" / "harness_memoria" / "hooks"


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #


def test_sem_config_carregar_devolve_none(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text("# vazio\n", encoding="utf-8")
    assert carregar(tmp_path) is None


def test_config_invalida_lanca_em_vez_de_virar_default(projeto: Path):
    """Config presente e quebrada grita. Inerte por typo é bug de horas."""
    (projeto / ".claude" / "harness.json").write_text("{ não é json }", encoding="utf-8")
    with pytest.raises(ErroDeConfig):
        carregar(projeto)


def test_chave_desconhecida_reprova(projeto: Path):
    escrever_config(projeto, {"diarioo": {"teto_linhas": 10}})
    with pytest.raises(ErroDeConfig, match="desconhecida"):
        carregar(projeto)


def test_chave_desconhecida_dentro_de_secao_reprova(projeto: Path):
    escrever_config(projeto, {"diario": {"teto_linha": 10}})
    with pytest.raises(ErroDeConfig, match="teto_linha"):
        carregar(projeto)


@pytest.mark.parametrize(
    "hook",
    ["session_start.py", "session_end.py", "reafirmar.py", "guardar.py", "formatar.py"],
)
def test_hook_e_inerte_em_projeto_sem_config(tmp_path: Path, hook: str):
    """Nenhum hook escreve, bloqueia ou injeta num projeto que não pediu o harness.

    Roda o hook como subprocesso, que é como o Claude Code o roda — importar e chamar
    `main()` não exercitaria o `sys.path` bootstrap nem o `__main__`.
    """
    raiz = tmp_path / "alheio"
    raiz.mkdir()
    (raiz / "CLAUDE.md").write_text("# Projeto que não usa o harness\n", encoding="utf-8")

    evento = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "session_id": "s1",
            "cwd": str(raiz),
            "reason": "prompt_input_exit",
            "tool_input": {"file_path": str(raiz / ".env")},
        }
    )
    r = subprocess.run(
        [sys.executable, str(HOOKS / hook)],
        input=evento,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={"PATH": ""} | {"SYSTEMROOT": "C:\\Windows"},
        cwd=str(raiz),
    )
    assert r.returncode == 0, f"{hook} saiu com {r.returncode}: {r.stderr}"
    assert r.stdout.strip() == "", f"{hook} produziu saída em projeto sem config: {r.stdout}"
    assert not (raiz / "docs").exists(), f"{hook} criou docs/ num projeto sem config"


def test_guarda_nao_bloqueia_env_sem_config(tmp_path: Path):
    """Consequência deliberada do gate: nem as universais valem sem opt-in.

    Negar tool call num repositório que nunca pediu o harness é surpresa, e surpresa em
    bloqueio queima a confiança no mecanismo inteiro.
    """
    raiz = tmp_path / "alheio"
    raiz.mkdir()
    (raiz / "CLAUDE.md").write_text("# sem harness\n", encoding="utf-8")
    evento = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "cwd": str(raiz),
            "tool_input": {"file_path": str(raiz / ".env")},
        }
    )
    r = subprocess.run(
        [sys.executable, str(HOOKS / "guardar.py")],
        input=evento,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(raiz),
    )
    assert "deny" not in r.stdout


def test_guarda_bloqueia_env_com_config(projeto: Path):
    evento = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "cwd": str(projeto),
            "tool_input": {"file_path": str(projeto / ".env")},
        }
    )
    r = subprocess.run(
        [sys.executable, str(HOOKS / "guardar.py")],
        input=evento,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(projeto),
    )
    assert "deny" in r.stdout


# --------------------------------------------------------------------------- #
# Extração de invioláveis
# --------------------------------------------------------------------------- #


def test_extrai_primeira_frase_de_bullet(projeto: Path):
    regras = invioaveis(projeto, ConfigReafirmacao(sub_bloco="**NUNCA**"))
    assert regras == [
        "Escrever segredo no repositório.",
        "Tratar identificador como número.",
    ]


def test_sub_bloco_isola_so_as_proibicoes(projeto: Path):
    """`**SEMPRE**` não entra: só proibição absoluta vale reafirmação."""
    regras = invioaveis(projeto, ConfigReafirmacao(sub_bloco="**NUNCA**"))
    assert not any("testes" in r for r in regras)


def test_sem_sub_bloco_pega_a_secao_inteira(projeto: Path):
    regras = invioaveis(projeto, ConfigReafirmacao())
    assert any("testes" in r for r in regras)


def test_titulo_casa_por_prefixo(tmp_path: Path):
    """`## Regras invioláveis (guardrails)` tem de casar — é como o ValidaNI escreve."""
    raiz = tmp_path / "p"
    raiz.mkdir()
    (raiz / "CLAUDE.md").write_text(
        "## Regras invioláveis (guardrails)\n1. **Nunca escreva no Pipedrive.** Detalhe.\n",
        encoding="utf-8",
    )
    assert invioaveis(raiz, ConfigReafirmacao()) == ["Nunca escreva no Pipedrive."]


def test_negrito_com_dois_pontos_e_rotulo_nao_regra(tmp_path: Path):
    """Defeito medido no ValidaNI: `**Idempotência do sync:**` sozinho não proíbe nada."""
    raiz = tmp_path / "p"
    raiz.mkdir()
    (raiz / "CLAUDE.md").write_text(
        "## Regras invioláveis\n"
        "1. **Idempotência do sync:** o sync escreve SÓ colunas que vêm do Pipedrive. "
        "Nunca sobrescreve o workflow.\n",
        encoding="utf-8",
    )
    regras = invioaveis(raiz, ConfigReafirmacao())
    assert regras == ["Idempotência do sync: o sync escreve SÓ colunas que vêm do Pipedrive."]


def test_ponto_no_meio_de_expressao_nao_parte_a_regra(tmp_path: Path):
    """`vw_aluno_publico (só anon_id).` não deve virar duas frases."""
    raiz = tmp_path / "p"
    raiz.mkdir()
    (raiz / "CLAUDE.md").write_text(
        "## Regras invioláveis\n"
        "- Enviar `aluno.nome` — ou qualquer PII — para o LLM. O nome é re-anexado depois.\n",
        encoding="utf-8",
    )
    assert invioaveis(raiz, ConfigReafirmacao()) == [
        "Enviar `aluno.nome` — ou qualquer PII — para o LLM."
    ]


def test_secao_ausente_devolve_lista_vazia(tmp_path: Path):
    raiz = tmp_path / "p"
    raiz.mkdir()
    (raiz / "CLAUDE.md").write_text("# nada aqui\n", encoding="utf-8")
    assert invioaveis(raiz, ConfigReafirmacao()) == []


def test_max_itens_limita(projeto: Path):
    regras = invioaveis(projeto, ConfigReafirmacao(max_itens=1))
    assert len(regras) == 1


def test_qualquer_chave_com_dollar_e_anotacao(projeto: Path):
    """JSON não tem comentário; a convenção `$` é a única forma de justificar uma escolha.

    Uma por seção não basta — medido na primeira config escrita a sério, que precisou de duas
    na mesma seção e foi reprovada por `$comment2`.
    """
    escrever_config(
        projeto,
        {
            "$schema": "x",
            "$comment": "a",
            "$comment2": "b",
            "$qualquer-coisa": "c",
            "diario": {"$comment": "a", "$comment2": "b", "$porque": "c", "teto_linhas": 300},
        },
    )
    cfg = carregar(projeto)
    assert cfg is not None
    assert cfg.diario.teto_linhas == 300


def test_chave_sem_dollar_continua_reprovando(projeto: Path):
    """A tolerância vale só para `$`: typo em campo real tem de continuar reprovando."""
    escrever_config(projeto, {"diario": {"comment": "sem dollar", "teto_linhas": 300}})
    with pytest.raises(ErroDeConfig, match="comment"):
        carregar(projeto)
