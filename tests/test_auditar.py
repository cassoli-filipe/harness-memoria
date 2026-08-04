"""Testes do motor de auditoria — com ênfase nos caminhos de FALHA.

Auditor que só sabe passar não vale nada: cada teste aqui quebra uma coisa de propósito e
exige que o motor perceba. Vários correspondem a defeitos que existiram de verdade nos
projetos de origem, e o docstring do teste diz qual.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from conftest import escrever_config

from harness_memoria.auditar import Contexto, rodar
from harness_memoria.config import carregar


def auditar(raiz: Path) -> Contexto:
    cfg = carregar(raiz)
    assert cfg is not None, "fixture sem harness.json"
    ctx = Contexto(raiz=raiz, cfg=cfg)
    rodar(ctx)
    return ctx


def falhas_com(ctx: Contexto, trecho: str) -> list[str]:
    return [f for f in ctx.falhas if trecho.lower() in f.lower()]


# --------------------------------------------------------------------------- #
# Piso: o projeto válido passa
# --------------------------------------------------------------------------- #


def test_projeto_valido_nao_tem_falha(projeto: Path):
    ctx = auditar(projeto)
    assert ctx.falhas == [], f"projeto de referência deveria passar: {ctx.falhas}"


# --------------------------------------------------------------------------- #
# Ordem do diário — o defeito que a migração do ValidaNI revelou
# --------------------------------------------------------------------------- #


def test_diario_do_mais_recente_para_o_mais_antigo_reprova(projeto: Path, entrada_de_diario):
    """Diário invertido faz a reinjeção pegar a entrada MAIS VELHA, calado.

    `ultima_entrada` devolve o último bloco `##` do arquivo. Num diário escrito com a
    entrada nova no topo — convenção razoável, e a do ValidaNI antes da migração — isso
    injeta a entrada mais antiga em toda sessão sem nenhum sinal de erro.
    """
    mes = datetime.now().strftime("%Y-%m")
    arq = projeto / "docs" / "diario" / f"{mes}.md"
    arq.write_text(
        f"# Diário · {mes}\n\n---\n"
        + entrada_de_diario(f"{mes}-20")
        + entrada_de_diario(f"{mes}-05"),
        encoding="utf-8",
    )
    ctx = auditar(projeto)
    achado = falhas_com(ctx, "ordem cronológica")
    assert achado, f"ordem invertida deveria reprovar. Falhas: {ctx.falhas}"
    assert "mais RECENTE para o mais antigo" in achado[0]


def test_diario_em_ordem_cronologica_passa(projeto: Path, entrada_de_diario):
    mes = datetime.now().strftime("%Y-%m")
    arq = projeto / "docs" / "diario" / f"{mes}.md"
    arq.write_text(
        f"# Diário · {mes}\n\n---\n"
        + entrada_de_diario(f"{mes}-05")
        + entrada_de_diario(f"{mes}-20"),
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "ordem cronológica") == []


def test_entrada_de_outro_mes_no_arquivo_do_mes_reprova(projeto: Path, entrada_de_diario):
    mes = datetime.now().strftime("%Y-%m")
    arq = projeto / "docs" / "diario" / f"{mes}.md"
    arq.write_text(f"# Diário · {mes}\n\n---\n" + entrada_de_diario("2019-01-01"), encoding="utf-8")
    assert falhas_com(auditar(projeto), "fora do mês do arquivo")


def test_diario_acima_do_teto_reprova(projeto: Path, entrada_de_diario):
    mes = datetime.now().strftime("%Y-%m")
    arq = projeto / "docs" / "diario" / f"{mes}.md"
    corpo = f"# Diário · {mes}\n\n---\n" + entrada_de_diario(f"{mes}-01")
    corpo += "\n".join(f"- linha {i}" for i in range(500))
    arq.write_text(corpo, encoding="utf-8")
    escrever_config(projeto, {"diario": {"teto_linhas": 50}})
    assert falhas_com(auditar(projeto), "teto 50")


# --------------------------------------------------------------------------- #
# Invioláveis: o cheque que torna política-como-dado seguro
# --------------------------------------------------------------------------- #


def test_sem_secao_de_invioaveis_reprova(projeto: Path):
    """Sem a seção, a reafirmação e o aviso pós-compactação ficam MUDOS.

    Silêncio é o pior resultado: quem instalou o harness acha que está protegido.
    """
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8").replace("## Regras invioláveis", "## Outra coisa"),
        encoding="utf-8",
    )
    achado = falhas_com(auditar(projeto), "MUDOS")
    assert achado, "seção ausente deveria reprovar"


def test_inviolavel_longa_reprova_em_vez_de_truncar(projeto: Path):
    """Meia proibição lê como permissão, então item longo reprova — não é truncado."""
    p = projeto / "CLAUDE.md"
    longa = "Fazer " + "coisa muito específica e detalhada " * 8 + "sem parar."
    p.write_text(
        p.read_text(encoding="utf-8").replace("- Escrever segredo no repositório.", f"- {longa}"),
        encoding="utf-8",
    )
    achado = falhas_com(auditar(projeto), "invioláveis: item com")
    assert achado
    assert "encurte a PRIMEIRA FRASE" in achado[0]


def test_reafirmacao_desligada_nao_exige_secao(projeto: Path):
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8").replace("## Regras invioláveis", "## Outra coisa"),
        encoding="utf-8",
    )
    escrever_config(projeto, {"reafirmacao": {"habilitado": False}})
    assert falhas_com(auditar(projeto), "MUDOS") == []


# --------------------------------------------------------------------------- #
# ADR
# --------------------------------------------------------------------------- #


def test_adr_morto_sem_substituto_reprova(projeto: Path):
    """ADR `superseded` sem `substituido-por:` deixa o índice injetado sem o que seguir."""
    (projeto / "docs" / "adr" / "0002-morta.md").write_text(
        "---\nstatus: superseded\ndata: 2026-02-01\n---\n\n# ADR-0002 — Decisão morta\n",
        encoding="utf-8",
    )
    idx = projeto / "docs" / "adr" / "README.md"
    idx.write_text(
        idx.read_text(encoding="utf-8") + "| [0002](0002-morta.md) | Morta | superseded |\n",
        encoding="utf-8",
    )
    achado = falhas_com(auditar(projeto), "não declara `substituido-por:`")
    assert achado


def test_supersessao_unilateral_reprova(projeto: Path):
    """Quem morre aponta o substituto E o substituto declara quem substituiu."""
    (projeto / "docs" / "adr" / "0002-nova.md").write_text(
        "---\nstatus: accepted\ndata: 2026-02-01\nsubstitui: [ADR-0001]\n---\n\n"
        "# ADR-0002 — Nova decisão\n\n## Plano de Implementação\n\n- feito\n",
        encoding="utf-8",
    )
    idx = projeto / "docs" / "adr" / "README.md"
    idx.write_text(
        idx.read_text(encoding="utf-8") + "| [0002](0002-nova.md) | Nova | accepted |\n",
        encoding="utf-8",
    )
    achado = falhas_com(auditar(projeto), "supersessão unilateral")
    assert achado, f"falhas: {auditar(projeto).falhas}"


def test_adr_fora_do_indice_reprova(projeto: Path):
    (projeto / "docs" / "adr" / "0002-orfa.md").write_text(
        "---\nstatus: proposed\ndata: 2026-02-01\n---\n\n# ADR-0002 — Órfã do índice\n",
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "não está no índice")


def test_referencia_a_adr_morto_em_fonte_operacional_reprova(projeto: Path):
    """Ponteiro velho faz mais dano que ponteiro nenhum (arXiv:2404.03114)."""
    (projeto / "docs" / "adr" / "0002-morta.md").write_text(
        "---\nstatus: superseded\ndata: 2026-02-01\nsubstituido-por: [ADR-0001]\n---\n\n"
        "# ADR-0002 — Decisão morta\n",
        encoding="utf-8",
    )
    (projeto / "docs" / "adr" / "0001-primeira.md").write_text(
        "---\nstatus: accepted\ndata: 2026-01-15\nsubstitui: [ADR-0002]\n---\n\n"
        "# ADR-0001 — Primeira decisão do projeto\n\n## Plano de Implementação\n\n- feito\n",
        encoding="utf-8",
    )
    idx = projeto / "docs" / "adr" / "README.md"
    idx.write_text(
        idx.read_text(encoding="utf-8") + "| [0002](0002-morta.md) | Morta | superseded |\n",
        encoding="utf-8",
    )
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8") + "\nPara persistência, siga a ADR-0002.\n",
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "manda seguir ADR-0002")


def test_mencao_historica_a_adr_morto_passa(projeto: Path):
    """`substitu` na vizinhança marca a menção como histórica e libera."""
    (projeto / "docs" / "adr" / "0002-morta.md").write_text(
        "---\nstatus: superseded\ndata: 2026-02-01\nsubstituido-por: [ADR-0001]\n---\n\n"
        "# ADR-0002 — Decisão morta\n",
        encoding="utf-8",
    )
    (projeto / "docs" / "adr" / "0001-primeira.md").write_text(
        "---\nstatus: accepted\ndata: 2026-01-15\nsubstitui: [ADR-0002]\n---\n\n"
        "# ADR-0001 — Primeira decisão do projeto\n\n## Plano de Implementação\n\n- feito\n",
        encoding="utf-8",
    )
    idx = projeto / "docs" / "adr" / "README.md"
    idx.write_text(
        idx.read_text(encoding="utf-8") + "| [0002](0002-morta.md) | Morta | superseded |\n",
        encoding="utf-8",
    )
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8") + "\nA ADR-0001 substituiu a ADR-0002.\n",
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "manda seguir ADR-0002") == []


def test_status_pt_br_e_aceito_normalizado(projeto: Path):
    """Corpus migrado escreve `aceito`; reescrever 22 corpos por uma palavra não se paga."""
    (projeto / "docs" / "adr" / "0001-primeira.md").write_text(
        "---\nstatus: aceito\ndata: 2026-01-15\n---\n\n"
        "# ADR 0001 — Primeira decisão do projeto\n\n## Plano de Implementação\n\n- feito\n",
        encoding="utf-8",
    )
    ctx = auditar(projeto)
    assert falhas_com(ctx, "status") == []
    assert ctx.adrs["0001"]["status"] == "accepted"


def test_secao_plano_desligada_nao_exige(projeto: Path):
    (projeto / "docs" / "adr" / "0001-primeira.md").write_text(
        "---\nstatus: accepted\ndata: 2026-01-15\n---\n\n# ADR-0001 — Sem plano\n",
        encoding="utf-8",
    )
    escrever_config(projeto, {"adr": {"secao_plano": None}})
    assert falhas_com(auditar(projeto), "Plano de Implementação") == []


def test_secao_plano_exigida_reprova_quando_falta(projeto: Path):
    (projeto / "docs" / "adr" / "0001-primeira.md").write_text(
        "---\nstatus: accepted\ndata: 2026-01-15\n---\n\n# ADR-0001 — Sem plano\n",
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "Plano de Implementação")


# --------------------------------------------------------------------------- #
# Mapa caminho→ADR e ponteiros
# --------------------------------------------------------------------------- #


def test_mapa_com_caminho_inexistente_reprova(projeto: Path):
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8").replace("`scripts/`", "`nao/existe/`"),
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "`nao/existe/` não existe")


def test_mapa_ausente_reprova(projeto: Path):
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8").replace("### Qual ADR ler", "### Outra seção"),
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "Qual ADR ler")


def test_script_citado_e_inexistente_reprova(projeto: Path):
    (projeto / "scripts" / "checar.py").unlink()
    assert falhas_com(auditar(projeto), "scripts/checar.py")


def test_script_com_prefixo_de_diretorio_nao_da_falso_positivo(projeto: Path):
    r"""Regressão da primeira instalação real: `apps/web/scripts/x.py` existia e reprovava.

    Com `\bscripts/…` o `\b` casava depois da barra de `apps/web/`, o prefixo era descartado
    e o auditor procurava `scripts/x.py` na raiz. Falso positivo é pior que cheque ausente:
    ensina a ignorar o auditor.
    """
    alvo = projeto / "apps" / "web" / "scripts"
    alvo.mkdir(parents=True)
    (alvo / "gen-icons.py").write_text("# stub\n", encoding="utf-8")
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8") + "\nRode `python apps/web/scripts/gen-icons.py`.\n",
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "gen-icons.py") == []


def test_script_com_prefixo_de_diretorio_e_inexistente_reprova(projeto: Path):
    """O prefixo não vira desculpa para não checar: o caminho completo é verificado."""
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8") + "\nRode `python apps/web/scripts/fantasma.py`.\n",
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "apps/web/scripts/fantasma.py")


def test_claude_md_acima_do_teto_reprova(projeto: Path):
    p = projeto / "CLAUDE.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n" * 300, encoding="utf-8")
    escrever_config(projeto, {"auditoria": {"teto_claude_md": 40}})
    assert falhas_com(auditar(projeto), "teto 40")


# --------------------------------------------------------------------------- #
# Checks do projeto
# --------------------------------------------------------------------------- #


def test_checks_do_projeto_rodam(projeto: Path):
    (projeto / "scripts" / "guardas.py").write_text(
        "def registrar(ctx):\n    ctx.falhar('fronteira do projeto violada')\n",
        encoding="utf-8",
    )
    escrever_config(projeto, {"auditoria": {"checks_do_projeto": "scripts/guardas.py"}})
    assert falhas_com(auditar(projeto), "fronteira do projeto violada")


def test_checks_do_projeto_ausentes_reprovam(projeto: Path):
    """Módulo apontado e inexistente NÃO passa em silêncio: seria CI verde sem auditar."""
    escrever_config(projeto, {"auditoria": {"checks_do_projeto": "scripts/nao_existe.py"}})
    achado = falhas_com(auditar(projeto), "NÃO rodaram")
    assert achado


def test_checks_do_projeto_sem_registrar_reprovam(projeto: Path):
    (projeto / "scripts" / "guardas.py").write_text("x = 1\n", encoding="utf-8")
    escrever_config(projeto, {"auditoria": {"checks_do_projeto": "scripts/guardas.py"}})
    assert falhas_com(auditar(projeto), "não expõe `registrar(ctx)`")


def test_check_que_explode_entra_como_falha_nomeada(projeto: Path):
    """Check que levanta não pode esconder o resultado dos outros nem passar como verde."""
    (projeto / "scripts" / "guardas.py").write_text(
        "def registrar(ctx):\n    raise ValueError('boom')\n", encoding="utf-8"
    )
    escrever_config(projeto, {"auditoria": {"checks_do_projeto": "scripts/guardas.py"}})
    assert falhas_com(auditar(projeto), "ValueError")
