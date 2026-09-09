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
import time
from pathlib import Path

from ..config import Config, ErroDeConfig, carregar, raiz_projeto
from ._leve import forcar_utf8

# Dois imports que este módulo NÃO faz mais, e o motivo é o mesmo: os três hooks quentes
# (`guardar`, `reafirmar`, `formatar`) importam `_comum` a cada tool call e o caminho de
# decisão deles não toca nenhum dos dois. Medido com `-X importtime`, cumulativo:
#
# * `tempfile` — 18,2 ms, arrastando `shutil` (10,0). Único uso é `pasta_estado`, que
#   `guardar` e `formatar` nunca chamam; virou import local ali.
# * `..diario` — 9,1 ms, arrastando `subprocess` (6,8) e `datetime` (1,0), para trazer uma
#   função de 4 linhas que reconfigura o stdout. Agora vem de `._leve`, que não importa
#   nada. Ver o comentário em `_leve.forcar_utf8` sobre a cópia.
#
# `contextlib` continua no topo de propósito: são 14,8 ms cumulativos, mas quase todos são
# `collections`/`functools`/`operator`, que `json` e `dataclasses` importam de todo jeito
# no mesmo processo. Medido tirá-lo: 126,4 → 127,8 ms, isto é, nada.

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
    import tempfile  # 18,2 ms de import, e só `reafirmar` chega até aqui

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
    """Expira o CONTADOR de escritas por sessão — e só ele.

    O glob é `escritas_*.txt` e **não pode virar `*.txt`**, por mais que "limpar o
    diretório de estado" pareça o gesto natural. `session_end` guarda ali
    `diffstat_visto.txt`, a impressão do worktree com que a última sessão do projeto
    terminou, e ela existe justamente para NÃO expirar: sem marca, a idade do diff é
    desconhecida e o piso volta a cobrar de uma sessão de leitura a sujeira deixada por
    outra — a entrada vazia que passa a ser a `ultima_entrada` reinjetada. Um contador de
    sessão morta em 7 dias é lixo; a marca de projeto não é.

    E a regressão não seria pega por teste: os casos criam a marca dentro da mesma
    execução, então ela nunca está velha o bastante para o glob largo a apagar. Se algum
    dia houver mais de um prefixo com validade própria, o certo é um mapa
    prefixo -> validade, não um glob que pega tudo.
    """
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
# pacote. É por isso que o bootstrap se repete em todo script de hook — o número de
# linhas e de arquivos já mudou duas vezes, então não fica escrito aqui.
#
# Nos cinco hooks com pré-gate essa inserção passou a ser feita com `os.path` em vez de
# `Path(__file__).resolve().parents[2]`: `pathlib` custa 7,2 ms e era o PRIMEIRO import do
# arquivo, isto é, acontecia antes de o pré-gate de `_leve` poder dizer que o hook não tem
# nada a fazer neste projeto.
