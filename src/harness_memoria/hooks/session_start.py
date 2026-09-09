#!/usr/bin/env python3
"""Hook SessionStart — reinjeta a memória do projeto no contexto.

Par do hook de fim de sessão. A evidência que sustenta o desenho é que aderência a
instrução decai DENTRO da sessão, não por causa do formato do arquivo de instruções —
portanto a contramedida é reinjeção, e o momento mais valioso é `source: compact`, quando
o contexto acabou de ser comprimido.

O autoteste confere **fidelidade**, não só que o hook roda: bloco injetado que se apresenta
como completo e não está é pior que bloco ausente, porque não gera gatilho de leitura. Cada
cheque em `conferir_fidelidade` corresponde a um defeito que existiu de verdade.

O bloco tem ORÇAMENTO, e o orçamento não é gosto nosso — ver `TETO_PLATAFORMA_CHARS`. Todo
corte sai pelas máquinas de corte ANUNCIADO que já existem (`adr.indice_compactado` +
`adr.anunciar_corte`, `diario.recortar_entrada` e o teto do digest de becos), nunca por uma
fatia cega no texto montado: fatiar o texto cortaria o índice DEPOIS do cabeçalho que
promete o índice inteiro, que é o falso completo que este arquivo existe para não produzir.

Autoteste:  python src/harness_memoria/hooks/session_start.py --autoteste [--projeto CAMINHO]
"""

from __future__ import annotations

import os
import sys

ROTULO = "contexto"

#: Erro do bootstrap, se houver. O `try/except` que implementa "nunca derrubar a sessão"
#: começava no `__main__`, e o `from harness_memoria...` ficava FORA dele — a única linha
#: sem rede. Reproduzido: com um erro de sintaxe no fim de `config.py` (o que um `git pull`
#: no meio, um arquivo truncado ou um interpretador incompatível produzem) este hook saía
#: com rc=1, stdout vazio e um traceback cru no stderr, sem rótulo dizendo de onde vinha —
#: e a sessão começava sem memória nenhuma e sem aviso.
_ERRO_DE_BOOTSTRAP: str | None = None

#: `_leve`, quando ele importar. Começa em `None` porque ele pode ser o arquivo quebrado —
#: ver o ramo de desistência em `main`.
L = None

try:
    # `os.path`, não `Path(__file__).resolve().parents[2]`: `pathlib` custa 7,2 ms e era o
    # PRIMEIRO import do arquivo, isto é, pago antes de o pré-gate abaixo poder dizer que
    # este hook não tem nada a fazer neste projeto.
    _AQUI = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(_AQUI)))

    from harness_memoria.hooks import _leve as L  # noqa: E402

    # PRÉ-GATE — ver `_leve.gate_barato`. Este hook dispara por `SessionStart` (1-4x por
    # sessão) e por `SubagentStart` (uma vez por Task), e o segundo é o caro: medido p25 de
    # n=12 num projeto sem `.claude/harness.json`, este script como `SubagentStart` custava
    # 115,4 ms contra 46,8 ms dos três hooks já pré-gateados — numa sessão de orquestração
    # com várias Tasks isso multiplica. As duas guardas: `__main__` porque a suíte importa
    # este módulo (um `sys.exit(0)` em tempo de import mataria a coleta do pytest), e
    # `--autoteste` porque lá o projeto vem por `--projeto`, não pelo cwd.
    if __name__ == "__main__" and "--autoteste" not in sys.argv and L.gate_barato() is False:
        L.sair_sem_fazer_nada()

    import re  # noqa: E402
    from dataclasses import replace  # noqa: E402
    from pathlib import Path  # noqa: E402

    from harness_memoria import adr, diario  # noqa: E402
    from harness_memoria.config import Config, ErroDeConfig, carregar, invioaveis  # noqa: E402
    from harness_memoria.hooks import _comum as C  # noqa: E402

    #: A seção de becos da última entrada. O cabeçalho fica no grupo 1 e é PRESERVADO na
    #: substituição: `recortar_entrada` parte a entrada por `^### `, então apagar o cabeçalho
    #: apagaria a seção do recorte por prioridade — e ela é rank 0, a última a sair.
    _SECAO_DE_BECOS = re.compile(
        rf"^(### {re.escape(diario.SECAO_BECOS)}[ \t]*\n)(.*?)(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )
except Exception as e:  # noqa: BLE001 — pacote inconsistente não derruba a sessão
    _ERRO_DE_BOOTSTRAP = f"{type(e).__name__}: {e}"


#: Teto de `additionalContext` na plataforma. **Não é escolha nossa**: acima dele o Claude
#: Code substitui o bloco inteiro por um preview de ~2 KB mais o caminho de um arquivo.
#: Medido num consumidor real de 53 ADRs, o bloco media 15.485 ch (startup) e 16.014
#: (compact), e em 14 das últimas 40 sessões dele foi o preview que chegou — a tese do
#: repositório desligada em ~35% das sessões, sem nada acusar, porque `conferir_fidelidade`
#: conferia a string que este arquivo MONTOU e não a que a plataforma ENTREGOU.
#:
#: Os tetos que o projeto já configurava foram escolhidos um a um, e a soma deles (5.000 da
#: entrada + 4.500 do digest de becos + índice SEM teto nenhum) estourava este número antes
#: de o índice começar. O orçamento abaixo não inventa botão novo — os rejeitados 2 e 4 do
#: diagnóstico descartam `teto_contexto_injetado_chars` e `teto_indice_chars` justamente
#: porque nasceriam `None`, inertes por default: ele reparte o que já existe.
#:
#: PROVENIÊNCIA, porque isto vai envelhecer: o número vem da doc de hooks e da observação
#: acima, não de uma constante do binário. Procurei o literal no executável instalado
#: (2.1.263) e ele não está lá em forma legível, então não há nada para importar nem lugar
#: para conferir numa atualização da plataforma — o sinal de que o teto mudou vai ser o
#: preview voltando a aparecer no transcript.
TETO_PLATAFORMA_CHARS = 10_000

#: Reserva do BLOCO do índice de ADR, prosa inclusa, dentro do orçamento. O índice era a
#: única peça sem teto e a maior do bloco: 6.518-7.724 ch nos consumidores reais, 42-48% do
#: total. 3.500 ch levam ~28 linhas de 120 ch, isto é ~28 ADRs nomeados por disparo, e
#: mantêm o índice na mesma ordem de grandeza da fatia que ele já tinha (35% contra 42-48%).
#: A diferença é que agora ele CABE, e o que não cabe sai anunciado com o TOTAL real e o
#: caminho do README; a alternativa medida era perder o bloco inteiro em 35% das sessões.
PISO_DO_INDICE_CHARS = 3_500

#: Teto do bloco REDUZIDO, o do `SubagentStart`: invioláveis + digest de becos, sem índice
#: de ADR e sem entrada de diário. Teto próprio de propósito — o subagente recebe um bloco
#: por arranque e a conta dele não é a da thread principal. 6.000 ch cabem nos dois itens
#: sem cortar nenhum: as invioláveis medem no máximo 1.200 ch (`max_itens` 8 ×
#: `teto_item_chars` 150; os três CLAUDE.md reais desta máquina dão 6-7 itens) e o digest
#: satura em 4.500. Medido em 10 sessões reais: os subagentes fizeram 491-1313 tool calls
#: contra 32-350 da thread principal, e em 4 delas a MAIORIA das escritas (219 contra 19) —
#: na primeira, 92% das escritas saíram de agentes que não viram inviolável nenhuma.
TETO_SUBAGENTE_CHARS = 6_000

#: Separador entre blocos. O custo dele entra no orçamento.
SEPARADOR = "\n\n---\n\n"

#: Trecho estável da marca de `diario._marca_de_truncamento`, usado pelo cheque 3: item de
#: beco ausente do bloco é falha, EXCETO quando a entrada saiu com a marca — truncar
#: avisando é a política do projeto, e reprovar quem avisou seria o falso positivo que
#: ensina a ignorar o cheque. `tests/test_session_start.py` reprova se a marca divergir.
MARCA_DE_TRUNCAMENTO = "truncada; leia a entrada completa"


def main(argv: list[str] | None = None) -> int:
    if _ERRO_DE_BOOTSTRAP is not None:
        # A mensagem existe para ser lida no dia do `git pull` no meio: rotulada, no stderr,
        # e com a CAUSA (o import que falhou), não com a consequência.
        print(
            f"[{ROTULO}] pacote não importável, sessão sem memória: {_ERRO_DE_BOOTSTRAP}",
            file=sys.stderr,
        )
        return 0

    argv = list(argv if argv is not None else sys.argv[1:])
    C.preparar(ROTULO)
    autoteste = "--autoteste" in argv
    explicito = _arg(argv, "--projeto") if autoteste else None

    if autoteste:
        evento = {
            "source": "compact",
            "cwd": explicito or os.getcwd(),
            "hook_event_name": "SessionStart",
        }
        ctx = _contexto_explicito(Path(explicito)) if explicito else C.contexto(evento, ROTULO)
    else:
        evento = C.ler_evento()
        ctx = C.contexto(evento, ROTULO)

    if ctx is None:
        if autoteste:
            print(
                f"[{ROTULO}] projeto sem `.claude/harness.json` — hook inerte por desenho",
                file=sys.stderr,
            )
        return 0
    raiz, cfg = ctx

    # O payload de `SubagentStart` não tem `source` (tem `agent_id`/`agent_type`), então a
    # ramificação é pelo nome do evento. Subagente recebe o bloco REDUZIDO: ele escreve mais
    # que a thread principal e não vê inviolável nenhuma, mas injetar nele o índice inteiro
    # de ADR e a última entrada do diário seria pagar o bloco completo a cada arranque de
    # Task — e a decisão do projeto foi deixar os dois FORA do bloco reduzido.
    #
    # Confirmado no executável instalado (2.1.263) que a saída deste evento é aproveitada:
    # `if(_o.additionalContexts&&_o.additionalContexts.length>0)ls.push(..._o.additionalContexts)`
    # no tratador rotulado `SubagentStart:${e.agentType}`. Falta a verificação ao vivo com
    # uma Task de verdade, que é o que o registro em `hooks/hooks.json` vai permitir.
    evento_nome = str(evento.get("hook_event_name") or "SessionStart")
    reduzido = evento_nome == "SubagentStart"

    contexto_texto = montar(raiz, cfg, str(evento.get("source") or "startup"), reduzido=reduzido)
    if not contexto_texto:
        return 0

    C.emitir_contexto(evento_nome, contexto_texto)
    if not autoteste:
        return 0

    # O autoteste confere os DOIS blocos e imprime os dois tamanhos, porque os dois são
    # injetados em produção e o reduzido tem teto próprio: conferir só o completo deixaria o
    # bloco novo entrar sem nenhum cheque de fidelidade.
    rc = conferir_fidelidade(raiz, cfg, contexto_texto, reduzido=reduzido)
    outro = montar(raiz, cfg, "startup", reduzido=not reduzido)
    return rc | conferir_fidelidade(raiz, cfg, outro, reduzido=not reduzido)


def montar(raiz: Path, cfg: Config, origem: str, *, reduzido: bool = False) -> str:
    """O bloco injetado, dentro do orçamento e nomeando tudo o que cortou.

    DUAS PASSADAS, e a primeira é a que importa no caso comum: monta as peças no tamanho
    NATURAL (os limites que o projeto configurou) e devolve isso quando cabe. Só quando não
    cabe é que o orçamento reparte. Cortar um bloco que a plataforma entregaria inteiro
    seria jogar contexto fora — medido no corpus de 10 ADRs, o bloco natural mede 9.203 ch e
    a repartição incondicional o levava a 4.845, isto é 4.358 ch de memória descartados sem
    nenhuma necessidade. O preço da segunda passada é reler o diário e os ADRs: medido p25
    de n=25, `montar` sai de 5,00 para 10,25 ms no corpus de 30 ADRs e de 9,22 para 17,90 ms
    no de 60, contra os ~150 ms que este hook paga só de import, uma vez por sessão. E o
    preço só é pago por quem estoura o teto, que é exatamente quem precisa.

    `reduzido=True` é o bloco do `SubagentStart`: invioláveis + digest de becos, com teto
    próprio. Está aqui, e não num script novo, porque é a MESMA montagem com duas peças de
    menos — duas montagens divergiriam na primeira correção de orçamento.
    """
    teto = TETO_SUBAGENTE_CHARS if reduzido else TETO_PLATAFORMA_CHARS
    natural = _blocos(raiz, cfg, origem, reduzido, teto=None, cotas=None)
    if len(_juntar(natural)) <= teto:
        return _juntar(natural)
    cotas = _orcar(teto, natural, cfg)
    return _juntar(_blocos(raiz, cfg, origem, reduzido, teto=teto, cotas=cotas))


def _blocos(
    raiz: Path,
    cfg: Config,
    origem: str,
    reduzido: bool,
    *,
    teto: int | None,
    cotas: tuple[int | None, int | None] | None,
) -> list[str]:
    """As peças do bloco, na ordem de SAÍDA. `teto=None` monta tudo sem orçamento.

    A ordem de MONTAGEM não é a de saída, e as duas razões estão nos comentários abaixo: as
    invioláveis são orçadas primeiro porque nunca podem ser cortadas, e o digest de becos é
    calculado antes da entrada porque quem monta a entrada precisa saber quais itens dela já
    vão no digest.
    """
    # 1. Invioláveis. Nunca cortadas — meia proibição lê como permissão.
    bloco_regras = _bloco_de_regras(raiz, cfg, origem, reduzido)

    # 2. Becos ANTES da entrada. Os becos da última entrada estão SEMPRE duplicados no mesmo
    #    bloco (475 ch verbatim medidos em corpus de 30 ADRs), porque `becos_sem_saida` varre
    #    do mais recente e eles são os primeiros itens. No caso truncado o dano dobrava:
    #    entrada de 5.753 ch com limite 5.000 devolvia 3.681 e descartava `O que foi feito`
    #    para PRESERVAR a seção duplicada, que é rank 0 em `prioridade_secoes`.
    cota_entrada, cota_becos = cotas if cotas else (None, None)
    bloco_becos, becos = _bloco_de_becos(cfg, cota_becos)

    bloco_entrada = ""
    if cfg.diario.injetar_ultima_entrada and not reduzido:
        bloco_entrada = _bloco_da_entrada(cfg, becos, cota_entrada)

    if reduzido:
        return [bloco_regras, bloco_becos]

    # 3. O índice fica com o que sobrou, e o corte dele é em CHARS porque char é o que a
    #    plataforma conta. A moldura (a prosa do bloco) é medida pelo código que a escreve,
    #    com `9999` no lugar do total: o total real só é conhecido depois de ler os ADRs, e
    #    4 dígitos é o pior caso possível no formato de nome de arquivo — a estimativa fica
    #    no máximo 3 ch pessimista, contra o custo de ler todos os arquivos uma vez mais.
    teto_indice = None
    if teto is not None:
        gasto = _com_separador(bloco_regras) + _com_separador(bloco_becos)
        gasto += _com_separador(bloco_entrada)
        teto_indice = teto - gasto - len(_bloco_do_indice(cfg, [], 9999, 0))
    linhas, total, nomeados = adr.indice_compactado(
        cfg.pasta_adr, cfg.adr.limite_indice, teto_indice
    )
    bloco_adr = _bloco_do_indice(cfg, linhas, total, nomeados)
    return [bloco_entrada, bloco_becos, bloco_adr, bloco_regras]


def _orcar(teto: int, natural: list[str], cfg: Config) -> tuple[int | None, int | None]:
    """As cotas de `(entrada, becos)` quando o bloco natural não cabe. Em chars de BLOCO.

    `None` numa das duas significa "fica no tamanho natural" — e não "zero".

    A ordem de quem cede não é gosto: é a granularidade do corte de cada peça.

    1. O ÍNDICE cede primeiro, até `PISO_DO_INDICE_CHARS`, e muitas vezes só ele basta. Era
       a única peça sem teto nenhum, é a maior do bloco (42-48% nos consumidores reais), e o
       corte dele é de uma LINHA por vez, com `anunciar_corte` dizendo o total e onde achar
       o resto.
    2. O DIGEST DE BECOS cede depois, também item por item.
    3. A ENTRADA cede por ÚLTIMO, porque ela é a única peça que cai em DEGRAU: o recorte
       descarta seção inteira, então baixar a cota dela em 70 ch pode derrubar 3.200. Medido
       no corpus de 60 ADRs, com a repartição proporcional que eu tinha escrito primeiro: a
       entrada caía de 3.913 para 649 ch e o bloco fechava em 8.437 de 10.000 — 1.563 ch de
       memória não entregues a ninguém, porque o índice já estava completo e o degrau da
       entrada não tinha como usar a sobra. Cobrando o déficit das peças de corte fino, o
       bloco fecha em ~10.000 com a entrada inteira.

    O piso do digest é UM item (o teto de item do próprio projeto mais a prosa): um item já
    carrega o "N de M" que aponta o resto, e zero itens apagaria o bloco em silêncio — o
    contrário do que este arquivo existe para fazer.
    """
    if len(natural) == 2:  # bloco reduzido: só o digest de becos pode ceder
        regras, _ = natural
        return 0, max(0, teto - _com_separador(regras) - len(SEPARADOR))

    entrada, becos, indice, regras = natural
    reserva = min(PISO_DO_INDICE_CHARS, _com_separador(indice))
    disponivel = max(0, teto - _com_separador(regras) - reserva)
    if _com_separador(entrada) + _com_separador(becos) <= disponivel:
        # A memória recente já cabe no que sobra: as duas ficam NATURAIS e o índice absorve
        # o excesso inteiro. É o caso comum de quem tem corpus grande de ADR.
        return None, None
    if not entrada:
        return None, max(0, disponivel - len(SEPARADOR))
    piso_becos = min(disponivel, _prosa_de_becos(cfg) + cfg.diario.teto_item_beco_chars)
    cota_becos = max(piso_becos, min(_com_separador(becos), disponivel - _com_separador(entrada)))
    return max(0, disponivel - cota_becos - len(SEPARADOR)), max(0, cota_becos - len(SEPARADOR))


def conferir_fidelidade(
    raiz: Path, cfg: Config, contexto_texto: str, *, reduzido: bool = False
) -> int:
    """Confere que o que o bloco PROMETE é o que ele ENTREGA. Roda no CI."""
    falhas: list[str] = []
    teto = TETO_SUBAGENTE_CHARS if reduzido else TETO_PLATAFORMA_CHARS

    # 0. o bloco cabe no que a plataforma ENTREGA. Era o ramo que faltava: os quatro cheques
    #    abaixo conferem o bloco contra si mesmo, e nenhum conferia o bloco contra o teto de
    #    `additionalContext`. Um bloco que se apresenta completo e é substituído por um
    #    preview mais um caminho de arquivo é o pior caso do "truncar calado".
    if len(contexto_texto) > teto:
        # Depois do orçamento de `montar`, a ÚNICA peça que não cede é o bloco de
        # invioláveis — as outras três têm máquina de corte anunciado. Então a instrução
        # aqui é sobre ela: mandar baixar `limite_injecao_chars` seria mandar mexer no que
        # já está sendo cortado.
        falhas.append(
            f"bloco com {len(contexto_texto)} chars, acima do teto de {teto} que a "
            f"plataforma ENTREGA — acima dele o `additionalContext` inteiro é substituído "
            f"por um preview mais um caminho de arquivo. As três peças de memória já são "
            f"cortadas por orçamento; o que sobra é a seção de invioláveis do CLAUDE.md, "
            f"que não é cortada nunca: reduza o número de itens dela"
        )

    if reduzido:
        # O bloco reduzido existe PARA levar as invioláveis a quem escreve sem tê-las lido:
        # se uma delas não chegou, ele não tem por que existir.
        regras = invioaveis(raiz, cfg.reafirmacao)
        for r in regras:
            if r not in contexto_texto:
                falhas.append(f"bloco reduzido (subagente) sem a inviolável: {r[:70]}…")
        return _relatar(
            falhas,
            f"bloco reduzido (subagente) com {len(contexto_texto)} chars e "
            f"{len(regras)} invioláveis",
        )

    todos = adr.indice_para_injecao(cfg.pasta_adr)

    # 1. o índice injetado é o índice inteiro — ou se declara PARCIAL e diz onde está o
    #    resto. O que não se admite é o silêncio: era um corte fixo em 20 derrubando 9 ADRs.
    #    A lista conferida é a de UMA LINHA POR ADR: os aposentados vão agregados no bloco,
    #    e o token `ADR-0005` sobrevive dentro de `ADR-0005→ADR-0019`.
    if todos:
        if "índice PARCIAL" not in contexto_texto:
            for linha in todos:
                num = linha.split(maxsplit=1)[0]
                if num not in contexto_texto:
                    falhas.append(f"{num} está no índice de ADR e não chegou ao contexto")
        elif "este índice está cortado" not in contexto_texto:
            falhas.append("índice cortado sem a nota que diz quantos faltam e onde achá-los")
        elif f"{len(todos)} ADRs" not in contexto_texto:
            falhas.append(
                f"índice cortado sem anunciar o TOTAL real ({len(todos)}) — sem o total, "
                f"quem lê não tem como perceber a diferença"
            )

    # 2. ADR morto nunca aparece sem dizer o que seguir no lugar. `superseded` e não
    #    `STATUS_MORTOS`: `deprecated` é o status de quem NÃO tem sucessor, a auditoria
    #    passou a aceitá-lo, e exigi-lo aqui deixava um ADR `deprecated` PASSANDO em
    #    `python -m harness_memoria.auditar` e REPROVANDO neste autoteste, que é um passo do
    #    CI. Divergência entre os dois canais não tem saída correta nenhuma.
    dados = adr.dados_dos_adrs(cfg.pasta_adr)
    for num, d in dados.items():
        if d["status"] == "superseded" and not d["substituido_por"]:
            falhas.append(
                f"ADR-{num} está superseded e não declara `substituido-por:` — o índice "
                f"injetado não tem como dizer o que seguir no lugar. Se nada o substituiu, "
                f"o status é `deprecated`"
            )

    # 3. o recorte da entrada preserva as seções de retomada, que é o que o diário serve
    if cfg.diario.injetar_ultima_entrada:
        ultima = diario.ultima_entrada(cfg.pasta_diario)
        if ultima:
            _, corpo = ultima
            _, secoes = diario.partir_em_secoes(corpo)
            presentes = [t for t, _ in secoes]
            for alvo in cfg.diario.prioridade_secoes[:3]:
                if any(t.startswith(alvo) for t in presentes) and alvo not in contexto_texto:
                    falhas.append(
                        f"a seção '{alvo}' existe na última entrada e o recorte a descartou"
                    )
            falhas += _becos_perdidos(cfg, corpo, contexto_texto)

    # 4. toda inviolável extraída cabe numa linha. Estourar não trunca — reprova, porque
    #    meia proibição lê como permissão.
    for r in invioaveis(raiz, cfg.reafirmacao):
        if len(r) > cfg.reafirmacao.teto_item_chars:
            falhas.append(
                f"inviolável com {len(r)} chars (teto {cfg.reafirmacao.teto_item_chars}): "
                f"{r[:70]}… — encurte a PRIMEIRA FRASE dela no CLAUDE.md; o resto do "
                f"raciocínio continua no item, só não entra na reafirmação"
            )

    return _relatar(
        falhas,
        f"{len(todos)} ADRs no índice, {len(contexto_texto)} chars injetados "
        f"(teto {teto}), seções de retomada preservadas",
    )


# --------------------------------------------------------------------------- #
# Os blocos
# --------------------------------------------------------------------------- #


def _bloco_de_regras(raiz: Path, cfg: Config, origem: str, reduzido: bool) -> str:
    if not reduzido and origem != "compact":
        return ""
    regras = invioaveis(raiz, cfg.reafirmacao)
    if not regras:
        return ""
    itens = "\n".join(f"- {r}" for r in regras)
    if reduzido:
        return (
            "## Invioláveis deste projeto (você é um subagente e não leu o `CLAUDE.md`)\n\n" + itens
        )
    return (
        "## Aviso pós-compactação\n\n"
        "O contexto acabou de ser comprimido. Antes de continuar, reconfirme as "
        "invioláveis do `CLAUDE.md`:\n" + itens
    )


def _bloco_de_becos(cfg: Config, cota: int | None) -> tuple[str, list[str]]:
    """`(bloco, itens)`. `cota` é o espaço do BLOCO, prosa inclusa; `None` usa o configurado.

    O laço no fim não é paranoia: `teto_becos_chars` limita a SOMA DO TEXTO dos itens, e o
    bloco acrescenta 3 ch por item que ninguém contava (o `- ` na frente e o `\\n` entre
    eles). Reproduzido pelo teste do bloco reduzido: com o teto do digest em 12.000 e o do
    subagente em 6.000, o bloco saía com 6.031 ch — 31 ch acima, isto é 11 itens de
    renderização. Tirar item do FIM é o corte correto porque a lista vem do mais recente
    para o mais antigo, e `_moldar_becos` recalcula o "N de M" e o "os outros N estão em…" a
    cada volta, então o que sai continua anunciado. O piso é UM item: zero itens apagaria o
    bloco em silêncio.
    """
    teto_itens = cfg.diario.teto_becos_chars
    if cota is not None:
        teto_itens = max(0, min(teto_itens, cota - _prosa_de_becos(cfg)))
    becos, total = diario.becos_sem_saida(
        cfg.pasta_diario, replace(cfg.diario, teto_becos_chars=teto_itens)
    )
    bloco = _moldar_becos(cfg, becos, total)
    while cota is not None and len(becos) > 1 and len(bloco) > cota:
        becos = becos[:-1]
        bloco = _moldar_becos(cfg, becos, total)
    return bloco, becos


def _prosa_de_becos(cfg: Config) -> int:
    """A prosa do bloco de becos, medida pelo código que a escreve.

    Item fictício porque `_moldar_becos` devolve "" para lista vazia — e é a frase do "os
    outros N estão em..." que faz esta prosa valer ~300 ch, não o cabeçalho. Medir em vez de
    fixar uma constante ao lado: quem editar a frase não tem como esquecer o orçamento.
    """
    return len(_moldar_becos(cfg, ["x"], 9999)) - len("- x")


def _moldar_becos(cfg: Config, becos: list[str], total: int) -> str:
    if not becos:
        return ""
    faltam = total - len(becos)
    resto = (
        f"\n\nOs outros {faltam} estão nas seções `### {diario.SECAO_BECOS}` de "
        f"`{cfg.diario.pasta}/` e `{cfg.diario.pasta}/arquivo/` — procure por esse título "
        f"antes de insistir numa abordagem que parece nova."
        if faltam > 0
        else ""
    )
    return (
        f"## Becos sem saída já explorados ({len(becos)} de {total}, "
        f"do mais recente para o mais antigo)\n\n"
        + "\n".join(f"- {item}" for item in becos)
        + resto
    )


def _bloco_da_entrada(cfg: Config, becos: list[str], cota: int | None) -> str:
    ultima = diario.ultima_entrada(cfg.pasta_diario)
    if not ultima:
        return ""
    nome, corpo = ultima
    onde = f"{cfg.diario.pasta}/{nome}"
    cabecalho = f"## Memória do projeto — última entrada do diário (`{onde}`)\n\n"
    corpo = _apontar_becos_do_digest(corpo, becos, cfg)
    limite = cfg.diario.limite_injecao_chars
    if cota is not None:
        limite = max(0, min(limite, cota - len(cabecalho)))
    return cabecalho + diario.recortar_entrada(
        corpo, replace(cfg.diario, limite_injecao_chars=limite), onde
    )


def _bloco_do_indice(cfg: Config, linhas: list[str], total: int, nomeados: int) -> str:
    """O bloco do índice. Com `linhas=[]` e `total` fictício, é a MOLDURA — ver `montar`."""
    if not total:
        return ""
    # O total vai em número de propósito: se esta lista for cortada, a divergência entre o
    # número anunciado e o que está em tela denuncia o corte.
    onde = f"{cfg.adr.pasta}/README.md"
    completo = "índice completo" if nomeados >= total else "índice PARCIAL"
    corpo = "".join(f"- {linha}\n" for linha in linhas)
    # A frase sobre `superseded` sai quando a linha agregada dos aposentados existe: ela já
    # diz "NÃO siga — substituto ao lado", e repetir em prosa o que a linha diz é gordura.
    sobre_mortos = (
        ""
        if any(linha.startswith(adr.PREFIXO_APOSENTADOS) for linha in linhas)
        else " ADR `superseded` **não** se segue — siga o substituto indicado na linha."
    )
    return (
        f"## Decisões arquiteturais vigentes ({completo}, {total} ADRs)\n\n"
        + corpo
        + f"\nDetalhe em `{cfg.adr.pasta}/`. Um ADR aceito tem precedência sobre o "
        "CLAUDE.md. Se sua tarefa contradiz um deles, PARE e pergunte."
        + sobre_mortos
        + adr.anunciar_corte(total, nomeados, onde)
    )


# --------------------------------------------------------------------------- #
# Becos: o mesmo item não é pago duas vezes no mesmo bloco
# --------------------------------------------------------------------------- #


def _itens_da_secao(corpo: str) -> list[str]:
    """Os itens de `### Tentativas descartadas` da entrada, normalizados a uma linha."""
    achou = _SECAO_DE_BECOS.search(corpo)
    if not achou:
        return []
    itens = re.split(r"^- ", achou.group(2), flags=re.MULTILINE)[1:]
    return [" ".join(i.split()) for i in itens if i.strip()]


def _no_digest(item: str, becos: list[str], cfg: Config) -> bool:
    """O item da entrada já está no digest?

    Respondido com a MESMA função que montou o digest (`diario._resumir_beco`) e não com uma
    heurística local: duas implementações de "este item é aquele" divergem na primeira
    correção, e a versão barata — comparar os 60 primeiros chars — é justamente a chave de
    dedup que se mediu perder 93% dos itens de um corpus.
    """
    resumido = diario._resumir_beco(item, cfg.diario.teto_item_beco_chars)
    return any(b.endswith(resumido) for b in becos)


def _apontar_becos_do_digest(corpo: str, becos: list[str], cfg: Config) -> str:
    """Troca por um ponteiro os itens da seção que comprovadamente entraram no digest.

    Só os que entraram, e com os DOIS números. A guarda ingênua ("se `becos` não está vazio,
    apague a seção") apagaria os itens que o teto de 4.500 ch deixou de fora — truncar
    calado com selo de completude, que é o defeito mais caro do repositório.
    """
    itens = _itens_da_secao(corpo)
    if not itens:
        return corpo
    dentro = [i for i in itens if _no_digest(i, becos, cfg)]
    if not dentro:
        return corpo
    fora = [i for i in itens if i not in dentro]
    if fora:
        nota = (
            f"> O digest de becos abaixo já traz {_contar(len(dentro), 'item', 'itens')} desta "
            f"seção, de {len(itens)}; {_contar(len(fora), 'item continua', 'itens continuam')} "
            f"aqui.\n"
        )
    else:
        nota = (
            f"> O digest de becos abaixo já traz esta seção inteira, com a data — "
            f"{_contar(len(itens), 'item', 'itens')}.\n"
        )
    troca = "\n" + nota + "".join(f"- {i}\n" for i in fora) + "\n"
    return _SECAO_DE_BECOS.sub(lambda m: m.group(1) + troca, corpo, count=1)


def _becos_perdidos(cfg: Config, corpo: str, contexto_texto: str) -> list[str]:
    """Cheque 3, a metade que faltava: cada ITEM da seção chegou ao bloco?

    O cheque antigo olhava só o TÍTULO da seção, então trocar os itens por um ponteiro
    passaria verde mesmo que o ponteiro mentisse. Duas frouxuras deliberadas: a comparação é
    feita no texto NORMALIZADO (item de duas linhas na entrada é um item só), e a marca de
    truncamento dispensa o cheque — quando a entrada saiu truncada ela AVISOU, e reprovar
    quem avisou seria o falso positivo que ensina a ignorar o cheque.
    """
    if MARCA_DE_TRUNCAMENTO in contexto_texto:
        return []
    normalizado = " ".join(contexto_texto.split())
    perdidos = []
    for item in _itens_da_secao(corpo):
        resumido = diario._resumir_beco(item, cfg.diario.teto_item_beco_chars)
        if item not in normalizado and resumido not in normalizado:
            perdidos.append(
                f"o beco '{item[:60]}…' está na última entrada e não chegou ao bloco — "
                f"nem em texto nem no digest"
            )
    return perdidos


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #


def _juntar(blocos: list[str]) -> str:
    return SEPARADOR.join(b for b in blocos if b)


def _contar(n: int, um: str, varios: str) -> str:
    """Concordância de número: `1 item` / `3 itens`.

    O bloco é lido por um modelo, e "Os 1 itens desta seção" gasta atenção com nada.
    """
    return f"{n} {um if n == 1 else varios}"


def _com_separador(bloco: str) -> int:
    """O custo do bloco no orçamento. Conta o separador do ÚLTIMO bloco também, que não
    existe: 7 ch de pessimismo, contra uma aritmética que depende de quantas peças entraram.
    """
    return len(bloco) + len(SEPARADOR) if bloco else 0


def _relatar(falhas: list[str], resumo: str) -> int:
    for f in falhas:
        print(f"[{ROTULO}] FALHA: {f}", file=sys.stderr)
    if not falhas:
        print(f"[{ROTULO}] ok — {resumo}", file=sys.stderr)
    return 1 if falhas else 0


def _contexto_explicito(raiz: Path) -> tuple[Path, Config] | None:
    """Gate para o `--projeto` do autoteste, sem passar por `raiz_projeto`.

    `raiz_projeto` dá PRIORIDADE a `CLAUDE_PROJECT_DIR` sobre os candidatos, e é a
    precedência certa no caminho de hook, onde o candidato é o `cwd` do evento e não uma
    escolha de ninguém. No autoteste o candidato é uma escolha explícita do operador: dentro
    de uma sessão do Claude Code a variável está SEMPRE setada, e `--autoteste --projeto
    <fixture>` conferia o projeto CORRENTE e respondia "ok" sobre o alvo errado — o pior
    resultado possível para um cheque.
    """
    try:
        cfg = carregar(raiz)
    except ErroDeConfig as e:
        print(f"[{ROTULO}] config inválida, hook inerte: {e}", file=sys.stderr)
        return None
    return None if cfg is None else (raiz, cfg)


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
        print(f"[{ROTULO}] hook falhou: {type(e).__name__}: {e}", file=sys.stderr)
        codigo = 0
    sys.exit(codigo)
