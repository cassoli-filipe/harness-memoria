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

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness_memoria.hooks import _comum as C  # noqa: E402

ROTULO = "formatar"
TIMEOUT_S = 25


def main(argv: list[str] | None = None) -> int:
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


def _talvez_formatar(regra: dict, arquivo: Path, raiz: Path) -> None:
    extensoes = tuple(str(e).lower() for e in (regra.get("extensoes") or ()))
    if arquivo.suffix.lower() not in extensoes:
        return
    bruto = list(regra.get("comando") or ())
    if not bruto:
        return
    exe = (
        shutil.which(bruto[0]) or shutil.which(f"{bruto[0]}.cmd") or shutil.which(f"{bruto[0]}.exe")
    )
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
        achado = shutil.which(nome) or shutil.which(f"{nome}.cmd") or shutil.which(f"{nome}.exe")
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
