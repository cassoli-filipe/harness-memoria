"""O que precisa ser decidido ANTES de importar o pacote — e por isso não importa nada.

Este módulo é a única exceção ao resto de `hooks/`: aqui só entram `os` e `sys`, que o
interpretador já carregou antes da primeira linha de qualquer hook. Nada de `pathlib`,
`json`, `dataclasses` ou `..diario` — esse é exatamente o custo que ele existe para evitar.

O incidente: num projeto que **não** adotou o harness, cada hook pagava a cadeia de import
inteira para não fazer absolutamente nada. Medido com `-X importtime` nesta máquina, o
`import harness_memoria.hooks._comum` custa 85,6 ms, assim distribuídos (cumulativo, ms):
`tempfile` 18,2 (arrasta `shutil` 10,0) · `json` 15,6 · `contextlib` 14,8 · `pathlib` 7,2 ·
`harness_memoria.config` 27,7 (arrasta `dataclasses` 18,5, que arrasta `inspect` 16,0) ·
`harness_memoria.diario` 9,1 (arrasta `subprocess` 6,8 + `datetime` 1,0). Do outro lado da
balança, `config.carregar()` custa 0,24 ms e o `os.path.exists` do próprio `harness.json`
custa 0,026 ms. O custo era IMPORTAR, nunca ler política.

A conta por sessão, num projeto sem config: uma sessão longa de 120 escritas + 80 Bash
dispara 440 processos de hook (3 por escrita — `guardar` no PreToolUse, `formatar` e
`reafirmar` no PostToolUse — e 1 por Bash). Medido p25 de n=40 rodadas intercaladas
antes/depois, com o piso de interpretador nu em 44,3 ms:

    guardar  Write  148,4 → 56,0 ms      reafirmar  Write  150,6 → 55,9 ms
    guardar  Bash   149,9 → 57,1 ms      formatar   Write  141,5 → 53,5 ms

    a sessão inteira: 64,9 s → 24,4 s de bloqueio, contra um piso de 19,5 s

É o maior desperdício de latência do repositório, e ele acontecia justamente em quem nunca
pediu o harness — o gate existe para o plugin poder ficar habilitado no nível do usuário,
e o preço dele era esse.
"""

from __future__ import annotations

import os
import sys

#: O mesmo nome que `config.NOME_ARQUIVO`, escrito de novo de propósito: importar a
#: constante de lá custaria o `config` inteiro — 27,7 ms —, que é o que este módulo evita.
#: São duas cópias de uma string, e `tests/test_hooks_quentes.py` reprova se divergirem.
NOME_CONFIG = "harness.json"


def gate_barato() -> bool | None:
    """O projeto adotou o harness? `None` significa "não sei" — e aí quem decide é `config`.

    APROXIMAÇÃO DELIBERADA, e a diferença com `config.raiz_projeto` importa: lá os
    candidatos são `CLAUDE_PROJECT_DIR`, depois o `cwd` **do evento**, depois o cwd do
    processo. Ler o `cwd` do evento exigiria `json` (15,6 ms medidos) e um parser, que é o
    custo que este módulo existe para não pagar. Aqui há dois candidatos e três respostas:

    * `False` — achei uma raiz (tem `CLAUDE.md`) e ela **não** tem `.claude/harness.json`.
      É o único caso em que o hook pode sair sem importar nada.
    * `True` — achei a raiz e ela adotou. O hook segue o caminho normal.
    * `None` — não achei raiz. Isto **não** é "não adotou", é ignorância: a autoridade
      continua sendo `config.raiz_projeto` + `config.carregar`, no caminho normal.

    Custa 0,048 ms medidos, contra 27,7 ms de importar `config` para responder o mesmo.

    Só o `False` encurta o caminho, e portanto só ele precisa estar certo. Quando
    `CLAUDE_PROJECT_DIR` aponta para uma raiz, a decisão é **exata** — é o mesmo primeiro
    candidato de `raiz_projeto`, e a plataforma seta essa variável em todo hook. O cwd do
    processo entra como segundo candidato para cobrir invocação manual, a suíte e o job de
    gate do CI, onde a variável não existe; nesse ramo ele pode divergir do `cwd` do
    evento, e é por isso que cada hook só consulta o pré-gate quando é `__main__` (ver o
    comentário no topo dos três).
    """
    try:
        candidatos = (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd())
    except OSError:
        # cwd apagado debaixo do processo. Ignorância, não veredicto: quem lança aqui
        # derrubaria um hook que hoje simplesmente não faz nada.
        return None
    for candidato in candidatos:
        if not candidato:
            continue
        if os.path.exists(os.path.join(candidato, "CLAUDE.md")):
            return os.path.exists(os.path.join(candidato, ".claude", NOME_CONFIG))
    return None


def sair_sem_fazer_nada(aviso: str = "") -> None:
    """Sai com 0 depois de **drenar** o stdin. Não volta.

    Drenar não é higiene: o Claude Code escreve o evento no pipe do hook, e um processo que
    sai sem ler deixa a escrita do outro lado sem leitor. Sair com 0 é a política que os
    hooks já têm ("nunca derrubar a sessão"); o que muda é sair com 0 sem ter importado
    nada.

    `isatty` porque um hook rodado à mão num terminal bloquearia para sempre no `read()`.
    """
    if aviso:
        print(aviso, file=sys.stderr)
    try:
        if sys.stdin is not None and not sys.stdin.isatty():
            sys.stdin.read()
    except (OSError, ValueError):
        pass  # noqa: SIM105 — `contextlib.suppress` custa 14,8 ms de import aqui
    sys.exit(0)


def forcar_utf8() -> None:
    """No Windows o stdout padrão é cp1252 e engasga em acento e em seta.

    CÓPIA CONSCIENTE de `diario.forcar_utf8`, e a cópia é o ponto: `_comum` importava esta
    função de `..diario`, e o import arrastava `subprocess` + `datetime` (9,1 ms medidos)
    para dentro de um hook que só quer decidir se bloqueia uma escrita. As duas versões
    fazem a mesma coisa com mecanismos diferentes de supressão — `contextlib.suppress` lá,
    `try/except/pass` aqui, porque `import contextlib` custa 14,8 ms neste ponto — e
    `tests/test_hooks_quentes.py` reprova se o comportamento das duas divergir.
    """
    for stream in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105 — `contextlib.suppress` custaria os 14,8 ms de import
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass
