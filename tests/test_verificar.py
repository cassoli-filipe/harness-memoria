"""Sensores no `Stop`: verificar o que o turno escreveu antes de o agente dizer "pronto".

Até aqui o harness só tinha GUIAS (reinjeção, reafirmação) e uma guarda preventiva; nada
conferia o trabalho do agente dentro do loop. A auditoria roda no CI, depois do push, e só
olha documentação. O sensor fecha o laço: o turno que escreveu código só termina com os
comandos de verificação do projeto verdes — ou com a falha devolvida ao agente, com a cauda
da saída e o que fazer.

Plataforma medida em 2026-10-09 (`claude -p` 2.1.295): o `Stop` de plugin respeita o
`timeout` do `hooks.json`, um hook de 90 s completa e bloqueia, e o motivo do bloqueio entra
no transcript como `user` com `isMeta: true`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import escrever_config

from harness_memoria import diario, sensores
from harness_memoria.config import carregar

HOOK = Path(__file__).resolve().parents[1] / "src" / "harness_memoria" / "hooks" / "verificar.py"
FALHA = [sys.executable, "-c", "import sys; print('linha 1'); print('boom final'); sys.exit(1)"]
PASSA = [sys.executable, "-c", "print('ok')"]


# --------------------------------------------------------------------------- #
# Transcript sintético no formato real
# --------------------------------------------------------------------------- #


def _prompt(texto: str, ts: str) -> dict:
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": texto}}


def _escrita(caminho: str, ts: str, ferramenta: str = "Write") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"id-{caminho}",
                    "name": ferramenta,
                    "input": {"file_path": caminho},
                }
            ],
        },
    }


def _feedback_do_stop(ts: str) -> dict:
    return {
        "type": "user",
        "isMeta": True,
        "timestamp": ts,
        "message": {"role": "user", "content": "Stop hook feedback:\nreprovou"},
    }


def _transcript(tmp_path: Path, linhas: list[dict]) -> Path:
    p = tmp_path / "sessao.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in linhas), encoding="utf-8")
    return p


def _turno_que_escreveu(tmp_path: Path, raiz: Path, nome: str = "x.py") -> Path:
    alvo = raiz / "scripts" / nome
    alvo.write_text("x = 1\n", encoding="utf-8")
    return _transcript(
        tmp_path,
        [
            _prompt("faça X", "2026-10-09T10:00:00.000Z"),
            _escrita(str(alvo), "2026-10-09T10:00:05Z"),
        ],
    )


# --------------------------------------------------------------------------- #
# Janela do turno
# --------------------------------------------------------------------------- #


def test_janela_do_turno_comeca_no_ultimo_prompt_humano(tmp_path: Path):
    t = _transcript(
        tmp_path,
        [
            _prompt("primeiro", "2026-10-09T10:00:00Z"),
            _escrita("/p/a.py", "2026-10-09T10:00:01Z"),
            _prompt("segundo", "2026-10-09T11:00:00.500Z"),
            _escrita("/p/b.py", "2026-10-09T11:00:01Z"),
            _feedback_do_stop("2026-10-09T11:00:02Z"),
            _escrita("/p/c.md", "2026-10-09T11:00:03Z", "Edit"),
        ],
    )
    escritos, inicio = sensores.arquivos_do_turno(str(t), tmp_path)
    assert escritos == ["/p/b.py", "/p/c.md"]
    esperado = datetime(2026, 10, 9, 11, 0, 0, 500_000, tzinfo=timezone.utc).timestamp()
    assert inicio == pytest.approx(esperado)


@pytest.mark.skipif(shutil.which("git") is None, reason="git ausente")
def test_janela_soma_o_que_o_git_viu_mudar_depois_do_inicio(tmp_path: Path):
    raiz = tmp_path / "repo"
    raiz.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=raiz, check=True)
    velho = raiz / "velho.py"
    velho.write_text("a\n", encoding="utf-8")
    os.utime(velho, (time.time() - 3600, time.time() - 3600))
    (raiz / "via_bash.py").write_text("b\n", encoding="utf-8")
    # Nome acentuado: no Windows a saída do git vinha decodificada em cp1252 e o caminho
    # chegava corrompido ao sensor.
    (raiz / "ação.py").write_text("c\n", encoding="utf-8")
    agora = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    t = _transcript(tmp_path, [_prompt("gere o código", agora)])
    escritos, _ = sensores.arquivos_do_turno(str(t), raiz)
    nomes = [Path(e).name for e in escritos]
    assert "via_bash.py" in nomes
    assert "ação.py" in nomes
    assert "velho.py" not in nomes


def test_sem_transcript_nao_ha_janela(tmp_path: Path):
    assert sensores.arquivos_do_turno(None, tmp_path) == ([], None)


def test_seleciona_por_extensao_e_relanca_quem_falhou(tmp_path: Path):
    cfg_s = (
        {"nome": "py", "comando": PASSA, "extensoes": [".py"]},
        {"nome": "md", "comando": PASSA, "extensoes": [".md"]},
        {"nome": "tudo", "comando": PASSA},
    )
    nomes = [s["nome"] for s in sensores.selecionar(cfg_s, ["/p/a.py"], set())]
    assert nomes == ["py", "tudo"]
    assert sensores.selecionar(cfg_s, [], set()) == []
    assert [s["nome"] for s in sensores.selecionar(cfg_s, [], {"md"})] == ["md"]


# --------------------------------------------------------------------------- #
# O hook como o Claude Code o roda
# --------------------------------------------------------------------------- #


def _config(raiz: Path, *comandos: dict, **extra) -> None:
    escrever_config(raiz, {"sensores": {"comandos": list(comandos), **extra}})


def _rodar(
    raiz: Path,
    transcript: Path | None,
    sessao: str,
    ativo: bool = False,
    ultima: str = "Pronto.",
    env_extra: dict | None = None,
    args=(),
):
    evento = {
        "session_id": sessao,
        "transcript_path": str(transcript) if transcript else None,
        "cwd": str(raiz),
        "hook_event_name": "Stop",
        "stop_hook_active": ativo,
        "last_assistant_message": ultima,
    }
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("CLAUDE_PROJECT_DIR", "HARNESS_MEMORIA_NARRANDO", "HARNESS_MEMORIA_SENSORES")
    }
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(HOOK), *args],
        input=json.dumps(evento),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=raiz,
        env=env,
        timeout=60,
    )


def _saida(r) -> dict:
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else {}


def test_bloqueia_com_a_cauda_e_o_que_fazer(projeto: Path, tmp_path: Path):
    _config(
        projeto,
        {
            "nome": "testes",
            "comando": FALHA,
            "extensoes": [".py"],
            "remediacao": "Não marque teste como skip.",
        },
    )
    out = _saida(_rodar(projeto, _turno_que_escreveu(tmp_path, projeto), "s-bloqueia"))
    assert out["decision"] == "block"
    assert "testes" in out["reason"] and "boom final" in out["reason"]
    assert "tentativa 1 de 3" in out["reason"]
    assert "Não marque teste como skip." in out["reason"]
    assert "scripts/x.py" in out["reason"]
    assert len(out["reason"]) <= sensores.TETO_DO_MOTIVO_CHARS
    # Medido no e2e de 2026-10-09: com o sensor contradizendo um pedido explícito do usuário
    # ("sem docstring"), o agente obedeceu ao usuário — certo — e gastou as 3 tentativas sem
    # ter como sair. A saída legítima existe (pergunta ao usuário libera) e tem de ser dita.
    assert "pergunte" in out["reason"]
    # ...mas a saída só vale para o OPOSTO do que o usuário pediu: com "contradiz", o agente
    # do e2e viu conflito entre "retorna a + b" e "recuse str" e deixou de consertar.
    assert "OPOSTO" in out["reason"]
    assert "testes" in out["systemMessage"]


def test_sensor_verde_nao_emite_nada(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": PASSA, "extensoes": [".py"]})
    assert _saida(_rodar(projeto, _turno_que_escreveu(tmp_path, projeto), "s-verde")) == {}


def test_turno_sem_escrita_nao_roda_sensor(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": FALHA})
    t = _transcript(tmp_path, [_prompt("só leia", "2026-10-09T10:00:00Z")])
    assert _saida(_rodar(projeto, t, "s-leitura")) == {}


def test_teto_de_bloqueios_libera_e_novo_turno_zera(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": FALHA}, max_bloqueios=2)
    t = _turno_que_escreveu(tmp_path, projeto)
    assert _saida(_rodar(projeto, t, "s-teto"))["decision"] == "block"
    assert _saida(_rodar(projeto, t, "s-teto", ativo=True))["decision"] == "block"
    liberado = _saida(_rodar(projeto, t, "s-teto", ativo=True))
    assert "decision" not in liberado
    assert "liberado" in liberado["systemMessage"]
    assert _saida(_rodar(projeto, t, "s-teto"))["decision"] == "block"


def test_continuacao_relanca_o_sensor_que_falhou_mesmo_sem_escrita(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": FALHA, "extensoes": [".py"]})
    assert _saida(_rodar(projeto, _turno_que_escreveu(tmp_path, projeto), "s-relanca"))
    sem_escrita = _transcript(tmp_path, [_prompt("faça X", "2026-10-09T10:00:00Z")])
    assert _saida(_rodar(projeto, sem_escrita, "s-relanca", ativo=True))["decision"] == "block"


def test_pergunta_ao_usuario_nao_e_bloqueada(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": FALHA})
    out = _saida(
        _rodar(
            projeto, _turno_que_escreveu(tmp_path, projeto), "s-pergunta", ultima="Prefere A ou B?"
        )
    )
    assert "decision" not in out and "pergunta" in out["systemMessage"]


def test_bloquear_false_so_avisa(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": FALHA, "bloquear": False})
    out = _saida(_rodar(projeto, _turno_que_escreveu(tmp_path, projeto), "s-aviso"))
    assert "decision" not in out and "testes" in out["systemMessage"]


def test_executavel_ausente_libera_e_avisa(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": ["nao-existe-harness-xyz"]})
    out = _saida(_rodar(projeto, _turno_que_escreveu(tmp_path, projeto), "s-ausente"))
    assert "decision" not in out and "não encontrado" in out["systemMessage"]


def test_timeout_mata_a_arvore_e_libera(projeto: Path, tmp_path: Path):
    neto = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "time.sleep(30)"
    )
    _config(projeto, {"nome": "lento", "comando": [sys.executable, "-c", neto], "timeout_s": 1})
    t0 = time.time()
    out = _saida(_rodar(projeto, _turno_que_escreveu(tmp_path, projeto), "s-lento"))
    assert time.time() - t0 < 15, "o neto segurando a saída não pode travar o hook"
    assert "decision" not in out and "tempo" in out["systemMessage"]


@pytest.mark.parametrize(
    "var", [("HARNESS_MEMORIA_NARRANDO", "1"), ("HARNESS_MEMORIA_SENSORES", "0")]
)
def test_variaveis_de_desligamento(projeto: Path, tmp_path: Path, var):
    _config(projeto, {"nome": "testes", "comando": FALHA})
    r = _rodar(
        projeto, _turno_que_escreveu(tmp_path, projeto), "s-desligado", env_extra={var[0]: var[1]}
    )
    assert _saida(r) == {}


def test_sem_sensores_configurados_e_inerte(projeto: Path, tmp_path: Path):
    assert _saida(_rodar(projeto, _turno_que_escreveu(tmp_path, projeto), "s-vazio")) == {}


# --------------------------------------------------------------------------- #
# Diário e autoteste
# --------------------------------------------------------------------------- #


def test_resultado_do_sensor_vai_para_o_piso(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": FALHA}, max_bloqueios=1)
    t = _turno_que_escreveu(tmp_path, projeto)
    _rodar(projeto, t, "s-diario")
    _rodar(projeto, t, "s-diario", ativo=True)
    falhas = sensores.falhas_para_o_diario(projeto, "s-diario")
    assert falhas == [{"tipo": "sensor", "alvo": "testes", "detalhe": "reprovou 2×, não resolvido"}]
    assert diario.linhas_de_falhas(falhas) == ["- sensor `testes` reprovou 2×, **não resolvido**"]


def test_sensor_que_voltou_a_passar_aparece_resolvido(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": FALHA})
    t = _turno_que_escreveu(tmp_path, projeto)
    _rodar(projeto, t, "s-resolvido")
    _config(projeto, {"nome": "testes", "comando": PASSA})
    _rodar(projeto, t, "s-resolvido", ativo=True)
    assert sensores.falhas_para_o_diario(projeto, "s-resolvido")[0]["detalhe"] == (
        "reprovou 1×, resolvido"
    )


def test_autoteste_confere_os_executaveis(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": PASSA})
    ok = subprocess.run(
        [sys.executable, str(HOOK), "--autoteste", "--projeto", str(projeto)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    _config(projeto, {"nome": "testes", "comando": ["nao-existe-harness-xyz"]})
    falha = subprocess.run(
        [sys.executable, str(HOOK), "--autoteste", "--projeto", str(projeto)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert falha.returncode == 1 and "nao-existe-harness-xyz" in falha.stdout


def test_estado_de_sensor_expira_como_o_contador(projeto: Path):
    from harness_memoria.hooks import _comum as C

    velho = C.pasta_estado(projeto) / "sensores_velha.json"
    velho.write_text("{}", encoding="utf-8")
    os.utime(velho, (time.time() - 30 * 86_400, time.time() - 30 * 86_400))
    marca = C.pasta_estado(projeto) / "diffstat_visto.txt"
    marca.write_text("x", encoding="utf-8")
    os.utime(marca, (time.time() - 30 * 86_400, time.time() - 30 * 86_400))
    C._limpar_estado_velho(C.pasta_estado(projeto))
    assert not velho.exists()
    assert marca.exists(), "a marca do diffstat é do projeto e nunca expira"


def test_config_carrega_sensores_do_proprio_repositorio():
    cfg = carregar(Path(__file__).resolve().parents[1])
    assert cfg is not None and [s["nome"] for s in cfg.sensores.comandos] == ["lint", "testes"]


def test_piso_do_session_end_lista_o_sensor_vermelho(projeto: Path, tmp_path: Path):
    _config(projeto, {"nome": "testes", "comando": FALHA}, max_bloqueios=1)
    t = _turno_que_escreveu(tmp_path, projeto)
    _rodar(projeto, t, "s-piso")
    _rodar(projeto, t, "s-piso", ativo=True)

    evento = {
        "session_id": "s-piso",
        "transcript_path": str(t),
        "cwd": str(projeto),
        "hook_event_name": "SessionEnd",
        "reason": "other",
    }
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "CLAUDE_PROJECT_DIR",
            "HARNESS_MEMORIA_NARRANDO",
            "CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS",
        )
    }
    r = subprocess.run(
        [sys.executable, str(HOOK.parent / "session_end.py")],
        input=json.dumps(evento),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=projeto,
        env=env,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    mes = projeto / "docs" / "diario" / f"{datetime.now():%Y-%m}.md"
    texto = mes.read_text(encoding="utf-8")
    secao = texto.split("### Falhas observadas (fatos extraídos)")[1]
    assert secao.lstrip().startswith("- sensor `testes` reprovou 2×, **não resolvido**")


@pytest.mark.parametrize(
    "mensagem,pergunta",
    [
        ("Prefere A ou B?", True),
        # Medido no e2e: o agente pergunta e depois lista as opções — o "?" não é o último
        # caractere, e a primeira versão da heurística deixava o laço seguir até o teto.
        ("O sensor reprovou.\n\nComo você quer seguir?\n\n1. Recusar str\n2. Aceitar str", True),
        ("Pronto, `calc.py` criado e testado.", False),
        ("Usei `x if y else z`? Não — usei um if comum.\n\n" + "Detalhe longo. " * 80, False),
    ],
)
def test_pergunta_ao_usuario_e_detectada_no_fim_da_mensagem(mensagem: str, pergunta: bool):
    assert sensores.termina_com_pergunta(mensagem) is pergunta
