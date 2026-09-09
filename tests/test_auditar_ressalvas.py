"""Testes da ressalva grave 3 (revisão adversarial): comentário HTML satisfazendo cheque.

A linha do índice de ADR em `template/docs/adr/README.md` virou
`<!-- | [0001](0001-exemplo.md) | ... | -->` para não deixar link morto num índice de
fábrica. O cheque de presença de `auditar_adrs` (`f.name not in texto_indice`) lia o
arquivo como texto puro — o comentário SATISFAZIA o cheque. O revisor provou o dano montando
o consumidor sintético do `ci.yml`: a auditoria aprovava com "índice sincronizado" e a
tabela visível do índice não tinha NENHUMA linha para o único ADR do projeto; apagando só a
linha comentada, a auditoria reprovava — ou seja, o cheque verde não provava sincronia
nenhuma.

O critério de prova é o do revisor: **apagar (ou comentar) a linha tem de mudar o resultado
da auditoria.** Cada teste abaixo verifica isso num dos dois sentidos.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from conftest import escrever_config

from harness_memoria.auditar import Contexto, rodar
from harness_memoria.config import carregar

RAIZ_REPO = Path(__file__).resolve().parents[1]


def auditar(raiz: Path) -> Contexto:
    cfg = carregar(raiz)
    assert cfg is not None, "fixture sem harness.json"
    ctx = Contexto(raiz=raiz, cfg=cfg)
    rodar(ctx)
    return ctx


def falhas_com(ctx: Contexto, trecho: str) -> list[str]:
    return [f for f in ctx.falhas if trecho.lower() in f.lower()]


# --------------------------------------------------------------------------- #
# O cenário exato do revisor: consumidor derivado de `template/`, como o ci.yml monta
# --------------------------------------------------------------------------- #


def _montar_consumidor_como_o_ci(raiz: Path) -> None:
    """Reproduz o passo "Montar um projeto consumidor a partir do template" do `ci.yml`.

    Copia `template/docs/` inteiro (README.md e template.md tal como distribuídos) e deriva
    `0001-exemplo.md` do `template.md` — é essa derivação que faz o CI nascer com um ADR
    real de verdade sem manter um exemplo escrito à mão (ADR-0001 deste repo, decisão que
    motivou o commit `e889dbc`).
    """
    (raiz / ".claude").mkdir(parents=True, exist_ok=True)
    docs_tpl = RAIZ_REPO / "template" / "docs"
    (raiz / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    (raiz / "docs" / "diario").mkdir(parents=True, exist_ok=True)
    for nome in ("README.md", "template.md"):
        (raiz / "docs" / "adr" / nome).write_text(
            (docs_tpl / "adr" / nome).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (raiz / "docs" / "diario" / "README.md").write_text(
        (docs_tpl / "diario" / "README.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    mes = datetime.now().strftime("%Y-%m")
    (raiz / "docs" / "diario" / f"{mes}.md").write_text(
        f"# Diário · {mes}\n\n---\n\n## {mes}-01 — Entrada de exemplo\n\n"
        "### Tentativas descartadas\n\n- abordagem X → falhou. **Não repetir.**\n",
        encoding="utf-8",
    )

    tpl = (raiz / "docs" / "adr" / "template.md").read_text(encoding="utf-8")
    corpo = tpl.split("\n---\n", 2)[-1]
    corpo = re.sub(
        r"^# ADR-NNNN —.*$",
        "# ADR-0001 — Exemplo de problema com a solução escolhida",
        corpo,
        count=1,
        flags=re.MULTILINE,
    )
    campos = "\n".join(
        f"{c}: {v}"
        for c, v in re.findall(r"^([a-z-]+):\s*(.*)$", tpl.split("\n---")[0], re.MULTILINE)
    )
    campos = campos.replace("status: proposed", "status: accepted").replace(
        "data: AAAA-MM-DD", "data: 2026-01-01"
    )
    (raiz / "docs" / "adr" / "0001-exemplo.md").write_text(
        f"---\n{campos}\n---\n{corpo}", encoding="utf-8"
    )

    (raiz / "CLAUDE.md").write_text(
        "# Projeto Consumidor\n\n"
        "## Regras invioláveis\n\n**NUNCA**\n\n"
        "- Escrever segredo no repositório.\n\n"
        f"## Memória\n\n- [diário](docs/diario/{mes}.md)\n\n"
        "### Qual ADR ler — por caminho que você vai tocar\n\n"
        "| Caminho | ADRs |\n| --- | --- |\n| `docs/` | 0001 |\n",
        encoding="utf-8",
    )
    escrever_config(raiz, {})


def test_template_distribuido_gera_consumidor_que_passa(tmp_path: Path):
    """O template distribuído, tal como está, produz um consumidor que a auditoria aprova.

    Isto é o que o CI cobra a cada push — se `template/docs/adr/README.md` voltar a ter a
    linha do índice só em comentário, este teste reprova.
    """
    raiz = tmp_path / "consumidor"
    _montar_consumidor_como_o_ci(raiz)
    ctx = auditar(raiz)
    assert ctx.falhas == [], f"consumidor derivado do template deveria passar: {ctx.falhas}"


def test_apagar_a_linha_do_indice_muda_o_resultado(tmp_path: Path):
    """O critério de prova do revisor: apagar a linha visível tem de reprovar a auditoria.

    Se este teste passar mas a linha comentada (abaixo) também passar, o cheque de índice é
    decorativo — não prova sincronia nenhuma.
    """
    raiz = tmp_path / "consumidor"
    _montar_consumidor_como_o_ci(raiz)
    indice = raiz / "docs" / "adr" / "README.md"
    texto = indice.read_text(encoding="utf-8")
    sem_linha = texto.replace("| [0001](0001-exemplo.md) | {problema + solução} | proposed |\n", "")
    assert sem_linha != texto, "a linha esperada não estava no índice — fixture desatualizada"
    indice.write_text(sem_linha, encoding="utf-8")

    achado = falhas_com(auditar(raiz), "não está no índice")
    assert achado, "0001-exemplo.md sem linha no índice deveria reprovar"


def test_linha_do_indice_so_em_comentario_html_reprova(tmp_path: Path):
    """A regressão em si: reescreve a linha visível como comentário HTML e espera reprovar.

    Antes da correção, isto passava — era exatamente o estado em que
    `template/docs/adr/README.md` foi entregue pela onda que criou a convenção de andaime.
    """
    raiz = tmp_path / "consumidor"
    _montar_consumidor_como_o_ci(raiz)
    indice = raiz / "docs" / "adr" / "README.md"
    texto = indice.read_text(encoding="utf-8")
    linha_real = "| [0001](0001-exemplo.md) | {problema + solução} | proposed |\n"
    assert linha_real in texto
    linha_comentada = "<!-- | [0001](0001-exemplo.md) | {problema + solução} | proposed | -->\n"
    indice.write_text(texto.replace(linha_real, linha_comentada), encoding="utf-8")

    achado = falhas_com(auditar(raiz), "não está no índice")
    assert achado, (
        "entrada só em comentário HTML deveria reprovar — cheque satisfeito por texto "
        "invisível equivale a cheque inexistente (princípio 11)"
    )


def test_nota_instrucional_em_comentario_html_continua_liberada(tmp_path: Path):
    """O filtro de comentário não pode confundir andaime com nota para humano.

    `template/docs/adr/README.md` usa comentário HTML também para instruir quem lê
    (`<!-- Caminho natural de quem procura... -->`), e isso tem de continuar sem reprovar —
    senão o remédio do princípio 9 (falso positivo) troca de lugar.
    """
    raiz = tmp_path / "consumidor"
    _montar_consumidor_como_o_ci(raiz)
    ctx = auditar(raiz)
    assert falhas_com(ctx, "por domínio") == []


# --------------------------------------------------------------------------- #
# Coerência: `auditar_indice_por_dominio` sofre da mesma classe de bug com comentário de
# VÁRIAS linhas — a linha real cai DENTRO do comentário, mas isolada ela começa com "-" e
# passaria pelo filtro de uma linha só.
# --------------------------------------------------------------------------- #

ADR_DEPRECIADO = """\
---
status: deprecated
data: 2026-02-01
---

# ADR-0002 — Decisão descontinuada

Não vale mais e nada a substituiu.
"""


def test_referencia_a_adr_morto_dentro_de_comentario_multilinha_nao_falsifica_presenca(
    projeto: Path,
):
    """Entrada de domínio dentro de um comentário HTML de várias linhas não deve contar.

    Um comentário `<!-- -->` de uma linha só já escapa do cheque porque a linha inteira
    começa com `<!--`, não com `-`. Um comentário de VÁRIAS linhas tem a entrada real
    (`- **legado:** 0002`) isolada na própria linha — e essa linha começa com `-` de
    verdade. Sem filtrar o comentário primeiro, o cheque tratava aquilo como entrada real e
    reprovava por falta de marca num texto que ninguém vê, o que é o mesmo falso positivo
    da ressalva grave, só que no cheque vizinho.
    """
    (projeto / "docs" / "adr" / "0002-descontinuada.md").write_text(
        ADR_DEPRECIADO, encoding="utf-8"
    )
    indice = projeto / "docs" / "adr" / "README.md"
    texto = indice.read_text(encoding="utf-8")
    texto = texto.replace(
        "| [0001](0001-primeira.md) | Primeira decisão | accepted |\n",
        "| [0001](0001-primeira.md) | Primeira decisão | accepted |\n"
        "| [0002](0002-descontinuada.md) | Decisão descontinuada | deprecated |\n",
    )
    texto += "\n## Por domínio\n\n<!--\n- **legado:** 0002\n-->\n"
    indice.write_text(texto, encoding="utf-8")

    ctx = auditar(projeto)
    achado = falhas_com(ctx, "sem marca")
    assert achado == [], (
        f"entrada só dentro de comentário multi-linha não deveria reprovar: {achado}"
    )


def test_referencia_a_adr_morto_fora_de_comentario_continua_reprovando(projeto: Path):
    """Controle do teste acima: a MESMA entrada, fora de comentário, tem de continuar pega.

    Sem este controle, o teste anterior não provaria nada — passaria mesmo se o cheque
    inteiro tivesse sido silenciado.
    """
    (projeto / "docs" / "adr" / "0002-descontinuada.md").write_text(
        ADR_DEPRECIADO, encoding="utf-8"
    )
    indice = projeto / "docs" / "adr" / "README.md"
    texto = indice.read_text(encoding="utf-8")
    texto = texto.replace(
        "| [0001](0001-primeira.md) | Primeira decisão | accepted |\n",
        "| [0001](0001-primeira.md) | Primeira decisão | accepted |\n"
        "| [0002](0002-descontinuada.md) | Decisão descontinuada | deprecated |\n",
    )
    texto += "\n## Por domínio\n\n- **legado:** 0002\n"
    indice.write_text(texto, encoding="utf-8")

    achado = falhas_com(auditar(projeto), "sem marca")
    assert achado, "entrada real, fora de comentário, sem marca deveria reprovar"


# --------------------------------------------------------------------------- #
# Ressalva menor: `docs/adr/template.md` não pode divergir de `template/docs/adr/template.md`
# --------------------------------------------------------------------------- #


def test_template_auto_hospedado_e_copia_do_template_distribuido():
    """`docs/adr/0001-auto-hospedagem.md` afirma que os dois arquivos são cópia um do outro.

    A afirmação já divergiu uma vez em silêncio: a onda que copiou o arquivo o fez antes de
    uma edição no distribuído (as linhas de `emenda:`/`emendado-por:`), e nada acusou. Este
    teste transforma a afirmação do ADR num cheque mecânico.
    """
    distribuido = (RAIZ_REPO / "template" / "docs" / "adr" / "template.md").read_text(
        encoding="utf-8"
    )
    auto_hospedado = (RAIZ_REPO / "docs" / "adr" / "template.md").read_text(encoding="utf-8")
    assert auto_hospedado == distribuido, (
        "docs/adr/template.md divergiu de template/docs/adr/template.md — "
        "`cp template/docs/adr/template.md docs/adr/template.md` reconcilia"
    )
