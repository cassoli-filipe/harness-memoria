"""Índice de ADR: leitura do frontmatter, status, supersessão e linhas para injeção.

Mudança de desenho em relação ao original
-----------------------------------------
No rede_inspira_app o índice injetado era extraído por regex da TABELA de
`docs/adr/README.md`, o que amarrava a reinjeção à ordem das colunas de um markdown
escrito à mão. Aqui o índice é derivado dos **arquivos de ADR** — frontmatter para status
e supersessão, primeira linha `#` para o título. O README continua obrigatório e continua
auditado (todo ADR tem de estar listado nele), mas deixa de ser fonte de verdade para o
que chega ao contexto: a fonte é o ADR.

Isso removeu duas coisas: um acoplamento a formato de tabela — que já ia dar trabalho na
migração do segundo projeto, cuja tabela nem existia — e a possibilidade de o índice
injetado discordar dos arquivos sem nada acusar.

Somente biblioteca padrão.
"""

from __future__ import annotations

import re
from pathlib import Path

STATUS_VALIDOS = {"proposed", "accepted", "implemented", "superseded", "deprecated"}
STATUS_MORTOS = {"superseded", "deprecated"}

#: Vocabulário em pt-BR aceito na migração de um corpus existente, normalizado na leitura.
#: Os 22 ADRs do ValidaNI nasceram com "aceito"; reescrever 22 corpos para trocar uma
#: palavra do cabeçalho seria pior que aceitar as duas grafias aqui.
_SINONIMOS_STATUS = {
    "aceito": "accepted",
    "aceita": "accepted",
    "proposto": "proposed",
    "proposta": "proposed",
    "implementado": "implemented",
    "implementada": "implemented",
    "substituido": "superseded",
    "substituído": "superseded",
    "substituida": "superseded",
    "substituída": "superseded",
    "depreciado": "deprecated",
    "depreciada": "deprecated",
}

#: Aceita `# ADR-0022 — x` e `# ADR 0022 — x`. Dois projetos, duas grafias, nenhuma
#: melhor que a outra — e um cheque que reprovasse uma delas só geraria 22 edições de
#: cabeçalho sem ganho de informação.
_TITULO = re.compile(r"^#\s*ADR[-\s](\d{4})\s*[—\-–:]?\s*(.*)$", re.MULTILINE)


def arquivos_adr(pasta: Path) -> list[Path]:
    if not pasta.exists():
        return []
    return sorted(pasta.glob("[0-9][0-9][0-9][0-9]-*.md"))


def ler_frontmatter(texto: str) -> dict[str, str]:
    """Campos do frontmatter YAML. `{}` se não houver — não é erro aqui, é dado."""
    if not texto.startswith("---"):
        return {}
    fim = texto.find("\n---", 3)
    if fim == -1:
        return {}
    campos: dict[str, str] = {}
    for linha in texto[3:fim].splitlines():
        m = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", linha.strip())
        if m:
            campos[m.group(1).lower()] = m.group(2).strip()
    return campos


def normalizar_status(bruto: str) -> str:
    """Status canônico em inglês, aceitando o vocabulário pt-BR de corpus migrado."""
    s = bruto.split("#")[0].strip().strip("`*").lower()
    return _SINONIMOS_STATUS.get(s, s)


def titulo_de(texto: str, num: str) -> str:
    """Título do ADR, do cabeçalho `# ADR-NNNN — …`. Vazio se não achar."""
    for m in _TITULO.finditer(texto):
        if m.group(1) == num:
            return m.group(2).strip().rstrip(".")
    return ""


def dados_dos_adrs(pasta: Path) -> dict[str, dict]:
    """`{'0007': {'status':..., 'titulo':..., 'substituido_por': [...], 'substitui': [...]}}`.

    Uma leitura por arquivo, reusada por todos os consumidores (injeção e auditoria).
    """
    saida: dict[str, dict] = {}
    for f in arquivos_adr(pasta):
        num = f.name[:4]
        try:
            texto = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = ler_frontmatter(texto)
        saida[num] = {
            "arquivo": f,
            "status": normalizar_status(fm.get("status", "")),
            "status_bruto": fm.get("status", ""),
            "data": fm.get("data", "").split("#")[0].strip(),
            "titulo": titulo_de(texto, num) or fm.get("titulo", ""),
            "substituido_por": re.findall(r"(\d{4})", fm.get("substituido-por", "")),
            "substitui": re.findall(r"(\d{4})", fm.get("substitui", "")),
            # Emenda é o meio-termo entre "vale inteiro" e "não siga": um ADR novo muda UMA
            # das decisões de um ADR de várias. Marcar o antigo como `superseded` mentiria
            # sobre as outras; não marcar nada deixaria quem lê a decisão revogada achando
            # que ela vale. Os dois casos que criaram isto: a decisão 3 da 0014 do ValidaNI,
            # e as quatro ADRs de harness do rede_inspira_app, cujo mecanismo saiu do repo
            # sem que nenhuma delas fosse revertida.
            "emenda": re.findall(r"(\d{4})", fm.get("emenda", "")),
            "emendado_por": re.findall(r"(\d{4})", fm.get("emendado-por", "")),
            "texto": texto,
        }
    return saida


def indice_para_injecao(pasta: Path, limite: int | None = None) -> list[str]:
    """Linhas do índice de ADR para reinjeção no início da sessão.

    **Sem limite por padrão.** Um limite de 20 escondia 9 dos 29 ADRs do projeto de origem
    em silêncio, enquanto o bloco injetado se anunciava como o índice das decisões
    vigentes: o agente não tinha como saber que faltava algo, nem gatilho para abrir o
    índice real. Entre os cortados estava justamente o ADR que substituía a política de
    PII — o bloco exibia `[superseded]` e escondia o que seguir no lugar.

    ADR `superseded` sai com o substituto em linha, para o bloco ser autossuficiente.
    Quem passar `limite` é responsável por anunciar o corte — ver `anunciar_corte`.
    Truncar em silêncio é pior que truncar avisando: o aviso cria gatilho de leitura.

    **Uma linha por ADR, sempre.** Quem INJETA usa `indice_compactado`, que agrega os
    aposentados; esta função é a lista canônica de "todo ADR que tem de estar nomeado no
    bloco", e é assim que `conferir_fidelidade` a usa. Manter as duas é deliberado: se a
    conferência olhasse a mesma lista compactada que a montagem produziu, ela concordaria
    consigo mesma por construção.
    """
    dados = dados_dos_adrs(pasta)
    linhas: list[str] = []
    for num in sorted(dados):
        d = dados[num]
        status = d["status"] or "(sem status)"
        if status in STATUS_MORTOS and d["substituido_por"]:
            substitutos = ", ".join(f"ADR-{s}" for s in d["substituido_por"])
            status = f"{status} → siga {substitutos}"
        linhas.append(f"ADR-{num} [{status}] {d['titulo']}".rstrip())
    return linhas if limite is None else linhas[:limite]


#: Prefixo das linhas agregadas de ADR aposentado. É público porque quem monta o bloco
#: precisa saber se ela está lá para não repetir, em prosa, o que ela já diz — ver o rodapé
#: em `hooks/session_start.py`.
PREFIXO_APOSENTADOS = "Aposentados"

_AGREGADO_COM_SUBSTITUTO = f"{PREFIXO_APOSENTADOS}, NÃO siga — substituto ao lado: "
_AGREGADO_SEM_SUBSTITUTO = f"{PREFIXO_APOSENTADOS} (sem substituto declarado), NÃO siga: "

#: Custo que o bloco do `SessionStart` acrescenta a cada linha: o `- ` na frente e o `\n`
#: que a junta à seguinte. O orçamento em chars é conferido AQUI, onde se sabe qual linha
#: entra, e não no texto já montado: fatiar o texto montado cortaria o índice DEPOIS do
#: cabeçalho que diz "índice completo, 67 ADRs", produzindo o falso completo que
#: `conferir_fidelidade` existe justamente para pegar.
_CUSTO_DE_LINHA = len("- ") + len("\n")


def indice_compactado(
    pasta: Path, limite: int | None = None, teto_chars: int | None = None
) -> tuple[list[str], int, int]:
    """`(linhas, total_de_adrs, adrs_nomeados)` — o índice com os APOSENTADOS agregados.

    Os mortos saem em UMA linha (duas, quando há morto sem substituto), porque a linha
    inteira deles é gordura constante: medido em corpus de 30 ADRs com 7 mortos, as 7 linhas
    completas somam 690 ch (27% do índice) contra 178 ch da linha agregada — 512 ch (~146
    tokens) economizados por disparo, independentemente do tamanho do corpus, **sem esconder
    um único número de ADR**. O token `ADR-0005` sobrevive dentro de `ADR-0005→ADR-0019`,
    então o cheque 1 de `conferir_fidelidade` (`linha.split(maxsplit=1)[0]`) continua vendo
    todos.

    Duas fatias e não uma: morto SEM substituto vai em linha própria, com o mesmo texto
    "(sem substituto declarado)" que o auditor já usa. A agregação óbvia
    (`f"ADR-{n}→ADR-{subs[0]}"`) estouraria com `IndexError` nesse caso e, se protegida por
    um `if` distraído, sumiria com o ADR de um bloco que se declara completo — que é o
    defeito que esta função existe para não introduzir. `deprecated` é exatamente o status
    de quem não tem sucessor, e ele passou a ser legal na auditoria.

    `limite` (contagem, de `adr.limite_indice`) e `teto_chars` (orçamento calculado em
    `montar`) cortam só os VIVOS: os aposentados são orçados primeiro porque custam ~18 ch
    por ADR contra 110-120 ch da linha viva, e "não siga isto" é o que sai mais caro
    esquecer. `adrs_nomeados` conta os ADRs cujo número chegou ao texto — é ele, não
    `len(linhas)`, que diz se o índice é completo, e é ele que alimenta `anunciar_corte`.
    """
    dados = dados_dos_adrs(pasta)
    vivos: list[str] = []
    com_substituto: list[str] = []
    sem_substituto: list[str] = []
    for num in sorted(dados):
        d = dados[num]
        status = d["status"] or "(sem status)"
        if status in STATUS_MORTOS:
            if d["substituido_por"]:
                # `/` entre substitutos porque a vírgula já separa os PARES na linha.
                alvo = "/".join(f"ADR-{s}" for s in d["substituido_por"])
                com_substituto.append(f"ADR-{num}→{alvo}")
            else:
                sem_substituto.append(f"ADR-{num}")
            continue
        vivos.append(f"ADR-{num} [{status}] {d['titulo']}".rstrip())

    if limite is not None:
        vivos = vivos[:limite]

    agregadas = [
        (_AGREGADO_COM_SUBSTITUTO + ", ".join(com_substituto), len(com_substituto)),
        (_AGREGADO_SEM_SUBSTITUTO + ", ".join(sem_substituto), len(sem_substituto)),
    ]
    linhas_agregadas: list[str] = []
    nomeados = 0
    gasto = 0
    for linha, quantos in agregadas:
        if not quantos:
            continue
        if teto_chars is not None and gasto + len(linha) + _CUSTO_DE_LINHA > teto_chars:
            # Não cabe: os ADRs dela contam como NÃO nomeados e o bloco se declara PARCIAL.
            continue
        linhas_agregadas.append(linha)
        nomeados += quantos
        gasto += len(linha) + _CUSTO_DE_LINHA

    dentro: list[str] = []
    for linha in vivos:
        if teto_chars is not None and gasto + len(linha) + _CUSTO_DE_LINHA > teto_chars:
            break  # prefixo, não peneira: cortar do meio produziria uma lista arbitrária
        dentro.append(linha)
        nomeados += 1
        gasto += len(linha) + _CUSTO_DE_LINHA

    return dentro + linhas_agregadas, len(dados), nomeados


def anunciar_corte(total: int, injetadas: int, onde: str) -> str:
    """Nota obrigatória quando o índice não vai inteiro para o contexto."""
    if injetadas >= total:
        return ""
    return (
        f"\n\n**Atenção: este índice está cortado** — {injetadas} de {total} ADRs. "
        f"Abra `{onde}` para os {total - injetadas} restantes."
    )


def adrs_tocados(arquivos: list[str], pasta_adr: Path, raiz: Path) -> list[str]:
    """IDs de ADR entre os arquivos escritos numa sessão, na ordem em que apareceram."""
    try:
        prefixo = pasta_adr.relative_to(raiz).as_posix()
    except ValueError:
        prefixo = "docs/adr"
    padrao = re.compile(rf"{re.escape(prefixo)}/(\d{{4}})-")
    ids: list[str] = []
    for a in arquivos:
        m = padrao.search(a.replace("\\", "/"))
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return [f"ADR-{i}" for i in ids]


# --------------------------------------------------------------------------- #
# Mapa "Qual ADR ler" por caminho (ADR-0009)
# --------------------------------------------------------------------------- #

#: Sem `## Regra`, a `## Decisão` entra INTEIRA até este tamanho; acima, só o ponteiro.
#: Medido em 2026-10-09: aqui as decisões têm de 381 a 2.016 ch (8 de 9 cabem); no ValidaNI,
#: de 512 a 21.487 ch (19 de 93 cabem), mas 71 dos 93 têm `## Regra`.
TETO_DECISAO_CHARS = 1_500

#: O bloco inteiro de uma escrita. Abaixo do teto de 10.000 ch da plataforma (ADR-0004) com
#: folga, porque ele chega junto de um resultado de ferramenta, não sozinho.
TETO_ADRS_POR_CAMINHO_CHARS = 6_000

#: Acima disto, o auditor avisa que a linha do mapa é grossa demais. Um bloco de
#: `TETO_ADRS_POR_CAMINHO_CHARS` entrega de 4 a 9 ADRs por escrita nos corpora medidos, então
#: uma linha maior só chega inteira depois de várias escritas no caminho. Medido no ValidaNI
#: em 2026-10-09: `apps/web/src/` aponta 58 ADRs e levaria 10 escritas (~55 mil ch).
MAX_ADRS_POR_LINHA_DO_MAPA = 10

_SECAO_DO_MAPA = re.compile(
    r"^#{2,4} Qual ADR ler.*?\n(.*?)(?=^#{2,4} |\Z)", re.MULTILINE | re.DOTALL
)


def mapa_por_caminho(texto_claude_md: str) -> list[tuple[list[str], list[str]]] | None:
    """`[(caminhos, números de ADR)]`, uma tupla por linha útil do mapa; `None` sem a seção.

    Um parser só, para os dois leitores: o auditor, que confere que o mapa aponta para o que
    existe, e o `PreToolUse`, que entrega os ADRs na escrita. Dois parsers divergiriam na
    primeira correção, e o mapa que o auditor aprova passaria a não ser o mapa que o hook lê.
    Só tokens de 4 dígitos contam como número: `0005–0008` vira 0005 e 0008.
    """
    m = _SECAO_DO_MAPA.search(texto_claude_md)
    if not m:
        return None
    saida: list[tuple[list[str], list[str]]] = []
    for linha in m.group(1).splitlines():
        if not linha.startswith("|") or set(linha) <= set("|- "):
            continue
        colunas = [c.strip() for c in linha.strip("|").split("|")]
        if len(colunas) < 2 or colunas[0].lower() == "caminho":
            continue
        saida.append((re.findall(r"`([^`]+)`", colunas[0]), re.findall(r"\b(\d{4})\b", colunas[1])))
    return saida


def adrs_do_caminho(mapa: list[tuple[list[str], list[str]]], rel: str, raiz: Path) -> list[str]:
    """Números dos ADRs de todas as linhas que casam `rel`, sem repetir, na ordem do mapa."""
    nums: list[str] = []
    for caminhos, numeros in mapa:
        if any(_casa_caminho(c, rel, raiz) for c in caminhos):
            for n in numeros:
                if n not in nums:
                    nums.append(n)
    return nums


def _casa_caminho(entrada: str, rel: str, raiz: Path) -> bool:
    """Pasta (com `/` no fim, ou que existe como pasta) casa por prefixo; arquivo, exato."""
    alvo = entrada.strip().replace("\\", "/").removeprefix("./")
    if alvo.endswith("/") or (raiz / alvo).is_dir():
        return rel.startswith(alvo.rstrip("/") + "/")
    return rel == alvo


def contexto_por_caminho(
    raiz: Path, pasta: Path, nums: list[str], rel: str
) -> tuple[str, list[str]]:
    """`(bloco para o additionalContext, ADRs que ele entrega)`; `("", [])` sem nada vivo.

    De cada ADR: a `## Regra`, se houver; senão a `## Decisão` inteira, se couber em
    `TETO_DECISAO_CHARS`; senão só o cabeçalho com o tamanho e o caminho. Nunca texto pela
    metade: a parte cortada de uma decisão costuma ser a que restringe, e meia decisão lê
    como permissão.

    Os ADRs entram na ordem do mapa enquanto o bloco cabe em `TETO_ADRS_POR_CAMINHO_CHARS`.
    O primeiro que não cabe e todos depois dele são NOMEADOS numa linha e ficam fora de
    `mostrados`, para a próxima escrita no caminho os entregar inteiros. A versão anterior
    rebaixava todos a ponteiro antes de cortar, e no ValidaNI, onde `apps/web/src/` aponta
    58 ADRs, entregava 20 ponteiros e nenhuma `## Regra`, embora 71 dos 93 ADRs de lá
    tenham uma.
    """
    por_num = {f.name[:4]: f for f in arquivos_adr(pasta)}
    abertura = (
        f'## ADRs de `{rel}` — mapa "Qual ADR ler" do CLAUDE.md\n\n'
        f"Valem para o arquivo desta escrita. Cada um aparece uma vez por sessão; o texto "
        f"completo está no caminho ao lado do título."
    )
    pecas: list[str] = []
    mostrados: list[str] = []
    adiados: list[str] = []

    def montar(pendentes: list[str]) -> str:
        blocos = [abertura, *pecas]
        if pendentes:
            nomes = ", ".join(f"ADR-{n}" for n in pendentes[:_MAX_NOMES_ADIADOS])
            if len(pendentes) > _MAX_NOMES_ADIADOS:
                nomes += f" e mais {len(pendentes) - _MAX_NOMES_ADIADOS}"
            blocos.append(
                f"> Também mapeados para este caminho, ficam para a próxima escrita nele por "
                f"espaço: {nomes}."
            )
        return "\n\n".join(blocos)

    for i, num in enumerate(nums):
        peca = _peca_do_adr(raiz, por_num.get(num), num)
        if peca is None:
            continue
        pecas.append(peca)
        # Mede com os que faltam já nomeados: é o texto que sai se este for o último a caber.
        if len(montar(nums[i + 1 :])) <= TETO_ADRS_POR_CAMINHO_CHARS:
            mostrados.append(num)
            continue
        pecas.pop()
        adiados = nums[i:]
        break
    if not pecas:
        return "", []
    return montar(adiados), mostrados


#: Na linha dos adiados. Sem teto, um mapa de 500 ADRs gastaria só em nomes o bloco inteiro e
#: nenhum ADR caberia — nem esta escrita nem as seguintes entregariam coisa alguma.
_MAX_NOMES_ADIADOS = 30


def _peca_do_adr(raiz: Path, f: Path | None, num: str) -> str | None:
    """Cabeçalho e corpo de um ADR vivo; `None` para ausente, ilegível ou morto."""
    if f is None:
        return None
    try:
        texto = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    status = normalizar_status(ler_frontmatter(texto).get("status", ""))
    if status in STATUS_MORTOS:
        return None
    try:
        onde = f.relative_to(raiz).as_posix()
    except ValueError:
        onde = f.as_posix()
    regra, decisao = _secao(texto, "Regra"), _secao(texto, "Decis[ãa]o")
    if regra:
        corpo = regra
    elif decisao and len(decisao) <= TETO_DECISAO_CHARS:
        corpo = decisao
    elif decisao:
        corpo = f"> Decisão com {len(decisao)} ch, fora deste bloco: leia `{onde}` antes de editar."
    else:
        corpo = f"> Leia `{onde}` antes de editar."
    return f"### ADR-{num} [{status}] {titulo_de(texto, num)} — `{onde}`\n\n{corpo}"


def _secao(texto: str, nome: str) -> str:
    m = re.search(rf"^## {nome}\s*\n(.*?)(?=^## |\Z)", texto, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""
