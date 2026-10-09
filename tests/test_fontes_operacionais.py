"""Fontes operacionais: o default cobre o layout de plugin, e o projeto SOMA as suas.

Dois buracos medidos neste repositório em 2026-10-09. As quatro `skills/*/SKILL.md` do
próprio plugin ficavam fora de todo cheque de ponteiro velho — o default só conhecia a
convenção de projeto consumidor (`.claude/skills/*/SKILL.md`). E o `FUNDAMENTOS.md`, de 803
linhas, pedia por escrito para entrar na auditoria e não entrava: a única forma de pô-lo lá
era sobrescrever a lista inteira no `harness.json`, copiando os doze padrões do default — a
config que repete o default e mente sobre ter sido pensada.
"""

from __future__ import annotations

from pathlib import Path

from conftest import escrever_config

from harness_memoria.auditar import Contexto, rodar
from harness_memoria.config import ConfigAuditoria, carregar


def _auditar(raiz: Path) -> Contexto:
    cfg = carregar(raiz)
    assert cfg is not None
    ctx = Contexto(raiz=raiz, cfg=cfg)
    rodar(ctx)
    return ctx


def _cita_script_morto(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("Rode `python scripts/sumiu.py` antes de tudo.\n", encoding="utf-8")


def test_skill_de_plugin_e_fonte_operacional(projeto: Path):
    assert "skills/*/SKILL.md" in ConfigAuditoria().fontes_operacionais
    _cita_script_morto(projeto / "skills" / "minha-skill" / "SKILL.md")
    ctx = _auditar(projeto)
    assert [f for f in ctx.falhas if f.startswith("skills/minha-skill/SKILL.md cita")]


def test_fontes_extras_somam_ao_default(projeto: Path):
    _cita_script_morto(projeto / "FUNDAMENTOS.md")
    assert not [f for f in _auditar(projeto).falhas if "FUNDAMENTOS.md cita" in f]

    escrever_config(projeto, {"auditoria": {"fontes_operacionais_extras": ["FUNDAMENTOS.md"]}})
    ctx = _auditar(projeto)
    assert [f for f in ctx.falhas if f.startswith("FUNDAMENTOS.md cita")]
    # o default continua valendo: o CLAUDE.md segue auditado
    assert ctx.fontes_operacionais()[0].name == "CLAUDE.md"


def test_fonte_extra_que_nao_casa_nada_reprova(projeto: Path):
    escrever_config(projeto, {"auditoria": {"fontes_operacionais_extras": ["NAO-EXISTE.md"]}})
    ctx = _auditar(projeto)
    assert [f for f in ctx.falhas if "NAO-EXISTE.md" in f and "não casa" in f]


def test_arquivo_casado_por_dois_padroes_e_auditado_uma_vez(projeto: Path):
    escrever_config(projeto, {"auditoria": {"fontes_operacionais_extras": ["*.md"]}})
    _cita_script_morto(projeto / "README.md")
    ctx = _auditar(projeto)
    assert len([f for f in ctx.falhas if f.startswith("README.md cita")]) == 1
