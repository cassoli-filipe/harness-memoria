"""Rotação mensal do diário: o plano, a correção mecânica e o que ela NUNCA toca.

A rotação era a única falha do auditor com remediação 100% derivável — mover o mês fechado
para `arquivo/`, criar o mês novo com o cabeçalho, trocar o ponteiro do CLAUDE.md — e mesmo
assim dependia de alguém fazê-la à mão. Medido neste próprio repositório: o CI do `main`
ficou vermelho desde 2026-10-08 por um commit que mudou uma linha do README, porque virou o
mês. Vermelho por calendário ensina a ignorar o vermelho, que é o defeito que o auditor
existe para evitar.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from conftest import _entrada

from harness_memoria.auditar import Contexto, rodar
from harness_memoria.auditar.__main__ import main as auditar_main
from harness_memoria.config import carregar
from harness_memoria.diario import planejar_rotacao, rotacionar

HOJE = datetime(2026, 10, 9)
FECHADO = "2026-09"


def _com_mes_fechado(raiz: Path, mes: str = FECHADO) -> Path:
    """O projeto do fixture como ele fica no dia em que o mês vira: tudo aponta para `mes`."""
    pasta = raiz / "docs" / "diario"
    for p in pasta.glob("[0-9]*.md"):
        p.unlink()
    (pasta / f"{mes}.md").write_text(
        f"# Diário · {mes}\n\n---\n"
        + _entrada(f"{mes}-08", "abordagem X → falhou. **Não repetir:** Y."),
        encoding="utf-8",
    )
    claude = raiz / "CLAUDE.md"
    texto = re.sub(r"docs/diario/\d{4}-\d{2}\.md", f"docs/diario/{mes}.md", _ler(claude))
    claude.write_text(texto, encoding="utf-8")
    return pasta


def _ler(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _cfg(raiz: Path):
    cfg = carregar(raiz)
    assert cfg is not None
    return cfg


# --------------------------------------------------------------------------- #
# Plano
# --------------------------------------------------------------------------- #


def test_plano_vazio_quando_o_mes_ja_foi_rodado(projeto: Path):
    agora = datetime.now()
    plano = planejar_rotacao(projeto, _cfg(projeto).diario, agora)
    assert not plano.mecanico
    assert rotacionar(projeto, _cfg(projeto).diario, agora) == []


def test_plano_arquiva_mes_fechado_e_seus_sufixos(projeto: Path):
    pasta = _com_mes_fechado(projeto)
    (pasta / f"{FECHADO}b.md").write_text(f"# Diário · {FECHADO}\n", encoding="utf-8")
    plano = planejar_rotacao(projeto, _cfg(projeto).diario, HOJE)
    assert sorted(p.name for p in plano.arquivar) == [f"{FECHADO}.md", f"{FECHADO}b.md"]
    assert plano.criar == pasta / "2026-10.md"
    assert plano.mecanico


def test_plano_ignora_mes_futuro_e_nome_fora_do_padrao(projeto: Path):
    pasta = _com_mes_fechado(projeto)
    (pasta / "2026-10.md").write_text("# Diário · 2026-10\n", encoding="utf-8")
    (pasta / "2026-11.md").write_text("# Diário · 2026-11\n", encoding="utf-8")
    (pasta / "2026-09-rascunho.md").write_text("rascunho\n", encoding="utf-8")
    plano = planejar_rotacao(projeto, _cfg(projeto).diario, HOJE)
    assert [p.name for p in plano.arquivar] == [f"{FECHADO}.md"]
    assert plano.criar is None


def test_claude_md_sem_ponteiro_nao_e_mecanico(projeto: Path):
    _com_mes_fechado(projeto)
    claude = projeto / "CLAUDE.md"
    claude.write_text(re.sub(r"- \[diário\].*\n", "", _ler(claude)), encoding="utf-8")
    plano = planejar_rotacao(projeto, _cfg(projeto).diario, HOJE)
    assert plano.sem_ponteiro
    assert plano.ponteiros == ()


# --------------------------------------------------------------------------- #
# Correção
# --------------------------------------------------------------------------- #


def test_rotacionar_arquiva_cria_o_mes_e_troca_o_ponteiro(projeto: Path):
    pasta = _com_mes_fechado(projeto)
    acoes = rotacionar(projeto, _cfg(projeto).diario, HOJE)

    assert (pasta / "arquivo" / f"{FECHADO}.md").exists()
    assert not (pasta / f"{FECHADO}.md").exists()
    novo = pasta / "2026-10.md"
    assert _ler(novo).startswith("# Diário · 2026-10\n")
    assert "docs/diario/2026-10.md" in _ler(projeto / "CLAUDE.md")
    assert f"docs/diario/{FECHADO}.md" not in _ler(projeto / "CLAUDE.md")
    assert len(acoes) == 3


def test_ponteiro_dentro_de_cerca_e_preservado(projeto: Path):
    _com_mes_fechado(projeto)
    claude = projeto / "CLAUDE.md"
    exemplo = f"\n```markdown\n- [diário](docs/diario/{FECHADO}.md)\n```\n"
    claude.write_text(_ler(claude) + exemplo, encoding="utf-8")
    rotacionar(projeto, _cfg(projeto).diario, HOJE)
    texto = _ler(claude)
    assert "- [diário](docs/diario/2026-10.md) — mês corrente." in texto
    assert exemplo in texto


def test_ponteiro_com_ancora_cita_entrada_e_vai_para_arquivo(projeto: Path):
    _com_mes_fechado(projeto)
    claude = projeto / "CLAUDE.md"
    claude.write_text(
        _ler(claude) + f"\nVer [o incidente](docs/diario/{FECHADO}.md#2026-09-08).\n",
        encoding="utf-8",
    )
    rotacionar(projeto, _cfg(projeto).diario, HOJE)
    assert f"(docs/diario/arquivo/{FECHADO}.md#2026-09-08)" in _ler(claude)


def test_preserva_crlf_do_claude_md(projeto: Path):
    _com_mes_fechado(projeto)
    claude = projeto / "CLAUDE.md"
    claude.write_bytes(_ler(claude).replace("\n", "\r\n").encode("utf-8"))
    rotacionar(projeto, _cfg(projeto).diario, HOJE)
    bruto = claude.read_bytes()
    assert b"docs/diario/2026-10.md" in bruto
    assert bruto.count(b"\r\n") == bruto.count(b"\n")
    # No Windows, escrever em modo texto SEM `newline=""` traduz o `\n` de cada linha já
    # terminada em `\r\n` e produz `\r\r\n` — a contagem acima não pega isso sozinha.
    assert b"\r\r" not in bruto


def test_conflito_em_arquivo_nao_sobrescreve(projeto: Path):
    pasta = _com_mes_fechado(projeto)
    (pasta / "arquivo").mkdir()
    (pasta / "arquivo" / f"{FECHADO}.md").write_text("versão antiga\n", encoding="utf-8")
    plano = planejar_rotacao(projeto, _cfg(projeto).diario, HOJE)
    assert [p.name for p in plano.conflitos] == [f"{FECHADO}.md"]
    rotacionar(projeto, _cfg(projeto).diario, HOJE)
    assert _ler(pasta / "arquivo" / f"{FECHADO}.md") == "versão antiga\n"
    assert (pasta / f"{FECHADO}.md").exists()


def test_rotacionar_e_idempotente(projeto: Path):
    _com_mes_fechado(projeto)
    assert rotacionar(projeto, _cfg(projeto).diario, HOJE)
    assert rotacionar(projeto, _cfg(projeto).diario, HOJE) == []


def test_sem_git_cai_no_rename_e_avisa(projeto: Path):
    _com_mes_fechado(projeto)
    acoes = rotacionar(projeto, _cfg(projeto).diario, HOJE)
    assert any("não rastreado" in a for a in acoes)


@pytest.mark.skipif(shutil.which("git") is None, reason="git ausente")
def test_git_mv_quando_o_arquivo_e_rastreado(projeto: Path):
    _com_mes_fechado(projeto)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=projeto,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "base")
    acoes = rotacionar(projeto, _cfg(projeto).diario, HOJE)
    assert any("git mv" in a for a in acoes)
    assert f"R  docs/diario/{FECHADO}.md -> docs/diario/arquivo/{FECHADO}.md" in git(
        "status", "--porcelain"
    )


# --------------------------------------------------------------------------- #
# Auditoria
# --------------------------------------------------------------------------- #


def test_auditoria_passa_depois_de_rotacionar(projeto: Path):
    _com_mes_fechado(projeto)
    rotacionar(projeto, _cfg(projeto).diario, HOJE)
    ctx = Contexto(raiz=projeto, cfg=_cfg(projeto), hoje=HOJE)
    rodar(ctx)
    assert ctx.falhas == []


def test_mes_fechado_esquecido_no_topo_avisa_antes_e_reprova_depois_do_dia_limite(
    projeto: Path,
):
    pasta = _com_mes_fechado(projeto)
    (pasta / "2026-10.md").write_text("# Diário · 2026-10\n\n---\n", encoding="utf-8")
    claude = projeto / "CLAUDE.md"
    claude.write_text(_ler(claude).replace(f"{FECHADO}.md", "2026-10.md"), encoding="utf-8")

    cedo = Contexto(raiz=projeto, cfg=_cfg(projeto), hoje=datetime(2026, 10, 2))
    rodar(cedo)
    assert not [f for f in cedo.falhas if "rotação pendente" in f]
    assert [a for a in cedo.avisos if "rotação pendente" in a]

    tarde = Contexto(raiz=projeto, cfg=_cfg(projeto), hoje=HOJE)
    rodar(tarde)
    assert [f for f in tarde.falhas if "rotação pendente" in f and "--corrigir" in f]


def test_ponteiro_defasado_sugere_corrigir(projeto: Path):
    _com_mes_fechado(projeto)
    ctx = Contexto(raiz=projeto, cfg=_cfg(projeto), hoje=HOJE)
    rodar(ctx)
    assert [f for f in ctx.falhas if "CLAUDE.md não aponta" in f and "--corrigir" in f]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_corrigir_imprime_as_acoes_e_audita(projeto: Path, capsys):
    anterior = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    _com_mes_fechado(projeto, anterior)
    rc = auditar_main(["--projeto", str(projeto), "--corrigir"])
    saida = capsys.readouterr().out
    assert "Correções mecânicas:" in saida
    assert f"arquivo/{anterior}.md" in saida
    assert rc == 0, saida


def test_cli_reprova_opcao_desconhecida(projeto: Path, capsys):
    assert auditar_main(["--projeto", str(projeto), "--corrijir"]) == 2
    assert "--corrijir" in capsys.readouterr().out
