"""Testes do recorte por prioridade, do digest de becos e do índice de ADR."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from harness_memoria import adr, diario
from harness_memoria.config import ConfigDiario


def _entrada_gorda(data: str) -> str:
    return f"""
## {data} — Entrada gorda

**Estado:** concluído

### O que foi feito

{"- mudança concreta e verificável, com bastante texto para ocupar espaço" * 1}
{chr(10).join("- item " + "x" * 90 for _ in range(20))}

### Por quê

{"razão longa " * 60}

### Como (o não-óbvio)

- decisão que não se deduz do diff

### Tentativas descartadas

- abordagem A → falhou porque Y. **Não repetir:** use B.

### Verificação

- 3 testes passaram

### Aberto / Próximo passo

- [ ] próximo passo

### Retomar com

```bash
pytest
```
"""


def _montar_diario(pasta: Path, entradas: list[str]) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    mes = datetime.now().strftime("%Y-%m")
    (pasta / f"{mes}.md").write_text(
        f"# Diário · {mes}\n\n---\n" + "".join(entradas), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Recorte por prioridade
# --------------------------------------------------------------------------- #


def test_recorte_descarta_secao_inteira_e_preserva_retomada(tmp_path: Path):
    """O corte por caractere levava 39% da entrada e decapitava as seções do FIM.

    "O que foi feito" sai primeiro porque é a única reconstruível do `git log`; as três
    primeiras da prioridade — o que já falhou, o que ficou aberto, como retomo — ficam.
    """
    cfg = ConfigDiario(limite_injecao_chars=1_200)
    corpo = _entrada_gorda("2026-08-01")
    assert len(corpo) > cfg.limite_injecao_chars

    saida = diario.recortar_entrada(corpo, cfg, "docs/diario/2026-08.md")

    assert len(saida) <= cfg.limite_injecao_chars
    assert "### Tentativas descartadas" in saida, "a seção de maior retorno não pode sair"
    assert "### Aberto / Próximo passo" in saida
    assert "### Retomar com" in saida
    # O CORPO da seção sai; o NOME dela fica, na nota de omissão. Testar pela string solta
    # confundiria as duas coisas — a nota citar "O que foi feito" é o comportamento certo.
    assert "### O que foi feito" not in saida, "a reconstruível do git log deveria sair primeiro"
    assert "Seções omitidas por espaço" in saida, "recorte silencioso vira falso completo"
    assert "O que foi feito" in saida, "o que saiu tem de ser NOMEADO na nota"
    assert "docs/diario/2026-08.md" in saida, "tem de dizer onde está a entrada inteira"


def test_entrada_pequena_passa_intacta(tmp_path: Path):
    cfg = ConfigDiario()
    corpo = "## 2026-08-01 — Curta\n\n### Verificação\n\n- ok\n"
    assert diario.recortar_entrada(corpo, cfg) == corpo


# --------------------------------------------------------------------------- #
# Becos sem saída
# --------------------------------------------------------------------------- #


def test_becos_do_mais_recente_para_o_mais_antigo(tmp_path: Path):
    pasta = tmp_path / "diario"
    mes = datetime.now().strftime("%Y-%m")
    _montar_diario(
        pasta,
        [
            f"\n## {mes}-01 — Velha\n\n### {diario.SECAO_BECOS}\n\n- beco VELHO → falhou. **Não repetir.**\n",
            f"\n## {mes}-20 — Nova\n\n### {diario.SECAO_BECOS}\n\n- beco NOVO → falhou. **Não repetir.**\n",
        ],
    )
    itens, total = diario.becos_sem_saida(pasta, ConfigDiario())
    assert total == 2
    assert "NOVO" in itens[0], f"o mais recente vem primeiro: {itens}"
    assert "VELHO" in itens[1]


def test_becos_deduplicam(tmp_path: Path):
    pasta = tmp_path / "diario"
    mes = datetime.now().strftime("%Y-%m")
    igual = "mesmíssima abordagem repetida em duas sessões → falhou. **Não repetir.**"
    _montar_diario(
        pasta,
        [
            f"\n## {mes}-01 — A\n\n### {diario.SECAO_BECOS}\n\n- {igual}\n",
            f"\n## {mes}-20 — B\n\n### {diario.SECAO_BECOS}\n\n- {igual}\n",
        ],
    )
    _, total = diario.becos_sem_saida(pasta, ConfigDiario())
    assert total == 1


def test_beco_longo_preserva_a_licao_do_fim(tmp_path: Path):
    pasta = tmp_path / "diario"
    mes = datetime.now().strftime("%Y-%m")
    longo = "contexto " * 60 + "→ falhou porque Z. **Não repetir:** faça W."
    _montar_diario(pasta, [f"\n## {mes}-01 — A\n\n### {diario.SECAO_BECOS}\n\n- {longo}\n"])
    itens, _ = diario.becos_sem_saida(pasta, ConfigDiario(teto_item_beco_chars=120))
    assert itens[0].endswith("**Não repetir:** faça W."), itens[0]


def test_teto_de_becos_respeitado_e_total_reportado(tmp_path: Path):
    pasta = tmp_path / "diario"
    mes = datetime.now().strftime("%Y-%m")
    entradas = [
        f"\n## {mes}-{i:02d} — E{i}\n\n### {diario.SECAO_BECOS}\n\n- beco número {i} "
        + "y" * 200
        + " → falhou. **Não repetir.**\n"
        for i in range(1, 20)
    ]
    _montar_diario(pasta, entradas)
    itens, total = diario.becos_sem_saida(pasta, ConfigDiario(teto_becos_chars=600))
    assert total == 19
    assert len(itens) < total, "o teto tem de cortar"
    assert sum(len(i) for i in itens) <= 600


# --------------------------------------------------------------------------- #
# Última entrada
# --------------------------------------------------------------------------- #


def test_ultima_entrada_e_a_do_fim_do_arquivo(tmp_path: Path):
    pasta = tmp_path / "diario"
    mes = datetime.now().strftime("%Y-%m")
    _montar_diario(
        pasta,
        [f"\n## {mes}-01 — Primeira\n\n- a\n", f"\n## {mes}-20 — Última\n\n- b\n"],
    )
    nome, corpo = diario.ultima_entrada(pasta)
    assert "Última" in corpo


def test_ultima_entrada_cai_para_arquivo_quando_mes_novo_esta_vazio(tmp_path: Path):
    """Entre a rotação do mês e a primeira sessão registrada, a memória não pode zerar."""
    pasta = tmp_path / "diario"
    (pasta / "arquivo").mkdir(parents=True)
    mes = datetime.now().strftime("%Y-%m")
    (pasta / f"{mes}.md").write_text(f"# Diário · {mes}\n\n---\n", encoding="utf-8")
    (pasta / "arquivo" / "2026-01.md").write_text(
        "# Diário · 2026-01\n\n---\n\n## 2026-01-15 — Do arquivo\n\n- a\n",
        encoding="utf-8",
    )
    nome, corpo = diario.ultima_entrada(pasta)
    assert "Do arquivo" in corpo
    assert nome.startswith("arquivo/")


# --------------------------------------------------------------------------- #
# Índice de ADR
# --------------------------------------------------------------------------- #


def test_indice_traz_substituto_em_linha(tmp_path: Path):
    pasta = tmp_path / "adr"
    pasta.mkdir()
    (pasta / "0001-velha.md").write_text(
        "---\nstatus: superseded\ndata: 2026-01-01\nsubstituido-por: [ADR-0002]\n---\n\n"
        "# ADR-0001 — Decisão velha\n",
        encoding="utf-8",
    )
    (pasta / "0002-nova.md").write_text(
        "---\nstatus: accepted\ndata: 2026-02-01\nsubstitui: [ADR-0001]\n---\n\n"
        "# ADR-0002 — Decisão nova\n",
        encoding="utf-8",
    )
    linhas = adr.indice_para_injecao(pasta)
    assert linhas[0] == "ADR-0001 [superseded → siga ADR-0002] Decisão velha"
    assert linhas[1] == "ADR-0002 [accepted] Decisão nova"


def test_indice_aceita_titulo_com_espaco(tmp_path: Path):
    pasta = tmp_path / "adr"
    pasta.mkdir()
    (pasta / "0001-x.md").write_text(
        "---\nstatus: aceito\ndata: 2026-01-01\n---\n\n# ADR 0001 — Com espaço\n",
        encoding="utf-8",
    )
    assert adr.indice_para_injecao(pasta) == ["ADR-0001 [accepted] Com espaço"]


def test_anunciar_corte_so_fala_quando_corta(tmp_path: Path):
    assert adr.anunciar_corte(10, 10, "docs/adr/README.md") == ""
    nota = adr.anunciar_corte(10, 4, "docs/adr/README.md")
    assert "4 de 10" in nota
    assert "6 restantes" in nota
