"""A seção `sensores` do harness.json: carga estrita e auditoria do que não age.

Mesma divisão das guardas (`_CHAVES_DE_REGRA` × `CHAVES_OBRIGATORIAS_DE_REGRA`): chave
DESCONHECIDA num sensor não tem interpretação válida e reprova na carga; chave obrigatória
AUSENTE produz um sensor que faz parse e não roda, e reprova na auditoria — lançar na carga
deixaria todos os hooks inertes num upgrade de plugin.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import escrever_config

from harness_memoria.auditar import Contexto, rodar
from harness_memoria.config import ErroDeConfig, carregar

VALIDO = {"nome": "testes", "comando": ["python", "-c", "pass"], "extensoes": [".py"]}


def _auditar(raiz: Path) -> Contexto:
    cfg = carregar(raiz)
    assert cfg is not None
    ctx = Contexto(raiz=raiz, cfg=cfg)
    rodar(ctx)
    return ctx


def _falhas_de_sensor(ctx: Contexto) -> list[str]:
    return [f for f in ctx.falhas if "sensores" in f]


def test_sem_secao_nao_ha_sensor(projeto: Path):
    cfg = carregar(projeto)
    assert cfg is not None and cfg.sensores.comandos == ()


def test_sensor_valido_carrega_e_passa_na_auditoria(projeto: Path):
    escrever_config(projeto, {"sensores": {"comandos": [VALIDO, {**VALIDO, "nome": "lint"}]}})
    cfg = carregar(projeto)
    assert cfg is not None and [s["nome"] for s in cfg.sensores.comandos] == ["testes", "lint"]
    assert _falhas_de_sensor(_auditar(projeto)) == []


def test_chave_desconhecida_no_sensor_reprova_na_carga(projeto: Path):
    escrever_config(projeto, {"sensores": {"comandos": [{**VALIDO, "timeout": 30}]}})
    with pytest.raises(ErroDeConfig, match=r"sensores\.comandos\[0\].*timeout"):
        carregar(projeto)


def test_sensor_que_nao_e_objeto_reprova_na_carga(projeto: Path):
    escrever_config(projeto, {"sensores": {"comandos": ["uv run pytest"]}})
    with pytest.raises(ErroDeConfig, match="deveria ser um objeto"):
        carregar(projeto)


def test_anotacao_no_sensor_e_aceita(projeto: Path):
    escrever_config(projeto, {"sensores": {"comandos": [{**VALIDO, "$por_que": "x"}]}})
    assert carregar(projeto) is not None


def test_auditoria_reprova_sensor_sem_comando(projeto: Path):
    escrever_config(projeto, {"sensores": {"comandos": [{"nome": "testes"}]}})
    assert [f for f in _falhas_de_sensor(_auditar(projeto)) if "`comando`" in f]


def test_auditoria_reprova_comando_que_nao_e_lista_de_strings(projeto: Path):
    escrever_config(projeto, {"sensores": {"comandos": [{"nome": "t", "comando": "pytest -x"}]}})
    assert [f for f in _falhas_de_sensor(_auditar(projeto)) if "lista" in f]


def test_auditoria_reprova_nome_duplicado(projeto: Path):
    escrever_config(projeto, {"sensores": {"comandos": [VALIDO, VALIDO]}})
    assert [f for f in _falhas_de_sensor(_auditar(projeto)) if "duplicado" in f]


def test_auditoria_reprova_timeout_acima_do_orcamento(projeto: Path):
    escrever_config(
        projeto,
        {"sensores": {"orcamento_total_s": 60, "comandos": [{**VALIDO, "timeout_s": 90}]}},
    )
    assert [f for f in _falhas_de_sensor(_auditar(projeto)) if "orcamento_total_s" in f]


def test_auditoria_reprova_cwd_inexistente(projeto: Path):
    escrever_config(projeto, {"sensores": {"comandos": [{**VALIDO, "cwd": "apps/web"}]}})
    assert [f for f in _falhas_de_sensor(_auditar(projeto)) if "apps/web" in f]


def test_auditoria_reprova_placeholder_de_arquivo(projeto: Path):
    sensor = {**VALIDO, "comando": ["ruff", "check", "{arquivo}"]}
    escrever_config(projeto, {"sensores": {"comandos": [sensor]}})
    assert [f for f in _falhas_de_sensor(_auditar(projeto)) if "{arquivo" in f]
