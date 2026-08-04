#!/usr/bin/env python3
"""Hook SessionEnd — grava a entrada do diário de engenharia.

Fluxo:
  1. guarda anti-recursão -> 2. filtro de motivo -> 3. gate de config
  -> 4. fatos determinísticos -> 5. narrativa via `claude -p` -> 6. queda garantida
  -> 7. append em <diario>/AAAA-MM.md

Este hook NUNCA deve quebrar o encerramento da sessão: todo caminho sai com 0.

Autoteste:  python src/harness_memoria/hooks/session_end.py --autoteste [--projeto CAMINHO]
            (não escreve: mostra a entrada que gravaria)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness_memoria import diario  # noqa: E402
from harness_memoria.adr import adrs_tocados  # noqa: E402
from harness_memoria.config import Config  # noqa: E402
from harness_memoria.hooks import _comum as C  # noqa: E402

ROTULO = "diario"
MOTIVOS_QUE_REGISTRAM = {"clear", "logout", "prompt_input_exit", "other"}
TIMEOUT_LLM_S = 120

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
- {abordagem} → falhou porque {razao}. **Não repetir.**
  (omita a seção inteira se nada foi descartado)

### Verificação
- {evidencia com número; comandos rodados e resultado}

### Aberto / Próximo passo
- [ ] {acao}
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    C.preparar(ROTULO)

    # ---- 1. guarda anti-recursão --------------------------------------------
    # O `claude -p` chamado abaixo também encerra sessão e dispararia este hook.
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

    # ---- 2. filtro de motivo ------------------------------------------------
    motivo = str(evento.get("reason") or "other")
    if not autoteste and motivo not in MOTIVOS_QUE_REGISTRAM:
        return 0

    # ---- 3. gate ------------------------------------------------------------
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

    # ---- 4. fatos determinísticos (o piso do registro) ----------------------
    fatos = diario.fatos_do_transcript(evento.get("transcript_path"))
    git = diario.fatos_do_git(raiz)

    if not autoteste and not fatos["arquivos_escritos"] and not fatos["comandos"]:
        # Sem mudança de estado, sem entrada. O diário registra resultado, não presença.
        return 0

    # ---- 5. narrativa por LLM ----------------------------------------------
    corpo, indisponivel = (
        (None, "autoteste: LLM não chamado") if autoteste else _narrar(raiz, cfg, fatos, git, agora)
    )

    # ---- 6. queda garantida ------------------------------------------------
    if not corpo:
        corpo = diario.entrada_deterministica(raiz, cfg.pasta_adr, fatos, git, agora, indisponivel)
    else:
        corpo = corpo.rstrip() + "\n\n" + _rodape_fatos(fatos, git)

    # ---- 7. append ---------------------------------------------------------
    if autoteste:
        # O autoteste NÃO escreve. O diário é append-only e entrada passada não se corrige,
        # então rodá-lo sujaria permanentemente o mês com uma entrada de zero arquivo — que
        # a própria regra do diário proíbe. Aqui ele só mostra.
        destino = diario.caminho_mes(cfg.pasta_diario, cfg.diario, agora)
        print(
            f"[{ROTULO}] autoteste: entrada NÃO gravada. Iria para "
            f"{destino.relative_to(raiz).as_posix()}:",
            file=sys.stderr,
        )
        print(corpo)
        return 0

    destino = diario.anexar_entrada(cfg.pasta_diario, cfg.diario, corpo, agora)
    print(
        f"[{ROTULO}] entrada gravada em {destino.relative_to(raiz).as_posix()}",
        file=sys.stderr,
    )
    return 0


def _narrar(
    raiz: Path, cfg: Config, fatos: dict, git: dict, agora: datetime
) -> tuple[str | None, str | None]:
    """Chama `claude -p` para narrar a sessão. Devolve `(corpo, motivo_de_indisponibilidade)`."""
    exe = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if not exe:
        return None, "executável `claude` não encontrado no PATH"

    prompt = _montar_prompt(raiz, cfg, fatos, git, agora)

    ambiente = dict(os.environ)
    ambiente[C.VAR_GUARDA] = "1"  # impede que o filho dispare este mesmo hook

    args = [exe, "-p"]
    modelo = os.environ.get("HARNESS_MEMORIA_MODELO")
    if modelo:
        args += ["--model", modelo]

    try:
        r = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_LLM_S,
            cwd=str(raiz),
            env=ambiente,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return None, f"`claude -p` excedeu {TIMEOUT_LLM_S}s"
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
