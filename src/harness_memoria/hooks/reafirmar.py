#!/usr/bin/env python3
"""Hook PostToolUse — reafirma as invioláveis a cada N escritas da sessão.

Fecha o único vão que a evidência aponta e o resto do harness não cobria. O estudo fatorial
que originou este hook (arXiv:2605.10039, 1.650 sessões de Claude Code) mede o decaimento
**por passo dentro da sessão** — cada função gerada corresponde a ~5,6% menos chance de
conformidade (OR 0,944) — e nenhuma variável de formato de arquivo tem efeito detectável.
A contramedida é reinjeção; o harness reinjetava só em `SessionStart`, isto é, num evento
que numa sessão longa acontece uma vez e nunca mais.

Registrado `async: true` no `hooks.json`, e a premissa que este docstring afirmava antes
era FALSA: dizia "saída de hook `async` é descartada pelo Claude Code", e por isso o hook
era síncrono. Na versão instalada o binário colhe o resultado do hook assíncrono e entrega
o `additionalContext` no turno seguinte — não descarta nada. O preço é um turno de atraso
numa mensagem cuja função é combater decaimento ao longo de dezenas de passos; o ganho é
não bloquear ~145 ms em cada escrita, sendo que 14 de cada 15 execuções não emitem nada
(~15 s numa sessão de 120 escritas). Não existe uma terceira via: `asyncRewake` dispara
pelo exit 2, que no runner é caminho de *blocking error* — semântica de bloqueio para o que
é lembrete.

As regras vêm do `CLAUDE.md` do projeto, extraídas — não copiadas. Ver `config.invioaveis`.

Autoteste:  python src/harness_memoria/hooks/reafirmar.py --autoteste [--projeto CAMINHO]
"""

from __future__ import annotations

import os
import sys

ROTULO = "reafirmar"
FERRAMENTAS_DE_ESCRITA = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

#: Erro do bootstrap, se houver. O `from harness_memoria...` ficava FORA do `try/except` que
#: implementa "nunca derrubar a sessão" — a única linha sem rede. Com um erro de sintaxe no
#: fim de `config.py` este hook saía com rc=1 e traceback cru no stderr, a cada escrita.
_ERRO_DE_BOOTSTRAP: str | None = None

#: `_leve`, quando ele importar. Começa em `None` porque ele pode ser o arquivo quebrado —
#: ver o ramo de desistência em `main`.
L = None

try:
    # `os.path`, não `Path(__file__).resolve().parents[2]`: `pathlib` custa 7,2 ms e era o
    # primeiro import do arquivo, antes de o pré-gate poder desistir.
    _AQUI = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(_AQUI)))

    from harness_memoria.hooks import _leve as L  # noqa: E402

    # PRÉ-GATE — ver `_leve.gate_barato`. Num projeto sem `.claude/harness.json` este hook
    # não emite nada, e pagava 85,6 ms de import para descobrir. Medido p25 de n=40 rodadas
    # intercaladas, cenário sem config: 150,6 → 55,9 ms (piso 44,3). As duas guardas:
    # `__main__` porque a suíte importa este
    # módulo (um `sys.exit(0)` em tempo de import mataria a coleta do pytest), e
    # `--autoteste` porque lá o projeto vem por `--projeto`, não pelo cwd.
    if __name__ == "__main__" and "--autoteste" not in sys.argv and L.gate_barato() is False:
        L.sair_sem_fazer_nada()

    import json  # noqa: E402
    from pathlib import Path  # noqa: E402  — grátis aqui: `config` importa `pathlib`

    from harness_memoria.config import Config, invioaveis  # noqa: E402
    from harness_memoria.hooks import _comum as C  # noqa: E402
except Exception as e:  # noqa: BLE001 — pacote inconsistente não derruba a sessão
    _ERRO_DE_BOOTSTRAP = f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    if _ERRO_DE_BOOTSTRAP is not None:
        aviso = f"[{ROTULO}] pacote não importável, hook inerte: {_ERRO_DE_BOOTSTRAP}"
        # Quando o arquivo quebrado é o próprio `_leve`, `L` não existe: medido, a mensagem
        # saía `NameError: name 'L' is not defined` e apontava para este arquivo em vez do
        # truncado. `sys` é import do topo, fora do `try`.
        if L is None:
            print(aviso, file=sys.stderr)
            return 0
        L.sair_sem_fazer_nada(aviso)
    argv = list(argv if argv is not None else sys.argv[1:])
    C.preparar(ROTULO)
    if "--autoteste" in argv:
        return _autoteste(_arg(argv, "--projeto") or os.getcwd())

    # O `claude -p` que narra o diário também dispara PostToolUse. Ele não é uma sessão de
    # desenvolvimento e não deve consumir contador nem receber lembrete.
    if C.narrando():
        return 0

    evento = C.ler_evento()
    if str(evento.get("tool_name") or "") not in FERRAMENTAS_DE_ESCRITA:
        return 0

    ctx = C.contexto(evento, ROTULO)
    if ctx is None:
        return 0
    raiz, cfg = ctx
    if not cfg.reafirmacao.habilitado:
        return 0

    contagem = C.incrementar_contador(raiz, str(evento.get("session_id") or "sem-sessao"))
    if contagem <= 0 or contagem % cfg.reafirmacao.intervalo_escritas != 0:
        return 0

    msg = montar_mensagem(raiz, cfg, contagem)
    if msg:
        C.emitir_contexto("PostToolUse", msg)
    return 0


def montar_mensagem(raiz: Path, cfg: Config, contagem: int) -> str:
    """A reafirmação. Vazia quando o projeto não tem invioláveis extraíveis.

    Vazia é o comportamento correto nesse caso: inventar regra genérica ("siga as boas
    práticas") gastaria contexto para não dizer nada, e a ausência da seção no CLAUDE.md é
    reprovada pela auditoria, que é o lugar de reclamar disso.
    """
    regras = invioaveis(raiz, cfg.reafirmacao)
    if not regras:
        return ""
    linhas = [
        f"Reafirmação automática do harness — {contagem} escritas nesta sessão "
        f"(aderência decai por passo).",
        f"Invioláveis do CLAUDE.md de `{cfg.projeto}`, em uma linha cada:",
    ]
    linhas += [f"· {r}" for r in regras]
    if cfg.reafirmacao.rodape:
        linhas.append(cfg.reafirmacao.rodape)
    return "\n".join(linhas)


def _autoteste(projeto: str) -> int:
    """Simula uma sessão de escritas e confere QUANDO a reafirmação sai."""
    # `subprocess` só é usado aqui, para re-executar este próprio script. No topo do módulo
    # ele custava 6,8 ms em CADA escrita da sessão, para nada.
    import subprocess
    import tempfile

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
    eu = os.path.realpath(__file__)
    intervalo = cfg.reafirmacao.intervalo_escritas

    # O filho é o hook DE VERDADE, sem `--autoteste`, então o pré-gate vale para ele. Duas
    # coisas tinham de mudar aqui por causa disso, e as duas são o mesmo bug: o filho
    # herdava o ambiente do autoteste em vez de receber o projeto que se pediu para testar.
    #
    # * `cwd=raiz` — sem isso o filho herda o cwd do PAI, e rodar
    #   `reafirmar.py --autoteste --projeto <com-config>` de dentro de um projeto sem
    #   `harness.json` passava de "todos os casos corretos" para "1 caso(s) com falha · sai
    #   em [15, 30], saiu em []". A raiz do harness passou a ter `CLAUDE.md` (ADR-0001),
    #   então este é o caminho que o job `autotestes` exercita de verdade.
    # * `CLAUDE_PROJECT_DIR` fora do ambiente — ela é o PRIMEIRO candidato de
    #   `config.raiz_projeto` e do pré-gate, e ganha do `cwd`. Rodar o autoteste de dentro
    #   de uma sessão do Claude Code fazia o filho auditar o projeto da sessão, não o de
    #   `--projeto`.
    ambiente = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}

    def disparar(ferramenta: str, sessao: str) -> bool:
        entrada = json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": ferramenta,
                "session_id": sessao,
                "cwd": str(raiz),
            }
        )
        r = subprocess.run(
            [sys.executable, eu],
            input=entrada,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(raiz),
            env=ambiente,
        )
        return "additionalContext" in (r.stdout or "")

    with tempfile.TemporaryDirectory() as tmp:
        sessao = "autoteste-" + os.path.basename(tmp)

        saiu_em = [i for i in range(1, 2 * intervalo + 1) if disparar("Write", sessao)]
        esperado = [intervalo, 2 * intervalo]
        ok = saiu_em == esperado
        falhas += 0 if ok else 1
        print(f"{'ok   ' if ok else 'FALHA'} sai em {esperado}, saiu em {saiu_em}")

        outra = sessao + "-b"
        saiu = disparar("Write", outra)
        ok = not saiu
        falhas += 0 if ok else 1
        print(
            f"{'ok   ' if ok else 'FALHA'} contador é por sessão "
            f"(1ª escrita da nova: {'saiu' if saiu else 'não saiu'})"
        )

        antes = C.ler_contador(raiz, outra)
        disparar("Bash", outra)
        depois = C.ler_contador(raiz, outra)
        ok = antes == depois
        falhas += 0 if ok else 1
        print(f"{'ok   ' if ok else 'FALHA'} Bash não incrementa ({antes} → {depois})")

        for s in (sessao, outra):
            C.apagar_contador(raiz, s)

    msg = montar_mensagem(raiz, cfg, cfg.reafirmacao.intervalo_escritas)
    regras = invioaveis(raiz, cfg.reafirmacao)
    ok = bool(regras)
    falhas += 0 if ok else 1
    print(f"{'ok   ' if ok else 'FALHA'} extraiu {len(regras)} inviolável(is) do CLAUDE.md")

    # Teto por item: a auditoria é quem reprova, mas o autoteste imprime para o número
    # aparecer junto do custo da mensagem.
    longas = [r for r in regras if len(r) > cfg.reafirmacao.teto_item_chars]
    ok = not longas
    falhas += 0 if ok else 1
    print(
        f"{'ok   ' if ok else 'FALHA'} toda inviolável cabe em "
        f"{cfg.reafirmacao.teto_item_chars} chars"
        + (f" — estouram: {[r[:50] for r in longas]}" if longas else "")
    )

    custo = len(msg) / cfg.reafirmacao.intervalo_escritas if msg else 0
    print(
        f"\n{'todos os casos corretos' if not falhas else f'{falhas} caso(s) com falha'} · "
        f"mensagem: {len(msg)} chars a cada {intervalo} escritas "
        f"(~{custo:.0f} chars amortizados por escrita)"
    )
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
    except Exception as e:  # noqa: BLE001 — hook nunca propaga exceção
        print(f"[{ROTULO}] hook falhou: {type(e).__name__}: {e}", file=sys.stderr)
        codigo = 0
    sys.exit(codigo)
