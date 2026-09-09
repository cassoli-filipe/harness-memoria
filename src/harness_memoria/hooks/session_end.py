#!/usr/bin/env python3
"""Hook SessionEnd — grava o PISO do diário de engenharia.

Fluxo:
  1. guarda anti-recursão -> 2. gate de config -> 3. fatos determinísticos
  -> 4. filtros: já registrada à mão? houve mudança de estado NESTA sessão?
  -> 5. narrativa por LLM SÓ no caminho opt-in
  -> 6. append de UMA entrada em <diario>/AAAA-MM.md

**Este hook é o piso, não o narrador.** Até esta mudança ele tentava narrar por
`claude -p` ANTES de gravar o piso, e por isso nunca gravou nada: a plataforma dá
1.500 ms a hook DE PLUGIN e o `"timeout": 160` de `hooks/hooks.json` não levanta esse
orçamento (a aritmética está em `_orcamento_ms`), enquanto `claude -p` mede 14,5-33 s
nesta máquina. O processo era morto no meio do passo da narrativa, antes de chegar ao
piso, que ficava DEPOIS dela. Medido em três projetos consumidores desde a virada para
plugin: ZERO entradas com a assinatura deste hook, contra 20+ escritas pela skill
`/encerrar-sessao`. O piso mede 330-500 ms ponta a ponta (start do interpretador 119 ms +
`fatos_do_git` 193 ms + `fatos_do_transcript` de um transcript de 11,5 MB 158 ms + 43 ms
da datação do `diffstat`, esta última medida em 15 processos), isto é, 3x de folga dentro
do orçamento.

A narrativa é da skill `/encerrar-sessao`, que roda DENTRO da sessão, com o contexto
inteiro e sem orçamento de 1,5 s. Aqui ela só é tentada quando o consumidor levantou o
orçamento — e, nesse caminho, com tempo reservado para o piso.

**UMA entrada por sessão, sempre.** O diário é append-only e entrada passada não se
corrige, então "gravar o piso e depois gravar a narrativa" produziria DUAS entradas da
mesma sessão — e a segunda passaria a ser a que o `SessionStart` reinjeta. Por isso o
append é o ÚLTIMO passo dos dois caminhos: o default não chama LLM nenhum, e o opt-in dá
ao `claude -p` só `orçamento − RESERVA_DO_PISO_MS`, para que o estouro caia no piso ainda
dentro do orçamento. Não existe caminho em que este hook escreva duas vezes. E quando a
sessão já registrou a entrada à mão (a skill), o piso é DISPENSADO — ver `_ja_registrada`.

Este hook NUNCA deve quebrar o encerramento da sessão: todo caminho sai com 0.

Autoteste:  python src/harness_memoria/hooks/session_end.py --autoteste [--projeto CAMINHO]
            (não escreve: mostra a entrada que gravaria)
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROTULO = "diario"

#: Erro do bootstrap, se houver. Era o único hook dos seis com o `sys.path.insert` + o
#: `from harness_memoria...` FORA de qualquer rede — e o `FUNDAMENTOS.md` já afirmava, em
#: duas seções, que os seis o tinham dentro. Reproduzido pelo revisor com a árvore quebrada
#: (erro de sintaxe no fim de `config.py`, que é o que um `git pull` no meio produz): os
#: outros cinco saíam rc=0 com a mensagem rotulada e a causa, este saía **rc=1 com
#: traceback cru no stderr** — no encerramento da sessão, que é o pior momento para a
#: plataforma receber um hook que falha. `os`, `sys` e os stdlib acima ficam fora do `try`
#: de propósito: são os que não podem faltar, e `sys` é o que imprime a mensagem.
_ERRO_DE_BOOTSTRAP: str | None = None

try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from harness_memoria import diario  # noqa: E402
    from harness_memoria.adr import adrs_tocados  # noqa: E402
    from harness_memoria.config import Config  # noqa: E402
    from harness_memoria.hooks import _comum as C  # noqa: E402
except Exception as e:  # noqa: BLE001 — pacote inconsistente não derruba a sessão
    _ERRO_DE_BOOTSTRAP = f"{type(e).__name__}: {e}"

# Não há filtro por `reason`, de propósito. O enum é fechado e validado pela plataforma —
# ["clear","resume","logout","prompt_input_exit","other"] no binário 2.1.263 — e os cinco
# valores querem dizer a mesma coisa: a sessão acabou. O conjunto que existia aqui listava
# quatro deles e esquecia `resume`, que é, ao lado de `clear`, um dos dois únicos motivos
# disparados de DENTRO do REPL (`zLe(me,"resume")`): metade dos encerramentos in-session
# saía sem registro e sem uma linha de stderr (reproduzido com o mesmo transcript —
# `reason=clear` gravava, `reason=resume` saía vazio). Conjunto que enumera todos os
# valores possíveis é código que finge decidir; quem decide é o passo 4.
# NÃO inverter isto para lista de exclusão: gravar por default entrada de semântica
# desconhecida contradiz a convenção "chave desconhecida REPROVA" de config.py.

#: Variável que a PRÓPRIA plataforma lê para levantar o orçamento deste hook (documentada
#: em code.claude.com/docs/en/hooks, seção SessionEnd). É o único sinal do caminho opt-in
#: que o hook consegue observar: `timeout` de hook de plugin não levanta nada, e daqui de
#: dentro não se vê que o consumidor declarou um SessionEnd no `settings.json` dele — quem
#: faz isso põe esta variável no `env` do mesmo arquivo.
VAR_ORCAMENTO = "CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS"

#: Orçamento em ms quando ninguém o levanta: `var oyn=1500` no binário 2.1.263.
ORCAMENTO_PISO_MS = 1500

#: Custo já pago antes da primeira linha de `main()`: start do interpretador 119 ms +
#: import do pacote 85,6 ms, medidos. Entra na conta porque a plataforma cronometra o
#: PROCESSO, não a função.
PARTIDA_MS = 205

#: Reservado para montar e gravar o piso depois que o narrador devolve ou estoura. A
#: montagem custa poucos ms (os fatos já estão na mão); a folga existe para o `_lock` do
#: diário disputado por duas sessões terminando junto, que espera até 40×0,25 s.
RESERVA_DO_PISO_MS = 1000

#: Abaixo desta sobra não vale gastar o orçamento chamando `claude -p`: medido 14,50 s e
#: 15,29 s para `claude -p "Responda apenas: ok"`, e 17,5-19,6 s com o prompt real de
#: 41.951 chars. Filho que certamente não termina atrasa o piso e faz a plataforma matar o
#: processo antes do append — que é exatamente a perda que este arquivo conserta.
MINIMO_PARA_NARRAR_MS = 20_000

#: Teto do filho, para o caso de o consumidor declarar um orçamento enorme.
TETO_NARRATIVA_S = 120

#: Nome de arquivo de mês do diário: `AAAA-MM.md` e os sufixos de desdobramento
#: (`AAAA-MMb.md`). Serve para distinguir "esta sessão registrou o diário" de "esta sessão
#: mexeu no `README.md` da pasta do diário", que é trabalho sobre o formato.
_ARQUIVO_DE_MES = re.compile(r"^\d{4}-\d{2}[a-z]?$")

#: Arquivo em `C.pasta_estado(raiz)` com o `git diff --stat` com que a última sessão deste
#: projeto TERMINOU — a data que falta ao `diffstat`. Duas partes, e as duas por medição:
#: a primeira linha é o HASH do conteúdo (`diff-sha256:`), que é o que se compara, e o resto
#: é o `--stat` legível, para o humano depurando "por que este projeto não registra?" abrir
#: o arquivo e VER o que o hook comparou.
#:
#: A primeira versão guardava só o `--stat` e comparava o texto dele. `--stat` é um SUMÁRIO
#: e COLIDE: duas sessões que mudam o mesmo arquivo com a mesma contagem de linhas produzem
#: `arquivo | 4 ++--` idêntico, e a segunda era descartada como "worktree igual ao da sessão
#: anterior" — perda silenciosa na única via que este sinal existe para servir (a sessão de
#: orquestração, cujas escritas saem de subagentes e não aparecem no transcript principal).
#: Achado pelo verificador em três sessões de orquestração seguidas num consumidor.
#: O conteúdo custa 7,1 ms a mais: `git diff HEAD` mede p25 54,5 ms contra 47,4 do
#: `--stat` (n=15, neste repo), num orçamento de 1.500 ms em que o piso inteiro gasta ~288.
#:
#: Não entra no `escritas_*.txt` de `_comum._limpar_estado_velho` de propósito: aquele
#: expira em 7 dias porque é um contador por sessão, e expirar ESTA marca traria de volta a
#: entrada de ruído em todo projeto que ficou uma semana parado. É um arquivo por projeto.
_MARCA_DO_DIFF = "diffstat_visto.txt"

#: Prefixo da primeira linha da marca. Marca sem ele é de uma versão anterior do hook: o
#: `_hash_de` devolve `None` e o caminho de ignorância trata (registra), em vez de comparar
#: hash com texto de `--stat` e nunca casar — que faria a entrada de ruído voltar calada em
#: todo projeto que já tinha marca no temp.
_PREFIXO_IMPRESSAO = "diff-sha256:"

INSTRUCAO = """\
Você está escrevendo UMA entrada do diário de engenharia de um projeto de software.
Responda SOMENTE com o markdown da entrada, sem preâmbulo, sem cercas de código ao redor,
sem usar ferramentas.

Escreva em português do Brasil. Máximo 25 linhas. Números em vez de adjetivos.
NUNCA inclua token, segredo, credencial, URL interna ou dado pessoal.{proibicoes}
Decisão arquitetural não é descrita aqui — cite apenas o ID (ex.: ADR-0023).

Formato exato:

## {data} — {titulo}

**Estado:** concluído | parcial | bloqueado
**Escopo:** `caminho/tocado/`
**ADRs:** {ids}

### O que foi feito
- {mudanca}

### Por quê
{gatilho}

### Como (o não-óbvio)
- {decisao}

### Tentativas descartadas
- {abordagem} → falhou porque {razao}. **Não repetir:** {licao}
  (omita a seção inteira se nada foi descartado)

### Verificação
- {evidencia com número; comandos rodados e resultado}

### Aberto / Próximo passo
- [ ] {acao}
"""


def main(argv: list[str] | None = None) -> int:
    if _ERRO_DE_BOOTSTRAP is not None:
        # A mensagem existe para ser lida no dia do `git pull` no meio: rotulada, no
        # stderr, e com a CAUSA (o import que falhou), não com a consequência.
        print(
            f"[{ROTULO}] pacote não importável, sessão sem registro: {_ERRO_DE_BOOTSTRAP}",
            file=sys.stderr,
        )
        return 0

    inicio = time.monotonic()
    argv = list(argv if argv is not None else sys.argv[1:])
    C.preparar(ROTULO)

    # ---- 1. guarda anti-recursão --------------------------------------------
    # O `claude -p` do caminho opt-in também encerra sessão e dispararia este hook.
    if C.narrando():
        return 0

    autoteste = "--autoteste" in argv
    if autoteste:
        evento = {
            "reason": "prompt_input_exit",
            "cwd": _arg(argv, "--projeto") or os.getcwd(),
            "transcript_path": None,
            "session_id": "autoteste",
            "hook_event_name": "SessionEnd",
        }
    else:
        evento = C.ler_evento()

    # ---- 2. gate ------------------------------------------------------------
    ctx = C.contexto(evento, ROTULO)
    if ctx is None:
        if autoteste:
            print(
                f"[{ROTULO}] projeto sem `.claude/harness.json` — hook inerte por desenho",
                file=sys.stderr,
            )
        return 0
    raiz, cfg = ctx
    agora = datetime.now()

    # ---- 3. fatos determinísticos (o piso do registro) ----------------------
    fatos = diario.fatos_do_transcript(evento.get("transcript_path"))
    git = diario.fatos_do_git(raiz)
    # A marca é LIDA antes de ser regravada: é o retrato de como a sessão anterior deste
    # projeto deixou o worktree, e é a única data que o `diffstat` tem. O autoteste não
    # participa — ele é um dry run e não pode mover a linha de base de ninguém.
    marca = None if autoteste else _marca_anterior(raiz)
    # A impressão é calculada UMA vez e serve a dois consumidores: a comparação com a marca
    # anterior e a regravação. `git["diffstat"]` entra de carona porque `fatos_do_git` já
    # pagou aquele comando — o único custo novo aqui é o `git diff HEAD` do hash.
    impressao = "" if autoteste else _impressao_do_diff(raiz, git["diffstat"])
    marca_gravada = False if autoteste else _gravar_marca(raiz, impressao)

    # ---- 4. filtros: já registrada à mão? mudança de estado NESTA sessão? ---
    if fatos["erro_parse"] and not autoteste:
        # Antes este diagnóstico só aparecia DENTRO de `entrada_deterministica`, que o
        # `return 0` abaixo nunca deixava chamar: produzido e jogado fora. E o gatilho
        # realista não é o arquivo faltando — é o formato interno do transcript mudar, o
        # que o próprio `_achar_tool_uses` admite. Nesse dia `arquivos_escritos` fica
        # vazio em TODAS as sessões e nada na auditoria detecta "o diário parou".
        print(f"[{ROTULO}] transcript ilegível: {fatos['erro_parse']}", file=sys.stderr)

    # "Piso não compete com escolha deliberada" é o que a skill `/encerrar-sessao` promete
    # por escrito — e até agora era promessa vazia, porque o hook nunca chegava a gravar.
    # Agora que ele grava sempre, a sessão em que alguém rodou a skill terminaria com DUAS
    # entradas, e a do hook seria a ÚLTIMA: `ultima_entrada` reinjetaria o registro
    # automático em vez da narrativa escrita à mão, que é a de maior valor. A skill grava
    # com Write/Edit, então o transcript principal tem a escrita no arquivo de mês — este
    # é o sinal, e ele custa zero (os fatos já estão na mão).
    ja = _ja_registrada(fatos["arquivos_escritos"], cfg.pasta_diario)
    if not autoteste and ja is not None:
        print(
            f"[{ROTULO}] a sessão já registrou {ja.name} à mão — piso dispensado", file=sys.stderr
        )
        return 0

    # O diário registra RESULTADO, não presença (regra 6 do README do diário) — e o
    # RESULTADO tem de ser DESTA sessão. Ver `_motivo_para_nao_registrar`.
    if not autoteste:
        motivo = _motivo_para_nao_registrar(fatos, git, marca, marca_gravada, impressao)
        if motivo:
            print(f"[{ROTULO}] {motivo}", file=sys.stderr)
            return 0

    # ---- 5. narrativa por LLM (só no caminho opt-in) ------------------------
    janela = None if autoteste else _janela_de_narrativa(_gasto_ms(inicio))
    if autoteste:
        corpo, indisponivel = None, "autoteste: LLM não chamado"
    elif janela is None:
        corpo, indisponivel = None, _motivo_sem_orcamento(cfg)
    elif not fatos["arquivos_escritos"]:
        # Sem arquivo escrito no transcript não há o que narrar: o prompt iria com
        # "Arquivos escritos: (nenhum)" e o LLM escreveria a partir do diffstat, que o
        # piso já transcreve verbatim. Seriam 20 s de latência no encerramento por nada.
        corpo, indisponivel = None, "nenhuma escrita no transcript: nada para narrar"
    else:
        try:
            corpo, indisponivel = _narrar(raiz, cfg, fatos, git, agora, janela)
        except Exception as e:  # noqa: BLE001 — o piso não depende de o narrador ser correto
            # `_narrar` já trata OSError, SubprocessError e TimeoutExpired. Isto cobre o
            # resto (um bug em `_montar_prompt`, um MemoryError num transcript enorme):
            # sem este `except`, uma exceção aqui abortaria `main()` ANTES do append e a
            # sessão voltaria a não deixar rastro — a falha que este arquivo conserta.
            corpo, indisponivel = None, f"falha inesperada no narrador: {type(e).__name__}: {e}"

    # ---- 6. append de UMA entrada -------------------------------------------
    if corpo:
        corpo = corpo.rstrip() + "\n\n" + _rodape_fatos(fatos, git)
    else:
        corpo = diario.entrada_deterministica(raiz, cfg.pasta_adr, fatos, git, agora, indisponivel)

    if autoteste:
        # O autoteste NÃO escreve. O diário é append-only e entrada passada não se corrige,
        # então rodá-lo sujaria permanentemente o mês com uma entrada de zero arquivo — que
        # a própria regra do diário proíbe. Aqui ele só mostra. É este caminho que o CI roda
        # contra o projeto sintético em todo push.
        destino = diario.caminho_mes(cfg.pasta_diario, cfg.diario, agora)
        print(
            f"[{ROTULO}] autoteste: entrada NÃO gravada. Iria para "
            f"{destino.relative_to(raiz).as_posix()}:",
            file=sys.stderr,
        )
        print(corpo)
        return 0

    destino = diario.anexar_entrada(cfg.pasta_diario, cfg.diario, corpo, agora)
    # A marca é refeita DEPOIS do append, e este é o passo que faltava na primeira versão
    # da correção: o arquivo de mês é rastreado, então a entrada que este hook acabou de
    # anexar aparece no `git diff --stat` da sessão SEGUINTE. Com a marca de antes do
    # append, toda sessão de leitura que viesse depois de uma sessão produtiva via um diff
    # diferente e ganhava entrada de ruído — o defeito de volta, uma sessão adiante.
    # Reproduzido por `test_diff_igual_a_marca_da_sessao_anterior_nao_registra`, que
    # reprovou com `assert 3 == 2` antes deste bloco existir.
    _gravar_marca(raiz, _impressao_do_diff(raiz))
    print(
        f"[{ROTULO}] entrada gravada em {destino.relative_to(raiz).as_posix()} "
        f"({_gasto_ms(inicio):.0f} ms de {_orcamento_ms()} ms de orçamento)",
        file=sys.stderr,
    )
    return 0


def _gasto_ms(inicio: float) -> float:
    """Milissegundos gastos por este PROCESSO, incluindo o que veio antes de `main()`."""
    return PARTIDA_MS + (time.monotonic() - inicio) * 1000


def _orcamento_ms() -> int:
    """Orçamento real deste hook em ms, na aritmética do CLI.

    `afe()` no binário 2.1.263:

        let e = env.CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS;
        if (e !== void 0 && e > 0) return e;
        let t = 0;
        for (...) if (f.timeout && f.timeout * 1000 > t) t = f.timeout * 1000;
        return Math.max(1500, Math.min(t, 60000));

    aplicado como `AbortSignal.timeout(afe())` nas chamadas `zLe(t,"clear",…)` e
    `zLe(me,"resume",…)`. O laço percorre só os registros de settings/SDK: hook de plugin
    mora em `registeredHooks`, que `afe()` NÃO consulta. Logo o `"timeout": 160` de
    `hooks/hooks.json` deixa `t=0` e o resultado é `max(1500, min(0, 60000))` = **1500**.
    A variável de ambiente é o único jeito de levantar, e ela não passa pelo teto de 60 s
    — o teto vale só para o ramo dos settings.
    """
    bruto = os.environ.get(VAR_ORCAMENTO)
    if bruto is None:
        return ORCAMENTO_PISO_MS
    try:
        valor = int(bruto.strip())
    except ValueError:
        # Mesma leitura do CLI: string não-numérica reprova o `> 0` e cai no default.
        return ORCAMENTO_PISO_MS
    return valor if valor > 0 else ORCAMENTO_PISO_MS


def _ja_registrada(escritos: list[str], pasta_diario: Path) -> Path | None:
    """O arquivo de mês do diário que ESTA sessão escreveu, se houver.

    Escopo deliberado: o sinal vem do transcript DESTA sessão, não do estado do diário.
    Checar "a última entrada é de hoje" perderia a segunda sessão produtiva do dia, que é
    o caso comum; e uma escrita feita por subagente não aparece no transcript principal,
    então nesse caminho o piso ainda é anexado (uma entrada a mais é recuperável, uma
    entrada a menos não).
    """
    for a in escritos:
        p = Path(a)
        if p.suffix != ".md" or not _ARQUIVO_DE_MES.match(p.stem):
            continue
        if pasta_diario in (p.parent, *p.parent.parents):
            return p
    return None


def _marca_anterior(raiz: Path) -> str | None:
    """O `git diff --stat` com que a sessão anterior deste projeto terminou, ou `None`.

    `None` é ignorância, não "worktree limpo": primeira sessão do projeto, temp limpo por
    reboot (`C.pasta_estado` documenta que estado não sobrevive a um) ou temp sem permissão.
    Quem trata a ignorância é `_motivo_para_nao_registrar`.

    `ValueError` cobre a marca corrompida (byte inválido para UTF-8, que é o que um
    desligamento no meio da escrita deixa): também é ignorância, não motivo para lançar.
    """
    try:
        return (C.pasta_estado(raiz) / _MARCA_DO_DIFF).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _diffstat_agora(raiz: Path) -> str:
    """`git diff --stat HEAD`, a MESMA string que `diario.fatos_do_git` põe em `diffstat`.

    Cópia consciente do comando e do corte em 2.000 ch, e a cópia é o ponto: a marca tem de
    ser refeita DEPOIS do append, e `fatos_do_git` roda cinco comandos (193 ms medidos) para
    devolver quatro campos, dos quais aqui só um interessa — medido 35 ms (p25 de 15
    processos) contra 193, no orçamento de 1.500 ms. Reusar `fatos_do_git` custaria os 193
    inteiros. `tests/test_session_end.py` reprova se as duas versões divergirem, e a
    divergência é o tipo que não aparece: ela faria a marca nunca casar, e a entrada de
    ruído por sujeira antiga voltaria calada.

    O `if returncode == 0 else ""` cobre o repositório sem HEAD sem precisar do
    `rev-parse --verify` que `fatos_do_git` faz: sem commit, `git diff --stat HEAD` sai
    diferente de zero e as duas versões devolvem "".
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(raiz), "diff", "--stat", "HEAD"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
        return (r.stdout or "").strip()[:2000] if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _impressao_do_diff(raiz: Path, stat: str | None = None) -> str:
    """A impressão do worktree: `diff-sha256:<hash do conteúdo>` e o `--stat` legível embaixo.

    O hash é do `git diff HEAD` INTEIRO, não do sumário — ver `_MARCA_DO_DIFF` para a
    colisão que isso fecha. `stat` é aceito de fora porque `fatos_do_git` já pagou aquele
    comando no caminho principal; sem ele, refaz por `_diffstat_agora` (é o caso da segunda
    gravação, depois do append).

    Nunca lança: sem git, sem HEAD ou com o comando falhando, o hash é o da string vazia e a
    impressão continua comparável — duas execuções sem git casam entre si, que é o
    comportamento certo para "não sei ler o worktree".
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(raiz), "diff", "HEAD"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
        bruto = (r.stdout or "") if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        bruto = ""
    h = hashlib.sha256(bruto.encode("utf-8", "replace")).hexdigest()[:16]
    texto = _diffstat_agora(raiz) if stat is None else stat
    return f"{_PREFIXO_IMPRESSAO}{h}\n{texto}"


def _hash_de(marca: str | None) -> str | None:
    """O hash da primeira linha da marca, ou `None` se ela não tiver o prefixo.

    `None` significa "não sei comparar" e cai no mesmo caminho de ignorância da marca
    ausente. Cobre a marca escrita por uma versão anterior do hook e a marca truncada por
    desligamento no meio da escrita.
    """
    linhas = (marca or "").splitlines()
    if not linhas or not linhas[0].startswith(_PREFIXO_IMPRESSAO):
        return None
    return linhas[0][len(_PREFIXO_IMPRESSAO) :] or None


def _gravar_marca(raiz: Path, diffstat: str) -> bool:
    """Deixa o diff desta sessão como linha de base da PRÓXIMA. Nunca lança.

    Chamada em TODA execução, inclusive nas que não anexam entrada — inclusive na que
    dispensa o piso porque a skill já registrou. A marca descreve o WORKTREE, não a decisão
    de registrar, e uma marca que só avançasse nas sessões produtivas voltaria a cobrar o
    diff antigo da sessão de leitura seguinte.

    Chamada DUAS vezes no caminho que anexa: antes (é também a sonda de "o estado é
    utilizável?") e depois, porque o arquivo de mês é rastreado e a própria entrada entra no
    diff — ver o comentário no fim de `main`.

    O `False` é usado: sem poder gravar, a ignorância desta execução não se conserta na
    próxima, e o default seguro inverte — ver `_motivo_para_nao_registrar`.

    Sem lock, ao contrário do `diario._lock`: duas sessões terminando juntas gravam ambas o
    retrato do momento e a última vence, o que é convergente. O lock do diário existe
    porque append-only não tolera intercalação; sobrescrever um retrato tolera.
    """
    try:
        (C.pasta_estado(raiz) / _MARCA_DO_DIFF).write_text(diffstat, encoding="utf-8")
        return True
    except OSError:
        return False


def _motivo_para_nao_registrar(
    fatos: dict,
    git: dict,
    marca: str | None,
    marca_gravada: bool,
    impressao: str,
) -> str | None:
    """`None` quando esta sessão mudou o estado do projeto; senão o motivo, para o stderr.

    São dois sinais porque nenhum dos dois basta sozinho:

    * `arquivos_escritos` sozinho perde a sessão de orquestração — as escritas saem de
      subagentes e o transcript principal vê 3,4% dos tool calls (medido: 29 `tool_use` no
      principal contra 345 nos de subagente), então ele vem VAZIO com o diff no disco.
      Varrer os JSONL de subagente para preencher isso foi rejeitado: 300-600 ms a mais no
      orçamento de 1.500 ms troca o registro pelo detalhe do registro.
    * `git['diffstat']` não vale como único critério, e `git['status']` não vale nem como
      segundo: repositório cronicamente sujo (um `?? .venv/` que nunca sai) daria entrada
      em TODA sessão de leitura.

    **E `git diff --stat` não tem DATA** — era o furo que sobrou depois de o piso passar a
    gravar. Modificação não-commitada de uma sessão ANTERIOR (o estado normal de quem
    trabalha em pedaços) contava como mudança desta. Reproduzido pelo verificador: numa
    sessão só de leitura (Read + Bash, zero escrita) sobre sujeira antiga, o hook anexava
    uma entrada cujo único conteúdo era o diff daquela sujeira, sob "Nenhuma escrita de
    arquivo registrada nesta sessão" — e o `SessionStart` seguinte injetava ESSA entrada
    como "última entrada do diário", deslocando do bloco a decisão que valia (verificado:
    "Decisão que importa" -> ausente). O diário é append-only, então cada sessão de leitura
    empurrava a memória real mais para trás: ponteiro NOVO e VAZIO, o princípio 6 pelo
    efeito. Aconteceu com o `docs/diario/` DESTE repo, duas entradas, durante a verificação.

    A data vem da marca (`_gravar_marca`): "impressão igual à marca" quer dizer "o worktree
    está como a sessão anterior o deixou", e aí o diff não é resultado desta sessão. Largar o
    `diffstat` foi descartado — ele existe justamente para o caso dos subagentes.

    A comparação é por HASH DO CONTEÚDO, não pelo texto do `--stat`: o sumário colide, e a
    colisão apagava justamente a sessão de orquestração. Ver `_MARCA_DO_DIFF`.

    Sem marca a IDADE do diff é desconhecida, e a decisão passa a ser pela legibilidade do
    transcript. As três saídas, e o motivo de cada default:

    * transcript ilegível ou ausente -> REGISTRA. Não se sabe o que a sessão fez, e perda
      silenciosa é pior que excesso; é também o caminho da sessão de orquestração sem
      transcript principal.
    * marca não pôde ser gravada (temp sem permissão) -> REGISTRA. Ignorância que não se
      conserta na próxima sessão não pode virar silêncio permanente.
    * transcript legível e sem escrita nenhuma -> NÃO registra. Aqui o excesso não é "uma
      entrada a mais", que seria recuperável: é uma entrada VAZIA que vira a
      `ultima_entrada` e expulsa do bloco injetado a entrada que tinha conteúdo. A janela
      de ignorância é UMA sessão por projeto por vida do temp — a marca desta execução a
      fecha —, e a entrada que se perde nela é recuperável com `/encerrar-sessao`; a que
      se ganharia não é, porque o diário é append-only.
    """
    if fatos["arquivos_escritos"]:
        return None
    if not git["diffstat"]:
        # Comando isolado deixou de qualificar: um `ls` num repo limpo é presença, não
        # resultado, e o diário é append-only — entrada sobre presença não se apaga depois.
        return "sessão sem mudança de estado — nada a registrar"
    anterior, atual = _hash_de(marca), _hash_de(impressao)
    if anterior is not None and atual is not None:
        if anterior != atual:
            return None
        return (
            "sessão sem mudança de estado atribuível a ela: o diff no disco é o mesmo com "
            "que a sessão anterior terminou — nada a registrar"
        )
    if fatos["erro_parse"] or not marca_gravada:
        return None
    return (
        "sessão sem mudança de estado atribuível a ela: diff no disco de idade desconhecida "
        "(primeira sessão deste projeto, ou estado perdido no reboot) e transcript sem "
        "escrita nenhuma — nada a registrar"
    )


def _motivo_sem_orcamento(cfg: Config) -> str:
    """O que a entrada de piso diz no lugar da narrativa: um PONTEIRO, não um erro.

    Aponta a skill DO PROJETO quando existe uma (`diario.skill_de_encerramento`), porque
    `/encerrar-sessao` cede a vez para ela — mandar chamar a skill que vai se recusar é
    ponteiro velho no rodapé da única entrada que a sessão deixou.
    """
    return (
        f"narrativa por LLM fora do caminho crítico (este hook tem {_orcamento_ms()} ms de "
        f"orçamento); rode `{cfg.diario.skill_de_encerramento or '/encerrar-sessao'}` para a "
        "entrada narrada"
    )


def _janela_de_narrativa(gasto_ms: float) -> float | None:
    """Segundos que sobram para o `claude -p`, ou `None` para não tentar.

    `None` é o default deliberado, não uma falha: sem orçamento levantado, a narrativa não
    entra no caminho crítico do encerramento. Ver o docstring do módulo.
    """
    orcamento = _orcamento_ms()
    if orcamento <= ORCAMENTO_PISO_MS:
        return None
    sobra = orcamento - gasto_ms - RESERVA_DO_PISO_MS
    if sobra < MINIMO_PARA_NARRAR_MS:
        return None
    return min(sobra / 1000, TETO_NARRATIVA_S)


def _narrar(
    raiz: Path, cfg: Config, fatos: dict, git: dict, agora: datetime, timeout_s: float
) -> tuple[str | None, str | None]:
    """Chama `claude -p` para narrar a sessão. Devolve `(corpo, motivo_de_indisponibilidade)`."""
    # UMA chamada, não três: `shutil.which` já expande `PATHEXT` sozinho — nesta máquina
    # `which("claude")` devolve `...\.local\bin\claude.EXE` e `which("claude.cmd")` devolve
    # `None`, isto é, o sufixo explícito não acha nada que o nome puro perca. Medido com o
    # `claude` fora de um PATH de 42 entradas, que é o caso em que as três rodavam até o
    # fim: 20,71 → 4,55 ms de p25 em 40 chamadas. Terceiro e último sítio da varredura —
    # `formatar._executavel` carrega a sondagem completa de `PATHEXT` e já falava dele no
    # passado, o que fazia do docstring de lá um ponteiro velho enquanto esta linha existia.
    exe = shutil.which("claude")
    if not exe:
        return None, "executável `claude` não encontrado no PATH"

    prompt = _montar_prompt(raiz, cfg, fatos, git, agora)

    ambiente = dict(os.environ)
    ambiente[C.VAR_GUARDA] = "1"  # impede que o filho dispare este mesmo hook

    # `--strict-mcp-config` faz o filho ignorar os servidores MCP do usuário e do projeto.
    # Medido pareado com o prompt real de 41.951 chars: 22,70 -> 19,63 s e 29,67 -> 17,51 s
    # (média -29%). A INSTRUCAO já manda "sem usar ferramentas", então MCP nenhum é útil
    # aqui; e nesta máquina três servidores falharam na conexão, um com CONNECT_TIMEOUT de
    # 30.000 ms — MCP quebrado de um projeto qualquer virava latência no encerramento de
    # TODOS. Num CLI antigo, sem a flag, o filho sai rc=1 com `error: unknown option` e o
    # piso é gravado logo abaixo: degradação graciosa, não perda.
    args = [exe, "-p", "--strict-mcp-config"]
    modelo = os.environ.get("HARNESS_MEMORIA_MODELO")
    if modelo:
        args += ["--model", modelo]

    try:
        r = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(raiz),
            env=ambiente,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return None, f"`claude -p` excedeu {timeout_s:.0f}s (o que sobrava do orçamento do hook)"
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"falha ao executar `claude -p`: {e}"

    if r.returncode != 0:
        detalhe = (r.stderr or "").strip().splitlines()
        return None, (
            f"`claude -p` saiu com {r.returncode}: {detalhe[-1][:200] if detalhe else 'sem stderr'}"
        )

    saida = _limpar_cercas((r.stdout or "").strip())
    if not saida.startswith("## "):
        return None, "resposta do LLM fora do formato esperado"
    if len(saida) < 80:
        return None, "resposta do LLM vazia ou truncada"
    return saida, None


def _limpar_cercas(texto: str) -> str:
    linhas = texto.splitlines()
    if linhas and linhas[0].startswith("```"):
        linhas = linhas[1:]
    if linhas and linhas[-1].strip() == "```":
        linhas = linhas[:-1]
    return "\n".join(linhas).strip()


def _montar_prompt(raiz: Path, cfg: Config, fatos: dict, git: dict, agora: datetime) -> str:
    escritos = "\n".join(f"- {a}" for a in fatos["arquivos_escritos"][:60]) or "- (nenhum)"
    comandos = "\n".join(f"- {c}" for c in fatos["comandos"][:30]) or "- (nenhum)"
    ids = ", ".join(adrs_tocados(fatos["arquivos_escritos"], cfg.pasta_adr, raiz)) or "—"
    proibicoes = (
        "\nNUNCA inclua, também: " + "; ".join(cfg.diario.proibicoes) + "."
        if cfg.diario.proibicoes
        else ""
    )
    instrucao = (
        INSTRUCAO.replace("{data}", agora.strftime("%Y-%m-%d"))
        .replace("{proibicoes}", proibicoes)
        .replace("{ids}", "IDs ou —")
        .replace("{titulo}", "título imperativo do que mudou")
    )
    return (
        instrucao
        + "\n\n=== FATOS VERIFICADOS DA SESSÃO (use como base; não invente) ===\n"
        + f"Projeto: {cfg.projeto}\n"
        + f"Data: {agora.strftime('%Y-%m-%d %H:%M')}\n"
        + f"Branch: {git['branch']}\nÚltimo commit: {git['ultimo_commit'] or '(nenhum)'}\n"
        + f"ADRs tocados: {ids}\n"
        + f"Turnos do usuário: {fatos['turnos_usuario']}\n\n"
        + f"Arquivos escritos:\n{escritos}\n\nComandos executados:\n{comandos}\n\n"
        + f"git diff --stat:\n{git['diffstat'] or '(vazio)'}\n\n"
        + f"git status --porcelain:\n{git['status'] or '(limpo)'}\n\n"
        + "=== PEDIDO ORIGINAL DO USUÁRIO ===\n"
        + (fatos["primeiro_pedido"] or "(não capturado)")
        + "\n\n=== RECORTE DA CONVERSA ===\n"
        + (fatos["excerto"] or "(transcript indisponível)")
    )


def _rodape_fatos(fatos: dict, git: dict) -> str:
    ferramentas = (
        ", ".join(f"{k}×{v}" for k, v in sorted(fatos["ferramentas"].items(), key=lambda x: -x[1]))
        or "nenhuma"
    )
    return (
        "<!-- fatos determinísticos do hook de fim de sessão -->\n"
        f"<sub>Registro automático · branch `{git['branch']}` · "
        f"{len(fatos['arquivos_escritos'])} arquivo(s) escrito(s) · "
        f"{len(fatos['comandos'])} comando(s) · ferramentas: {ferramentas}</sub>"
    )


def _arg(argv: list[str], nome: str) -> str | None:
    if nome in argv:
        i = argv.index(nome)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception as e:  # noqa: BLE001 — hook nunca propaga exceção
        print(f"[{ROTULO}] hook falhou sem gravar: {type(e).__name__}: {e}", file=sys.stderr)
        codigo = 0
    sys.exit(codigo)
