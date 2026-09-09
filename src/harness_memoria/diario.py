"""Diário de engenharia: leitura, escrita append-only e recorte para injeção.

Port generalizado do `lib_diario.py` do rede_inspira_app. Cada teto que era constante de
módulo virou campo de `ConfigDiario`, e o comentário que justificava o número foi com ele
— o número sem a medição que o produziu é o primeiro a ser mexido por engano.

Somente biblioteca padrão.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import ConfigDiario

#: A seção de maior retorno do diário: é o que impede o próximo agente de repetir um beco
#: sem saída já explorado. Nome fixo de propósito — é o contrato entre quem escreve
#: (skill/hook de fim de sessão) e quem lê (`becos_sem_saida`), e um nome por projeto
#: tornaria o digest incompatível entre projetos sem ganho nenhum.
SECAO_BECOS = "Tentativas descartadas"

LIMITE_TRANSCRIPT_CHARS = 40_000
FERRAMENTAS_DE_ESCRITA = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
SUFIXOS_DESDOBRAMENTO = "bcdefghij"
_PADRAO_MES = "[0-9][0-9][0-9][0-9]-[0-9][0-9]*.md"

#: Fronteira de entrada dentro do arquivo do mês: `## ` **com data**, casada por lookahead
#: (o cabeçalho da entrada fica no bloco, então o leitor não reprefixa `"## "`).
#:
#: A data é obrigatória porque partir por `^## ` cru parte a entrada no exemplo de formato
#: que ela mesma documenta: medido, uma entrada de 411 ch com um bloco ```markdown fazia
#: `ultima_entrada` devolver 237 ch começando no MEIO da cerca, com a data PLACEHOLDER
#: (`AAAA-MM-DD` — e com o `**Estado:**` do EXEMPLO, o que dá ao fragmento cara de entrada
#: inteira), e fazia `becos_sem_saida` perder o prefixo de data dos itens daquela entrada.
#: O bloco se anuncia "última entrada do diário" e entregava fragmento com data falsa.
#:
#: Custo declarado: `## ` sem data deixa de ser fronteira de entrada. É a mesma exigência
#: que o regex de `auditar_ordem_do_diario` já faz e que a regra 5 do README do diário
#: ("datas absolutas") manda; para o caso não ficar mudo, `auditar_diario` reprova o
#: arquivo com `^## ` sem data.
_FRONTEIRA_ENTRADA = re.compile(r"^(?=## \d{4}-\d{2}-\d{2})", re.MULTILINE)
_DATA_DA_ENTRADA = re.compile(r"## (\d{4}-\d{2}-\d{2})")


def forcar_utf8() -> None:
    """No Windows o stdout padrão é cp1252 e engasga em acento e em seta.

    Todo entry point deste pacote chama isto antes de imprimir.
    """
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Caminhos
# --------------------------------------------------------------------------- #


def caminho_mes(pasta: Path, cfg: ConfigDiario, quando: datetime | None = None) -> Path:
    """Arquivo do mês corrente, respeitando o desdobramento por teto de linhas.

    `2026-07.md` estourou o teto -> `2026-07b.md`, depois `2026-07c.md`.
    """
    quando = quando or datetime.now()
    prefixo = quando.strftime("%Y-%m")
    ultimo = pasta / f"{prefixo}.md"
    for sufixo in ("", *SUFIXOS_DESDOBRAMENTO):
        candidato = pasta / f"{prefixo}{sufixo}.md"
        if not candidato.exists() or _contar_linhas(candidato) < cfg.teto_linhas:
            return candidato
        ultimo = candidato
    return ultimo


def _contar_linhas(p: Path) -> int:
    try:
        with p.open(encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# --------------------------------------------------------------------------- #
# Escrita (append-only, com lock)
# --------------------------------------------------------------------------- #


def anexar_entrada(
    pasta: Path, cfg: ConfigDiario, corpo: str, quando: datetime | None = None
) -> Path:
    """Anexa uma entrada ao arquivo do mês. Cria o arquivo com cabeçalho se necessário."""
    quando = quando or datetime.now()
    destino = caminho_mes(pasta, cfg, quando)
    destino.parent.mkdir(parents=True, exist_ok=True)

    with _lock(destino):
        if not destino.exists():
            destino.write_text(_cabecalho_mes(quando), encoding="utf-8")
        with destino.open("a", encoding="utf-8") as f:
            f.write("\n" + corpo.rstrip() + "\n")

    if _contar_linhas(destino) > cfg.teto_linhas:
        print(
            f"[diario] {destino.name} passou de {cfg.teto_linhas} linhas — "
            f"{remediacao_do_teto(cfg, destino)}",
            file=sys.stderr,
        )
    return destino


def remediacao_do_teto(cfg: ConfigDiario, arquivo: Path) -> str:
    """O que FAZER quando o arquivo do mês passa do teto de linhas.

    Duas frases porque as duas saídas são diferentes, e a instrução impossível é pior que
    nenhuma. Reproduzido: com os 10 arquivos do mês (`AAAA-MM.md` + os
    `len(SUFIXOS_DESDOBRAMENTO)` sufixos) no teto, `caminho_mes` devolve `AAAA-MMj.md`,
    `anexar_entrada` o leva a 404 e 408 linhas e imprimia DUAS VEZES "a próxima entrada
    abre um novo arquivo" — não abre, não há próximo sufixo —, enquanto `auditar_diario`
    reprovava com "feche e abra o próximo sufixo". Auditor que produz falha sem correção é
    o jeito mais rápido de ensinar a ignorá-lo (princípio 9).

    Não estendemos os sufixos: 10 arquivos de 400 linhas no mesmo mês é sinal de que o mês
    fechado devia ter ido para `arquivo/`, não de que faltam letras.
    """
    if not arquivo.stem.endswith(SUFIXOS_DESDOBRAMENTO[-1]):
        return "a próxima entrada abre um novo arquivo."
    return (
        f"é o último dos {len(SUFIXOS_DESDOBRAMENTO) + 1} arquivos do mês e não há próximo "
        "sufixo: mova os MAIS ANTIGOS do mês para `arquivo/` (o digest de becos varre "
        "`arquivo/` também, então a ordem não muda) ou aumente `diario.teto_linhas` (hoje "
        f"{cfg.teto_linhas}) no `.claude/harness.json`."
    )


def _cabecalho_mes(quando: datetime) -> str:
    return (
        f"# Diário · {quando.strftime('%Y-%m')}\n\n"
        "Regras e formato: [`README.md`](README.md). "
        "Meses fechados: [`arquivo/`](arquivo/).\n\n---\n"
    )


class _lock:
    """Lock de arquivo simples, para não intercalar duas sessões terminando junto."""

    def __init__(self, destino: Path, tentativas: int = 40, espera: float = 0.25) -> None:
        self.caminho = destino.with_suffix(destino.suffix + ".lock")
        self.tentativas = tentativas
        self.espera = espera
        self.fd: int | None = None

    def __enter__(self):
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(self.tentativas):
            try:
                self.fd = os.open(str(self.caminho), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                # Lock órfão de um processo morto: expira em 60 s.
                try:
                    if time.time() - self.caminho.stat().st_mtime > 60:
                        self.caminho.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(self.espera)
        return self  # segue sem lock em vez de perder a entrada

    def __exit__(self, *_):
        # Só quem DETÉM o lock o remove. Antes, quem desistia (fd=None depois de 40×0,25 s)
        # apagava o lock alheio: no Windows isso levanta PermissionError [WinError 32] após
        # 10,0 s medidos, com o corpo JÁ gravado, e o session_end imprime a mensagem falsa
        # "hook falhou sem gravar"; no Linux (metade da matriz do CI) o unlink de arquivo
        # aberto SUCEDE e a exclusão mútua entre duas sessões terminando junto simplesmente
        # deixa de existir. O reaper de 60 s do `__enter__` continua sendo o que cobre lock
        # de processo morto — ele não resolve este caso, em que os dois estão vivos.
        if self.fd is not None:
            os.close(self.fd)
            with contextlib.suppress(OSError):
                self.caminho.unlink(missing_ok=True)
        return False


# --------------------------------------------------------------------------- #
# Leitura
# --------------------------------------------------------------------------- #


def arquivos_do_diario(pasta: Path) -> list[Path]:
    """Arquivos do diário, do mês mais recente para o mais antigo, incluindo `arquivo/`.

    A ordem é por nome, que para `AAAA-MM[sufixo].md` é a ordem cronológica — e o
    desdobramento (`b`, `c`) ordena corretamente depois do mês sem sufixo.
    """
    if not pasta.exists():
        return []
    saida = sorted(pasta.glob(_PADRAO_MES), key=lambda p: p.name, reverse=True)
    saida += sorted((pasta / "arquivo").glob(_PADRAO_MES), key=lambda p: p.name, reverse=True)
    return saida


def ultima_entrada(pasta: Path) -> tuple[str, str] | None:
    """`(caminho_relativo, markdown)` da entrada mais recente do diário.

    Cai para o arquivo anterior — inclusive dentro de `arquivo/` — quando o arquivo do mês
    corrente existe mas ainda não tem entrada. Sem essa queda, todo dia entre a rotação do
    mês e a primeira sessão registrada do mês novo começaria sem nenhuma memória de diário
    no contexto, que é justamente quando ela vale mais.

    Assume ordem CRONOLÓGICA dentro do arquivo (entrada nova no fim), que é o que
    `anexar_entrada` produz. Diário escrito do mais recente para o mais antigo devolveria
    aqui a entrada mais VELHA — é por isso que a migração de um diário existente inverte a
    ordem em vez de ensinar as duas ao leitor.
    """
    for alvo in arquivos_do_diario(pasta):
        try:
            texto = alvo.read_text(encoding="utf-8")
        except OSError:
            continue
        partes = _FRONTEIRA_ENTRADA.split(texto)
        if len(partes) < 2:
            continue  # só o cabeçalho do mês: ainda não há entrada aqui
        return alvo.relative_to(pasta).as_posix(), partes[-1].strip()
    return None


def partir_em_secoes(corpo: str) -> tuple[str, list[tuple[str, str]]]:
    """Separa o cabeçalho da entrada (antes do primeiro `###`) das suas seções."""
    partes = re.split(r"^### (.+)$", corpo, flags=re.MULTILINE)
    cabecalho = partes[0]
    secoes = [(partes[i].strip(), partes[i + 1]) for i in range(1, len(partes) - 1, 2)]
    return cabecalho, secoes


def _marca_de_truncamento(rotulo: str, arquivo: str) -> str:
    """O sinal de que existe mais texto — a última coisa a cair.

    Leva o caminho porque no caso truncado ela pode ser a única linha que sobra do
    mecanismo de aviso: truncar calado remove o único gatilho de leitura (princípio 8).
    """
    onde = f" em `{arquivo}`" if arquivo else ""
    return f"\n\n[…{rotulo} truncada; leia a entrada completa{onde}…]"


def _nota_de_omissao(nomes: list[str], restantes: int, onde: str) -> str:
    mais = f" e mais {restantes}" if restantes else ""
    return (
        "\n> Seções omitidas por espaço, da menos prioritária para a mais: "
        f"{', '.join(nomes)}{mais}{onde}.\n"
    )


def recortar_entrada(corpo: str, cfg: ConfigDiario, arquivo: str = "") -> str:
    """Encaixa a entrada no limite de injeção descartando seção INTEIRA, por prioridade.

    Ver `ConfigDiario.prioridade_secoes` para o porquê da ordem. O que sai é sempre nomeado
    na nota final: o leitor precisa saber que existe mais, senão o recorte vira falso
    completo — o mesmo defeito de um índice truncado em silêncio.

    A nota e a marca são montadas ANTES do corte e concatenadas DEPOIS, porque cortar o
    texto já montado as comia junto. Reproduzido com `ConfigDiario()` de fábrica: entrada
    de 11.223 ch saía com 5.045 ch — 45 ch ACIMA do limite declarado — sem a nota de
    omissão e sem o caminho do arquivo. As seções de retomada (`Aberto / Próximo passo`,
    `Retomar com`) tinham sido descartadas pela prioridade e NOMEADAS na nota; o corte no
    fim comia justamente a nota, então a função quebrava o contrato do próprio docstring e
    o leitor não tinha como saber o que faltava nem onde achar. O excesso sobre o limite
    ainda torna inútil qualquer orçamento montado sobre `limite_injecao_chars`, que é o que
    o bloco do `SessionStart` faz.
    """
    limite = cfg.limite_injecao_chars
    if len(corpo) <= limite:
        return corpo

    cabecalho, secoes = partir_em_secoes(corpo)
    if not secoes:
        marca = _marca_de_truncamento("entrada", arquivo)
        return corpo[: max(0, limite - len(marca))].rstrip() + marca

    def rank(titulo: str) -> int:
        for i, alvo in enumerate(cfg.prioridade_secoes):
            if titulo.startswith(alvo):
                return i
        return len(cfg.prioridade_secoes)  # seção fora do formato sai antes das conhecidas

    def nota_de(omitidas: list[str]) -> str:
        if not omitidas:
            return ""
        onde = f" — entrada completa em `{arquivo}`" if arquivo else ""
        nomes, restantes = list(omitidas), 0
        # Piso: a nota não pode comer o corpo que ela anuncia. Os sete nomes do default
        # somam ~190 ch, que é 13% de um limite de 1.500 e 38% de um de 500.
        while len(nomes) > 1 and len(_nota_de_omissao(nomes, restantes, onde)) > limite / 3:
            nomes.pop()
            restantes += 1
        return _nota_de_omissao(nomes, restantes, onde)

    def montar(indices: set[int], nota: str) -> str:
        texto = cabecalho.rstrip() + "\n"
        for i in sorted(indices):
            texto += f"\n### {secoes[i][0]}\n{secoes[i][1].strip()}\n"
        return texto + nota

    manter = set(range(len(secoes)))
    # menos importante primeiro; empate desfeito pela última posição no documento
    fila = sorted(manter, key=lambda i: (-rank(secoes[i][0]), -i))
    omitidas: list[str] = []

    while len(fila) > 1 and len(montar(manter, nota_de(omitidas))) > limite:
        vitima = fila.pop(0)
        manter.discard(vitima)
        omitidas.append(secoes[vitima][0])

    nota = nota_de(omitidas)
    saida = montar(manter, nota)
    if len(saida) <= limite:
        return saida

    # Sobrou uma seção só e ela não cabe: aí sim corta o TEXTO, com a nota e a marca
    # preservadas fora do corte.
    marca = _marca_de_truncamento("seção", arquivo)
    espaco = limite - len(marca) - len(nota)
    if espaco < 0:
        # Limite menor que a própria moldura (o menor exercitado no projeto é 1.200 e o
        # default é 5.000): a nota cede antes da marca, que é o sinal.
        nota, espaco = "", limite - len(marca)
    return montar(manter, "")[: max(0, espaco)].rstrip() + marca + nota


def becos_sem_saida(pasta: Path, cfg: ConfigDiario) -> tuple[list[str], int]:
    """Becos já explorados, do mais recente para o mais antigo, e o total encontrado.

    Derivado das seções `### Tentativas descartadas` de TODO o diário, inclusive de
    `arquivo/`. Deliberadamente **não** gera arquivo: um artefato derivado com o mesmo
    texto do diário seria duplicação — a fonte continua única, isto é só uma segunda
    leitura dela.

    Existe porque o `SessionStart` injetava UMA entrada, e no projeto de origem essa seção
    acumulou 77 itens em 17 entradas: 76 deles inalcançáveis sem alguém decidir abrir três
    arquivos. Medido lá: a mesma classe de erro reincidiu ao menos três vezes.

    Quem chama é responsável por anunciar a diferença entre os dois números.
    """
    itens: list[str] = []
    vistos: set[str] = set()
    padrao_secao = re.compile(
        rf"^### {re.escape(SECAO_BECOS)}\s*\n(.*?)(?=^### |\Z)", re.MULTILINE | re.DOTALL
    )

    for p in arquivos_do_diario(pasta):
        try:
            texto = p.read_text(encoding="utf-8")
        except OSError:
            continue
        # entradas vêm em ordem cronológica no arquivo; queremos a mais recente antes
        for bloco in reversed(_FRONTEIRA_ENTRADA.split(texto)[1:]):
            achou_data = _DATA_DA_ENTRADA.match(bloco)
            data = achou_data.group(1) if achou_data else ""
            secao = padrao_secao.search(bloco)
            if not secao:
                continue
            for cru in re.split(r"^- ", secao.group(1), flags=re.MULTILINE)[1:]:
                item = " ".join(cru.split())
                if not item:
                    continue
                # A chave é o item INTEIRO. Era `item.lower()[:60]`, e a grafia legada, que
                # o corpus existente tem (`- {abordagem} → falhou porque {razão}. **Não
                # repetir.**`), põe a abordagem primeiro: quem escreve repete a frase de
                # abertura e diverge no fim, onde mora a lição. Medido: 100 becos distintos
                # sobre 7 subsistemas colapsavam em 7 (93% de perda) e um corpus de 2.160 becos
                # todos distintos sobrevivia 175 (91,9%) — sem truncamento envolvido, os
                # itens medem 207 ch contra o teto de 240. E como `total` é contado
                # PÓS-dedup, o bloco anunciava "7 de 7" e o rodapé "os outros 0": o aviso
                # de corte mentia na mesma taxa do corte.
                chave = item.lower()
                if chave in vistos:
                    continue
                vistos.add(chave)
                prefixo = f"{data} · " if data else ""
                itens.append(prefixo + _resumir_beco(item, cfg.teto_item_beco_chars))

    dentro: list[str] = []
    gasto = 0
    for item in itens:
        if gasto + len(item) > cfg.teto_becos_chars:
            break
        dentro.append(item)
        gasto += len(item)
    return dentro, len(itens)


def _resumir_beco(item: str, teto: int) -> str:
    """Encurta preservando a lição, que mora no FIM do item.

    Truncar pela frente decapitaria justamente a parte imperativa ("**Não repetir:** …"),
    que é a única acionável.
    """
    if len(item) <= teto:
        return item
    # `[.:]?` dentro do negrito porque `\*\*Não repetir:?\*\*` NÃO casava `**Não repetir.**`
    # — o ponto está dentro do negrito, e essa é justamente a grafia que o bloco canônico do
    # template, a skill `/encerrar-sessao` e o fixture do CI prescrevem. Medido com teto
    # 240: item de 314 ch terminando em `**Não repetir.** …` saía com 241 ch cortados no
    # meio da palavra e a lição AUSENTE; o mesmo item com dois-pontos saía com a lição
    # intacta. A instrução de autoria prometia o oposto do que o mecanismo fazia.
    m = re.search(r"\*\*Não repetir[.:]?\*\*:?\s*(.*)", item)
    licao = m.group(1).strip() if m else ""
    # Grupo VAZIO (`**Não repetir.**` sem nada depois, que é a grafia legada, que o corpus
    # existente tem) cai no corte pela frente: emitir `… **Não repetir:** ` sem lição seria
    # um beco em branco no contexto — pior que truncar avisando.
    if licao:
        espaco = teto - len(licao) - len("… **Não repetir:** ")
        if espaco > 40:
            return f"{item[: m.start()][:espaco].rstrip()}… **Não repetir:** {licao}"
    return item[:teto].rstrip() + "…"


# --------------------------------------------------------------------------- #
# Fatos determinísticos: transcript + git
# --------------------------------------------------------------------------- #


def _achar_tool_uses(no, saida: list[dict]) -> None:
    """Varre recursivamente qualquer estrutura procurando blocos de uso de ferramenta.

    O formato do transcript é interno e pode mudar entre versões do Claude Code: a
    varredura recursiva é deliberadamente agnóstica ao aninhamento.
    """
    if isinstance(no, dict):
        if no.get("type") == "tool_use" and isinstance(no.get("name"), str):
            saida.append({"nome": no["name"], "entrada": no.get("input") or {}})
        for v in no.values():
            _achar_tool_uses(v, saida)
    elif isinstance(no, list):
        for v in no:
            _achar_tool_uses(v, saida)


def fatos_do_transcript(caminho: str | None) -> dict:
    """Extrai fatos verificáveis do transcript JSONL. Nunca lança."""
    fatos: dict = {
        "ferramentas": {},
        "arquivos_escritos": [],
        "comandos": [],
        "turnos_usuario": 0,
        "primeiro_pedido": "",
        "excerto": "",
        "erro_parse": None,
    }
    if not caminho:
        fatos["erro_parse"] = "transcript_path ausente"
        return fatos
    p = Path(caminho)
    if not p.exists():
        fatos["erro_parse"] = f"transcript não encontrado: {caminho}"
        return fatos

    textos: list[str] = []
    vistos: set[str] = set()
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    obj = json.loads(linha)
                except json.JSONDecodeError:
                    continue

                usos: list[dict] = []
                _achar_tool_uses(obj, usos)
                for uso in usos:
                    nome = uso["nome"]
                    fatos["ferramentas"][nome] = fatos["ferramentas"].get(nome, 0) + 1
                    entrada = uso["entrada"]
                    if not isinstance(entrada, dict):
                        continue
                    if nome in FERRAMENTAS_DE_ESCRITA:
                        fp = entrada.get("file_path") or entrada.get("notebook_path")
                        if isinstance(fp, str) and fp not in vistos:
                            vistos.add(fp)
                            fatos["arquivos_escritos"].append(fp)
                    elif nome in ("Bash", "PowerShell"):
                        cmd = entrada.get("command")
                        if isinstance(cmd, str):
                            fatos["comandos"].append(cmd.strip().splitlines()[0][:200])

                papel = obj.get("role") or (obj.get("message") or {}).get("role") or obj.get("type")
                texto = _texto_de(obj)
                if texto:
                    textos.append(f"[{papel}] {texto}")
                if papel == "user" and texto and not texto.startswith("["):
                    fatos["turnos_usuario"] += 1
                    if not fatos["primeiro_pedido"]:
                        fatos["primeiro_pedido"] = texto[:600]
    except OSError as e:
        fatos["erro_parse"] = f"falha ao ler transcript: {e}"
        return fatos

    junto = "\n".join(textos)
    if len(junto) > LIMITE_TRANSCRIPT_CHARS:
        metade = LIMITE_TRANSCRIPT_CHARS // 2
        junto = junto[:metade] + "\n\n[…recorte…]\n\n" + junto[-metade:]
    fatos["excerto"] = junto
    return fatos


def _texto_de(obj) -> str:
    """Concatena os blocos de texto de uma linha do transcript."""
    msg = obj.get("message") if isinstance(obj, dict) else None
    conteudo = msg.get("content") if isinstance(msg, dict) else None
    if conteudo is None and isinstance(obj, dict):
        conteudo = obj.get("content") or obj.get("text")
    if isinstance(conteudo, str):
        return conteudo.strip()
    if isinstance(conteudo, list):
        partes = [
            b.get("text", "")
            for b in conteudo
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
        return "\n".join(x for x in partes if x).strip()
    return ""


def fatos_do_git(raiz: Path) -> dict:
    """`git status --porcelain` e `git diff --stat`. Nunca lança."""

    def rodar(args: list[str]) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", str(raiz), *args],
                capture_output=True,
                text=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
            )
            return (r.stdout or "").strip() if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    tem_head = bool(rodar(["rev-parse", "--verify", "HEAD"]))
    return {
        "branch": rodar(["rev-parse", "--abbrev-ref", "HEAD"]) or "(sem commit)",
        "status": rodar(["status", "--porcelain"])[:4000],
        "diffstat": rodar(["diff", "--stat", "HEAD"])[:2000] if tem_head else "",
        "ultimo_commit": rodar(["log", "-1", "--oneline"]) if tem_head else "",
    }


# --------------------------------------------------------------------------- #
# Entrada determinística — o piso do registro
# --------------------------------------------------------------------------- #


def entrada_deterministica(
    raiz: Path,
    pasta_adr: Path,
    fatos: dict,
    git: dict,
    quando: datetime,
    motivo_indisponivel: str | None,
) -> str:
    """Entrada montada só de fatos, para quando o narrador por LLM não está disponível.

    O piso existe para que "o LLM falhou" nunca signifique "a sessão não deixou rastro".
    """
    from .adr import adrs_tocados

    escritos = fatos["arquivos_escritos"]
    ferramentas = (
        ", ".join(f"{k}×{v}" for k, v in sorted(fatos["ferramentas"].items(), key=lambda x: -x[1]))
        or "nenhuma"
    )
    adrs = ", ".join(adrs_tocados(escritos, pasta_adr, raiz)) or "—"

    linhas = [
        f"## {quando.strftime('%Y-%m-%d')} — Sessão registrada automaticamente "
        f"({quando.strftime('%H:%M')})",
        "",
        "**Estado:** registro automático",
        f"**Escopo:** {len(escritos)} arquivo(s) escrito(s) · branch `{git['branch']}`",
        f"**ADRs tocados:** {adrs}",
        "",
        "### O que foi feito (fatos extraídos)",
    ]
    if escritos:
        for a in escritos[:25]:
            linhas.append(f"- `{_relativo(a, raiz)}`")
        if len(escritos) > 25:
            linhas.append(f"- …e {len(escritos) - 25} outro(s)")
    else:
        linhas.append("- Nenhuma escrita de arquivo registrada nesta sessão.")

    if fatos["comandos"]:
        linhas += ["", "### Comandos executados"]
        for c in fatos["comandos"][:12]:
            linhas.append(f"- `{c}`")
        if len(fatos["comandos"]) > 12:
            linhas.append(f"- …e {len(fatos['comandos']) - 12} outro(s)")

    linhas += [
        "",
        "### Verificação",
        f"- Ferramentas usadas: {ferramentas}",
        f"- Turnos do usuário: {fatos['turnos_usuario']}",
    ]
    if git["diffstat"]:
        linhas += ["", "```", git["diffstat"], "```"]

    if motivo_indisponivel:
        linhas += [
            "",
            f"> **resumo-narrativo: indisponível** — {motivo_indisponivel}",
            "> Registro determinístico preservado (caminho de queda do hook de fim de sessão).",
        ]
    if fatos.get("erro_parse"):
        linhas += ["", f"> Aviso do parser de transcript: {fatos['erro_parse']}"]
    return "\n".join(linhas)


def _relativo(caminho: str, raiz: Path) -> str:
    try:
        return Path(caminho).relative_to(raiz).as_posix()
    except (ValueError, OSError):
        return Path(caminho).name
