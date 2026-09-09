"""Motor de auditoria da documentação e das fronteiras estruturais.

Existe porque documentação sem verificação mecânica apodrece, e porque a regra inviolável
que é determinística deve ser checada por máquina, não por leitura.

O que este módulo NÃO faz: cheque de fronteira específico de um projeto. Esses vivem no
projeto, num módulo apontado por `auditoria.checks_do_projeto`, e recebem o mesmo
`Contexto`. A divisão é a mesma do resto do pacote — mecanismo aqui, política lá.

Contrato de um módulo de checks do projeto::

    def registrar(ctx):
        \"\"\"Chamado depois dos checks genéricos, com falhas já acumuladas.\"\"\"
        if (ctx.raiz / "apps/web/src/lib/supabase.ts").exists():
            ...
            ctx.falhar("service_role vazou para o browser")
        ctx.avisar("isto não reprova o build")

Uso:  python -m harness_memoria.auditar [--projeto CAMINHO] [--silencioso]
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from ..adr import (
    STATUS_MORTOS,
    STATUS_VALIDOS,
    arquivos_adr,
    dados_dos_adrs,
    ler_frontmatter,
)
from ..config import (
    CHAVES_OBRIGATORIAS_DE_REGRA,
    Config,
    _mascara_de_cerca,
    caminho_config,
    invioaveis,
)
from ..diario import SECAO_BECOS, arquivos_do_diario, remediacao_do_teto

#: Uma citação a ADR morto é legítima quando a vizinhança diz que houve substituição.
#: É o que separa "siga a ADR-0007" de "a ADR-0023 substituiu a ADR-0007".
MARCADORES_DE_SUPERSESSAO = (
    "substitu",
    "superad",
    "superseded",
    "deprecated",
    "históric",
)

STATUS_QUE_EXIGEM_PLANO = {"accepted", "implemented"}


@dataclass
class Contexto:
    raiz: Path
    cfg: Config
    falhas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    _adrs: dict | None = None

    def falhar(self, msg: str) -> None:
        self.falhas.append(msg)

    def avisar(self, msg: str) -> None:
        self.avisos.append(msg)

    @property
    def adrs(self) -> dict:
        """Dados de todos os ADRs, lidos uma vez por execução."""
        if self._adrs is None:
            self._adrs = dados_dos_adrs(self.cfg.pasta_adr)
        return self._adrs

    def rel(self, p: Path) -> str:
        try:
            return p.relative_to(self.raiz).as_posix()
        except ValueError:
            return str(p)

    def fontes_operacionais(self) -> list[Path]:
        """Arquivos que INSTRUEM um agente, e por isso não podem citar ADR morto."""
        saida: list[Path] = []
        for padrao in self.cfg.auditoria.fontes_operacionais:
            saida += [p for p in sorted(self.raiz.glob(padrao)) if p.is_file()]
        return saida


def _fora_de_cerca(texto: str) -> str:
    """O mesmo texto sem as linhas dentro de bloco de código.

    Ilustração não é instrução, e a máscara é a MESMA que `invioaveis()` usa
    (`config._mascara_de_cerca`) de propósito: duas implementações de "isto aqui é só
    exemplo" divergem na primeira correção, e essa já trata cerca aninhada, marcador de
    quatro backticks e cerca não fechada (que degrada para o texto inteiro, o comportamento
    anterior à máscara).

    Só para os cheques cuja contraparte no runtime também ignora cerca. Onde o mecanismo
    lê dentro dela, o auditor tem de ler também — ver o comentário do cheque de mês em
    `auditar_diario`.
    """
    linhas = texto.splitlines()
    cercado = _mascara_de_cerca(linhas)
    return "\n".join(x for x, dentro in zip(linhas, cercado, strict=True) if not dentro)


_COMENTARIO_HTML = re.compile(r"(?s)<!--.*?-->")


def _sem_comentario_html(texto: str) -> str:
    """O mesmo texto sem comentário HTML — ao lado de `_fora_de_cerca`, não no lugar dela.

    Nasceu de um caso concreto: a linha de exemplo do índice de ADR virou
    `<!-- | [0001](0001-exemplo.md) | ... | -->` para não deixar link morto na tabela
    visível de um template de fábrica, e o cheque de presença (`f.name not in texto_indice`)
    lia o arquivo como texto puro — o comentário SATISFAZIA o cheque. A auditoria aprovava
    com "índice sincronizado" enquanto a tabela visível ficava com zero linhas para o único
    ADR do projeto; todo consumidor novo nascia "sincronizado" sem nunca ter tido um índice
    de verdade. Cheque satisfeito por texto que ninguém vê equivale a cheque inexistente —
    a mesma doença do princípio 11, só que do lado do falso NEGATIVO de falha.

    Só entra nos cheques de PRESENÇA — "este item real já está listado aqui" — porque neste
    projeto o comentário HTML é convenção de andaime (linha de exemplo comentada, para
    descomentar na hora certa) e nota para humano (`<!-- Caminho natural de quem
    procura... -->`), nunca conteúdo que o mecanismo deveria contar como dado. Cheques que
    procuram um padrão INDESEJADO em vez de confirmar presença — `auditar_referencias_a_adr_morto`
    e `auditar_scripts_citados` — deliberadamente NÃO usam este filtro: quem lê o arquivo
    bruto numa sessão é o agente, não um navegador renderizando HTML, então uma referência
    ruim escondida num comentário continua enganando-o e tirar o filtro ali abriria um ponto
    cego novo — o oposto do que este helper existe para consertar.
    """
    return _COMENTARIO_HTML.sub("", texto)


# --------------------------------------------------------------------------- #
# ADRs
# --------------------------------------------------------------------------- #


def auditar_adrs(ctx: Contexto) -> None:
    pasta = ctx.cfg.pasta_adr
    if not pasta.exists():
        ctx.falhar(f"{ctx.cfg.adr.pasta}/ não existe")
        return

    indice = ctx.cfg.indice_adr
    if not indice.exists():
        ctx.falhar(f"{ctx.cfg.adr.pasta}/README.md (índice) não existe")
        return
    # `_sem_comentario_html`: sem ela, uma linha de exemplo comentada (o template distribui
    # uma) satisfaz "arquivo está no índice" sem nenhuma linha visível na tabela — ver o
    # docstring do helper para o caso medido.
    texto_indice = _sem_comentario_html(indice.read_text(encoding="utf-8"))

    arquivos = arquivos_adr(pasta)
    if not arquivos:
        ctx.avisar("nenhum ADR encontrado")
        return

    # Colisão de número tem de ser cobrada AQUI, sobre os arquivos, porque `dados_dos_adrs`
    # indexa por `f.name[:4]` e a segunda leitura sobrescreve a primeira em silêncio.
    # Medido com `0001-guardar-segredo-no-git.md` (superseded) ao lado de
    # `0001-nunca-guardar-segredo.md` (accepted): `arquivos_adr` acha 2, `dados_dos_adrs`
    # devolve 1 chave e a auditoria inteira saía com falhas=[] avisos=[] — o arquivo
    # sombreado não é cobrado do índice, o status dele não é validado e a supersessão dele
    # não é checada. Duas branches criando ADR ao mesmo tempo é o caminho normal para cá.
    for num, quantos in sorted(Counter(f.name[:4] for f in arquivos).items()):
        if quantos > 1:
            nomes = ", ".join(f.name for f in arquivos if f.name[:4] == num)
            ctx.falhar(
                f"ADR-{num} tem {quantos} arquivos: {nomes} — renumere um deles. O índice "
                f"injetado e a auditoria leem só um dos dois; o outro é invisível para os "
                f"dois, inclusive o status e a supersessão dele"
            )

    dados = ctx.adrs
    for num, d in sorted(dados.items()):
        f: Path = d["arquivo"]
        if f.name not in texto_indice:
            ctx.falhar(f"{f.name} não está no índice {ctx.cfg.adr.pasta}/README.md")

        if d["status"] not in STATUS_VALIDOS:
            bruto = d["status_bruto"] or "(vazio)"
            ctx.falhar(
                f"{f.name}: status '{bruto}' inválido "
                f"(esperado: {', '.join(sorted(STATUS_VALIDOS))})"
            )

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["data"]):
            ctx.falhar(f"{f.name}: campo `data` ausente ou fora do formato AAAA-MM-DD")

        if not d["titulo"]:
            ctx.falhar(f"{f.name}: título deve ser `# ADR-{num} — …` (ou `# ADR {num} — …`)")

        secao_plano = ctx.cfg.adr.secao_plano
        if secao_plano and d["status"] in STATUS_QUE_EXIGEM_PLANO and secao_plano not in d["texto"]:
            ctx.falhar(f"{f.name}: status '{d['status']}' exige a seção '{secao_plano}'")

        primeiro = ctx.cfg.adr.primeiro_com_regra
        if primeiro is not None and int(num) >= primeiro:
            _auditar_regra(ctx, f, d["texto"])

    # numeração contígua a partir de 0001
    esperados = {f"{i:04d}" for i in range(1, len(dados) + 1)}
    faltando = esperados - set(dados)
    if faltando:
        ctx.avisar(f"lacuna na numeração de ADR: {', '.join(sorted(faltando))}")

    _auditar_supersessao(ctx, dados)
    _auditar_emenda(ctx, dados)


def _auditar_supersessao(ctx: Contexto, dados: dict) -> None:
    """Supersessão é bidirecional: quem morre aponta o substituto e vice-versa.

    Sem os dois lados, um ADR novo pode substituir outro sem que quem lê o antigo saiba —
    e ponteiro velho faz mais dano que ponteiro nenhum.

    `substituido-por:` é exigido de `superseded`, não de todo status morto: `deprecated` é
    o status de quem morreu sem substituto, e é para esse caso que ele existe.
    """
    agregados = set(ctx.cfg.adr.agregados)

    for num, d in sorted(dados.items()):
        for alvo in d["substituido_por"]:
            if alvo not in dados:
                ctx.falhar(f"ADR-{num} aponta substituido-por ADR-{alvo}, que não existe")
            elif num not in dados[alvo]["substitui"]:
                ctx.falhar(
                    f"supersessão unilateral: ADR-{num} diz 'substituido-por ADR-{alvo}', "
                    f"mas ADR-{alvo} não declara 'substitui: [ADR-{num}]'"
                )
        if d["substituido_por"] and d["status"] != "superseded":
            ctx.falhar(
                f"ADR-{num} tem 'substituido-por' mas status é "
                f"'{d['status'] or '(vazio)'}' (esperado 'superseded')"
            )
        # `superseded`, e não `STATUS_MORTOS`: `deprecated` significa exatamente "não vale
        # mais e NADA o substituiu" — é o que o `template/docs/adr/README.md` documenta.
        # Exigir `substituido-por:` dos dois deixava o `deprecated` sem saída possível: sem
        # o campo caía aqui, com o campo caía no cheque de cima ("esperado 'superseded'"), e
        # nenhum ADR `deprecated` passava na auditoria — justo o status que a skill manda
        # usar quando nada substituiu. Falha sem correção é o jeito mais rápido de ensinar a
        # ignorar o auditor (princípio 9), e o próprio motor já pressupõe morto-sem-substituto
        # nos fallbacks "(sem substituto declarado)" mais abaixo.
        if d["status"] == "superseded" and not d["substituido_por"]:
            ctx.falhar(
                f"ADR-{num} está superseded e não declara `substituido-por:` — "
                f"o índice injetado no início da sessão não tem como dizer o que seguir "
                f"no lugar, e ADR morto sem substituto é pior que ADR nenhum. Se nada o "
                f"substituiu, o status é `deprecated`"
            )

    for num, d in sorted(dados.items()):
        for alvo in d["substitui"]:
            if alvo not in dados:
                ctx.falhar(f"ADR-{num} diz substituir ADR-{alvo}, que não existe")
            elif num not in dados[alvo]["substituido_por"]:
                # ADR agregado é substituído em partes: só avisa.
                nivel = ctx.avisar if alvo in agregados else ctx.falhar
                nivel(
                    f"supersessão unilateral: ADR-{num} diz 'substitui ADR-{alvo}', "
                    f"mas ADR-{alvo} não declara 'substituido-por: [ADR-{num}]'"
                )


def _auditar_emenda(ctx: Contexto, dados: dict) -> None:
    """`emenda:` e `emendado-por:` andam em par, como a supersessão.

    Emenda é o meio-termo entre "vale inteiro" e "não siga": um ADR novo muda UMA das
    decisões de um ADR que tem várias. Marcar o antigo como `superseded` mentiria sobre as
    decisões dele que seguem valendo; não marcar nada deixaria quem lê a decisão revogada
    achando que ela vale — que é o dano de ponteiro velho, na pior forma, porque a parte
    errada fica cercada de partes certas.

    Nasceu como cheque de projeto no ValidaNI (a ADR-0023 emendou a decisão 3 da ADR-0014) e
    veio para o motor no segundo caso: no rede_inspira_app, quatro ADRs de harness tiveram o
    mecanismo movido para fora do repositório sem que nenhuma decisão fosse revertida. Dois
    consumidores, e o cheque é puro mecanismo de frontmatter — igual ao de supersessão.
    """
    for num, d in sorted(dados.items()):
        for alvo in d["emenda"]:
            if alvo not in dados:
                ctx.falhar(f"ADR-{num} diz emendar ADR-{alvo}, que não existe")
            elif num not in dados[alvo]["emendado_por"]:
                ctx.falhar(
                    f"emenda unilateral: ADR-{num} declara `emenda: [ADR-{alvo}]`, mas "
                    f"ADR-{alvo} não declara `emendado-por: [ADR-{num}]` — quem ler o "
                    f"ADR-{alvo} não fica sabendo que uma decisão dele mudou"
                )
        for alvo in d["emendado_por"]:
            if alvo not in dados:
                ctx.falhar(f"ADR-{num} diz ser emendado por ADR-{alvo}, que não existe")
            elif num not in dados[alvo]["emenda"]:
                ctx.falhar(
                    f"emenda unilateral: ADR-{num} declara `emendado-por: [ADR-{alvo}]`, "
                    f"mas ADR-{alvo} não declara `emenda: [ADR-{num}]`"
                )


def _auditar_regra(ctx: Contexto, f: Path, texto: str) -> None:
    """ADR a partir de `primeiro_com_regra` abre com `## Regra`, curta.

    É o resumo que permite decidir sem abrir o ADR inteiro — o corpus completo custa dezenas
    de milhares de tokens. Vale para os novos apenas: retrofitar os anteriores exigiria
    editar corpo de ADR aceito, e a regra de imutabilidade vale também para quem a
    implementa.
    """
    teto = ctx.cfg.adr.teto_linhas_regra
    m = re.search(r"^## Regra\s*\n(.*?)(?=^## |\Z)", texto, re.MULTILINE | re.DOTALL)
    if not m:
        ctx.falhar(
            f"{f.name}: falta a seção '## Regra' logo após o título — até {teto} linhas "
            f"dizendo o que seguir, para o leitor decidir sem abrir o ADR inteiro"
        )
        return
    linhas = [x for x in m.group(1).strip().splitlines() if x.strip()]
    if not linhas:
        ctx.falhar(f"{f.name}: a seção '## Regra' está vazia")
    elif len(linhas) > teto:
        ctx.falhar(
            f"{f.name}: '## Regra' tem {len(linhas)} linhas (teto {teto}) — "
            f"o resto do raciocínio vai nas seções de baixo"
        )


#: Seções do template que NÃO entram na conformidade porque já têm cheque dedicado, com
#: limiar próprio. `Regra` vale a partir de `adr.primeiro_com_regra` e não se retrofita.
_SECOES_COM_CHEQUE_PROPRIO = {"Regra"}


def auditar_conformidade_com_template(ctx: Contexto) -> None:
    """Todo ADR tem os campos de frontmatter e as seções `##` do `template.md` do projeto.

    O template É a declaração da convenção daquele projeto, então derivar dele custa zero
    configuração e não apodrece junto: mexer no template muda o que é exigido, o que é
    exatamente o comportamento desejado.

    Nasceu de um erro concreto durante a extração do harness. Um ADR novo saiu com 3 dos 7
    campos de frontmatter e uma estrutura de seções inventada — 8 seções com nomes próprios em
    vez das 10 do projeto, sem `Critérios de Verificação` nem `Referências` — porque foi
    redigido a partir do template genérico do pacote em vez do template do repositório. Nada
    acusou, e quem leu percebeu na hora que estava mais pobre que os 31 anteriores.

    "Genérico no lugar do específico" é a regressão que uma extração de mecanismo mais
    arrisca causar. Este cheque é a guarda contra ela.

    Campo ou seção EXTRA passa: `emenda:` não está no template e é legítimo. O que se exige é
    que nada do template falte.
    """
    if not ctx.cfg.adr.conformidade_com_template:
        return
    template = ctx.cfg.pasta_adr / "template.md"
    if not template.exists():
        # Sem template não há convenção declarada, e inventar uma seria pior que não checar.
        return
    try:
        texto_tpl = template.read_text(encoding="utf-8")
    except OSError:
        return

    campos_tpl = set(ler_frontmatter(texto_tpl))
    secoes_tpl = [
        s
        for s in re.findall(r"^## (.+)$", texto_tpl, re.MULTILINE)
        if s not in _SECOES_COM_CHEQUE_PROPRIO
    ]
    if not campos_tpl and not secoes_tpl:
        return

    limiar = ctx.cfg.adr.primeiro_com_template
    for num, d in sorted(ctx.adrs.items()):
        if limiar is not None and int(num) < limiar:
            continue
        nome = d["arquivo"].name
        faltam_campos = sorted(campos_tpl - set(ler_frontmatter(d["texto"])))
        if faltam_campos:
            ctx.falhar(
                f"{nome}: frontmatter sem {faltam_campos} — o `template.md` do projeto declara "
                f"{sorted(campos_tpl)}, e os outros ADRs seguem. Campo extra é permitido; "
                f"faltar não."
            )
        presentes = set(re.findall(r"^## (.+)$", d["texto"], re.MULTILINE))
        faltam_secoes = [s for s in secoes_tpl if s not in presentes]
        if faltam_secoes:
            ctx.falhar(
                f"{nome}: sem a(s) seção(ões) {faltam_secoes} do `template.md`. Escrever ADR "
                f"a partir de outro modelo produz registro mais pobre que os vizinhos, e é o "
                f"leitor que descobre."
            )


def auditar_referencias_a_adr_morto(ctx: Contexto) -> None:
    """Nenhum arquivo operacional manda seguir ADR `superseded` ou `deprecated`.

    Doc ERRADA é o único tipo de documentação que faz dano grande a um agente: com
    comentário incorreto o acerto medido cai de 78,5% para 68,1%, enquanto doc ausente ou
    incompleta praticamente não muda nada (arXiv:2404.03114). Ponteiro velho é pior que
    ponteiro nenhum.

    Este cheque existe porque o auditor original validava a supersessão ENTRE ADRs com rigor
    e não olhava quem os cita. O resultado foi o CLAUDE.md apontando a regra mais crítica do
    projeto para um ADR substituído, enquanto o índice dizia na mesma sessão
    "superseded: não siga".

    Menção histórica passa: basta a vizinhança da linha dizer que houve substituição.
    """
    mortos = {n: d for n, d in ctx.adrs.items() if d["status"] in STATUS_MORTOS}
    if not mortos:
        return

    for p in ctx.fontes_operacionais():
        try:
            linhas = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, linha in enumerate(linhas):
            for num in re.findall(r"ADR[-\s](\d{4})", linha):
                if num not in mortos:
                    continue
                vizinhanca = " ".join(linhas[max(0, i - 2) : i + 3]).lower()
                if any(m in vizinhanca for m in MARCADORES_DE_SUPERSESSAO):
                    continue
                # Não vale "passa se o substituto for citado por perto": isso abria um
                # buraco medido — um arquivo que menciona o ADR novo numa linha podia citar
                # o antigo como autoridade duas linhas abaixo. A PALAVRA que marca a
                # substituição é o critério, porque é ela que avisa o leitor.
                subs = mortos[num]["substituido_por"]
                alvo = ", ".join(f"ADR-{s}" for s in subs) or "(sem substituto declarado)"
                ctx.falhar(
                    f"{ctx.rel(p)}:{i + 1} manda seguir ADR-{num}, que está "
                    f"{mortos[num]['status']} — aponte para {alvo}. Se a menção é "
                    f"histórica, diga na linha que houve substituição."
                )


def auditar_indice_por_dominio(ctx: Contexto) -> None:
    """Na lista 'Por domínio' do índice, ADR morto tem de vir marcado.

    A tabela do índice carrega status por linha; a lista por domínio não carregava nenhum, e
    é o caminho natural de quem procura "os ADRs de tal assunto". Quem chegasse por ali
    recebia o morto e o vivo com o mesmo peso.
    """
    indice = ctx.cfg.indice_adr
    if not indice.exists():
        return
    # Mesmo filtro do índice principal, e pela mesma razão: um comentário HTML de VÁRIAS
    # linhas pode ter `- **{domínio}:** NNNN` como uma das linhas internas, e essa linha
    # começa com `-` — passaria pelo `startswith("-")` abaixo como se fosse entrada real.
    # Comentário de uma linha só (`<!-- - ... -->`) já falha nesse teste porque começa com
    # `<!--`, mas não há razão para o cheque depender de quantas linhas o comentário ocupa.
    trecho = _sem_comentario_html(indice.read_text(encoding="utf-8")).split("## Por domínio")
    if len(trecho) < 2:
        return
    for linha in trecho[1].splitlines():
        if not linha.strip().startswith("-"):
            continue
        for num in re.findall(r"\b(\d{4})\b", linha):
            d = ctx.adrs.get(num)
            if d and d["status"] in STATUS_MORTOS and f"{num} (" not in linha:
                # A marca é derivada do frontmatter, não fixa: mandar escrever
                # `(superada → NNNN)` num `deprecated` — que por definição não tem NNNN —
                # é instruir o impossível, e era o segundo cheque em que caía quem
                # consertava o primeiro.
                subs = " ".join(d["substituido_por"])
                marca = f"{num} (superada → {subs})" if subs else f"{num} (deprecated)"
                ctx.falhar(
                    f"{ctx.cfg.adr.pasta}/README.md, lista por domínio: {num} está "
                    f"{d['status']} e aparece sem marca — escreva `{marca}`"
                )


def auditar_contagem_de_adr_no_readme(ctx: Contexto) -> None:
    """A contagem de ADRs por status no README bate com os arquivos.

    É o tipo de número que ninguém relê e todo mundo repete: divergiu duas vezes num único
    dia no projeto de origem, sempre porque um ADR entrou e a linha de governança ficou
    parada.
    """
    p = ctx.raiz / "README.md"
    if not p.exists():
        return
    real: Counter[str] = Counter(d["status"] for d in ctx.adrs.values())
    total = sum(real.values())
    for linha in p.read_text(encoding="utf-8").splitlines():
        m = re.search(r"(\d+)\s+ADRs?\s*\(", linha)
        if not m:
            continue
        if int(m.group(1)) != total:
            ctx.falhar(
                f"README.md diz {m.group(1)} ADRs e existem {total} — "
                f"atualize a linha de governança"
            )
        for qtd, status in re.findall(r"(\d+)\s+`(\w+)`", linha):
            if status in STATUS_VALIDOS and int(qtd) != real.get(status, 0):
                ctx.falhar(f"README.md diz {qtd} ADR(s) `{status}` e existem {real.get(status, 0)}")
        return


def auditar_mapa_de_adr_por_caminho(ctx: Contexto) -> None:
    """O mapa caminho→ADR do CLAUDE.md aponta para caminho e ADR que existem.

    O mapa existe porque um corpus de ADR maduro custa dezenas de milhares de tokens: "LEIA
    o índice antes de mudar schema" é instrução que ninguém executa inteira, e a degradação
    por comprimento de contexto é medida (Chroma, *Context Rot*: queda bem antes do limite
    nominal em 18 modelos). Retrieval por caminho troca o corpus inteiro por 5 a 7 ADRs.

    Mapa que apodrece é pior que mapa nenhum — mesmo dano de ponteiro velho — então ele é
    verificado: caminho inexistente e ADR morto ou inexistente reprovam o build.
    """
    if not ctx.cfg.auditoria.exigir_mapa_por_caminho:
        return
    p = ctx.raiz / "CLAUDE.md"
    if not p.exists():
        return
    texto = p.read_text(encoding="utf-8")
    m = re.search(r"^#{2,4} Qual ADR ler.*?\n(.*?)(?=^#{2,4} |\Z)", texto, re.MULTILINE | re.S)
    if not m:
        ctx.falhar(
            "CLAUDE.md não tem a seção 'Qual ADR ler' — sem ela, a única instrução sobre "
            "ADR volta a ser 'leia o índice', que é a instrução que ninguém executa"
        )
        return

    linhas_uteis = 0
    for linha in m.group(1).splitlines():
        if not linha.startswith("|") or set(linha) <= set("|- "):
            continue
        colunas = [c.strip() for c in linha.strip("|").split("|")]
        if len(colunas) < 2 or colunas[0].lower() == "caminho":
            continue
        linhas_uteis += 1
        for caminho in re.findall(r"`([^`]+)`", colunas[0]):
            if not (ctx.raiz / caminho).exists():
                ctx.falhar(
                    f"CLAUDE.md, mapa de ADR por caminho: `{caminho}` não existe — "
                    f"corrija o caminho ou remova a linha"
                )
        for num in re.findall(r"\b(\d{4})\b", colunas[1]):
            d = ctx.adrs.get(num)
            if not d:
                ctx.falhar(f"CLAUDE.md, mapa de ADR por caminho: ADR-{num} não existe")
            elif d["status"] in STATUS_MORTOS:
                subs = ", ".join(f"ADR-{s}" for s in d["substituido_por"])
                # Sem substituto a instrução não pode ser "troque por": `deprecated` é o
                # status de quem não tem por quem ser trocado, e ele passou a ser legal aqui.
                saida = (
                    f"troque por {subs}"
                    if subs
                    else "remova a linha ou aponte o ADR que vale hoje — nada o substituiu"
                )
                ctx.falhar(
                    f"CLAUDE.md, mapa de ADR por caminho: ADR-{num} está {d['status']} — {saida}"
                )
    if not linhas_uteis:
        ctx.falhar("CLAUDE.md, mapa de ADR por caminho: tabela vazia")


# --------------------------------------------------------------------------- #
# Diário
# --------------------------------------------------------------------------- #


def auditar_diario(ctx: Contexto) -> None:
    pasta = ctx.cfg.pasta_diario
    if not pasta.exists():
        ctx.falhar(f"{ctx.cfg.diario.pasta}/ não existe")
        return

    hoje = datetime.now()
    mes = hoje.strftime("%Y-%m")
    dia_limite = ctx.cfg.diario.dia_limite_rotacao
    candidatos = sorted(pasta.glob(f"{mes}*.md"))
    if not candidatos:
        # Aviso pendente por semanas foi o que deixou o ponteiro do CLAUDE.md apontando
        # para um arquivo cujo head já estava três arquivos atrás. A partir do dia limite,
        # reprova.
        nivel = ctx.falhar if hoje.day >= dia_limite else ctx.avisar
        nivel(
            f"{ctx.cfg.diario.pasta}/{mes}.md não existe — rotação pendente. "
            f"`git mv {ctx.cfg.diario.pasta}/AAAA-MM*.md {ctx.cfg.diario.pasta}/arquivo/`, "
            f"crie `{ctx.cfg.diario.pasta}/{mes}.md` com o cabeçalho e atualize o ponteiro "
            f"do CLAUDE.md"
        )
    else:
        for arq in candidatos:
            texto = arq.read_text(encoding="utf-8")
            n = len(texto.splitlines())
            if n > ctx.cfg.diario.teto_linhas:
                # A remediação vem de `diario.remediacao_do_teto` porque no décimo arquivo
                # do mês não existe "próximo sufixo": com os 10 no teto, esta falha mandava
                # fechar e abrir um arquivo que `caminho_mes` não sabe gerar. Uma frase, um
                # lugar — a mesma que o `anexar_entrada` imprime.
                ctx.falhar(
                    f"{ctx.cfg.diario.pasta}/{arq.name} tem {n} linhas "
                    f"(teto {ctx.cfg.diario.teto_linhas}) — "
                    f"{remediacao_do_teto(ctx.cfg.diario, arq)}"
                )
            # Data fora do mês do arquivo é cobrada sobre o texto INTEIRO, cerca de código
            # inclusive, e isso é deliberado: `diario._FRONTEIRA_ENTRADA` não conhece cerca,
            # então um `## 2026-01-15` dentro de ```markdown É fronteira de entrada para o
            # mecanismo e a reinjeção parte ali. Ignorar a cerca aqui deixaria o auditor
            # cego para um corte que acontece de verdade.
            for data in re.findall(r"^## (\d{4}-\d{2}-\d{2})", texto, flags=re.MULTILINE):
                if not data.startswith(mes):
                    ctx.falhar(
                        f"{ctx.cfg.diario.pasta}/{arq.name} contém entrada de {data}, "
                        f"fora do mês do arquivo"
                    )
            # `## ` SEM data, ao contrário, é cobrada só FORA de cerca — dentro dela o
            # cabeçalho não é fronteira nem para o mecanismo nem para quem lê, e reprovar um
            # exemplo de formato seria falso positivo (princípio 9).
            #
            # O cheque existe porque `_FRONTEIRA_ENTRADA` passou a exigir `## AAAA-MM-DD`:
            # partir por `^## ` cru partia a entrada no exemplo de formato dentro de cerca
            # (411 ch de entrada voltavam como 237, começando na data placeholder). O custo
            # dessa exigência é que `## Sessão de terça` deixa de abrir entrada e o texto
            # entra colado na anterior, em silêncio, se nada reprovar. Não é convenção nova:
            # o regex de `auditar_ordem_do_diario` já exigia a data — só não denunciava.
            for titulo in re.findall(
                r"^## (?!\d{4}-\d{2}-\d{2})(.+)$", _fora_de_cerca(texto), flags=re.MULTILINE
            ):
                ctx.falhar(
                    f"{ctx.cfg.diario.pasta}/{arq.name}: cabeçalho `## {titulo.strip()}` sem "
                    f"data — entrada abre com `## AAAA-MM-DD`. Sem a data ela não é fronteira "
                    f"de entrada e o texto vai para o contexto colado na entrada anterior"
                )

    if not (pasta / "README.md").exists():
        ctx.falhar(f"{ctx.cfg.diario.pasta}/README.md (regras do diário) não existe")

    auditar_ordem_do_diario(ctx)


def auditar_ordem_do_diario(ctx: Contexto) -> None:
    """Entradas em ordem CRONOLÓGICA dentro do arquivo — a mais nova no fim.

    Não é preferência de estilo: `diario.ultima_entrada` pega o último bloco
    `## AAAA-MM-DD` do arquivo. Num diário escrito do mais recente para o mais antigo — que
    é uma convenção perfeitamente razoável e era a do ValidaNI — isso injeta a entrada MAIS
    VELHA no início de cada sessão, calado. O digest de becos sem saída sofre do mesmo: ele
    inverte a lista assumindo cronologia, então o orçamento é gasto pelos itens mais antigos.

    Duas convenções não podem coexistir sem que o leitor saiba qual está lendo; esta é a
    que o mecanismo assume, e aqui ela é verificada.
    """
    for arq in arquivos_do_diario(ctx.cfg.pasta_diario):
        try:
            texto = arq.read_text(encoding="utf-8")
        except OSError:
            continue
        datas = re.findall(r"^## (\d{4}-\d{2}-\d{2})", texto, flags=re.MULTILINE)
        if len(datas) < 2:
            continue
        if datas != sorted(datas):
            ordenado_ao_contrario = datas == sorted(datas, reverse=True)
            ctx.falhar(
                f"{ctx.rel(arq)}: entradas fora de ordem cronológica"
                + (
                    " — o arquivo está do mais RECENTE para o mais antigo. A reinjeção do "
                    "início da sessão pega o ÚLTIMO bloco do arquivo, então nesta ordem ela "
                    "injeta a entrada mais velha. Inverta a ordem das entradas."
                    if ordenado_ao_contrario
                    else f" ({datas[0]} … {datas[-1]}) — a mais nova vai no fim."
                )
            )


# --------------------------------------------------------------------------- #
# CLAUDE.md, invioláveis e ponteiros
# --------------------------------------------------------------------------- #


def auditar_claude_md(ctx: Contexto) -> None:
    p = ctx.raiz / "CLAUDE.md"
    if not p.exists():
        ctx.falhar("CLAUDE.md não existe")
        return
    texto = p.read_text(encoding="utf-8")
    n = len(texto.splitlines())
    teto = ctx.cfg.auditoria.teto_claude_md
    if n > teto:
        ctx.falhar(
            f"CLAUDE.md tem {n} linhas (teto {teto}) — mova conteúdo para ADR ou docs/. "
            f"Arquivo de instrução que cresce é Context Bloat, e o custo é pago em toda sessão"
        )

    # Os dois cheques abaixo olham o texto FORA de cerca. Medido num CLAUDE.md correto: um
    # bloco ```markdown que documenta o formato do mapa caminho→ADR gerava falha de link
    # quebrado, e reprovar o build por documentação correta é o pior defeito que um auditor
    # pode ter — ele ensina a ignorar os outros cheques (princípio 9). O gatilho é
    # provável justamente neste harness, cujo CLAUDE.md documenta formatos com exemplos.
    # Vale igual para o ponteiro do mês: exemplo dentro de cerca não é ponteiro.
    texto_util = _fora_de_cerca(texto)

    hoje = datetime.now()
    mes = hoje.strftime("%Y-%m")
    ponteiro = f"{ctx.cfg.diario.pasta}/{mes}.md"
    if ponteiro not in texto_util:
        # Ponteiro defasado não é cosmético: aponta para arquivo cujo head ficou atrás, e o
        # agente que segue o ponteiro em vez da injeção perde o mês inteiro.
        nivel = ctx.falhar if hoje.day >= ctx.cfg.diario.dia_limite_rotacao else ctx.avisar
        nivel(
            f"CLAUDE.md não aponta para o diário do mês corrente (`{ponteiro}`) — "
            f"atualize o ponteiro"
        )

    for alvo in re.findall(r"\]\(((?!https?://|#|mailto:)[^)]+)\)", texto_util):
        # `[texto](caminho "Título")` é sintaxe válida de markdown e o título NÃO faz parte
        # do caminho. Sem cortá-lo, `docs/guia.md "O guia"` reprovava com o arquivo em
        # disco — segundo falso positivo do mesmo cheque, medido no mesmo arquivo.
        partes = alvo.split()
        caminho = partes[0].split("#")[0] if partes else ""
        if caminho and not (ctx.raiz / caminho).exists():
            ctx.falhar(f"CLAUDE.md aponta para `{caminho}`, que não existe")


def auditar_invioaveis(ctx: Contexto) -> None:
    """A seção de invioláveis existe, tem itens, e cada item cabe em uma linha.

    Este cheque é o que torna "política como dado" seguro. A reafirmação intra-sessão e o
    aviso pós-compactação EXTRAEM a primeira frase de cada item; se a seção não existe, os
    dois emudecem sem avisar, e um harness que silenciosamente não reafirma nada é pior que
    nenhum — porque quem o instalou acha que está protegido.

    Item longo não é truncado, é reprovado: meia proibição lê como permissão.

    Audita a SEÇÃO, não a mensagem: a extração aqui é feita sem `max_itens` — o contrato
    está no docstring de `config.invioaveis` — porque o corte é orçamento da reafirmação e
    auditar o recorte seria auditar o que já cabe. Medido: um CLAUDE.md com 8 itens curtos
    e um 9º de 218 chars passava sem UMA LINHA de aviso, porque o 9º nunca chegava ao
    cheque de teto. Perdia duas vezes — a regra não é reafirmada e o teto por item deixa de
    existir a partir do 9º —, e em silêncio, ao contrário do índice de ADR, que se anuncia
    PARCIAL quando corta (princípio 11).
    """
    r = ctx.cfg.reafirmacao
    if not r.habilitado:
        return
    p = ctx.raiz / "CLAUDE.md"
    if not p.exists():
        return

    regras = invioaveis(ctx.raiz, replace(r, max_itens=10**6))
    if not regras:
        alvo = f"'{r.secao}'" + (f", sub-bloco '{r.sub_bloco}'" if r.sub_bloco else "")
        ctx.falhar(
            f"CLAUDE.md: não achei nenhuma inviolável em {alvo} — a reafirmação "
            f"intra-sessão e o aviso pós-compactação ficam MUDOS. Crie a seção com uma "
            f"lista, ou desligue com `reafirmacao.habilitado: false` no harness.json"
        )
        return

    for regra in regras:
        if len(regra) > r.teto_item_chars:
            ctx.falhar(
                f"CLAUDE.md, invioláveis: item com {len(regra)} chars "
                f'(teto {r.teto_item_chars}): "{regra[:60]}…" — encurte a PRIMEIRA FRASE. '
                f"O resto do raciocínio continua no item; só a primeira frase entra na "
                f"reafirmação, e ela precisa caber em uma linha para ser lida"
            )

    if len(regras) > r.max_itens:
        ctx.falhar(
            f"CLAUDE.md: a seção de invioláveis tem {len(regras)} itens e a reafirmação "
            f"leva {r.max_itens} — os {len(regras) - r.max_itens} do fim NÃO são "
            f"reafirmados, e o corte não se anuncia. Tire da seção o que não é proibição "
            f"absoluta, ou suba `reafirmacao.max_itens` no harness.json assumindo a "
            f"mensagem mais longa em toda escrita. Nos três corpora medidos a seção tem 6, "
            f"7 e 7 itens"
        )


def auditar_harness(ctx: Contexto) -> None:
    """Os hooks e scripts referenciados em `.claude/settings.json` existem."""
    cfg_path = ctx.raiz / ".claude" / "settings.json"
    if not cfg_path.exists():
        return
    texto = cfg_path.read_text(encoding="utf-8")
    for alvo in re.findall(r"\$\{CLAUDE_PROJECT_DIR\}[/\\]([^\"]+)", texto):
        if not (ctx.raiz / alvo.replace("\\", "/")).exists():
            ctx.falhar(f".claude/settings.json referencia `{alvo}`, que não existe")


def auditar_skill_de_encerramento(ctx: Contexto) -> None:
    """Se o projeto declara um comando próprio de fechamento, ele tem de existir.

    O `/encerrar-sessao` do plugin cede a vez para esse comando. Se o nome estiver errado ou
    o arquivo tiver sido renomeado, a cessão manda para o vazio: o usuário recebe "use
    `/handoff`" e o `/handoff` não existe mais. Ponteiro velho, de novo.

    **Aviso, não falha** — e a razão é honesta: o harness vê os arquivos do projeto, não as
    skills que outros plugins fornecem. Um nome legítimo vindo de plugin não estaria em
    `.claude/`, e reprovar o build nesse caso seria um falso positivo sem ação possível.
    Aviso surfaceia sem bloquear.
    """
    nome = ctx.cfg.diario.skill_de_encerramento
    if not nome:
        return
    limpo = nome.strip().lstrip("/")
    candidatos = [
        ctx.raiz / ".claude" / "commands" / f"{limpo}.md",
        ctx.raiz / ".claude" / "skills" / limpo / "SKILL.md",
    ]
    if any(p.exists() for p in candidatos):
        return
    onde = " ou ".join(f"`{ctx.rel(p)}`" for p in candidatos)
    ctx.avisar(
        f"`diario.skill_de_encerramento` aponta para `{nome}`, que não achei em {onde}. "
        f"Se vem de um plugin, ignore; se era um arquivo do projeto, o nome mudou e o "
        f"`/encerrar-sessao` vai mandar o usuário para um comando que não existe."
    )


#: A consequência CONCRETA de cada chave que falta, porque é ela que separa este cheque de
#: um validador de schema: "chave ausente" não diz o que se perde, e o que se perde aqui é
#: uma guarda inteira.
_SEM_ALVO = (
    "`guardar.py` descarta num `continue` calado a regra que não declara o próprio alvo, "
    "então a guarda existe na config e não bloqueia nada — e não há nem chave errada para "
    "procurar"
)
_CONSEQUENCIA_DE_CHAVE: dict[str, str] = {
    "padrao": _SEM_ALVO,
    "regex": _SEM_ALVO,
    "exemplo": (
        "`guardar.py --autoteste` gera o caso positivo dentro de um `if exemplo`, então a "
        "regra não é exercitada em lugar nenhum e o autoteste imprime aprovação sobre uma "
        "regex que pode estar quebrada"
    ),
}


#: `permitido_em` que termina em extensão de arquivo. Uma extensão é 1 a 5 caracteres sem
#: barra depois do último ponto do último segmento — larga o bastante para pegar `.xlsx` e
#: estreita para não acusar `v1.2` nem um diretório chamado `dados.brutos`. Barra final é o
#: sinal explícito de diretório e passa sempre.
_PARECE_ARQUIVO = re.compile(r"[^/\\]\.[A-Za-z0-9]{1,5}$")


def auditar_guardas(ctx: Contexto) -> None:
    """Toda regra de guarda declara as chaves sem as quais ela não age, e `permitido_em`
    aponta para um diretório.

    Este cheque mora aqui, e não em `carregar()`, por causa do SINAL. Chave desconhecida
    numa regra continua lançando `ErroDeConfig` na leitura — não tem interpretação válida
    nenhuma e aparece na hora em que alguém escreve a config. Chave obrigatória AUSENTE é
    outra coisa: produz uma config que faz parse e funciona, só com uma regra que não age.
    Lançar por isso significava `_comum.contexto` engolindo o erro e deixando os SEIS
    hooks inertes — sem reinjeção, sem reafirmação e sem a guarda de `.env` — no consumidor
    que só atualizou o plugin, com o aviso indo para um stderr que ninguém lê. Reprovar o
    build é proporcional; desligar o harness em cima de uma config que funcionava não é.

    A seção `guardas` era o ponto cego do auditor: até aqui `grep guardas` neste módulo
    dava zero linhas, e `carregar()` era o único lugar que podia pegar qualquer coisa dela.

    O cheque de `permitido_em` fecha o outro lado do mesmo ponto cego. A troca de
    substring por fronteira de caminho em `guardar._sob_prefixo` corrigiu um furo real
    (`tests/fixtures` liberava `tests/fixtures_antigos/`) e, no mesmo commit e em
    silêncio, mudou de liberado para BLOQUEADO o `permitido_em` que aponta a um arquivo
    específico — porque a fronteira exige algo depois do último segmento, e um arquivo
    não tem nada depois de si. Achado do revisor. Config que afirma uma exceção que o
    hook nega é a mesma classe de `_CHAVES_DE_REGRA`, e o lugar de acusar é aqui.
    """
    for secao, obrigatorias in CHAVES_OBRIGATORIAS_DE_REGRA.items():
        for i, regra in enumerate(getattr(ctx.cfg.guardas, secao)):
            if not isinstance(regra, dict):
                continue  # `carregar()` já reprovou: regra que não é objeto nem chega aqui
            ident = str(regra.get("padrao") or regra.get("regex") or "").strip()
            onde = f"`guardas.{secao}[{i}]`" + (f", `{ident}`" if ident else "")
            for chave in obrigatorias:
                if str(regra.get(chave) or "").strip():
                    continue
                ctx.falhar(
                    f"{ctx.rel(caminho_config(ctx.raiz))}: {onde} não declara `{chave}` — "
                    f"{_CONSEQUENCIA_DE_CHAVE[chave]}"
                )
            for alvo in tuple(regra.get("permitido_em") or ()):
                if _PARECE_ARQUIVO.search(str(alvo)):
                    ctx.falhar(
                        f"{ctx.rel(caminho_config(ctx.raiz))}: {onde} tem "
                        f'`permitido_em: ["{alvo}"]`, que parece um ARQUIVO — o prefixo é '
                        f"sempre um diretório, e apontá-lo a um arquivo NÃO libera aquele "
                        f"arquivo: bloqueia. Escreva o diretório que o contém."
                    )


def auditar_config_versionada(ctx: Contexto) -> None:
    """O `harness.json` não pode estar no `.gitignore`.

    A presença desse arquivo é o gate do harness. Se ele fica de fora do versionamento, o
    projeto passa a ter dois comportamentos: na máquina de quem o criou, o harness funciona;
    em qualquer checkout novo — o runner do CI, outra máquina, outra pessoa — os seis hooks
    ficam **silenciosamente** inertes e a auditoria reprova acusando que o projeto nunca
    adotou o harness. Diagnóstico enganoso, e o pior modo de falha que este desenho tem.

    Aconteceu na primeira instalação real: o `.gitignore` do ValidaNI é `.claude/*` com
    exceções nomeadas uma a uma, e `harness.json` não estava entre elas. Passou por
    aprovado — a auditoria roda com o arquivo em disco, e em disco ele estava lá.
    """
    alvo = caminho_config(ctx.raiz)
    if not alvo.exists() or not (ctx.raiz / ".git").exists():
        return
    try:
        r = subprocess.run(
            ["git", "-C", str(ctx.raiz), "check-ignore", "-q", str(alvo)],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return  # sem git usável: não é motivo para reprovar
    if r.returncode == 0:
        rel = ctx.rel(alvo)
        ctx.falhar(
            f"`{rel}` está no .gitignore, mas é o GATE do harness — sem ele versionado, "
            f"todo checkout novo (o CI inclusive) fica com os hooks inertes em silêncio e a "
            f"auditoria acusa que o projeto não adotou o harness. Se o .gitignore usa "
            f"`.claude/*` com exceções, adicione `!{rel}`."
        )


#: Caminho de script citado em prosa ou dentro de bloco de código, COM o prefixo de
#: diretório quando houver. O `(?:[\w.-]+/)*` é o que estava faltando: com `\bscripts/…` a
#: primeira instalação real reprovou `python apps/web/scripts/gen-pwa-icons.py` — o `\b`
#: casava depois da barra de `apps/web/`, o prefixo era descartado e o auditor procurava
#: `scripts/gen-pwa-icons.py` na raiz. Falso positivo é pior que cheque ausente: ele ensina
#: a ignorar o auditor.
#: O lookbehind garante que o casamento começa numa fronteira de caminho, e não no meio.
_SCRIPT_CITADO = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*scripts/[\w./-]+\.(?:py|mjs|sh|ts))")


def auditar_scripts_citados(ctx: Contexto) -> None:
    """Todo script citado num arquivo operacional existe.

    Checador de link markdown só vê link; comando dentro de bloco de código passava batido.
    Um script renomeado deixaria uma instrução que só falha quando alguém tenta executá-la —
    e a instrução que falha na primeira tentativa é a que faz o leitor desconfiar das outras.
    """
    for p in ctx.fontes_operacionais():
        try:
            texto = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for alvo in sorted(set(_SCRIPT_CITADO.findall(texto))):
            if not (ctx.raiz / alvo).exists():
                ctx.falhar(f"{ctx.rel(p)} cita `{alvo}`, que não existe")


def auditar_coerencia_readme_claude(ctx: Contexto) -> None:
    """README.md e CLAUDE.md não podem discordar sobre o mesmo fato.

    A repetição entre os dois não é acidente: descrevem o mesmo projeto para leitores
    diferentes. O que era acidente é ela não ser checada — no projeto de origem a referência
    da política de PII divergiu de verdade, com o README apontando o ADR novo e o CLAUDE.md
    ainda o substituído. O que sobrevive duplicado passa a ser comparado por máquina, não
    por disciplina.
    """
    readme, claude = ctx.raiz / "README.md", ctx.raiz / "CLAUDE.md"
    if not (readme.exists() and claude.exists()):
        return
    t_readme = readme.read_text(encoding="utf-8")
    t_claude = claude.read_text(encoding="utf-8")

    for fato in ctx.cfg.auditoria.fatos_compartilhados:
        rotulo, padrao = str(fato.get("rotulo") or "?"), str(fato.get("regex") or "")
        if not padrao:
            continue
        try:
            no_readme = set(re.findall(padrao, t_readme))
            no_claude = set(re.findall(padrao, t_claude))
        except re.error as e:
            ctx.falhar(f"auditoria.fatos_compartilhados: regex inválida `{padrao}` ({e})")
            continue
        if no_readme and no_claude and no_readme != no_claude:
            ctx.falhar(
                f"README.md e CLAUDE.md discordam sobre {rotulo}: "
                f"README diz {sorted(no_readme)}, CLAUDE.md diz {sorted(no_claude)}"
            )


# --------------------------------------------------------------------------- #
# Orquestração
# --------------------------------------------------------------------------- #

CHECKS_GENERICOS = (
    auditar_adrs,
    auditar_conformidade_com_template,
    auditar_referencias_a_adr_morto,
    auditar_mapa_de_adr_por_caminho,
    auditar_indice_por_dominio,
    auditar_coerencia_readme_claude,
    auditar_contagem_de_adr_no_readme,
    auditar_scripts_citados,
    auditar_diario,
    auditar_claude_md,
    auditar_invioaveis,
    auditar_harness,
    auditar_skill_de_encerramento,
    auditar_guardas,
    auditar_config_versionada,
)


def rodar(ctx: Contexto) -> None:
    """Roda os checks genéricos e, depois, os do projeto."""
    for check in CHECKS_GENERICOS:
        try:
            check(ctx)
        except Exception as e:  # noqa: BLE001
            # Um check que explode não deve esconder o resultado dos outros — mas também
            # não passa como verde: entra como falha nomeada.
            ctx.falhar(f"o check `{check.__name__}` levantou {type(e).__name__}: {e}")

    alvo = ctx.cfg.auditoria.checks_do_projeto
    if not alvo:
        return
    caminho = ctx.raiz / alvo
    if not caminho.exists():
        ctx.falhar(
            f"auditoria.checks_do_projeto aponta para `{alvo}`, que não existe — "
            f"os cheques de fronteira do projeto NÃO rodaram"
        )
        return
    try:
        spec = importlib.util.spec_from_file_location("harness_checks_do_projeto", caminho)
        if spec is None or spec.loader is None:
            raise ImportError(f"não consegui carregar {alvo}")
        modulo = importlib.util.module_from_spec(spec)
        sys.modules["harness_checks_do_projeto"] = modulo
        spec.loader.exec_module(modulo)
        registrar = getattr(modulo, "registrar", None)
        if registrar is None:
            ctx.falhar(f"`{alvo}` não expõe `registrar(ctx)` — nenhum cheque do projeto rodou")
            return
        registrar(ctx)
    except Exception as e:  # noqa: BLE001
        ctx.falhar(f"`{alvo}` falhou ao rodar: {type(e).__name__}: {e}")


def relatar(ctx: Contexto, silencioso: bool = False) -> int:
    if ctx.avisos and not silencioso:
        print(f"\n{len(ctx.avisos)} aviso(s):")
        for a in ctx.avisos:
            print(f"  · {a}")

    if ctx.falhas:
        print(f"\n{len(ctx.falhas)} FALHA(S):")
        for f in ctx.falhas:
            print(f"  x {f}")
        print("\nAuditoria reprovada.")
        return 1

    if not silencioso:
        total = len(ctx.adrs)
        print(
            f"\nAuditoria aprovada — {total} ADR(s), índice sincronizado, diário dentro do "
            f"teto e em ordem, invioláveis extraíveis, fronteiras íntegras."
        )
    return 0


__all__ = [
    "CHECKS_GENERICOS",
    "Contexto",
    "ler_frontmatter",
    "relatar",
    "rodar",
    "SECAO_BECOS",
]
