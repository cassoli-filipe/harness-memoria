#!/usr/bin/env python3
"""Hook PostToolUse — formata o arquivo recém-editado, se o formatador existir.

Deliberadamente silencioso e tolerante: numa máquina sem as dependências instaladas o hook
não faz nada e não reclama. Formatação é responsabilidade do formatador, não do CLAUDE.md —
regra de estilo em arquivo de instrução gasta contexto para dizer o que uma ferramenta já
garante.

Os formatadores vêm de `formatadores` no `harness.json`, porque são a parte mais
project-specific do harness: `ruff`+`prettier` no primeiro projeto, e nada garante que o
próximo tenha nem um nem outro. Cada item:

    {"extensoes": [".py"], "comando": ["ruff", "format", "{arquivo}"], "cwd": "."}

`{arquivo}` é substituído pelo caminho absoluto. Comando cujo executável não está no PATH é
ignorado sem ruído. `cwd` é relativo à raiz do projeto e opcional.

Autoteste:  python src/harness_memoria/hooks/formatar.py --autoteste [--projeto CAMINHO]
"""

from __future__ import annotations

import os
import sys

ROTULO = "formatar"
TIMEOUT_S = 25

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

    # PRÉ-GATE — ver `_leve.gate_barato`. Medido p25 de n=40 rodadas intercaladas, cenário
    # sem config: 141,5 → 53,5 ms (piso 44,3). As duas guardas: `__main__` porque a suíte
    # pode importar este módulo
    # (um `sys.exit(0)` em tempo de import mataria a coleta do pytest), e `--autoteste`
    # porque lá o projeto vem por `--projeto`, não pelo cwd.
    if __name__ == "__main__" and "--autoteste" not in sys.argv and L.gate_barato() is False:
        L.sair_sem_fazer_nada()

    from pathlib import Path  # noqa: E402  — grátis aqui: `config` importa `pathlib`

    from harness_memoria.hooks import _comum as C  # noqa: E402
except Exception as e:  # noqa: BLE001 — pacote inconsistente não derruba a sessão
    _ERRO_DE_BOOTSTRAP = f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    if _ERRO_DE_BOOTSTRAP is not None:
        aviso = f"[{ROTULO}] pacote não importável, hook inerte: {_ERRO_DE_BOOTSTRAP}"
        # Com `_leve.py` truncado, `L` não existe e o `L.sair_sem_fazer_nada` abaixo virava
        # `NameError`, que o `except` do `__main__` deste arquivo engole SEM imprimir nada —
        # medido: stderr completamente vazio, nos três hooks o pior caso era este. Um hook
        # silenciosamente inerte é o modo de falha mais caro do harness, porque não faz
        # ruído. `sys` é import do topo, fora do `try`.
        if L is None:
            print(aviso, file=sys.stderr)
            return 0
        L.sair_sem_fazer_nada(aviso)
    argv = list(argv if argv is not None else sys.argv[1:])
    C.preparar(ROTULO)
    if "--autoteste" in argv:
        return _autoteste(_arg(argv, "--projeto") or os.getcwd())

    evento = C.ler_evento()
    ctx = C.contexto(evento, ROTULO)
    if ctx is None:
        return 0
    raiz, cfg = ctx

    entrada = evento.get("tool_input") or {}
    caminho = entrada.get("file_path") if isinstance(entrada, dict) else None
    if not isinstance(caminho, str):
        return 0
    p = Path(caminho)
    if not p.exists():
        return 0

    for regra in cfg.formatadores:
        _talvez_formatar(regra, p, raiz)
    return 0


def _executavel(nome: str) -> str | None:
    """Caminho do formatador no PATH, ou `None`. UMA chamada de `shutil.which`, não três.

    Havia `which(nome) or which(f"{nome}.cmd") or which(f"{nome}.exe")` em três sítios, para
    cobrir o Windows. É desperdício puro, e foi provado por sondagem: com `PATHEXT` ausente,
    vazio, restrito ou completo, o sufixo explícito NUNCA acha algo que o nome puro não ache
    — `shutil.which` já expande `PATHEXT` sozinho. Em PATH POSIX (o ubuntu do CI) as duas
    chamadas extras nem tinham como achar nada. Medido com `.py` e `ruff` fora do PATH
    (o caso comum: `ruff` mora no `.venv`): 179,3 → 163,2 ms. `which` custa 9,6 ms quando
    não acha e 3,3 quando acha, com PATH de 59 entradas.
    """
    import shutil

    return shutil.which(nome)


def _talvez_formatar(regra: dict, arquivo: Path, raiz: Path) -> None:
    extensoes = tuple(str(e).lower() for e in (regra.get("extensoes") or ()))
    if arquivo.suffix.lower() not in extensoes:
        return
    bruto = list(regra.get("comando") or ())
    if not bruto:
        return

    # `shutil` (10,0 ms) e `subprocess` (6,8 ms) entram DEPOIS dos dois testes acima, e não
    # no topo da função: `_talvez_formatar` é chamada para TODA regra do projeto e a maioria
    # sai no teste de extensão — uma escrita em `.md` num projeto que só configura `.py` não
    # tem por que pagar nada. No topo do módulo não capturava nada. Medido, escrita `.py`
    # com `ruff` fora do PATH: 146,2 → 123,8 ms (p25, n=30).
    import contextlib
    import subprocess

    exe = _executavel(bruto[0])
    if not exe:
        return  # máquina sem a ferramenta: silêncio, não é problema do harness
    args = [exe] + [str(a).replace("{arquivo}", str(arquivo)) for a in bruto[1:]]
    cwd = raiz / str(regra.get("cwd") or ".")
    # Guarda de exigência: alguns formatadores só fazem sentido com o projeto instalado
    # (`prettier` sem `node_modules` falha em toda escrita e polui o log).
    exige = regra.get("exige")
    if exige and not (raiz / str(exige)).exists():
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            cwd=str(cwd) if cwd.exists() else None,
        )


def _autoteste(projeto: str) -> int:
    """Lista os formatadores configurados e diz quais estão disponíveis nesta máquina."""
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

    regras = cfg.formatadores
    if not regras:
        print(f"[{ROTULO}] nenhum formatador configurado — hook inerte neste projeto")
        return 0
    for regra in regras:
        bruto = list(regra.get("comando") or ())
        nome = bruto[0] if bruto else "(sem comando)"
        achado = _executavel(nome)
        exige = regra.get("exige")
        falta_exigencia = bool(exige) and not (raiz / str(exige)).exists()
        estado = (
            "ausente no PATH" if not achado else ("exigência ausente" if falta_exigencia else "ok")
        )
        print(f"  {list(regra.get('extensoes') or ())} -> {nome}: {estado}")
    return 0


def _arg(argv: list[str], nome: str) -> str | None:
    if nome in argv:
        i = argv.index(nome)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception:  # noqa: BLE001 — formatação nunca deve interromper o trabalho
        codigo = 0
    sys.exit(codigo)
