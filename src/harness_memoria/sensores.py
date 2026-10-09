"""Sensores: verificar o que o turno escreveu antes de o agente encerrar (ADR-0007).

O resto do harness é GUIA — diz ao agente o que vale antes de ele agir. Isto é SENSOR:
roda os comandos de verificação do projeto (`sensores.comandos` no `harness.json`) quando o
turno escreveu código, e devolve a falha ao agente com a cauda da saída e o que fazer, pelo
`decision: block` do hook `Stop`. Sem sensor, "pronto" era a palavra do agente; a
auditoria do CI olhava só documentação, e só depois do push.

Plataforma medida em 2026-10-09 (`claude -p` 2.1.295, plugin descartável que dorme N s e
bloqueia uma vez): o `Stop` de plugin RESPEITA o `timeout` do `hooks.json` — ao contrário
do `SessionEnd`, preso em 1.500 ms (ADR-0002). Com 120 s declarados, um hook de 90 s rodou
até o fim e o bloqueio fez o modelo continuar; com 30 s, o de 90 s morreu aos 30 e a sessão
terminou normalmente. O `Stop` dispara de novo depois do bloqueio, com
`stop_hook_active: true`, e o motivo entra no transcript como `user` com `isMeta: true`.

Falha ABERTA em tudo o que não é reprovação do sensor: timeout, executável ausente, erro de
sistema — libera o encerramento e avisa por `systemMessage`. Sensor que trava a sessão por
um defeito do próprio harness seria o modo de falha mais caro que existe.

Somente biblioteca padrão.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config, ConfigSensores
from .diario import FERRAMENTAS_DE_ESCRITA, _achar_tool_uses

#: Teto do `reason` inteiro. O motivo do bloqueio volta ao contexto do agente, e o teto de
#: `additionalContext` da plataforma é 10.000 ch (ADR-0004); 8.000 deixa folga para a
#: moldura da própria plataforma.
TETO_DO_MOTIVO_CHARS = 8_000

#: Folga no mtime de arquivo sujo no git contra o início do turno. O timestamp do transcript
#: é gravado depois de o prompt chegar; um arquivo escrito no mesmo segundo do prompt não
#: pode cair fora da janela por arredondamento.
FOLGA_DO_INICIO_S = 2.0

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass
class Resultado:
    nome: str
    comando: str
    rc: int | None = None
    segundos: float = 0.0
    cauda: str = ""
    #: Por que não houve código de saída: "timeout", "ausente", "pulado", "exige", "erro".
    sem_rc: str | None = None
    detalhe: str = ""
    acionado_por: list[str] = field(default_factory=list)

    @property
    def reprovou(self) -> bool:
        return self.rc not in (None, 0)


# --------------------------------------------------------------------------- #
# Quais arquivos o turno escreveu
# --------------------------------------------------------------------------- #


def arquivos_do_turno(transcript: str | None, raiz: Path) -> tuple[list[str], float | None]:
    """`(arquivos escritos no turno, início do turno em epoch)`.

    O turno começa no último prompt HUMANO: `type: user` sem `isMeta` e com texto, não um
    `tool_result`. O feedback de um bloqueio do `Stop` é `user` com `isMeta: true` — não
    reinicia a janela, e é isso que faz a continuação reverificar o turno inteiro, inclusive
    as escritas de antes do bloqueio.

    Ao que o transcript mostra (`Write`/`Edit`/…), soma-se o que o git viu mudar desde o
    início do turno: escrita por Bash (`sed -i`, gerador de código) e por subagente não
    aparece como `tool_use` de escrita na thread principal. Sem transcript não há janela —
    sem saber quando o turno começou, qualquer arquivo sujo do worktree contaria, e o
    sensor passaria a cobrar do agente o que outra sessão deixou.
    """
    if not transcript:
        return [], None
    p = Path(transcript)
    escritos: list[str] = []
    inicio: float | None = None
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            for linha in f:
                try:
                    obj = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if _e_prompt_humano(obj):
                    escritos, inicio = [], _epoch(obj.get("timestamp")) or inicio
                    continue
                usos: list[dict] = []
                _achar_tool_uses(obj, usos)
                for uso in usos:
                    entrada = uso["entrada"] if isinstance(uso["entrada"], dict) else {}
                    alvo = entrada.get("file_path") or entrada.get("notebook_path")
                    escrita = uso["nome"] in FERRAMENTAS_DE_ESCRITA and isinstance(alvo, str)
                    if escrita and alvo not in escritos:
                        escritos.append(alvo)
    except OSError:
        return [], None
    if inicio is not None:
        for sujo in _sujos_desde(raiz, inicio - FOLGA_DO_INICIO_S):
            if sujo not in escritos:
                escritos.append(sujo)
    return escritos, inicio


def _e_prompt_humano(obj: dict) -> bool:
    if obj.get("type") != "user" or obj.get("isMeta"):
        return False
    conteudo = (obj.get("message") or {}).get("content")
    if isinstance(conteudo, str):
        return bool(conteudo.strip())
    if isinstance(conteudo, list):
        tipos = {b.get("type") for b in conteudo if isinstance(b, dict)}
        return "text" in tipos and "tool_result" not in tipos
    return False


def _epoch(carimbo) -> float | None:
    """ISO 8601 do transcript em epoch. O `Z` sai à mão: `fromisoformat` do 3.10 o rejeita."""
    if not isinstance(carimbo, str):
        return None
    try:
        return datetime.fromisoformat(carimbo.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _sujos_desde(raiz: Path, desde: float) -> list[str]:
    """Arquivos que o git vê modificados ou novos, com mtime a partir de `desde`."""
    try:
        topo = subprocess.run(
            ["git", "-C", str(raiz), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = subprocess.run(
            ["git", "-C", str(raiz), "status", "--porcelain", "-z", "-uall"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if topo.returncode != 0 or status.returncode != 0:
        return []
    base = Path(topo.stdout.strip())
    saida: list[str] = []
    entradas = status.stdout.split("\0")
    i = 0
    while i < len(entradas):
        item = entradas[i]
        i += 1
        if len(item) < 4:
            continue
        if item[0] in "RC":
            i += 1  # no formato -z, o rename traz o caminho de ORIGEM na entrada seguinte
        caminho = base / item[3:]
        try:
            if caminho.is_file() and caminho.stat().st_mtime >= desde:
                saida.append(str(caminho))
        except OSError:
            continue
    return saida


def selecionar(comandos: tuple[dict, ...], escritos: list[str], falharam: set[str]) -> list[dict]:
    """Os sensores acionados: por extensão do que foi escrito, mais os que falharam antes.

    "Os que falharam antes" só entra na continuação de um bloqueio: sem isso, o agente que
    responde sem escrever nada encerraria o laço de verificação só por não ter escrito.
    """
    sufixos = {Path(e).suffix.lower() for e in escritos}
    saida = []
    for s in comandos:
        extensoes = {x.lower() for x in (s.get("extensoes") or ())}
        tocado = bool(escritos) and (not extensoes or bool(sufixos & extensoes))
        if tocado or s.get("nome") in falharam:
            saida.append(s)
    return saida


# --------------------------------------------------------------------------- #
# Rodar um sensor
# --------------------------------------------------------------------------- #


def rodar(sensor: dict, raiz: Path, timeout: float, cauda_chars: int) -> Resultado:
    comando = [str(x) for x in sensor.get("comando") or []]
    res = Resultado(nome=str(sensor.get("nome")), comando=" ".join(comando))
    if not comando:
        res.sem_rc, res.detalhe = "erro", "sem comando"
        return res
    exe = shutil.which(comando[0])
    if exe is None:
        res.sem_rc, res.detalhe = "ausente", f"`{comando[0]}` não encontrado no PATH"
        return res
    cwd = raiz / str(sensor.get("cwd") or ".")
    exige = sensor.get("exige")
    if exige and not (raiz / str(exige)).exists():
        res.sem_rc, res.detalhe = "exige", f"`{exige}` não existe"
        return res

    env = {**os.environ, "NO_COLOR": "1", "HARNESS_MEMORIA_SENSOR": res.nome}
    t0 = time.monotonic()
    # Saída para ARQUIVO, não para pipe: um neto que herda o pipe (servidor de teste,
    # watcher) segura o `communicate()` mesmo depois de o filho morrer por timeout, e o
    # hook ficaria preso até o timeout da plataforma.
    with tempfile.TemporaryFile() as saida:
        try:
            proc = subprocess.Popen(
                [exe, *comando[1:]],
                cwd=cwd if cwd.is_dir() else raiz,
                stdin=subprocess.DEVNULL,
                stdout=saida,
                stderr=subprocess.STDOUT,
                env=env,
                **_grupo_de_processo(),
            )
        except OSError as e:
            res.sem_rc, res.detalhe = "erro", f"{type(e).__name__}: {e}"
            return res
        try:
            res.rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _matar_arvore(proc)
            res.sem_rc, res.detalhe = "timeout", f"estourou o tempo limite de {timeout:.0f} s"
        res.segundos = time.monotonic() - t0
        saida.seek(0)
        bruto = saida.read().decode("utf-8", errors="replace")
    res.cauda = _ANSI.sub("", bruto).rstrip()[-cauda_chars:]
    return res


def _grupo_de_processo() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
    return {"start_new_session": True}


def _matar_arvore(proc: subprocess.Popen) -> None:
    """Mata o sensor E os filhos dele — `proc.kill()` sozinho deixa o neto vivo."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        proc.kill()
        proc.wait(timeout=5)


# --------------------------------------------------------------------------- #
# Estado por sessão
# --------------------------------------------------------------------------- #


def _caminho_estado(raiz: Path, sessao: str) -> Path:
    from .hooks import _comum as C

    seguro = re.sub(r"[^A-Za-z0-9_-]", "_", sessao or "sem-sessao")[:64]
    return C.pasta_estado(raiz) / f"sensores_{seguro}.json"


def carregar_estado(raiz: Path, sessao: str) -> dict:
    try:
        dados = json.loads(_caminho_estado(raiz, sessao).read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            dados.setdefault("bloqueios", {})
            dados.setdefault("ultimo", {})
            return dados
    except (OSError, ValueError):
        pass
    return {"bloqueios": {}, "ultimo": {}}


def salvar_estado(raiz: Path, sessao: str, estado: dict) -> None:
    from .hooks import _comum as C

    with contextlib.suppress(OSError):
        C._limpar_estado_velho(C.pasta_estado(raiz))
        _caminho_estado(raiz, sessao).write_text(json.dumps(estado), encoding="utf-8")


def falhas_para_o_diario(raiz: Path, sessao: str) -> list[dict]:
    """Sensores que reprovaram nesta sessão, no formato de `diario.linhas_de_falhas`.

    Os não resolvidos primeiro: são o que a próxima sessão herda.
    """
    ultimo = carregar_estado(raiz, sessao)["ultimo"]
    itens = []
    for nome, u in ultimo.items():
        vezes = int(u.get("falhas") or 0)
        if not vezes:
            continue
        situacao = "resolvido" if u.get("ok") else "não resolvido"
        itens.append({"tipo": "sensor", "alvo": nome, "detalhe": f"reprovou {vezes}×, {situacao}"})
    return sorted(itens, key=lambda i: i["detalhe"].endswith(", resolvido"))


# --------------------------------------------------------------------------- #
# A decisão
# --------------------------------------------------------------------------- #


def verificar(raiz: Path, cfg: Config, evento: dict) -> dict | None:
    """A saída do hook `Stop`: `{decision, reason, systemMessage}`, `{systemMessage}` ou nada."""
    s = cfg.sensores
    if not s.comandos:
        return None
    sessao = str(evento.get("session_id") or "sem-sessao")
    ativo = bool(evento.get("stop_hook_active"))
    estado = carregar_estado(raiz, sessao)
    if not ativo:
        estado["bloqueios"] = {}  # turno novo: as tentativas de conserto recomeçam

    escritos, _ = arquivos_do_turno(evento.get("transcript_path"), raiz)
    falharam = {n for n, u in estado["ultimo"].items() if not u.get("ok")} if ativo else set()
    escolhidos = selecionar(s.comandos, escritos, falharam)
    if not escolhidos:
        salvar_estado(raiz, sessao, estado)
        return None

    resultados = _rodar_no_orcamento(escolhidos, raiz, s, escritos)
    for r in resultados:
        if r.rc is None:
            continue
        u = estado["ultimo"].setdefault(r.nome, {"ok": True, "falhas": 0})
        u["ok"] = r.rc == 0
        u["falhas"] = int(u.get("falhas") or 0) + (1 if r.reprovou else 0)

    por_nome = {str(x.get("nome")): x for x in escolhidos}
    pergunta = termina_com_pergunta(str(evento.get("last_assistant_message") or ""))
    bloqueantes, avisos = [], []
    for r in resultados:
        if r.sem_rc:
            avisos.append(f"sensor `{r.nome}` não verificou ({r.detalhe}) — encerramento liberado")
        elif not r.reprovou:
            continue
        elif por_nome[r.nome].get("bloquear", True) is False:
            avisos.append(f"sensor `{r.nome}` reprovou (só aviso: `bloquear: false`)")
        elif pergunta:
            avisos.append(
                f"sensor `{r.nome}` reprovou — não bloqueei porque a última mensagem é uma "
                f"pergunta ao usuário"
            )
        elif estado["bloqueios"].get(r.nome, 0) >= s.max_bloqueios:
            avisos.append(
                f"sensor `{r.nome}` segue reprovando depois de {s.max_bloqueios} tentativa(s) — "
                f"encerramento liberado; a falha vai para o diário"
            )
        else:
            estado["bloqueios"][r.nome] = estado["bloqueios"].get(r.nome, 0) + 1
            bloqueantes.append(r)

    salvar_estado(raiz, sessao, estado)
    if bloqueantes:
        tentativa = max(estado["bloqueios"][r.nome] for r in bloqueantes)
        nomes = ", ".join(r.nome for r in bloqueantes)
        aviso = f"harness: {nomes} reprovou ({tentativa}/{s.max_bloqueios})"
        return {
            "decision": "block",
            "reason": _motivo(bloqueantes, len(resultados), tentativa, s, por_nome, raiz),
            "systemMessage": "; ".join([aviso, *avisos]),
        }
    if avisos:
        return {"systemMessage": "harness: " + "; ".join(avisos)}
    return None


_ITEM_DE_LISTA = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def termina_com_pergunta(mensagem: str) -> bool:
    """A resposta do agente termina pedindo uma decisão ao usuário.

    O último parágrafo que NÃO é lista de opções termina em "?". Medido no e2e de
    2026-10-09: o agente pergunta e em seguida enumera as opções ("Como você quer seguir?"
    + "1. … 2. …"), então exigir "?" como último caractere deixava o laço correr até o teto
    com o agente já esperando o usuário. Errar para o lado de liberar é barato: quem libera
    por pergunta emite `systemMessage` dizendo que o sensor reprovou.
    """
    paragrafos = [x.strip() for x in re.split(r"\n\s*\n", mensagem.strip()) if x.strip()]
    for paragrafo in reversed(paragrafos):
        if _ITEM_DE_LISTA.match(paragrafo):
            continue
        return paragrafo.rstrip("*_` ").endswith("?")
    return False


def _rodar_no_orcamento(
    escolhidos: list[dict], raiz: Path, s: ConfigSensores, escritos: list[str]
) -> list[Resultado]:
    resultados = []
    restante = float(s.orcamento_total_s)
    for sensor in escolhidos:
        timeout = float(sensor.get("timeout_s") or 60)
        if timeout > restante:
            res = Resultado(nome=str(sensor.get("nome")), comando=" ".join(sensor["comando"]))
            res.sem_rc = "pulado"
            res.detalhe = f"não cabia nos {restante:.0f} s que sobraram do orçamento"
            resultados.append(res)
            continue
        res = rodar(sensor, raiz, timeout, s.cauda_chars)
        res.acionado_por = _acionadores(sensor, escritos, raiz)
        restante -= res.segundos
        resultados.append(res)
    return resultados


def _acionadores(sensor: dict, escritos: list[str], raiz: Path) -> list[str]:
    extensoes = {x.lower() for x in (sensor.get("extensoes") or ())}
    saida = []
    for e in escritos:
        if extensoes and Path(e).suffix.lower() not in extensoes:
            continue
        try:
            saida.append(Path(e).resolve().relative_to(raiz.resolve()).as_posix())
        except (ValueError, OSError):
            saida.append(Path(e).name)
    return saida


def _motivo(
    falhas: list[Resultado],
    rodados: int,
    tentativa: int,
    s: ConfigSensores,
    por_nome: dict[str, dict],
    raiz: Path,
) -> str:
    """O texto que o agente lê. Escrito para ele: o que falhou, onde, e o que fazer."""
    cabeca = (
        f"[harness-memoria · sensores] {len(falhas)} de {rodados} reprovou após as escritas "
        f"deste turno (tentativa {tentativa} de {s.max_bloqueios})."
    )
    remedios = [
        str(por_nome[r.nome]["remediacao"]).rstrip(". ") + "."
        for r in falhas
        if por_nome[r.nome].get("remediacao")
    ]
    pe = (
        ("O que fazer: " + " ".join(remedios) + " " if remedios else "O que fazer: ")
        + "Conserte a causa e rode o mesmo comando antes de encerrar. Não desative nem "
        "afrouxe o sensor. Exceção: se cumprir o sensor exige fazer o OPOSTO do que o usuário "
        "pediu explicitamente, ou se a falha é anterior a você ou instável, não tente de novo "
        "— pergunte ao usuário como seguir, terminando a resposta com a pergunta, o que libera "
        f"o encerramento. Fora isso, após {s.max_bloqueios} tentativas o encerramento é "
        "liberado e a falha vai para o diário."
    )
    sobra = TETO_DO_MOTIVO_CHARS - len(cabeca) - len(pe) - 400 * len(falhas)
    cauda_max = max(200, min(s.cauda_chars, sobra // max(1, len(falhas))))
    blocos = []
    for r in falhas:
        gatilho = ", ".join(r.acionado_por[:3]) + (
            f" e mais {len(r.acionado_por) - 3}" if len(r.acionado_por) > 3 else ""
        )
        blocos.append(
            f"✗ {r.nome} — `{r.comando[:160]}` saiu com {r.rc} em {r.segundos:.1f} s"
            + (f" (acionado por: {gatilho})" if gatilho else "")
            + f"\n--- últimas linhas ---\n{r.cauda[-cauda_max:]}"
        )
    return "\n\n".join([cabeca, *blocos, pe])[:TETO_DO_MOTIVO_CHARS]


# --------------------------------------------------------------------------- #
# Autoteste
# --------------------------------------------------------------------------- #


def autoteste(raiz: Path, cfg: Config) -> int:
    """Confere, NA MÁQUINA onde o hook vai rodar, que todo sensor tem executável e cwd."""
    if not cfg.sensores.comandos:
        print("[sensores] nenhum sensor configurado — hook inerte por desenho")
        return 0
    falhas = 0
    for s in cfg.sensores.comandos:
        nome = s.get("nome")
        comando = [str(x) for x in s.get("comando") or []]
        if not comando or shutil.which(comando[0]) is None:
            falhas += 1
            alvo = comando[0] if comando else "(sem comando)"
            print(f"FALHA {nome}: `{alvo}` não encontrado no PATH — o sensor nunca rodaria")
            continue
        cwd = s.get("cwd")
        if cwd and not (raiz / str(cwd)).is_dir():
            falhas += 1
            print(f"FALHA {nome}: cwd `{cwd}` não existe")
            continue
        print(f"ok    {nome}: `{' '.join(comando)}` (timeout {s.get('timeout_s', 60)} s)")
    total = len(cfg.sensores.comandos)
    print(f"\n{total - falhas}/{total} sensores prontos para rodar")
    return 1 if falhas else 0
