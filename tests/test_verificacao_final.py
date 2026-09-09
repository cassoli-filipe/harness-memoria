"""O piso do SessionEnd não grava por sujeira de OUTRA sessão. Era o achado da verificação.

Arquivo escrito pelo verificador, não por quem implementou — existe para um achado só, e
para não deixá-lo virar folclore de relatório. Os dois casos nasceram `xfail(strict=True)`,
prendendo o defeito sem deixar a suíte vermelha; a correção fez o XPASS reprovar, que era o
critério, e o marcador saiu junto com ela. **Não devolva o `xfail`**: hoje estes dois casos
são o único lugar que reprova se a datação do `diffstat` for desfeita.

O defeito era: `session_end.main` gravava quando `arquivos_escritos or git["diffstat"]`. O
comentário no código excluía `git["status"]` como sinal, com o motivo certo ("repositório
cronicamente sujo — um `?? .venv/` que nunca sai — daria entrada em TODA sessão de
leitura"), mas mantinha `git["diffstat"]`. A distinção não se sustentava: `git diff --stat`
mostra modificação NÃO-COMMITADA de arquivo rastreado, que sobrevive ao fim da sessão
exatamente como o arquivo não-rastreado sobrevive. As duas são sujeira sem data.

Consequência medida, num consumidor sintético com uma modificação não-commitada anterior à
sessão e um transcript de sessão SÓ DE LEITURA (Read + Bash, zero escrita):
o hook anexava uma entrada cujo único conteúdo era o `git diff --stat` daquela sujeira
antiga, sob o título "Sessão registrada automaticamente" e o corpo "Nenhuma escrita de
arquivo registrada nesta sessão" — e `session_start` passava a injetar ESSA entrada como
"última entrada do diário", no lugar da decisão real. Verificado: a entrada anterior
desaparecia do bloco injetado. O diário é append-only, então a entrada não se apaga depois,
e cada sessão de leitura empurrava a memória real mais para trás.

Os dois testes que já existem em `tests/test_session_end.py` são complementares e não
cobrem este caso — nenhum dos dois estabelece QUANDO a sujeira apareceu:
  * `test_sessao_de_leitura_nao_suja_o_diario` fixa a pré-condição `diffstat == ""`
    (worktree limpo);
  * `test_diffstat_registra_a_sessao_cujas_escritas_sairam_de_subagente` cria a sujeira
    DURANTE a sessão, que é o caso que o sinal existe para pegar.

A correção, em `session_end._motivo_para_nao_registrar`: o hook grava em `C.pasta_estado`
o `git diff --stat` com que cada sessão TERMINA, e diff igual à marca deixa de contar como
mudança desta sessão. Aqui não há marca nenhuma (o projeto é novo em cada teste), então o
que estes dois casos exercitam é o default da IGNORÂNCIA — transcript legível e sem escrita
nenhuma não registra —, que é o ramo que o defeito tinha errado. Os ramos com marca, e o
`erro_parse`/`marca_gravada=False` que continuam registrando, estão em
`tests/test_session_end.py`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

HOOK_FIM = (
    Path(__file__).resolve().parents[1] / "src" / "harness_memoria" / "hooks" / "session_end.py"
)
HOOK_INICIO = (
    Path(__file__).resolve().parents[1] / "src" / "harness_memoria" / "hooks" / "session_start.py"
)

_ENTRADA = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)

#: A `CLAUDE_PROJECT_DIR` ganha do `cwd` do evento em `config.raiz_projeto`, então uma
#: sessão do Claude Code rodando esta suíte faria o hook resolver o projeto errado — e
#: escrever no diário do repositório de verdade. Aconteceu durante a verificação.
_VARS_A_LIMPAR = (
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS",
    "HARNESS_MEMORIA_NARRANDO",
    "HARNESS_MEMORIA_MODELO",
)


def _mes(raiz: Path) -> Path:
    return raiz / "docs" / "diario" / f"{datetime.now().strftime('%Y-%m')}.md"


def _entradas(raiz: Path) -> int:
    p = _mes(raiz)
    return len(_ENTRADA.findall(p.read_text(encoding="utf-8"))) if p.exists() else 0


def _git(raiz: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(raiz), *args], check=True, capture_output=True)


def _rodar(hook: Path, raiz: Path, evento: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for v in _VARS_A_LIMPAR:
        env.pop(v, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(evento),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(raiz),
        timeout=120,
    )


def _transcript_somente_leitura(base: Path) -> Path:
    """Sessão de exploração: um pedido, um Read, um Bash de leitura. Zero escrita."""
    linhas = [
        {"type": "user", "message": {"role": "user", "content": "me explica o índice de ADR"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "docs/adr/README.md"},
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "git log --oneline -5"},
                    }
                ],
            },
        },
    ]
    p = base / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(o) for o in linhas) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def projeto_sujo_de_antes(projeto: Path):
    """`projeto` da conftest, mas com uma modificação não-commitada ANTERIOR à sessão."""
    _git(projeto, "init", "-q")
    _git(projeto, "config", "user.email", "teste@local")
    _git(projeto, "config", "user.name", "teste")
    _git(projeto, "add", "-A")
    _git(projeto, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")
    # A sessão que fez esta mudança terminou; ela ficou no disco sem commit. É o estado
    # normal de quem trabalha em pedaços — e é indistinguível, para `git diff --stat`, de
    # uma mudança feita agora.
    (projeto / "scripts" / "checar.py").write_text(
        "# mexido numa sessão ANTERIOR\n", encoding="utf-8"
    )
    return projeto


@pytest.mark.skipif(shutil.which("git") is None, reason="precisa de git no PATH")
def test_leitura_em_repo_sujo_de_antes_nao_grava(projeto_sujo_de_antes: Path, tmp_path):
    """Sessão só de leitura + sujeira de antes: o piso não anexa nada.

    O diário registra RESULTADO, não presença — e o resultado aqui é de outra sessão.
    """
    raiz = projeto_sujo_de_antes
    tr = _transcript_somente_leitura(tmp_path)

    r = _rodar(
        HOOK_FIM,
        raiz,
        {
            "hook_event_name": "SessionEnd",
            "reason": "clear",
            "cwd": str(raiz),
            "session_id": "s-leitura",
            "transcript_path": str(tr),
        },
    )

    assert r.returncode == 0, r.stderr
    assert _entradas(raiz) == 1, (
        "o piso anexou entrada por sujeira de outra sessão; stderr: " + r.stderr
    )
    # O motivo vai para o stderr porque "nada a registrar" também é um resultado que
    # alguém vai precisar depurar — sem ele, o silêncio é indistinguível do hook inerte.
    assert "idade desconhecida" in r.stderr, r.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="precisa de git no PATH")
def test_a_entrada_de_ruido_nao_desloca_a_memoria_injetada(projeto_sujo_de_antes: Path, tmp_path):
    """O dano não era a linha no arquivo, era o bloco injetado na sessão SEGUINTE.

    `ultima_entrada` devolve a ÚLTIMA, e o piso anexava uma sem conteúdo: o `session_start`
    seguinte injetava "Nenhuma escrita de arquivo registrada nesta sessão" no lugar da
    entrada que documentava a decisão. É o princípio 6 ("ponteiro velho é pior que ponteiro
    nenhum") aplicado ao ponteiro NOVO e vazio — e é por isso que este teste olha o BLOCO,
    não o arquivo: contar entradas não distingue "não gravou" de "gravou e não atrapalhou".
    """
    raiz = projeto_sujo_de_antes
    tr = _transcript_somente_leitura(tmp_path)
    _rodar(
        HOOK_FIM,
        raiz,
        {
            "hook_event_name": "SessionEnd",
            "reason": "clear",
            "cwd": str(raiz),
            "session_id": "s-leitura",
            "transcript_path": str(tr),
        },
    )

    r = _rodar(
        HOOK_INICIO,
        raiz,
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "cwd": str(raiz),
            "session_id": "s-seguinte",
        },
    )
    assert r.returncode == 0, r.stderr
    bloco = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    assert "Nenhuma escrita de arquivo registrada" not in bloco, (
        "a entrada automática vazia entrou no bloco injetado"
    )
    assert "algo verificável" in bloco, (
        "a entrada real da conftest (`### O que foi feito — algo verificável`) foi "
        "deslocada do bloco pela entrada automática"
    )
