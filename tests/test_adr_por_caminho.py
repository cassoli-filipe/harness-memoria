"""ADRs do mapa "Qual ADR ler" injetados no PreToolUse de escrita (ADR-0009).

O mapa do CLAUDE.md era auditado e não tinha leitor mecânico: quem editava `diario.py`
recebia, no início da sessão, os títulos de cinco ADRs e nenhuma linha do que eles decidem.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import escrever_config

from harness_memoria import adr
from harness_memoria.config import carregar

HOOKS = Path(__file__).resolve().parents[1] / "src" / "harness_memoria" / "hooks"

MAPA = """\
### Qual ADR ler — por caminho que você vai tocar

| Caminho              | ADRs       |
| -------------------- | ---------- |
| `scripts/`           | 0001       |
| `src/lote.py`        | 0002, 0003 |
| `docs/`, `src/lote.py` | 0002     |
"""


def _adr(raiz: Path, num: str, *, status: str = "accepted", regra: str = "", decisao: str = ""):
    corpo = f"---\nstatus: {status}\ndata: 2026-01-15\n---\n\n# ADR-{num} — Decisão {num}\n\n"
    if regra:
        corpo += f"## Regra\n\n{regra}\n\n"
    corpo += f"## Contexto\n\nporque sim\n\n## Decisão\n\n{decisao or 'decidido'}\n\n"
    corpo += "## Plano de Implementação\n\n- feito\n"
    (raiz / "docs" / "adr" / f"{num}-decisao-{num}.md").write_text(corpo, encoding="utf-8")


def _com_mapa(projeto: Path) -> Path:
    claude = projeto / "CLAUDE.md"
    texto = claude.read_text(encoding="utf-8")
    inicio = texto.index("### Qual ADR ler")
    claude.write_text(texto[:inicio] + MAPA, encoding="utf-8")
    (projeto / "src").mkdir(exist_ok=True)
    (projeto / "src" / "lote.py").write_text("LOTE = 50\n", encoding="utf-8")
    _adr(projeto, "0002", regra="- Busque em lotes de 50.\n- Não paralelize com threads.")
    _adr(projeto, "0003", decisao="Lote de 50 porque 100 estoura 1 MB.")
    return projeto


def _escrever(
    raiz: Path, rel: str, *, sessao: str = "s1", agente: str | None = None, ferramenta="Edit"
):
    evento = {
        "hook_event_name": "PreToolUse",
        "tool_name": ferramenta,
        "session_id": sessao,
        "cwd": str(raiz),
        "tool_input": {"file_path": str(raiz / rel)},
    }
    if agente:
        evento["agent_id"] = agente
    r = subprocess.run(
        [sys.executable, str(HOOKS / "guardar.py")],
        input=json.dumps(evento),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(raiz),
        env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else {}


def _compactar(raiz: Path, sessao: str = "s1") -> None:
    evento = {"hook_event_name": "SessionStart", "source": "compact", "session_id": sessao}
    evento["cwd"] = str(raiz)
    r = subprocess.run(
        [sys.executable, str(HOOKS / "session_start.py")],
        input=json.dumps(evento),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(raiz),
        env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------- #
# O mapa
# --------------------------------------------------------------------------- #


def test_mapa_le_caminhos_e_numeros_de_cada_linha():
    assert adr.mapa_por_caminho(MAPA) == [
        (["scripts/"], ["0001"]),
        (["src/lote.py"], ["0002", "0003"]),
        (["docs/", "src/lote.py"], ["0002"]),
    ]


def test_sem_a_secao_o_mapa_e_none():
    assert adr.mapa_por_caminho("# Projeto\n\n## Regras\n") is None


def test_casa_prefixo_de_pasta_e_arquivo_exato(projeto: Path):
    mapa = adr.mapa_por_caminho(MAPA)
    _com_mapa(projeto)
    assert adr.adrs_do_caminho(mapa, "scripts/checar.py", projeto) == ["0001"]
    assert adr.adrs_do_caminho(mapa, "src/lote.py", projeto) == ["0002", "0003"]
    assert adr.adrs_do_caminho(mapa, "src/lote_v2.py", projeto) == []
    assert adr.adrs_do_caminho(mapa, "scriptsx/a.py", projeto) == []


def test_pasta_sem_barra_no_mapa_casa_por_prefixo(projeto: Path):
    mapa = [(["scripts"], ["0001"])]
    assert adr.adrs_do_caminho(mapa, "scripts/checar.py", projeto) == ["0001"]


# --------------------------------------------------------------------------- #
# O que entra de cada ADR
# --------------------------------------------------------------------------- #


def test_regra_tem_preferencia_sobre_a_decisao(projeto: Path):
    _com_mapa(projeto)
    texto, mostrados = adr.contexto_por_caminho(
        projeto, projeto / "docs" / "adr", ["0002"], "src/lote.py"
    )
    assert "Busque em lotes de 50" in texto
    assert "decidido" not in texto
    assert mostrados == ["0002"]


def test_sem_regra_entra_a_decisao_inteira(projeto: Path):
    _com_mapa(projeto)
    texto, _ = adr.contexto_por_caminho(projeto, projeto / "docs" / "adr", ["0003"], "src/lote.py")
    assert "Lote de 50 porque 100 estoura 1 MB." in texto
    assert "ADR-0003 [accepted] Decisão 0003" in texto


def test_decisao_maior_que_o_teto_vira_ponteiro_sem_texto_pela_metade(projeto: Path):
    _com_mapa(projeto)
    longa = "Frase da decisão. " * 120
    _adr(projeto, "0003", decisao=longa)
    texto, mostrados = adr.contexto_por_caminho(
        projeto, projeto / "docs" / "adr", ["0003"], "src/lote.py"
    )
    assert "Frase da decisão" not in texto
    assert "docs/adr/0003-decisao-0003.md" in texto
    assert f"{len(longa.strip())} ch" in texto
    assert mostrados == ["0003"]


def test_adr_morto_nao_entra(projeto: Path):
    _com_mapa(projeto)
    _adr(projeto, "0003", status="deprecated", decisao="não siga")
    texto, mostrados = adr.contexto_por_caminho(
        projeto, projeto / "docs" / "adr", ["0003"], "src/lote.py"
    )
    assert texto == "" and mostrados == []


def test_o_que_nao_cabe_fica_para_a_proxima_escrita_inteiro(projeto: Path):
    """Medido no ValidaNI: `apps/web/src/` aponta 58 ADRs. Rebaixar todos a ponteiro antes
    de cortar entregava 20 ponteiros e nenhuma `## Regra` — 71 dos 93 ADRs de lá têm uma.
    """
    _com_mapa(projeto)
    nums = [f"{n:04d}" for n in range(10, 20)]
    for n in nums:
        _adr(projeto, n, decisao=("x" * 1_400))
    pasta = projeto / "docs" / "adr"
    texto, mostrados = adr.contexto_por_caminho(projeto, pasta, nums, "src/lote.py")
    assert len(texto) <= adr.TETO_ADRS_POR_CAMINHO_CHARS
    assert 0 < len(mostrados) < len(nums)
    assert mostrados == nums[: len(mostrados)]
    assert texto.count("x" * 1_400) == len(mostrados)
    assert "ADR-0019" in texto  # nomeado, para a próxima escrita
    resto = nums[len(mostrados) :]
    texto2, mostrados2 = adr.contexto_por_caminho(projeto, pasta, resto, "src/lote.py")
    assert mostrados2 == resto[: len(mostrados2)] and mostrados2


def test_hook_entrega_na_escrita_seguinte_o_que_nao_coube(projeto: Path):
    _com_mapa(projeto)
    nums = [f"{n:04d}" for n in range(10, 20)]
    for n in nums:
        _adr(projeto, n, decisao=("x" * 1_400))
    claude = projeto / "CLAUDE.md"
    claude.write_text(
        claude.read_text(encoding="utf-8") + f"| `src/lote.py` | {', '.join(nums)} |\n",
        encoding="utf-8",
    )
    primeira = _escrever(projeto, "src/lote.py")["additionalContext"]
    segunda = _escrever(projeto, "src/lote.py")["additionalContext"]
    assert "### ADR-0002" in primeira and "### ADR-0002" not in segunda
    assert "### ADR-0019" not in primeira


# --------------------------------------------------------------------------- #
# O hook
# --------------------------------------------------------------------------- #


def test_escrita_no_caminho_mapeado_recebe_os_adrs(projeto: Path):
    _com_mapa(projeto)
    saida = _escrever(projeto, "src/lote.py")
    assert saida["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in saida
    assert "ADR-0002" in saida["additionalContext"]
    assert "ADR-0003" in saida["additionalContext"]


def test_cada_adr_uma_vez_por_sessao(projeto: Path):
    _com_mapa(projeto)
    assert _escrever(projeto, "src/lote.py")
    assert _escrever(projeto, "src/lote.py") == {}
    assert _escrever(projeto, "src/lote.py", sessao="s2")


def test_subagente_recebe_de_novo(projeto: Path):
    _com_mapa(projeto)
    assert _escrever(projeto, "src/lote.py")
    assert "ADR-0002" in _escrever(projeto, "src/lote.py", agente="a1")["additionalContext"]


def test_compactacao_zera_o_que_foi_mostrado(projeto: Path):
    _com_mapa(projeto)
    assert _escrever(projeto, "src/lote.py")
    _compactar(projeto)
    assert _escrever(projeto, "src/lote.py")


def test_caminho_fora_do_mapa_nao_recebe_nada(projeto: Path):
    _com_mapa(projeto)
    assert _escrever(projeto, "README.md") == {}


def test_escrita_negada_so_nega(projeto: Path):
    _com_mapa(projeto)
    (projeto / "src" / ".env").write_text("", encoding="utf-8")
    saida = _escrever(projeto, "src/.env", ferramenta="Write")
    assert saida["permissionDecision"] == "deny"
    assert "additionalContext" not in saida


def test_desligado_pela_config(projeto: Path):
    _com_mapa(projeto)
    escrever_config(projeto, {"adr": {"injetar_por_caminho": False}})
    assert carregar(projeto).adr.injetar_por_caminho is False
    assert _escrever(projeto, "src/lote.py") == {}


# --------------------------------------------------------------------------- #
# O auditor avisa do mapa grosso
# --------------------------------------------------------------------------- #


def _avisos_do_mapa(projeto: Path, n: int) -> list[str]:
    from harness_memoria.auditar import Contexto, rodar

    nums = [f"{i:04d}" for i in range(10, 10 + n)]
    claude = projeto / "CLAUDE.md"
    claude.write_text(
        claude.read_text(encoding="utf-8") + f"| `src/` | {', '.join(nums)} |\n", encoding="utf-8"
    )
    (projeto / "src").mkdir(exist_ok=True)
    ctx = Contexto(raiz=projeto, cfg=carregar(projeto))
    rodar(ctx)
    return [a for a in ctx.avisos if "mapa de ADR por caminho" in a]


def test_auditor_avisa_linha_do_mapa_com_adrs_demais(projeto: Path):
    """Medido no ValidaNI: `apps/web/src/` aponta 58 ADRs, que o PreToolUse entrega ao longo
    de 10 escritas (~55 mil ch). É política do consumidor; o auditor torna o custo visível."""
    avisos = _avisos_do_mapa(projeto, adr.MAX_ADRS_POR_LINHA_DO_MAPA + 1)
    assert len(avisos) == 1 and "`src/`" in avisos[0]


def test_auditor_nao_avisa_no_limite(projeto: Path):
    assert _avisos_do_mapa(projeto, adr.MAX_ADRS_POR_LINHA_DO_MAPA) == []


# --------------------------------------------------------------------------- #
# O mapa num arquivo próprio, apontado pela seção do CLAUDE.md (ADR-0010)
#
# Medido em 2026-10-09: o mapa fino levava o CLAUDE.md do rede-inspira de 150 para 203 linhas
# e o do slice de 150 para 173, contra o teto de 150 — o CLAUDE.md é carregado em toda sessão.
# --------------------------------------------------------------------------- #

PONTEIRO = """\
### Qual ADR ler — por caminho que você vai tocar

O mapa mora em [`docs/adr/mapa-por-caminho.md`](docs/adr/mapa-por-caminho.md).
"""


def _mapa_em_arquivo(projeto: Path) -> Path:
    _com_mapa(projeto)
    claude = projeto / "CLAUDE.md"
    texto = claude.read_text(encoding="utf-8")
    claude.write_text(texto[: texto.index("### Qual ADR ler")] + PONTEIRO, encoding="utf-8")
    arquivo = projeto / "docs" / "adr" / "mapa-por-caminho.md"
    arquivo.write_text("# Mapa por caminho\n\n" + MAPA.split("\n", 1)[1], encoding="utf-8")
    return arquivo


def test_ler_mapa_segue_o_ponteiro_da_secao(projeto: Path):
    arquivo = _mapa_em_arquivo(projeto)
    mapa, origem = adr.ler_mapa(projeto)
    assert origem == arquivo
    assert mapa == adr.mapa_por_caminho(MAPA)


def test_ler_mapa_com_a_tabela_no_claude_md_continua_igual(projeto: Path):
    _com_mapa(projeto)
    mapa, origem = adr.ler_mapa(projeto)
    assert origem == projeto / "CLAUDE.md"
    assert mapa == adr.mapa_por_caminho(MAPA)


def test_hook_entrega_os_adrs_do_mapa_em_arquivo(projeto: Path):
    _mapa_em_arquivo(projeto)
    assert "ADR-0002" in _escrever(projeto, "src/lote.py")["additionalContext"]


def test_auditor_confere_os_caminhos_do_mapa_em_arquivo(projeto: Path):
    from harness_memoria.auditar import Contexto, rodar

    arquivo = _mapa_em_arquivo(projeto)
    arquivo.write_text(
        arquivo.read_text(encoding="utf-8") + "| `nao/existe/` | 0002 |\n", encoding="utf-8"
    )
    ctx = Contexto(raiz=projeto, cfg=carregar(projeto))
    rodar(ctx)
    falhas = [f for f in ctx.falhas if "nao/existe/" in f]
    assert len(falhas) == 1 and "mapa-por-caminho.md" in falhas[0]


def test_auditor_reprova_ponteiro_para_arquivo_que_nao_existe(projeto: Path):
    from harness_memoria.auditar import Contexto, rodar

    _mapa_em_arquivo(projeto).unlink()
    ctx = Contexto(raiz=projeto, cfg=carregar(projeto))
    rodar(ctx)
    assert any(
        "mapa de adr por caminho" in f.lower() and "mapa-por-caminho.md" in f for f in ctx.falhas
    )
