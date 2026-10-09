"""Falhas observadas na sessão entram no piso do diário — como FATOS, não como becos.

Até aqui `fatos_do_transcript` só lia `tool_use`; o `tool_result` com `is_error` nunca era
lido. Resultado: o registro automático de uma sessão em que o pytest falhou três vezes e a
guarda negou uma escrita no `.env` dizia só "arquivos escritos" e "comandos executados" — a
parte da sessão que mais se parece com um beco sem saída era exatamente a que o piso
descartava. Os formatos abaixo são os vistos em transcripts reais desta máquina em
2026-10-09: `Exit code N`, `PreToolUse:<Ferramenta> hook error: …`, `Permission for this
action was denied …` e `<tool_use_error>…`.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from harness_memoria import diario
from harness_memoria.config import ConfigDiario, carregar
from harness_memoria.hooks import session_end as SE


def _uso(id_: str, nome: str, entrada: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": id_, "name": nome, "input": entrada}],
        },
    }


def _resultado(id_: str, texto: str, erro: bool = True) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": id_, "is_error": erro, "content": texto}
            ],
        },
    }


def _transcript(tmp_path: Path, linhas: list[dict]) -> str:
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in linhas), encoding="utf-8")
    return str(p)


def _sessao_com_falhas(tmp_path: Path) -> dict:
    return diario.fatos_do_transcript(
        _transcript(
            tmp_path,
            [
                _uso("t1", "Bash", {"command": "uv run pytest -x -q"}),
                _resultado("t1", "Exit code 1\nFAILED tests/x.py::y - TOKEN=abc123 vazou"),
                _uso("t2", "Bash", {"command": "grep -n foo x.py"}),
                _resultado("t2", "Exit code 1"),
                _uso("t3", "Write", {"file_path": "/p/.env", "content": "X=1"}),
                _resultado(
                    "t3",
                    "PreToolUse:Write hook error: Bloqueado: `.env` guarda segredos e está "
                    "no .gitignore. Edite `.env.example` (sem valores).",
                ),
                _uso("t4", "Bash", {"command": "git push --force"}),
                _resultado(
                    "t4",
                    "Permission for this action was denied by the Claude Code auto mode "
                    "classifier. Reason: [Destructive].",
                ),
                _uso("t5", "Edit", {"file_path": "/p/a.py"}),
                _resultado("t5", "<tool_use_error>File has been modified since read"),
                _uso("t6", "Bash", {"command": "uv run pytest -x -q"}),
                _resultado("t6", "Exit code 1\nFAILED tests/x.py::y"),
                _uso("t7", "Bash", {"command": "uv run ruff check ."}),
                _resultado("t7", "All checks passed!", erro=False),
            ],
        )
    )


# --------------------------------------------------------------------------- #
# Extração
# --------------------------------------------------------------------------- #


def test_pareia_cada_erro_com_o_comando_que_o_produziu(tmp_path: Path):
    falhas = _sessao_com_falhas(tmp_path)["falhas"]
    comandos = [f for f in falhas if f["tipo"] == "comando"]
    assert [(f["alvo"], f["detalhe"]) for f in comandos] == [
        ("uv run pytest -x -q", "exit 1"),
        ("uv run pytest -x -q", "exit 1"),
    ]


def test_grep_sem_resultado_nao_e_falha(tmp_path: Path):
    falhas = _sessao_com_falhas(tmp_path)["falhas"]
    assert not [f for f in falhas if f["alvo"].startswith("grep")]


def test_negacao_da_guarda_e_classificada_com_o_motivo(tmp_path: Path):
    guarda = [f for f in _sessao_com_falhas(tmp_path)["falhas"] if f["tipo"] == "guarda"]
    assert len(guarda) == 1
    assert guarda[0]["alvo"] == "/p/.env"
    assert guarda[0]["detalhe"].startswith("Bloqueado: `.env` guarda segredos")


def test_negacao_de_permissao_e_classificada(tmp_path: Path):
    perm = [f for f in _sessao_com_falhas(tmp_path)["falhas"] if f["tipo"] == "permissao"]
    assert [f["alvo"] for f in perm] == ["git push --force"]


def test_erro_de_uso_de_ferramenta_e_ruido(tmp_path: Path):
    falhas = _sessao_com_falhas(tmp_path)["falhas"]
    assert not [f for f in falhas if f["alvo"] == "/p/a.py"]


def test_transcript_sem_erro_nao_tem_falhas(tmp_path: Path):
    fatos = diario.fatos_do_transcript(
        _transcript(tmp_path, [_uso("a", "Bash", {"command": "ls"}), _resultado("a", "x", False)])
    )
    assert fatos["falhas"] == []


# --------------------------------------------------------------------------- #
# Renderização no piso
# --------------------------------------------------------------------------- #


def _entrada(projeto: Path, fatos: dict) -> str:
    git = {"branch": "main", "diffstat": "", "status": "", "ultimo_commit": ""}
    return diario.entrada_deterministica(
        projeto, projeto / "docs" / "adr", fatos, git, datetime(2026, 10, 9, 18, 0), None
    )


def test_piso_lista_as_falhas_com_contagem_e_sem_a_saida(projeto: Path, tmp_path: Path):
    texto = _entrada(projeto, _sessao_com_falhas(tmp_path))
    assert "### Falhas observadas (fatos extraídos)" in texto
    assert "- comando `uv run pytest -x -q` saiu com exit 1 (×2)" in texto
    assert "- guarda negou `/p/.env`: Bloqueado: `.env` guarda segredos" in texto
    assert "- permissão negada: `git push --force`" in texto
    assert "abc123" not in texto, "saída de comando não entra no diário versionado"
    assert "Tentativas descartadas" not in texto.split("### Falhas observadas")[0]


def test_piso_corta_em_oito_falhas_e_anuncia_o_resto(projeto: Path, tmp_path: Path):
    linhas = []
    for i in range(10):
        linhas += [
            _uso(f"c{i}", "Bash", {"command": f"make alvo{i}"}),
            _resultado(f"c{i}", "Exit code 2"),
        ]
    texto = _entrada(projeto, diario.fatos_do_transcript(_transcript(tmp_path, linhas)))
    secao = texto.split("### Falhas observadas (fatos extraídos)")[1]
    assert secao.count("- comando `make alvo") == diario.MAX_FALHAS_NO_PISO
    assert "- …e mais 2" in secao


def test_sem_falhas_a_secao_nao_aparece(projeto: Path, tmp_path: Path):
    fatos = diario.fatos_do_transcript(_transcript(tmp_path, []))
    assert "Falhas observadas" not in _entrada(projeto, fatos)


def test_digest_de_becos_nao_le_a_secao_de_falhas(projeto: Path, tmp_path: Path):
    arq = projeto / "docs" / "diario" / f"{datetime.now():%Y-%m}.md"
    antes, _ = diario.becos_sem_saida(projeto / "docs" / "diario", ConfigDiario())
    arq.write_text(
        arq.read_text(encoding="utf-8") + "\n" + _entrada(projeto, _sessao_com_falhas(tmp_path)),
        encoding="utf-8",
    )
    depois, _ = diario.becos_sem_saida(projeto / "docs" / "diario", ConfigDiario())
    assert depois == antes


def test_falhas_ficam_logo_depois_dos_becos_na_prioridade():
    assert ConfigDiario().prioridade_secoes[:2] == ("Tentativas descartadas", "Falhas observadas")


def test_narrador_recebe_as_falhas(projeto: Path, tmp_path: Path):
    cfg = carregar(projeto)
    assert cfg is not None
    git = {"branch": "main", "diffstat": "", "status": "", "ultimo_commit": ""}
    prompt = SE._montar_prompt(projeto, cfg, _sessao_com_falhas(tmp_path), git, datetime.now())
    assert "Falhas observadas:" in prompt
    assert "uv run pytest -x -q" in prompt.split("Falhas observadas:")[1]
