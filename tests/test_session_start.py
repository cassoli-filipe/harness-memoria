"""Rede de teste do bloco injetado pelo SessionStart — `montar()` e `conferir_fidelidade()`.

Este arquivo existe porque `montar()` decide **100% da conta de contexto** do harness e não
tinha um único teste: `grep -rn 'montar(' tests/` não achava nada, a cobertura de
`session_start.py` era **0/70 instruções**, e a única verificação era o `--autoteste` contra
1 ADR e 1 entrada de diário — que imprime `N chars injetados` e não regula nada. Ou seja "os
275 testes passam" nunca foi prova de nada sobre o tamanho do bloco, e o bloco estava
15.485 ch num consumidor real, contra um teto de 10.000 ch na plataforma: em 14 das últimas
40 sessões dele o `additionalContext` inteiro foi substituído por um preview mais um caminho
de arquivo, e nada acusou.

O corpus é sintético e parametrizado (`corpus(...)`) porque o que se mede aqui é o
MECANISMO de orçamento, não um repositório: 10 ADRs para o caso normal, 60 para o caso que
estoura, e os dois com o mesmo gerador. Depender de um repositório real faria a suíte falhar
por mudança alheia — que é a suíte que se aprende a ignorar.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from conftest import escrever_config

from harness_memoria import adr, diario
from harness_memoria.config import carregar, invioaveis
from harness_memoria.hooks import session_start as SS

#: `CLAUDE_PROJECT_DIR` tem PRIORIDADE sobre o `cwd` do evento em `config.raiz_projeto`.
#: Rodar a suíte de dentro de uma sessão do Claude Code faria todo teste que passa pelo
#: `main()` resolver o projeto ERRADO — e, depois da auto-hospedagem, o projeto errado é
#: este repositório. Mesma defesa de `tests/test_session_end.py`.
_VARS_A_LIMPAR = ("CLAUDE_PROJECT_DIR", "HARNESS_MEMORIA_NARRANDO")


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch: pytest.MonkeyPatch):
    for v in _VARS_A_LIMPAR:
        monkeypatch.delenv(v, raising=False)


# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #

CLAUDE_MD = """\
# Projeto com memória

## Regras invioláveis

**NUNCA**

- Escrever segredo no repositório. O `.env` está no .gitignore e o hook bloqueia.
- Tratar identificador como número. Zero à esquerda é significativo e se perde.
- Apagar entrada de diário já gravada. O arquivo é append-only por decisão.

**SEMPRE**

- Rodar os testes antes de declarar trabalho concluído.

## Memória do projeto

- [diário](docs/diario/{mes}.md) — mês corrente.
"""

#: Títulos com 60-70 ch, que é a ordem de grandeza medida nos dois consumidores reais
#: (linhas de índice de 110-120 ch, das quais ~20 são `ADR-NNNN [status] `). Título curto
#: faria o orçamento parecer folgado por artefato de fixture.
_TITULO = "Decisão {n:04d} sobre o subsistema {n} e o que ela exige de quem o toca"

_CORPO_ADR = """\
## Contexto

Havia duas formas de resolver e a escolhida não se deduz do diff.

## Decisão

A escolhida, com o motivo que a sustenta.
"""

#: Formato canônico do bloco de beco (README do diário e skill `/encerrar-sessao`): a lição
#: vem DEPOIS do negrito, porque é essa a única grafia que `diario._resumir_beco` preserva
#: ao encurtar.
_BECO = (
    "abordagem {i} — {enche} → falhou porque o subsistema {i} não expõe o estado "
    "necessário. **Não repetir:** use o caminho {i}b, que passa pelo adaptador."
)


def _adr(num: int, status: str, substituido_por: int | None = None) -> str:
    campos = [f"status: {status}", "data: 2026-01-15"]
    if substituido_por is not None:
        campos.append(f"substituido-por: [ADR-{substituido_por:04d}]")
    return (
        "---\n"
        + "\n".join(campos)
        + "\n---\n\n"
        + f"# ADR-{num:04d} — {_TITULO.format(n=num)}\n\n"
        + _CORPO_ADR
    )


def _entrada(data: str, titulo: str, becos: list[str], recheio: int = 0) -> str:
    # O recheio vai em DUAS seções de propósito. `recortar_entrada` descarta seção INTEIRA,
    # e com todo o volume numa só (`O que foi feito`, a primeira a sair) a entrada caía de
    # 8.400 para 1.297 ch num passo — folga que o consumidor real não tem: lá a entrada
    # recortada mede 3.634-4.242 ch. Fixture com folga falsa mede o orçamento errado.
    linhas = chr(10).join("- item de trabalho " + "x" * 60 for _ in range(recheio))
    corpo = f"""
## {data} — {titulo}

**Estado:** concluído
**Escopo:** `src/`

### O que foi feito

- mudança concreta e verificável no subsistema, com o número que a prova
{linhas}

### Por quê

- a alternativa custava mais do que entregava, medido em ms
{linhas}

### Como (o não-óbvio)

- a decisão que não se deduz do diff, com o incidente que a produziu

### Verificação

- 3 testes passaram, 1 falhava antes
"""
    if becos:
        corpo += "\n### Tentativas descartadas\n\n" + "\n".join(f"- {b}" for b in becos) + "\n"
    corpo += """
### Aberto / Próximo passo

- o que ficou de fora e por quê

### Retomar com

- `pytest tests/test_alvo.py`
"""
    return corpo


def corpus(
    raiz: Path,
    *,
    adrs: int = 10,
    mortos_com_substituto: int = 2,
    morto_sem_substituto: bool = True,
    becos: int = 15,
    becos_na_ultima: int = 3,
    recheio_da_ultima: int = 40,
    config: dict | None = None,
) -> Path:
    """Projeto sintético com ADRs vivos e aposentados, entrada gorda e digest de becos.

    `mortos_com_substituto` viram `superseded` apontando para o ÚLTIMO ADR (que é vivo), e
    `morto_sem_substituto` produz um `deprecated` sem `substituido-por:` — o caso que a
    auditoria passou a aceitar (é o status de quem não tem sucessor) e que o autoteste do
    hook ainda reprovava, divergência entre os dois canais.
    """
    mes = datetime.now().strftime("%Y-%m")
    (raiz / ".claude").mkdir(parents=True, exist_ok=True)
    (raiz / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    (raiz / "docs" / "diario").mkdir(parents=True, exist_ok=True)
    (raiz / "CLAUDE.md").write_text(CLAUDE_MD.replace("{mes}", mes), encoding="utf-8")

    for n in range(1, adrs + 1):
        if n <= mortos_com_substituto:
            texto = _adr(n, "superseded", substituido_por=adrs)
        elif morto_sem_substituto and n == mortos_com_substituto + 1:
            texto = _adr(n, "deprecated")
        else:
            texto = _adr(n, "accepted")
        (raiz / "docs" / "adr" / f"{n:04d}-decisao.md").write_text(texto, encoding="utf-8")
    (raiz / "docs" / "adr" / "README.md").write_text(
        "# ADRs\n\n## Por domínio\n\n- subsistema: 0001\n", encoding="utf-8"
    )

    def beco(i: int) -> str:
        return _BECO.format(i=i, enche="detalhe que ocupa espaço " * 3)

    velhos = [beco(i) for i in range(1, max(0, becos - becos_na_ultima) + 1)]
    ultimos = [beco(i) for i in range(becos - becos_na_ultima + 1, becos + 1)]

    texto = f"# Diário · {mes}\n\n---\n"
    # Entradas antigas em blocos de 4 becos: o digest varre do mais recente para o mais
    # antigo, então a ordem aqui é o que decide quem entra no teto.
    for i in range(0, len(velhos), 4):
        dia = f"{mes}-{(i // 4) + 1:02d}"
        texto += _entrada(dia, f"Entrada antiga {i // 4 + 1}", velhos[i : i + 4])
    texto += _entrada(f"{mes}-28", "Entrada gorda, a última", ultimos, recheio=recheio_da_ultima)
    (raiz / "docs" / "diario" / f"{mes}.md").write_text(texto, encoding="utf-8")

    escrever_config(raiz, config or {})
    return raiz


def _cfg(raiz: Path):
    cfg = carregar(raiz)
    assert cfg is not None
    return cfg


# --------------------------------------------------------------------------- #
# Caracterização: o que o bloco promete é o que ele entrega
# --------------------------------------------------------------------------- #


def test_corpus_e_grande_o_bastante_para_exercitar_os_cortes(tmp_path: Path):
    """Se o corpus não estoura os limites, os testes abaixo não testam nada."""
    raiz = corpus(tmp_path / "proj")
    cfg = _cfg(raiz)
    ultima = diario.ultima_entrada(cfg.pasta_diario)
    assert ultima is not None
    assert len(ultima[1]) > cfg.diario.limite_injecao_chars, "entrada precisa estourar o recorte"
    assert len(adr.indice_para_injecao(cfg.pasta_adr)) == 10
    _, total = diario.becos_sem_saida(cfg.pasta_diario, cfg.diario)
    assert total == 15


def test_bloco_completo_passa_na_fidelidade(tmp_path: Path):
    raiz = corpus(tmp_path / "proj", morto_sem_substituto=False)
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, "startup")
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0
    assert "índice completo" in texto


def test_indice_cortado_se_declara_parcial_com_o_total_real(tmp_path: Path):
    """Os três ramos de `conferir_fidelidade` que nenhum teste executava."""
    raiz = corpus(
        tmp_path / "proj", morto_sem_substituto=False, config={"adr": {"limite_indice": 4}}
    )
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, "startup")
    assert "índice PARCIAL" in texto
    assert "este índice está cortado" in texto
    assert "10 ADRs" in texto, "sem o TOTAL real, quem lê não percebe a diferença"
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0


def test_compact_reafirma_as_invioaveis_e_startup_nao(tmp_path: Path):
    raiz = corpus(tmp_path / "proj", morto_sem_substituto=False)
    cfg = _cfg(raiz)
    regras = invioaveis(raiz, cfg.reafirmacao)
    assert len(regras) == 4

    compact = SS.montar(raiz, cfg, "compact")
    assert "## Aviso pós-compactação" in compact
    for r in regras:
        assert r in compact

    startup = SS.montar(raiz, cfg, "startup")
    assert "## Aviso pós-compactação" not in startup


def test_deprecated_sem_substituto_nao_reprova_a_fidelidade(tmp_path: Path):
    """`deprecated` é o status de quem não tem sucessor — e a auditoria já o aceita.

    Enquanto o cheque 2 daqui exigia `substituido-por:` de todo `STATUS_MORTOS`, um ADR
    `deprecated` PASSAVA em `python -m harness_memoria.auditar` e REPROVAVA no autoteste do
    hook, que é um passo do CI. Divergência entre os dois canais é pior que o defeito
    original: ela não tem saída correta.
    """
    raiz = corpus(tmp_path / "proj", morto_sem_substituto=True)
    cfg = _cfg(raiz)
    dados = adr.dados_dos_adrs(cfg.pasta_adr)
    assert dados["0003"]["status"] == "deprecated"
    assert dados["0003"]["substituido_por"] == []

    texto = SS.montar(raiz, cfg, "startup")
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0


def test_superseded_sem_substituto_continua_reprovando(tmp_path: Path):
    raiz = corpus(tmp_path / "proj", mortos_com_substituto=0, morto_sem_substituto=False)
    cfg = _cfg(raiz)
    (raiz / "docs" / "adr" / "0002-decisao.md").write_text(_adr(2, "superseded"), encoding="utf-8")
    texto = SS.montar(raiz, cfg, "startup")
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 1


# --------------------------------------------------------------------------- #
# Lote 6: o bloco cabe no orçamento e nomeia o que cortou
# --------------------------------------------------------------------------- #

#: O teto da plataforma, escrito à mão de propósito: se alguém baixar
#: `SS.TETO_PLATAFORMA_CHARS` para fazer um teste passar, este número continua reprovando.
TETO_DA_PLATAFORMA = 10_000


@pytest.mark.parametrize("adrs,becos", [(10, 15), (30, 40), (60, 100)])
@pytest.mark.parametrize("origem", ["startup", "compact"])
def test_bloco_cabe_no_teto_da_plataforma(tmp_path: Path, adrs: int, becos: int, origem: str):
    """O defeito central: acima de 10.000 ch a plataforma troca o bloco por um preview.

    Medido nesta fixture ANTES do orçamento: startup 9.203 / 12.201 / 15.016 ch e compact
    9.500 / 12.498 / 15.313 para 10, 30 e 60 ADRs — os quatro últimos acima do teto, e
    `conferir_fidelidade` devolvia 0 nos seis, porque conferia a string montada e não a
    entregue. Os dois corpora grandes reproduzem o consumidor real (15.485 e 12.911 ch).
    """
    raiz = corpus(
        tmp_path / "proj", adrs=adrs, becos=becos, mortos_com_substituto=max(1, adrs // 5)
    )
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, origem)
    assert len(texto) <= TETO_DA_PLATAFORMA, f"bloco com {len(texto)} ch"
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0


def test_o_que_cabe_nao_e_cortado(tmp_path: Path):
    """Orçamento é para quem estoura. Cortar quem cabe é jogar contexto fora.

    Escrito depois de eu medir a versão anterior desta mudança, que reparticionava sempre:
    o bloco de 10 ADRs caía de 9.203 para 4.845 ch, com a entrada em 649 ch e 2 becos fora
    do digest, sem nenhuma necessidade — 4.358 ch de memória descartados em silêncio
    orçamentário.
    """
    raiz = corpus(tmp_path / "proj", adrs=10, becos=15)
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, "startup")
    assert "índice completo" in texto
    assert "(15 de 15" in texto, "o digest cabia inteiro e foi cortado"
    for secao in ("Aberto / Próximo passo", "Retomar com", "Como (o não-óbvio)"):
        assert secao in texto


def test_corpus_grande_de_adr_corta_so_o_indice(tmp_path: Path):
    """O caso dos consumidores reais: muito ADR, diário modesto.

    Só o índice cede, e a memória recente fica INTEIRA — é o ramo em que `_orcar` devolve
    cotas naturais para entrada e digest. O corte do índice sai anunciado com o TOTAL real,
    que é a diferença entre "índice cortado" e "índice que mente".
    """
    raiz = corpus(
        tmp_path / "proj",
        adrs=120,
        mortos_com_substituto=10,
        becos=4,
        becos_na_ultima=2,
        recheio_da_ultima=4,
    )
    cfg = _cfg(raiz)
    natural_becos, total_becos = diario.becos_sem_saida(cfg.pasta_diario, cfg.diario)
    assert len(natural_becos) == total_becos == 4, "o digest tem de caber inteiro neste caso"

    texto = SS.montar(raiz, cfg, "startup")
    assert len(texto) <= TETO_DA_PLATAFORMA, f"bloco com {len(texto)} ch"
    assert "índice PARCIAL, 120 ADRs" in texto
    assert "este índice está cortado" in texto
    assert "(4 de 4," in texto, "o digest cabia e foi cortado junto"
    for secao in ("Aberto / Próximo passo", "Retomar com"):
        assert secao in texto
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0


def test_indice_agrega_os_aposentados_sem_esconder_numero(tmp_path: Path):
    """Uma linha para todos os mortos com substituto, e nenhum número desaparece."""
    raiz = corpus(tmp_path / "proj", adrs=30, mortos_com_substituto=7, morto_sem_substituto=False)
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, "startup")

    assert f"{adr.PREFIXO_APOSENTADOS}, NÃO siga" in texto
    for n in range(1, 8):
        assert f"ADR-{n:04d}→ADR-0030" in texto
    # o cheque 1 continua vendo os sete: `ADR-0005` vive dentro de `ADR-0005→ADR-0030`
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0
    assert "índice completo" in texto

    # a economia é a linha completa de cada morto contra a linha agregada
    completas = [linha for linha in adr.indice_para_injecao(cfg.pasta_adr) if "superseded" in linha]
    assert len(completas) == 7
    agregada = next(linha for linha in texto.splitlines() if adr.PREFIXO_APOSENTADOS in linha)
    assert len(agregada) < sum(len(c) + 3 for c in completas) / 2


def test_indice_compactado_respeita_o_teto_em_chars_e_conta_quem_nomeou(tmp_path: Path):
    """A aritmética de `adr.indice_compactado`, direto: teto em chars e `nomeados`.

    `nomeados` é o número que decide "completo" contra "PARCIAL" e alimenta
    `anunciar_corte`. Ele conta ADRs, não linhas — a linha agregada nomeia vários — e é por
    isso que o orçamento não pode ser conferido contando linhas.
    """
    raiz = corpus(tmp_path / "proj", adrs=10, mortos_com_substituto=2, morto_sem_substituto=True)
    pasta = raiz / "docs" / "adr"

    linhas, total, nomeados = adr.indice_compactado(pasta)
    assert (total, nomeados) == (10, 10)
    assert len(linhas) == 7 + 2, "7 vivos + as duas linhas de aposentado"

    # Teto em que só cabem as duas agregadas: os vivos ficam de fora, e os 3 aposentados
    # continuam nomeados — 18 ch por ADR contra 110-120 da linha viva.
    linhas, total, nomeados = adr.indice_compactado(pasta, teto_chars=160)
    assert all(linha.startswith(adr.PREFIXO_APOSENTADOS) for linha in linhas)
    assert (total, nomeados) == (10, 3)
    assert sum(len(linha) + 3 for linha in linhas) <= 160

    # Teto em que só a PRIMEIRA agregada cabe: o ADR da segunda deixa de ser nomeado, e é
    # `nomeados` que faz o bloco se declarar PARCIAL em vez de esconder um aposentado.
    linhas, total, nomeados = adr.indice_compactado(pasta, teto_chars=120)
    assert (total, nomeados) == (10, 2)
    assert "ADR-0003" not in " ".join(linhas)

    # Teto abaixo de qualquer linha: ninguém é nomeado, e o bloco tem de se declarar PARCIAL.
    linhas, total, nomeados = adr.indice_compactado(pasta, teto_chars=10)
    assert (linhas, total, nomeados) == ([], 10, 0)


def test_indice_compactado_nao_perde_substituto_multiplo(tmp_path: Path):
    """`subs[0]` sumiria com o resto num bloco que se declara completo."""
    raiz = corpus(tmp_path / "proj", adrs=4, mortos_com_substituto=0, morto_sem_substituto=False)
    pasta = raiz / "docs" / "adr"
    (pasta / "0001-decisao.md").write_text(
        "---\nstatus: superseded\ndata: 2026-01-15\nsubstituido-por: [ADR-0003, ADR-0004]\n---\n\n"
        "# ADR-0001 — Decisão partida em duas\n",
        encoding="utf-8",
    )
    linhas, total, nomeados = adr.indice_compactado(pasta)
    assert (total, nomeados) == (4, 4)
    assert "ADR-0001→ADR-0003/ADR-0004" in "\n".join(linhas)

    cfg = _cfg(raiz)
    assert SS.conferir_fidelidade(raiz, cfg, SS.montar(raiz, cfg, "startup")) == 0


def test_morto_sem_substituto_sai_em_linha_propria(tmp_path: Path):
    raiz = corpus(tmp_path / "proj", adrs=10, mortos_com_substituto=2, morto_sem_substituto=True)
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, "startup")
    linha = next(linha for linha in texto.splitlines() if "sem substituto declarado" in linha)
    assert "ADR-0003" in linha
    assert "ADR-0001" not in linha, "o que tem substituto não entra na linha de quem não tem"
    assert "ADR-0001→ADR-0010" in texto
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0


def test_frase_sobre_superseded_sai_so_quando_a_linha_agregada_existe(tmp_path: Path):
    frase = "ADR `superseded` **não** se segue"

    com_mortos = corpus(tmp_path / "com", adrs=10, mortos_com_substituto=2)
    assert frase not in SS.montar(com_mortos, _cfg(com_mortos), "startup")

    sem_mortos = corpus(
        tmp_path / "sem", adrs=10, mortos_com_substituto=0, morto_sem_substituto=False
    )
    assert frase in SS.montar(sem_mortos, _cfg(sem_mortos), "startup")


def test_becos_da_ultima_entrada_nao_sao_pagos_duas_vezes(tmp_path: Path):
    """Reproduzido: os becos da última entrada estão SEMPRE duplicados no mesmo bloco.

    `becos_sem_saida` varre do mais recente, então os itens da última entrada são os
    primeiros do digest — e a entrada injetada os trazia de novo, verbatim.
    """
    raiz = corpus(tmp_path / "proj", adrs=10, becos=15, becos_na_ultima=3)
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, "startup")

    ultima = diario.ultima_entrada(cfg.pasta_diario)
    assert ultima is not None
    itens = SS._itens_da_secao(ultima[1])
    assert len(itens) == 3
    for item in itens:
        assert texto.count(item) == 1, "item pago duas vezes no mesmo bloco"
    assert "O digest de becos abaixo já traz esta seção inteira" in texto
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0


def test_itens_fora_do_digest_ficam_em_texto_com_os_dois_numeros(tmp_path: Path):
    """A guarda ingênua apagaria justamente o que o teto do digest deixou de fora."""
    raiz = corpus(
        tmp_path / "proj",
        adrs=10,
        becos=15,
        becos_na_ultima=3,
        config={"diario": {"teto_becos_chars": 600}},
    )
    cfg = _cfg(raiz)
    becos, _ = diario.becos_sem_saida(cfg.pasta_diario, cfg.diario)
    assert len(becos) == 2, "o teto de 600 ch tem de deixar 1 dos 3 itens fora do digest"

    texto = SS.montar(raiz, cfg, "startup")
    itens = SS._itens_da_secao(diario.ultima_entrada(cfg.pasta_diario)[1])
    fora = [i for i in itens if not SS._no_digest(i, becos, cfg)]
    assert len(fora) == 1
    assert fora[0] in texto, "o item que o digest não levou tem de continuar em texto"
    assert "de 3" in texto and "continua" in texto
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0


def test_cheque_3_reprova_quando_um_item_da_secao_desaparece(tmp_path: Path):
    """O cheque antigo olhava só o TÍTULO da seção: um ponteiro mentiroso passava verde."""
    raiz = corpus(
        tmp_path / "proj",
        adrs=10,
        becos=15,
        becos_na_ultima=3,
        config={"diario": {"teto_becos_chars": 600}},
    )
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, "startup")
    becos, _ = diario.becos_sem_saida(cfg.pasta_diario, cfg.diario)
    itens = SS._itens_da_secao(diario.ultima_entrada(cfg.pasta_diario)[1])
    fora = [i for i in itens if not SS._no_digest(i, becos, cfg)][0]

    mentiroso = texto.replace(fora, "")
    assert "Tentativas descartadas" in mentiroso
    assert SS.conferir_fidelidade(raiz, cfg, mentiroso) == 1


def test_marca_de_truncamento_nao_divergiu():
    """A constante daqui é uma cópia da marca de `diario`. Se divergir, o cheque 3 volta a
    reprovar entrada truncada — que avisou, e por isso não é falha."""
    assert SS.MARCA_DE_TRUNCAMENTO in diario._marca_de_truncamento("entrada", "docs/x.md")


@pytest.mark.parametrize("origem", ["startup", "resume", "clear", "compact", "fork"])
def test_montar_atende_os_cinco_source_e_so_compact_avisa(tmp_path: Path, origem: str):
    """`fork` existe no schema desde a 2.1.214 e não casava o matcher do `hooks.json`.

    O matcher é do manifesto, não deste arquivo; o que se prende aqui é que `montar` trata
    os cinco valores e que só `compact` acrescenta o aviso. NÃO se afirma
    `montar(resume) == montar(startup)`: no consumidor real os dois blocos diferem (9.958
    contra 10.138 ch), e o portão por igualdade foi rejeitado por causa disso.
    """
    raiz = corpus(tmp_path / "proj", adrs=10)
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, origem)
    assert "## Decisões arquiteturais vigentes" in texto
    assert ("## Aviso pós-compactação" in texto) == (origem == "compact")


# --------------------------------------------------------------------------- #
# Bloco reduzido (SubagentStart)
# --------------------------------------------------------------------------- #


def test_bloco_reduzido_leva_invioaveis_e_becos_e_mais_nada(tmp_path: Path):
    raiz = corpus(tmp_path / "proj", adrs=60, becos=100)
    cfg = _cfg(raiz)
    reduzido = SS.montar(raiz, cfg, "startup", reduzido=True)

    assert len(reduzido) <= SS.TETO_SUBAGENTE_CHARS
    for r in invioaveis(raiz, cfg.reafirmacao):
        assert r in reduzido
    assert "## Becos sem saída já explorados" in reduzido
    assert "## Decisões arquiteturais vigentes" not in reduzido
    assert "última entrada do diário" not in reduzido
    assert SS.conferir_fidelidade(raiz, cfg, reduzido, reduzido=True) == 0
    assert len(reduzido) < len(SS.montar(raiz, cfg, "startup"))


def test_bloco_reduzido_reprova_acima_do_teto_proprio(tmp_path: Path):
    raiz = corpus(tmp_path / "proj", adrs=10)
    cfg = _cfg(raiz)
    inchado = SS.montar(raiz, cfg, "startup", reduzido=True) + "x" * SS.TETO_SUBAGENTE_CHARS
    assert SS.conferir_fidelidade(raiz, cfg, inchado, reduzido=True) == 1


def test_bloco_reduzido_reprova_sem_inviolavel(tmp_path: Path):
    raiz = corpus(tmp_path / "proj", adrs=10)
    cfg = _cfg(raiz)
    regras = invioaveis(raiz, cfg.reafirmacao)
    mutilado = SS.montar(raiz, cfg, "startup", reduzido=True).replace(regras[0], "")
    assert SS.conferir_fidelidade(raiz, cfg, mutilado, reduzido=True) == 1


def test_bloco_reduzido_aperta_o_digest_para_caber_no_teto_proprio(tmp_path: Path):
    """Com o digest configurado acima do teto do subagente, quem cede é o digest.

    É a única peça que pode ceder no bloco reduzido: as invioláveis não são cortadas nunca.
    """
    raiz = corpus(
        tmp_path / "proj", adrs=10, becos=100, config={"diario": {"teto_becos_chars": 12_000}}
    )
    cfg = _cfg(raiz)
    natural, _ = diario.becos_sem_saida(cfg.pasta_diario, cfg.diario)
    assert sum(len(i) for i in natural) > SS.TETO_SUBAGENTE_CHARS, (
        "o corpus tem de estourar o teto do subagente, senão o aperto não é exercitado"
    )

    reduzido = SS.montar(raiz, cfg, "startup", reduzido=True)
    assert len(reduzido) <= SS.TETO_SUBAGENTE_CHARS
    for r in invioaveis(raiz, cfg.reafirmacao):
        assert r in reduzido
    assert " de 100," in reduzido, "digest cortado sem anunciar o total"
    assert "Os outros" in reduzido, "digest cortado sem dizer onde está o resto"
    assert SS.conferir_fidelidade(raiz, cfg, reduzido, reduzido=True) == 0


def test_sem_entrada_de_diario_o_orcamento_continua_valendo(tmp_path: Path):
    """`injetar_ultima_entrada: false` é o caso do consumidor que já injeta o handoff dele.

    Sem a entrada, o índice fica com o espaço dela — e antes do orçamento isso significava
    becos 4.633 + índice 5.869 = mais de 10.000 ch em 60 ADRs, com o bloco inteiro
    substituído por um preview.
    """
    raiz = corpus(
        tmp_path / "proj",
        adrs=60,
        becos=100,
        config={"diario": {"injetar_ultima_entrada": False}},
    )
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, "startup")
    assert "última entrada do diário" not in texto
    assert len(texto) <= TETO_DA_PLATAFORMA, f"bloco com {len(texto)} ch"
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0


# --------------------------------------------------------------------------- #
# O hook como o Claude Code o roda: subprocesso, evento no stdin
# --------------------------------------------------------------------------- #

SRC = Path(__file__).resolve().parents[1] / "src"
HOOK = SRC / "harness_memoria" / "hooks" / "session_start.py"


def _rodar(hook: Path, evento: str, cwd: Path, env_extra: dict | None = None, args=()):
    env = {k: v for k, v in os.environ.items() if k not in _VARS_A_LIMPAR}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(hook), *args],
        input=evento,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        env=env,
        timeout=120,
    )


def _contexto_de(saida: str) -> str:
    return json.loads(saida)["hookSpecificOutput"]["additionalContext"]


def test_subagent_start_recebe_o_bloco_reduzido(tmp_path: Path):
    """O payload de `SubagentStart` não tem `source`: a ramificação é por `hook_event_name`.

    Medido em 10 sessões reais: os subagentes fizeram 491-1313 tool calls contra 32-350 da
    thread principal, e em 4 delas a maioria das ESCRITAS — na primeira, 92% delas saíram de
    agentes que não viram inviolável nenhuma. Este teste é o contrato que a entrada nova do
    `hooks.json` vai consumir.
    """
    raiz = corpus(tmp_path / "proj", adrs=30, becos=40)
    evento = json.dumps(
        {
            "hook_event_name": "SubagentStart",
            "cwd": str(raiz),
            "agent_id": "a-1",
            "agent_type": "general-purpose",
        }
    )
    r = _rodar(HOOK, evento, cwd=raiz)
    assert r.returncode == 0, r.stderr
    saida = json.loads(r.stdout)
    assert saida["hookSpecificOutput"]["hookEventName"] == "SubagentStart"

    bloco = saida["hookSpecificOutput"]["additionalContext"]
    assert len(bloco) <= SS.TETO_SUBAGENTE_CHARS
    assert "## Decisões arquiteturais vigentes" not in bloco
    assert "Invioláveis deste projeto" in bloco


def test_session_start_recebe_o_bloco_completo(tmp_path: Path):
    raiz = corpus(tmp_path / "proj", adrs=30, becos=40)
    evento = json.dumps({"hook_event_name": "SessionStart", "source": "compact", "cwd": str(raiz)})
    r = _rodar(HOOK, evento, cwd=raiz)
    assert r.returncode == 0, r.stderr
    bloco = _contexto_de(r.stdout)
    assert len(bloco) <= TETO_DA_PLATAFORMA
    assert "## Decisões arquiteturais vigentes" in bloco
    assert "## Aviso pós-compactação" in bloco


def test_autoteste_com_projeto_explicito_ganha_da_variavel_de_ambiente(tmp_path: Path):
    """Lote 9.4 no canal do autoteste: dentro de uma sessão a variável está SEMPRE setada.

    `raiz_projeto` dá prioridade a `CLAUDE_PROJECT_DIR`, então `--autoteste --projeto
    <fixture>` conferia o projeto CORRENTE. Os dois ramos do defeito são caros: se o
    corrente não adotou o harness, o autoteste responde "hook inerte por desenho" e sai 0
    sem conferir nada (é o que este teste pega); se adotou e está verde, responde "ok" sobre
    o alvo errado.
    """
    raiz = corpus(tmp_path / "proj", adrs=10)
    alheio = tmp_path / "alheio"
    alheio.mkdir()
    (alheio / "CLAUDE.md").write_text("# Outro projeto\n", encoding="utf-8")

    r = _rodar(
        HOOK,
        "",
        cwd=alheio,
        env_extra={"CLAUDE_PROJECT_DIR": str(alheio)},
        args=("--autoteste", "--projeto", str(raiz)),
    )
    assert r.returncode == 0, r.stderr
    assert "inerte por desenho" not in r.stderr, (
        "conferiu o projeto da variável, não o do argumento"
    )
    assert "ADRs no índice" in r.stderr
    assert "índice completo, 10 ADRs" in _contexto_de(r.stdout)


def test_autoteste_imprime_os_dois_tamanhos(tmp_path: Path):
    raiz = corpus(tmp_path / "proj", adrs=30, becos=40)
    r = _rodar(HOOK, "", cwd=raiz, args=("--autoteste", "--projeto", str(raiz)))
    assert r.returncode == 0, r.stderr
    assert "chars injetados" in r.stderr
    assert "bloco reduzido (subagente) com" in r.stderr


def test_autoteste_reprova_quando_o_bloco_nao_e_fiel(tmp_path: Path):
    """Sem este caso, o passo do CI não distingue "hook fiel" de "hook que não confere"."""
    raiz = corpus(tmp_path / "proj", adrs=10, mortos_com_substituto=0, morto_sem_substituto=False)
    (raiz / "docs" / "adr" / "0002-decisao.md").write_text(_adr(2, "superseded"), encoding="utf-8")
    r = _rodar(HOOK, "", cwd=raiz, args=("--autoteste", "--projeto", str(raiz)))
    assert r.returncode == 1
    assert "ADR-0002 está superseded" in r.stderr


def test_pacote_quebrado_nao_derruba_a_sessao(tmp_path: Path):
    """Erro de sintaxe em `config.py` → rc=0 e mensagem ROTULADA, não traceback cru.

    O `try/except Exception` que implementa "nunca derrubar a sessão" começava no
    `__main__`, e o `from harness_memoria...` ficava fora dele — a única linha sem rede, num
    arquivo cujo docstring promete o contrário. Reproduzido nos cinco hooks: com `config.py`
    truncado, rc=1, stdout vazio e `SyntaxError` cru no stderr.
    """
    raiz = corpus(tmp_path / "proj", adrs=10)
    src = tmp_path / "src"
    shutil.copytree(SRC, src, ignore=shutil.ignore_patterns("__pycache__"))
    alvo = src / "harness_memoria" / "config.py"
    alvo.write_text(alvo.read_text(encoding="utf-8") + "\ndef quebrado(:\n", encoding="utf-8")

    evento = json.dumps({"hook_event_name": "SessionStart", "source": "startup", "cwd": str(raiz)})
    r = _rodar(src / "harness_memoria" / "hooks" / "session_start.py", evento, cwd=raiz)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""
    assert "Traceback" not in r.stderr, r.stderr
    assert "[contexto]" in r.stderr, r.stderr
    assert "SyntaxError" in r.stderr, r.stderr
