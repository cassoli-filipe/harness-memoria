#!/usr/bin/env python3
"""Hook PreCompact — instrui o sumarizador a preservar invioláveis e IDs de ADR ANTES da
compactação, em vez de reagir ao fato consumado.

Hoje o harness só PERCEBE a compactação depois dela: `SessionStart` detecta `source:
compact` e reinjeta o bloco inteiro (11.031 ch medidos num consumidor real). Este hook roda
ANTES, e a saída dele entra no resumo em si — confirmado lendo o binário instalado
(2.1.263), função `AJ`: o `newCustomInstructions` que alimenta o sumarizador é o `join` das
saídas STDOUT (trimadas) dos hooks de `PreCompact` que terminaram bem e não foram
bloqueados; `userDisplayMessage` só alimenta a exibição, não o resumo. Por isso a saída AQUI
é texto CRU — não `C.emitir_contexto`, não JSON — e por isso o ganho é de CUSTO DE CONTEXTO
ZERO: não injeta bloco novo, influencia o que a compactação decide preservar dentro do
próprio resumo. O bloco pós-compactação do `SessionStart` continua existindo: este hook
INSTRUI, aquele CONFERE.

`exit 2` em `PreCompact` BLOQUEIA A COMPACTAÇÃO inteira — confirmado no mesmo binário, a
string `Reactive compact blocked by PreCompact hook:` existe nele e é usada exatamente
assim. É o oposto do que "nunca derrubar a sessão" pede de um hook deste pacote: os outros
cinco hooks já saem sempre com 0, mas aqui sair com 2 por engano tem um efeito que nenhum
deles tem (parar a compactação, não só ficar sem efeito). Por isso o `except` do módulo
inteiro devolve 0 sem exceção, e não há nenhum caminho de código neste arquivo que produza
outro código de saída.

Registrado com `matcher: "manual|auto"` — o campo que a plataforma casa não é `source`
(como em `SessionStart`), é `trigger` (confirmado no mesmo binário: `matchQuery:t.trigger`,
`case"PreCompact":case"PostCompact":return e.trigger`). O payload do hook tem
`hook_event_name`, `trigger` e `custom_instructions` (o que já existia antes deste hook
rodar, por exemplo de um `/compact <instrução>` manual) — este hook não lê `custom_instructions`,
só acrescenta.

Autoteste:  python src/harness_memoria/hooks/pre_compact.py --autoteste [--projeto CAMINHO]
"""

from __future__ import annotations

import os
import sys

ROTULO = "pre_compact"

#: Erro do bootstrap, se houver. Mesmo padrão dos outros cinco hooks: o `try/except` que
#: implementa "nunca derrubar a sessão" tem de cobrir o `from harness_memoria...` também,
#: não só o corpo de `main()` — ver achado 7 do crítico, já corrigido nos outros cinco.
_ERRO_DE_BOOTSTRAP: str | None = None

#: `_leve`, quando ele importar. Começa em `None` porque ele pode ser o arquivo quebrado —
#: ver o ramo de desistência em `main`.
L = None

try:
    # `os.path`, não `Path(__file__).resolve().parents[2]`: `pathlib` custa 7,2 ms e era o
    # PRIMEIRO import do arquivo, pago antes de o pré-gate abaixo poder desistir.
    _AQUI = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(_AQUI)))

    from harness_memoria.hooks import _leve as L  # noqa: E402

    # PRÉ-GATE — ver `_leve.gate_barato`. Medido p25 de n=12 num projeto sem
    # `.claude/harness.json`: este hook custava 88,5 ms contra 46,8 ms dos três hooks já
    # pré-gateados, para um evento que na melhor das hipóteses não tem nada a fazer aqui. As
    # duas guardas: `__main__` porque a suíte importa este módulo (um `sys.exit(0)` em tempo
    # de import mataria a coleta do pytest), e `--autoteste` porque lá o projeto vem por
    # `--projeto`, não pelo cwd.
    if __name__ == "__main__" and "--autoteste" not in sys.argv and L.gate_barato() is False:
        L.sair_sem_fazer_nada()

    from pathlib import Path  # noqa: E402

    from harness_memoria.config import Config, invioaveis  # noqa: E402
    from harness_memoria.hooks import _comum as C  # noqa: E402
except Exception as e:  # noqa: BLE001 — pacote inconsistente não derruba a sessão
    _ERRO_DE_BOOTSTRAP = f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    if _ERRO_DE_BOOTSTRAP is not None:
        print(
            f"[{ROTULO}] pacote não importável, hook inerte: {_ERRO_DE_BOOTSTRAP}",
            file=sys.stderr,
        )
        return 0

    argv = list(argv if argv is not None else sys.argv[1:])
    C.preparar(ROTULO)
    if "--autoteste" in argv:
        return _autoteste(_arg(argv, "--projeto") or os.getcwd())

    evento = C.ler_evento()
    ctx = C.contexto(evento, ROTULO)
    if ctx is None:
        return 0
    raiz, cfg = ctx

    instrucao = montar_instrucao(raiz, cfg)
    if instrucao:
        # STDOUT CRU de propósito: isto vira `customInstructions` do sumarizador, não
        # `additionalContext` — não passa por `C.emitir_contexto`, que empacotaria em JSON
        # e faria a plataforma tratar como bloco de contexto, não como instrução de resumo.
        print(instrucao)
    return 0


def montar_instrucao(raiz: Path, cfg: Config) -> str:
    """O parágrafo que sobrevive DENTRO do resumo. Vazio quando não há inviolável extraível.

    As mesmas invioláveis que `reafirmar` reafirma e `session_start` reinjeta — extraídas,
    nunca copiadas (`config.invioaveis`). Vazio é o comportamento correto quando o projeto
    não tem seção de invioláveis: inventar regra genérica gastaria a instrução para não
    dizer nada, e a ausência da seção já é reprovada pela auditoria.
    """
    regras = invioaveis(raiz, cfg.reafirmacao)
    if not regras:
        return ""
    linhas = ["No resumo que você vai escrever agora, preserve:"]
    linhas += [f"- {r}" for r in regras]
    linhas.append(
        "- os IDs `ADR-NNNN` citados nesta sessão e qualquer abordagem descartada, com o motivo"
    )
    return "\n".join(linhas)


def _autoteste(projeto: str) -> int:
    from harness_memoria.config import ErroDeConfig, carregar, raiz_projeto

    raiz = raiz_projeto(projeto)
    try:
        cfg = carregar(raiz)
    except ErroDeConfig as e:
        print(f"FALHA config inválida: {e}")
        return 1
    if cfg is None:
        print(f"[{ROTULO}] {raiz} não tem `.claude/harness.json` — hook inerte por desenho")
        return 0

    falhas = 0
    texto = montar_instrucao(raiz, cfg)
    ok = bool(texto)
    falhas += 0 if ok else 1
    print(f"{'ok   ' if ok else 'FALHA'} instrução não vazia com config ({len(texto)} chars)")

    regras = invioaveis(raiz, cfg.reafirmacao)
    for r in regras:
        ok = r in texto
        falhas += 0 if ok else 1
        if not ok:
            print(f"FALHA inviolável ausente da instrução: {r[:60]}…")

    ok = "ADR-NNNN" in texto
    falhas += 0 if ok else 1
    print(f"{'ok   ' if ok else 'FALHA'} instrução pede para preservar IDs de ADR e becos")

    print(f"\n{'todos os casos corretos' if not falhas else f'{falhas} caso(s) com falha'}")
    return 1 if falhas else 0


def _arg(argv: list[str], nome: str) -> str | None:
    if nome in argv:
        i = argv.index(nome)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception as e:  # noqa: BLE001 — hook nunca propaga exceção, e nunca em `exit 2`:
        # `PreCompact` trata 2 como bloqueio da compactação, que nenhum outro hook deste
        # pacote faz — ver o docstring. `sys.exit` abaixo nunca recebe outro valor além de 0
        # ou do `int` que `main()`/`_autoteste` devolvem, e nenhum dos dois usa 2.
        print(f"[{ROTULO}] hook falhou: {type(e).__name__}: {e}", file=sys.stderr)
        codigo = 0
    sys.exit(codigo)
