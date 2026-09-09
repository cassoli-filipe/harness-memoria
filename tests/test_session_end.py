"""Testes do hook SessionEnd — o PISO do diário.

Este arquivo existe porque a cobertura de `session_end.py` era **0/79 instruções**: os
cinco hooks aparecem uma vez cada em `tests/`, na parametrização que afirma AUSÊNCIA de
saída em projeto sem config. Ou seja, "os 89 testes passam" nunca foi prova de nada sobre
este arquivo — e o hook estava inerte em produção (zero entradas com a assinatura dele em
três projetos consumidores) com a suíte verde.

Dois `claude` FALSOS fazem o trabalho pesado, porque a pergunta central é sobre QUEM é
chamado e QUANDO: um que grava o próprio argv (detector de "o filho foi gerado?") e dorme
3 s (a plataforma mata este hook em 1.500 ms, então gerar o filho é perder a entrada).
Nenhum teste aqui chama o `claude` de verdade.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
HOOK = SRC / "harness_memoria" / "hooks" / "session_end.py"

#: Fronteira de entrada do diário, a mesma que `diario._FRONTEIRA_ENTRADA` exige.
_ENTRADA = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)

#: Variáveis que precisam sair do ambiente em todo teste: `CLAUDE_PROJECT_DIR` tem
#: PRIORIDADE sobre o `cwd` do evento em `config.raiz_projeto`, então uma sessão do Claude
#: Code rodando a suíte faria o hook resolver o projeto errado — e escrever no diário do
#: repositório de verdade.
_VARS_A_LIMPAR = (
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS",
    "HARNESS_MEMORIA_NARRANDO",
    "HARNESS_MEMORIA_MODELO",
)


# --------------------------------------------------------------------------- #
# Andaime
# --------------------------------------------------------------------------- #


def _mes(raiz: Path) -> Path:
    return raiz / "docs" / "diario" / f"{datetime.now().strftime('%Y-%m')}.md"


def _entradas(raiz: Path) -> int:
    p = _mes(raiz)
    return len(_ENTRADA.findall(p.read_text(encoding="utf-8"))) if p.exists() else 0


def _transcript(base: Path, escritas: list[str], comandos: list[str]) -> Path:
    """Transcript JSONL sintético, no formato que `_achar_tool_uses` varre.

    `base` pode não existir: os testes de duas sessões precisam de um transcript por
    sessão, e o nome do arquivo é fixo.
    """
    base.mkdir(parents=True, exist_ok=True)
    linhas = [json.dumps({"type": "user", "message": {"role": "user", "content": "faça X"}})]
    for a in escritas:
        linhas.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Write", "input": {"file_path": a}}
                        ],
                    },
                }
            )
        )
    for c in comandos:
        linhas.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "name": "Bash", "input": {"command": c}}],
                    },
                }
            )
        )
    p = base / "transcript.jsonl"
    p.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return p


CORPO_FALSO = [
    "## 2026-09-08 - Entrada narrada pelo claude falso",
    "",
    "**Estado:** concluido",
    "",
    "### O que foi feito",
    "- narrativa sintetica com bem mais de oitenta caracteres, para passar no piso de len()",
]


def _claude_falso(base: Path, dormir: float = 0.0) -> tuple[Path, Path]:
    """`(pasta_para_o_PATH, marcador)`. O marcador recebe o argv do filho, se ele nascer.

    ASCII puro no stdout de propósito: no Windows o stdout de um `.cmd` sai na codepage
    ANSI e um acento aqui viraria falha de decodificação, não de comportamento.
    """
    pasta = base / "bin"
    pasta.mkdir(parents=True, exist_ok=True)
    marcador = base / "argv-do-filho.txt"
    alvo = pasta / "fake_claude.py"
    corpo = "\\n".join(CORPO_FALSO)
    alvo.write_text(
        "import sys, time, pathlib\n"
        f"pathlib.Path(r'{marcador}').write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
        "sys.stdin.read()\n"
        f"time.sleep({dormir})\n"
        f'sys.stdout.write("{corpo}\\n")\n',
        encoding="utf-8",
    )
    if os.name == "nt":
        (pasta / "claude.cmd").write_text(
            f'@echo off\r\n"{sys.executable}" "{alvo}" %*\r\n', encoding="utf-8"
        )
    else:
        sh = pasta / "claude"
        sh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{alvo}" "$@"\n', encoding="utf-8")
        sh.chmod(0o755)
    return pasta, marcador


def _evento(raiz: Path, transcript: Path | None, reason: str = "clear") -> dict:
    return {
        "hook_event_name": "SessionEnd",
        "reason": reason,
        "cwd": str(raiz),
        "session_id": "s-teste",
        "transcript_path": str(transcript) if transcript else str(raiz / "nao-existe.jsonl"),
    }


def _rodar(
    raiz: Path, evento: dict, bin_falso: Path, orcamento: str | None = None
) -> tuple[subprocess.CompletedProcess, float]:
    """Roda o hook como SUBPROCESSO, que é como o Claude Code o roda."""
    env = dict(os.environ)
    for v in _VARS_A_LIMPAR:
        env.pop(v, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = str(bin_falso) + os.pathsep + env["PATH"]
    if orcamento:
        env["CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS"] = orcamento
    t0 = time.perf_counter()
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(evento),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(raiz),
        timeout=120,
    )
    return r, (time.perf_counter() - t0) * 1000


@pytest.fixture
def limpo(monkeypatch):
    """Ambiente sem as variáveis que mudariam a decisão do hook, para teste in-process."""
    for v in _VARS_A_LIMPAR:
        monkeypatch.delenv(v, raising=False)


def _chamar_main(monkeypatch, evento: dict) -> int:
    from harness_memoria.hooks import session_end as se

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(evento)))
    return se.main([])


# --------------------------------------------------------------------------- #
# O piso grava, e grava sem LLM
# --------------------------------------------------------------------------- #


def test_piso_grava_a_entrada_sem_gerar_o_claude(projeto: Path, tmp_path: Path):
    """O defeito central: antes desta mudança, ZERO entradas eram gravadas.

    Medido com este mesmo andaime (5 execuções, `claude` falso dormindo 3 s, kill em
    1.500 ms como a plataforma faz): árvore anterior 0/5 entradas gravadas, morta em
    1.527 ms; árvore atual 5/5, p25 431 ms. O `< 3000 ms` abaixo não é cheque de
    performance — é o tempo que o `claude` falso dorme, então só reprova se o filho for
    gerado. Cheque de latência com número apertado em runner compartilhado é falso
    positivo, e falso positivo ensina a ignorar a suíte.
    """
    antes = _entradas(projeto)
    binf, marcador = _claude_falso(tmp_path, dormir=3.0)
    tr = _transcript(tmp_path, [str(projeto / "scripts" / "checar.py")], ["pytest -q"])

    r, ms = _rodar(projeto, _evento(projeto, tr), binf)

    assert r.returncode == 0
    assert _entradas(projeto) == antes + 1, r.stderr
    assert not marcador.exists(), f"o hook gerou `claude -p` no caminho default: {r.stderr}"
    assert ms < 3000, f"{ms:.0f} ms — o filho foi esperado"
    assert "registro automático" in _mes(projeto).read_text(encoding="utf-8")


def test_entrada_de_piso_aponta_a_skill_em_vez_de_mentir_sobre_a_narrativa(
    projeto: Path, tmp_path: Path
):
    """A entrada declara POR QUE não é narrada e o que rodar para tê-la (princípio 6)."""
    binf, _ = _claude_falso(tmp_path)
    tr = _transcript(tmp_path, [str(projeto / "scripts" / "checar.py")], [])
    _rodar(projeto, _evento(projeto, tr), binf)

    texto = _mes(projeto).read_text(encoding="utf-8")
    assert "resumo-narrativo: indisponível" in texto
    assert "/encerrar-sessao" in texto
    assert "1500 ms de orçamento" in texto


def test_piso_aponta_a_skill_do_projeto_quando_ela_existe(projeto: Path, tmp_path: Path):
    """`/encerrar-sessao` CEDE A VEZ quando há `skill_de_encerramento`: apontá-la seria

    mandar chamar a skill que vai se recusar.
    """
    from conftest import escrever_config

    escrever_config(projeto, {"diario": {"skill_de_encerramento": "/handoff"}})
    binf, _ = _claude_falso(tmp_path)
    tr = _transcript(tmp_path, [str(projeto / "scripts" / "checar.py")], [])
    _rodar(projeto, _evento(projeto, tr), binf)

    texto = _mes(projeto).read_text(encoding="utf-8")
    assert "`/handoff`" in texto
    assert "/encerrar-sessao" not in texto


def test_falha_inesperada_do_narrador_nao_perde_a_entrada(
    projeto: Path, tmp_path: Path, monkeypatch, limpo
):
    """O piso não pode depender de o narrador ser correto.

    Antes desta mudança o append vinha DEPOIS da narrativa sem rede: qualquer exceção que
    `_narrar` não tratasse (um bug em `_montar_prompt`, um `MemoryError` num transcript
    enorme) subia por `main()` e a sessão não deixava rastro nenhum.
    """
    from harness_memoria.hooks import session_end as se

    def explodir(*_a, **_k):
        raise RuntimeError("narrador quebrado")

    monkeypatch.setattr(se, "_narrar", explodir)
    monkeypatch.setenv(se.VAR_ORCAMENTO, "60000")  # caminho opt-in, senão nem tenta narrar
    tr = _transcript(tmp_path, [str(projeto / "scripts" / "checar.py")], [])
    antes = _entradas(projeto)

    assert _chamar_main(monkeypatch, _evento(projeto, tr)) == 0
    assert _entradas(projeto) == antes + 1
    assert "RuntimeError: narrador quebrado" in _mes(projeto).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Quem registra: o motivo não filtra mais; a mudança de estado filtra
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("reason", ["clear", "resume", "logout", "prompt_input_exit", "other"])
def test_os_cinco_motivos_registram(projeto: Path, tmp_path: Path, reason: str):
    """`resume` faltava no conjunto e é, com `clear`, um dos dois motivos disparados de

    dentro do REPL: metade dos encerramentos in-session saía sem registro e sem stderr.
    """
    binf, _ = _claude_falso(tmp_path)
    tr = _transcript(tmp_path, [str(projeto / "scripts" / "checar.py")], [])
    r, _ = _rodar(projeto, _evento(projeto, tr, reason=reason), binf)
    assert _entradas(projeto) == 2, f"reason={reason}: {r.stderr}"


def test_sessao_de_leitura_nao_suja_o_diario(projeto: Path, tmp_path: Path):
    """Comando isolado deixou de qualificar como mudança de estado.

    O diário é append-only: entrada sobre presença não se apaga depois. Antes, um único
    `ls` bastava para gravar.
    """
    from harness_memoria import diario

    assert diario.fatos_do_git(projeto)["diffstat"] == "", "pré-condição: worktree sem diff"
    binf, _ = _claude_falso(tmp_path)
    tr = _transcript(tmp_path, [], ["ls -la"])

    r, _ = _rodar(projeto, _evento(projeto, tr), binf)

    assert _entradas(projeto) == 1
    assert "sem mudança de estado" in r.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="precisa de git no PATH")
def test_diffstat_registra_a_sessao_cujas_escritas_sairam_de_subagente(
    projeto: Path, tmp_path: Path
):
    """A metade barata do achado dos subagentes.

    Numa sessão de orquestração o transcript principal vê 3,4% dos tool calls (29 contra
    345), então `arquivos_escritos` vem vazio com o diff real no disco — e o hook saía sem
    gravar e sem uma linha de stderr. Aqui o transcript nem existe, que é o caso extremo:
    o `erro_parse` era produzido e jogado fora dentro de uma função nunca chamada.
    """
    assert tmp_path in projeto.parents or projeto.is_relative_to(tmp_path)
    _repo_com_base(projeto)
    (projeto / "scripts" / "checar.py").write_text("# mudado por um subagente\n", encoding="utf-8")

    binf, marcador = _claude_falso(tmp_path)
    r, _ = _rodar(projeto, _evento(projeto, None), binf, orcamento="60000")

    assert _entradas(projeto) == 2, r.stderr
    assert "transcript ileg" in r.stderr
    assert "transcript" in _mes(projeto).read_text(encoding="utf-8")
    assert not marcador.exists(), "sem arquivo escrito no transcript não há o que narrar"


# --------------------------------------------------------------------------- #
# A DATA do `diffstat`: a marca em `C.pasta_estado`
#
# `git diff --stat` não tem data, e por isso o piso gravava por sujeira de OUTRA sessão —
# uma entrada VAZIA que virava a `ultima_entrada` e expulsava do bloco injetado a entrada
# que tinha conteúdo. Os dois casos que prenderam o defeito estão em
# `tests/test_verificacao_final.py` (era `xfail(strict=True)`); aqui ficam os ramos da
# correção, que é o que reprova se a marca for lida ou gravada no lugar errado.
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(shutil.which("git") is None, reason="precisa de git no PATH")
def test_diff_igual_a_marca_da_sessao_anterior_nao_registra(projeto: Path, tmp_path: Path):
    """Duas sessões, o mesmo diff: a segunda não é dona dele.

    A primeira sessão escreve, registra e deixa a marca. A segunda só lê, e o worktree
    continua exatamente como a primeira o deixou — é a sujeira SEM DATA que fazia toda
    sessão de leitura ganhar entrada num repositório que passa o dia não-commitado.
    """
    binf, _ = _claude_falso(tmp_path)
    _repo_com_base(projeto)
    (projeto / "scripts" / "checar.py").write_text("# mudado na sessão 1\n", encoding="utf-8")

    tr1 = _transcript(tmp_path / "s1", [str(projeto / "scripts" / "checar.py")], [])
    r1, _ = _rodar(projeto, _evento(projeto, tr1), binf)
    assert _entradas(projeto) == 2, r1.stderr

    tr2 = _transcript(tmp_path / "s2", [], ["git log --oneline -5"])
    r2, _ = _rodar(projeto, _evento(projeto, tr2), binf)

    assert _entradas(projeto) == 2, (
        "a sessão de leitura ganhou entrada pelo diff da sessão anterior: " + r2.stderr
    )
    assert "o mesmo com que a sessão anterior terminou" in r2.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="precisa de git no PATH")
def test_diff_que_mudou_depois_da_marca_registra(projeto: Path, tmp_path: Path):
    """O sinal não foi largado: diff DIFERENTE da marca continua registrando.

    É o caso que o `diffstat` existe para pegar e a razão de não bastar apagá-lo: a sessão
    de orquestração cujas escritas saíram de subagentes tem transcript principal legível e
    sem escrita nenhuma (medido: 29 `tool_use` no principal contra 345 nos de subagente).
    Aqui a segunda sessão é exatamente essa forma — e a `Workflow` que gerou os nove
    agentes desta rodada nem aparece como `Task`, então enumerar ferramentas de delegação
    não resolveria; comparar o diff resolve.
    """
    binf, _ = _claude_falso(tmp_path)
    _repo_com_base(projeto)
    (projeto / "scripts" / "checar.py").write_text("# mudado na sessão 1\n", encoding="utf-8")

    tr1 = _transcript(tmp_path / "s1", [str(projeto / "scripts" / "checar.py")], [])
    _rodar(projeto, _evento(projeto, tr1), binf)
    assert _entradas(projeto) == 2

    # A escrita que o transcript principal não vê: quem a fez foi um subagente.
    adr = projeto / "docs" / "adr" / "0001-primeira.md"
    adr.write_text(adr.read_text(encoding="utf-8") + "\n- passo do subagente\n", encoding="utf-8")
    tr2 = _transcript(tmp_path / "s2", [], ["python -m pytest"])
    r2, _ = _rodar(projeto, _evento(projeto, tr2), binf)

    assert _entradas(projeto) == 3, r2.stderr
    assert "0001-primeira.md" in _mes(projeto).read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="precisa de git no PATH")
def test_a_marca_e_gravada_mesmo_quando_o_piso_e_dispensado(projeto: Path, tmp_path: Path):
    """A marca descreve o WORKTREE, não a decisão de registrar.

    A sessão que rodou `/encerrar-sessao` não ganha entrada automática — e se ela não
    deixasse marca, o diff dela seria cobrado da sessão de leitura seguinte, que é o
    defeito de volta por uma porta lateral.
    """
    binf, _ = _claude_falso(tmp_path)
    _repo_com_base(projeto)
    (projeto / "scripts" / "checar.py").write_text("# mudado na sessão 1\n", encoding="utf-8")

    escritas = [str(_mes(projeto)), str(projeto / "scripts" / "checar.py")]
    tr1 = _transcript(tmp_path / "s1", escritas, [])
    r1, _ = _rodar(projeto, _evento(projeto, tr1), binf)
    assert "já registrou" in r1.stderr
    assert _entradas(projeto) == 1

    tr2 = _transcript(tmp_path / "s2", [], ["ls -la"])
    r2, _ = _rodar(projeto, _evento(projeto, tr2), binf)

    assert _entradas(projeto) == 1, (
        "a sessão de leitura pagou pelo diff da sessão que registrou à mão: " + r2.stderr
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="precisa de git no PATH")
def test_estado_inutilizavel_registra_em_vez_de_calar(projeto: Path, tmp_path: Path, monkeypatch):
    """Sem marca E sem poder gravá-la, o default INVERTE: registra.

    O outro ramo sem marca (`test_leitura_em_repo_sujo_de_antes_nao_grava`) aceita perder
    UMA entrada porque a marca desta execução fecha a janela na próxima. Quando
    `C.pasta_estado` não funciona — temp sem permissão —, não há próxima: a janela é
    permanente, e aí "não registra" viraria o defeito 1 de volta (zero entradas, calado)
    em todo projeto do disco. Uma entrada a mais é recuperável; o silêncio permanente não.
    """
    from harness_memoria.hooks import session_end as se

    for v in _VARS_A_LIMPAR:
        monkeypatch.delenv(v, raising=False)
    _repo_com_base(projeto)
    (projeto / "scripts" / "checar.py").write_text(
        "# sujeira de idade desconhecida\n", encoding="utf-8"
    )

    def temp_sem_permissao(_raiz):
        raise OSError("[WinError 5] acesso negado")

    monkeypatch.setattr(se.C, "pasta_estado", temp_sem_permissao)
    tr = _transcript(tmp_path / "s1", [], ["git log --oneline -5"])

    assert _chamar_main(monkeypatch, _evento(projeto, tr)) == 0
    assert _entradas(projeto) == 2


@pytest.mark.skipif(shutil.which("git") is None, reason="precisa de git no PATH")
def test_diffstat_agora_nao_pode_divergir_de_fatos_do_git(projeto: Path, tmp_path: Path):
    """As duas cópias do `git diff --stat HEAD` têm de devolver a MESMA string.

    `_diffstat_agora` existe para refazer a marca depois do append sem pagar os 193 ms dos
    cinco comandos de `fatos_do_git`. Se as duas divergirem — um `.strip()` a menos, um
    corte em outro tamanho, um dia em que `fatos_do_git` passe a usar `--stat=200` —, a
    marca nunca casa, o hook volta a gravar por sujeira sem data e NADA acusa: as duas
    saídas continuam plausíveis. É a mesma razão do teste que amarra `_leve.NOME_CONFIG` a
    `config.NOME_ARQUIVO`.
    """
    from harness_memoria import diario
    from harness_memoria.hooks import session_end as se

    # Sem repositório: as duas devolvem "" por caminhos diferentes (`rev-parse` reprova
    # numa, `returncode != 0` na outra).
    sem_git = tmp_path / "sem-git"
    sem_git.mkdir()
    assert se._diffstat_agora(sem_git) == diario.fatos_do_git(sem_git)["diffstat"] == ""

    _repo_com_base(projeto)
    assert se._diffstat_agora(projeto) == diario.fatos_do_git(projeto)["diffstat"] == ""

    (projeto / "scripts" / "checar.py").write_text("# mexido\n", encoding="utf-8")
    (projeto / "docs" / "diario" / "README.md").write_text("# outro\n", encoding="utf-8")
    agora = se._diffstat_agora(projeto)
    assert agora == diario.fatos_do_git(projeto)["diffstat"]
    assert "checar.py" in agora and "2 files changed" in agora, agora


def _git(raiz: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(raiz), *args], check=True, capture_output=True)


def _repo_com_base(raiz: Path) -> None:
    """`raiz` como repositório git com tudo commitado — worktree limpo é a pré-condição."""
    _git(raiz, "init", "-q")
    _git(raiz, "config", "user.email", "teste@local")
    _git(raiz, "config", "user.name", "teste")
    _git(raiz, "add", "-A")
    _git(raiz, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")


# --------------------------------------------------------------------------- #
# O caminho opt-in
# --------------------------------------------------------------------------- #


def test_opt_in_narra_com_strict_mcp_config_e_grava_uma_entrada_so(projeto: Path, tmp_path: Path):
    """Duas coisas no mesmo caso, porque são a mesma decisão.

    (1) `--strict-mcp-config`: sem ele o filho carrega os MCP do usuário — medido pareado
    com o prompt real de 41.951 chars, 22,70 -> 19,63 s e 29,67 -> 17,51 s, e nesta
    máquina três servidores MCP falharam, um com CONNECT_TIMEOUT de 30.000 ms.
    (2) UMA entrada: o diário é append-only, então "gravar o piso e depois a narrativa"
    daria duas entradas da mesma sessão, e a segunda seria a que o SessionStart reinjeta.
    """
    binf, marcador = _claude_falso(tmp_path)
    tr = _transcript(tmp_path, [str(projeto / "scripts" / "checar.py")], ["pytest -q"])
    antes = _entradas(projeto)

    r, _ = _rodar(projeto, _evento(projeto, tr), binf, orcamento="60000")

    assert marcador.read_text(encoding="utf-8").split() == ["-p", "--strict-mcp-config"]
    texto = _mes(projeto).read_text(encoding="utf-8")
    assert "Entrada narrada pelo claude falso" in texto, r.stderr
    assert _entradas(projeto) == antes + 1
    assert "resumo-narrativo: indisponível" not in texto
    assert "fatos determinísticos do hook de fim de sessão" in texto


def test_orcamento_baixo_nao_gera_o_filho(projeto: Path, tmp_path: Path):
    """Orçamento declarado que não cabe um `claude -p` (14,5-33 s medidos) não vale a

    tentativa: o filho que não termina atrasa o piso e a plataforma mata antes do append.
    """
    binf, marcador = _claude_falso(tmp_path, dormir=3.0)
    tr = _transcript(tmp_path, [str(projeto / "scripts" / "checar.py")], [])

    r, _ = _rodar(projeto, _evento(projeto, tr), binf, orcamento="5000")

    assert not marcador.exists()
    assert _entradas(projeto) == 2, r.stderr


# --------------------------------------------------------------------------- #
# A aritmética do orçamento (a razão de o hook nunca ter gravado)
# --------------------------------------------------------------------------- #


def test_sem_a_variavel_o_orcamento_e_1500_e_nao_se_narra(limpo):
    from harness_memoria.hooks import session_end as se

    assert se._orcamento_ms() == se.ORCAMENTO_PISO_MS == 1500
    assert se._janela_de_narrativa(0.0) is None


@pytest.mark.parametrize(
    ("valor", "espera_janela"),
    [
        ("1500", False),  # igual ao piso: ninguém levantou nada
        ("0", False),  # `e > 0` é falso no CLI, cai no default
        ("lixo", False),  # string não-numérica: idem
        ("20500", False),  # levanta, mas depois da reserva do piso não sobra o mínimo
        ("60000", True),
    ],
)
def test_janela_de_narrativa_segue_a_aritmetica_do_cli(monkeypatch, limpo, valor, espera_janela):
    from harness_memoria.hooks import session_end as se

    monkeypatch.setenv(se.VAR_ORCAMENTO, valor)
    janela = se._janela_de_narrativa(0.0)
    assert (janela is not None) is espera_janela
    if janela is not None:
        # O que sobra para o filho é o orçamento MENOS o que já se gastou e menos a
        # reserva do piso — é isso que garante que o estouro caia no piso dentro do prazo.
        assert janela == pytest.approx((60_000 - se.RESERVA_DO_PISO_MS) / 1000)


def test_a_reserva_do_piso_sai_da_janela(monkeypatch, limpo):
    from harness_memoria.hooks import session_end as se

    monkeypatch.setenv(se.VAR_ORCAMENTO, "60000")
    assert se._janela_de_narrativa(30_000.0) == pytest.approx(29.0)
    # Já gastou quase tudo: não sobra o mínimo, então nem tenta.
    assert se._janela_de_narrativa(40_000.0) is None


def test_o_teto_do_filho_limita_orcamento_absurdo(monkeypatch, limpo):
    from harness_memoria.hooks import session_end as se

    monkeypatch.setenv(se.VAR_ORCAMENTO, "600000")
    assert se._janela_de_narrativa(0.0) == se.TETO_NARRATIVA_S


# --------------------------------------------------------------------------- #
# Contratos que o CI depende
# --------------------------------------------------------------------------- #


def test_autoteste_nao_escreve(projeto: Path, tmp_path: Path):
    """Contrato preso de propósito: o CI roda este caminho contra o projeto sintético em

    todo push. O diário é append-only, então um autoteste que escrevesse sujaria o mês
    com uma entrada de zero arquivo — que a própria regra do diário proíbe.
    """
    env = dict(os.environ)
    for v in _VARS_A_LIMPAR:
        env.pop(v, None)
    env["PYTHONIOENCODING"] = "utf-8"
    binf, marcador = _claude_falso(tmp_path)
    env["PATH"] = str(binf) + os.pathsep + env["PATH"]
    antes = _mes(projeto).read_text(encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(HOOK), "--autoteste", "--projeto", str(projeto)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )

    assert r.returncode == 0
    assert _mes(projeto).read_text(encoding="utf-8") == antes
    assert "NÃO gravada" in r.stderr
    assert r.stdout.startswith("## ")
    assert not marcador.exists(), "o autoteste não chama LLM"


def test_pacote_quebrado_nao_derruba_o_encerramento(projeto: Path, tmp_path: Path):
    """Erro de sintaxe em `config.py` → rc=0 e mensagem ROTULADA, não traceback cru.

    O gêmeo deste teste existia para os três hooks quentes e para o `session_start`; este
    hook era o SEXTO, e era o único cujo `sys.path.insert` + `from harness_memoria...`
    ficavam fora do `try/except` de módulo — enquanto o `FUNDAMENTOS.md` já afirmava, em
    duas seções, que os seis o tinham dentro. Reproduzido pelo revisor com a árvore
    quebrada (o estado que um `git pull` no meio produz): os outros cinco saíam rc=0 com a
    causa, este saía **rc=1 com `SyntaxError` cru no stderr** — e o pior momento para a
    plataforma receber um hook que falha é o encerramento, quando não há mais sessão para
    mostrar o erro.
    """
    src = tmp_path / "src"
    shutil.copytree(SRC, src, ignore=shutil.ignore_patterns("__pycache__"))
    alvo = src / "harness_memoria" / "config.py"
    alvo.write_text(alvo.read_text(encoding="utf-8") + "\ndef quebrado(:\n", encoding="utf-8")

    binf, marcador = _claude_falso(tmp_path)
    env = dict(os.environ)
    for v in _VARS_A_LIMPAR:
        env.pop(v, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = str(binf) + os.pathsep + env["PATH"]
    tr = _transcript(tmp_path / "s1", [str(projeto / "scripts" / "checar.py")], [])

    r = subprocess.run(
        [sys.executable, str(src / "harness_memoria" / "hooks" / "session_end.py")],
        input=json.dumps(_evento(projeto, tr)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(projeto),
        timeout=120,
    )

    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr, r.stderr
    assert "diario" in r.stderr and "SyntaxError" in r.stderr, r.stderr
    assert _entradas(projeto) == 1, "hook inerte não escreve"
    assert not marcador.exists()


def test_hook_e_inerte_sem_config_mesmo_com_diff_no_disco(tmp_path: Path):
    """O gate vale antes de qualquer fato: nem stdout, nem `docs/` criado."""
    raiz = tmp_path / "alheio"
    raiz.mkdir()
    (raiz / "CLAUDE.md").write_text("# Projeto que não usa o harness\n", encoding="utf-8")
    binf, _ = _claude_falso(tmp_path)

    r, _ = _rodar(raiz, _evento(raiz, None), binf, orcamento="60000")

    assert r.stdout == ""
    assert not (raiz / "docs").exists()


# --------------------------------------------------------------------------- #
# Os modos de falha do narrador — todos caem no piso, nenhum perde a entrada
# --------------------------------------------------------------------------- #


def _chamar_narrar(monkeypatch, projeto: Path, tmp_path: Path, timeout_s: float, bin_pri: Path):
    """`_narrar` isolado, com `bin_pri` na frente do PATH.

    Isolado porque pelo caminho normal cada um destes modos de falha custaria 20 s (é o
    mínimo de sobra para o hook sequer tentar narrar). O que se verifica aqui é a MENSAGEM
    que desce para o piso — nenhum destes caminhos pode lançar.
    """
    from harness_memoria import diario
    from harness_memoria.config import carregar
    from harness_memoria.hooks import session_end as se

    monkeypatch.setenv("PATH", str(bin_pri) + os.pathsep + os.environ["PATH"])
    cfg = carregar(projeto)
    tr = _transcript(tmp_path, [str(projeto / "scripts" / "checar.py")], [])
    fatos = diario.fatos_do_transcript(str(tr))
    git = diario.fatos_do_git(projeto)
    return se._narrar(projeto, cfg, fatos, git, datetime.now(), timeout_s)


def _bin_com_script(pasta: Path, corpo: str) -> Path:
    """Um `claude` falso arbitrário: `corpo` é o código Python que ele executa."""
    pasta.mkdir(parents=True, exist_ok=True)
    f = pasta / "fake.py"
    f.write_text(corpo, encoding="utf-8")
    if os.name == "nt":
        (pasta / "claude.cmd").write_text(
            f'@echo off\r\n"{sys.executable}" "{f}" %*\r\n', encoding="utf-8"
        )
    else:
        sh = pasta / "claude"
        sh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{f}" "$@"\n', encoding="utf-8")
        sh.chmod(0o755)
    return pasta


def test_narrador_que_estoura_o_prazo_devolve_motivo_em_vez_de_lancar(
    projeto: Path, tmp_path: Path, monkeypatch, limpo
):
    """É o que torna o caminho opt-in seguro: o filho estoura, `_narrar` devolve

    `(None, motivo)` e a `RESERVA_DO_PISO_MS` que ficou de fora da janela paga o append.
    """
    binf, _ = _claude_falso(tmp_path, dormir=3.0)
    corpo, motivo = _chamar_narrar(monkeypatch, projeto, tmp_path, 0.5, binf)
    assert corpo is None
    assert "excedeu" in motivo


def test_cli_antigo_sem_strict_mcp_config_degrada_para_o_piso(
    projeto: Path, tmp_path: Path, monkeypatch, limpo
):
    """A nota de compatibilidade da flag, verificada: num CLI que não conhece

    `--strict-mcp-config` o filho sai rc=1 com `error: unknown option`, e isso vira
    motivo de indisponibilidade no piso — não exceção, não entrada perdida.
    """
    binf = _bin_com_script(
        tmp_path / "cli-velho",
        "import sys\nsys.stdin.read()\n"
        "sys.stderr.write('error: unknown option --strict-mcp-config\\n')\nsys.exit(1)\n",
    )
    corpo, motivo = _chamar_narrar(monkeypatch, projeto, tmp_path, 30.0, binf)
    assert corpo is None
    assert "saiu com 1" in motivo
    assert "unknown option" in motivo


def test_resposta_fora_do_formato_nao_vira_entrada(
    projeto: Path, tmp_path: Path, monkeypatch, limpo
):
    """Meia entrada é pior que entrada determinística: o formato é o contrato do diário."""
    binf = _bin_com_script(
        tmp_path / "tagarela",
        "import sys\nsys.stdin.read()\nsys.stdout.write('Claro! Aqui vai:\\n')\n",
    )
    corpo, motivo = _chamar_narrar(monkeypatch, projeto, tmp_path, 30.0, binf)
    assert corpo is None
    assert "fora do formato" in motivo


def test_sem_claude_no_path_o_narrador_nao_explode(
    projeto: Path, tmp_path: Path, monkeypatch, limpo
):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    monkeypatch.setenv("PATH", str(vazio))
    from harness_memoria import diario
    from harness_memoria.config import carregar
    from harness_memoria.hooks import session_end as se

    corpo, motivo = se._narrar(
        projeto,
        carregar(projeto),
        diario.fatos_do_transcript(None),
        {"branch": "x", "status": "", "diffstat": "", "ultimo_commit": ""},
        datetime.now(),
        30.0,
    )
    assert corpo is None
    assert "não encontrado no PATH" in motivo


def test_guarda_anti_recursao_cala_o_hook(projeto: Path, tmp_path: Path):
    """O `claude -p` do caminho opt-in também encerra sessão e dispararia este hook."""
    binf, _ = _claude_falso(tmp_path)
    env = dict(os.environ)
    for v in _VARS_A_LIMPAR:
        env.pop(v, None)
    env["HARNESS_MEMORIA_NARRANDO"] = "1"
    env["PATH"] = str(binf) + os.pathsep + env["PATH"]
    tr = _transcript(tmp_path, [str(projeto / "scripts" / "checar.py")], [])

    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(_evento(projeto, tr)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(projeto),
        timeout=120,
    )

    assert r.returncode == 0
    assert r.stdout == ""
    assert _entradas(projeto) == 1


# --------------------------------------------------------------------------- #
# Piso não compete com escolha deliberada
# --------------------------------------------------------------------------- #


def test_sessao_que_rodou_a_skill_nao_ganha_entrada_automatica(projeto: Path, tmp_path: Path):
    """A promessa que a skill `/encerrar-sessao` faz por escrito, agora implementada.

    Era promessa vazia enquanto o hook não gravava. Sem este ramo, a sessão em que alguém
    escreveu a entrada à mão terminaria com duas, e a AUTOMÁTICA seria a última — logo a
    que o `SessionStart` reinjeta, no lugar da narrativa que custou o contexto todo.
    """
    binf, _ = _claude_falso(tmp_path)
    tr = _transcript(tmp_path, [str(_mes(projeto)), str(projeto / "scripts" / "checar.py")], [])

    r, _ = _rodar(projeto, _evento(projeto, tr), binf)

    assert _entradas(projeto) == 1, r.stderr
    assert "já registrou" in r.stderr


def test_mexer_no_readme_do_diario_nao_dispensa_o_piso(projeto: Path, tmp_path: Path):
    """Trabalho sobre o FORMATO não é registro de sessão: só arquivo de mês conta."""
    binf, _ = _claude_falso(tmp_path)
    tr = _transcript(tmp_path, [str(projeto / "docs" / "diario" / "README.md")], [])

    r, _ = _rodar(projeto, _evento(projeto, tr), binf)

    assert _entradas(projeto) == 2, r.stderr


def test_entrada_em_mes_arquivado_tambem_conta(projeto: Path, tmp_path: Path):
    """`arquivos_do_diario` varre `arquivo/`, então uma correção lá também é registro."""
    from harness_memoria.hooks import session_end as se

    pasta = projeto / "docs" / "diario"
    assert se._ja_registrada([str(pasta / "arquivo" / "2026-01.md")], pasta) is not None
    assert se._ja_registrada([str(pasta / "arquivo" / "notas.md")], pasta) is None
    assert se._ja_registrada([str(projeto / "docs" / "2026-09.md")], pasta) is None
    assert se._ja_registrada([str(pasta / "2026-09b.md")], pasta) is not None


def test_marca_por_conteudo_nao_colide_como_o_stat_colidia(projeto: Path):
    """Duas sessões com o MESMO `--stat` e conteúdo diferente têm de ser distinguidas.

    `git diff --stat` é um sumário: trocar 4 linhas por outras 4 no mesmo arquivo produz
    `arquivo | 8 ++++----` idêntico. Com a marca guardando o TEXTO do `--stat`, a segunda
    sessão de orquestração era descartada como "worktree igual ao da anterior" — perda
    silenciosa na única via que o `diffstat` existe para servir. Achado pelo verificador em
    três sessões de orquestração seguidas num consumidor.

    Reprova na versão que compara `--stat`: lá as duas impressões saem iguais.
    """
    from harness_memoria.hooks import session_end as se

    alvo = projeto / "scripts" / "alvo.py"
    alvo.write_text("a = 1\nb = 2\nc = 3\nd = 4\n", encoding="utf-8")
    _repo_com_base(projeto)

    alvo.write_text("a = 9\nb = 9\nc = 9\nd = 9\n", encoding="utf-8")
    primeira = se._impressao_do_diff(projeto)
    alvo.write_text("a = 7\nb = 7\nc = 7\nd = 7\n", encoding="utf-8")
    segunda = se._impressao_do_diff(projeto)

    # A colisão do sumário é a PREMISSA do defeito. Se um dia ela deixar de valer, este
    # assert falha e o teste perde o sentido em vez de virar falso positivo silencioso.
    assert primeira.splitlines()[1:] == segunda.splitlines()[1:], "o --stat deixou de colidir"
    # O conteúdo não colide, e é por isso que a comparação passou a ser por ele.
    assert se._hash_de(primeira) != se._hash_de(segunda)


def test_marca_de_versao_antiga_cai_no_caminho_de_ignorancia():
    """Marca sem o prefixo é de um hook anterior: `None`, não comparação que nunca casa.

    Sem isto, o consumidor que já tinha marca no temp compararia hash com texto de `--stat`,
    nunca casaria, e a entrada de ruído por sujeira antiga voltaria calada.
    """
    from harness_memoria.hooks import session_end as se

    assert se._hash_de(" scripts/a.py | 2 +-\n 1 file changed") is None
    assert se._hash_de("") is None
    assert se._hash_de(None) is None
    assert se._hash_de(se._PREFIXO_IMPRESSAO + "abc123\n stat legivel aqui") == "abc123"
