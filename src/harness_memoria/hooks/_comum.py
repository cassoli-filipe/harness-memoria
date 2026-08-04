"""Plumbing comum aos hooks: bootstrap de path, leitura do evento, gate e estado.

Invariante de todos os hooks deste pacote: **nunca derrubar a sessão**. Toda exceção é
engolida no `__main__` de cada script e o processo sai com 0. Um harness de memória que
quebra o trabalho custa mais do que entrega.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from ..config import Config, ErroDeConfig, carregar, raiz_projeto
from ..diario import forcar_utf8

#: Marca o `claude -p` que narra o diário. Ele também é uma sessão do Claude Code e
#: dispararia SessionEnd e PostToolUse — o que geraria recursão no primeiro caso e
#: contador falso no segundo.
VAR_GUARDA = "HARNESS_MEMORIA_NARRANDO"

#: Idade máxima de estado de sessão antiga, em dias. Sem isto o diretório cresce para
#: sempre — uma sessão, um arquivo.
VALIDADE_ESTADO_DIAS = 7


def preparar(rotulo: str) -> None:
    """Chamado no topo de todo hook, antes de qualquer impressão."""
    forcar_utf8()
    _ = rotulo


def ler_evento(padrao: dict | None = None) -> dict:
    """Evento do hook, lido do stdin. `padrao` é usado pelo autoteste."""
    if padrao is not None:
        return padrao
    try:
        bruto = sys.stdin.read()
        return json.loads(bruto) if bruto.strip() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def contexto(evento: dict, rotulo: str) -> tuple[Path, Config] | None:
    """`(raiz, config)` do projeto, ou `None` quando o harness não se aplica aqui.

    `None` cobre dois casos deliberadamente diferentes no diagnóstico:

    * **sem `.claude/harness.json`** — silêncio total. É o gate: o plugin pode ficar
      habilitado no nível do usuário sem agir em projeto que não o pediu.
    * **config presente e inválida** — grita no stderr e desiste. Alguém quis habilitar,
      e config inerte por typo é um bug de horas.
    """
    raiz = raiz_projeto(evento.get("cwd"))
    try:
        cfg = carregar(raiz)
    except ErroDeConfig as e:
        print(f"[{rotulo}] config inválida, hook inerte: {e}", file=sys.stderr)
        return None
    if cfg is None:
        return None
    return raiz, cfg


def narrando() -> bool:
    """True dentro do `claude -p` que escreve o diário."""
    return os.environ.get(VAR_GUARDA) == "1"


def emitir_contexto(evento_nome: str, texto: str) -> None:
    """Imprime `additionalContext` no formato que o Claude Code lê."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": evento_nome,
                    "additionalContext": texto,
                }
            },
            ensure_ascii=False,
        )
    )


# --------------------------------------------------------------------------- #
# Estado por sessão
# --------------------------------------------------------------------------- #


def pasta_estado(raiz: Path) -> Path:
    """Diretório de estado efêmero, keyed pelo projeto.

    Fica no temp do sistema, e não no repositório nem em `${CLAUDE_PLUGIN_DATA}`, por três
    razões: não exige entrada de `.gitignore` em cada projeto consumidor; não depende de
    substituição de variável no `hooks.json`; e não vive num caminho que muda a cada
    atualização do plugin. Estado que se perde num reboot é aceitável — nenhuma sessão
    sobrevive a um.
    """
    chave = re.sub(r"[^A-Za-z0-9_-]", "_", str(raiz).lower())[-60:]
    p = Path(tempfile.gettempdir()) / "harness-memoria" / chave
    p.mkdir(parents=True, exist_ok=True)
    return p


def caminho_contador(raiz: Path, sessao: str) -> Path:
    # `session_id` vem do Claude Code, mas monta caminho: sanitiza.
    seguro = re.sub(r"[^A-Za-z0-9_-]", "_", sessao)[:64]
    return pasta_estado(raiz) / f"escritas_{seguro}.txt"


def incrementar_contador(raiz: Path, sessao: str) -> int:
    """Incrementa e devolve o contador de escritas da sessão. Nunca lança."""
    try:
        pasta = pasta_estado(raiz)
        _limpar_estado_velho(pasta)
        alvo = caminho_contador(raiz, sessao)
        atual = 0
        if alvo.exists():
            try:
                atual = int(alvo.read_text(encoding="utf-8").strip() or 0)
            except ValueError:
                atual = 0
        atual += 1
        alvo.write_text(str(atual), encoding="utf-8")
        return atual
    except OSError:
        return 0  # sem estado, sem reafirmação — nunca atrapalha a sessão


def ler_contador(raiz: Path, sessao: str) -> int:
    try:
        return int(caminho_contador(raiz, sessao).read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def apagar_contador(raiz: Path, sessao: str) -> None:
    with contextlib.suppress(OSError):
        caminho_contador(raiz, sessao).unlink(missing_ok=True)


def _limpar_estado_velho(pasta: Path) -> None:
    limite = time.time() - VALIDADE_ESTADO_DIAS * 86_400
    for p in pasta.glob("escritas_*.txt"):
        try:
            if p.stat().st_mtime < limite:
                p.unlink(missing_ok=True)
        except OSError:
            pass


# Nota sobre o bootstrap de `sys.path`: ele NÃO pode morar aqui. Este módulo importa
# `..config`, então precisaria do path já resolvido para ser importado — cada script de
# hook faz a inserção inline, nas suas primeiras linhas, antes de qualquer import do
# pacote. É por isso que aquelas quatro linhas se repetem nos cinco arquivos.
