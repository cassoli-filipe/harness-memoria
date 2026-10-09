"""A "última entrada" injetada é a última NARRADA; registros automáticos viram resumo.

Medido na sessão de 2026-10-09 deste repositório: o SessionStart injetou como "última
entrada" o piso automático de 2026-09-08 22:06 — "0 arquivo(s) escrito(s)", "Turnos do
usuário: 0", "transcript_path ausente" e um diffstat de 27 arquivos já commitados —, e a
entrada narrada do mesmo dia, a que tinha o porquê e o beco, ficou de fora. O slot mais
caro do bloco foi ocupado pela entrada de menor informação.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from harness_memoria import diario
from harness_memoria.config import carregar
from harness_memoria.hooks import session_start as SS

MES = datetime.now().strftime("%Y-%m")


def _cfg(raiz: Path):
    cfg = carregar(raiz)
    assert cfg is not None
    return cfg


def _automatica(raiz: Path, dia: int, hora: str = "22:06", escritos: int = 0) -> str:
    """Uma entrada EXATAMENTE como o hook de fim de sessão a grava — não uma imitação."""
    h, m = (int(x) for x in hora.split(":"))
    fatos = {
        "ferramentas": {},
        "arquivos_escritos": [str(raiz / f"a{i}.py") for i in range(escritos)],
        "comandos": [],
        "turnos_usuario": 0,
        "erro_parse": "transcript_path ausente",
    }
    git = {"branch": "main", "diffstat": " x.py | 1 +", "status": "", "ultimo_commit": ""}
    quando = datetime.strptime(f"{MES}-{dia:02d} {h:02d}:{m:02d}", "%Y-%m-%d %H:%M")
    return diario.entrada_deterministica(
        raiz, raiz / "docs" / "adr", fatos, git, quando, "narrativa fora do caminho crítico"
    )


def _anexar(raiz: Path, *blocos: str) -> None:
    arq = raiz / "docs" / "diario" / f"{MES}.md"
    novo = arq.read_text(encoding="utf-8") + "".join(f"\n{b}\n" for b in blocos)
    # `encoding` explícito: sem ele o Windows grava em cp1252 e engasga na seta `→` do
    # fixture — reprovou a matriz Windows do CI na primeira rodada deste arquivo.
    arq.write_text(novo, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Reconhecer o registro automático
# --------------------------------------------------------------------------- #


def test_reconhece_a_entrada_que_o_hook_grava(projeto: Path):
    assert diario.e_automatica(_automatica(projeto, 2))


def test_rodape_da_entrada_narrada_nao_a_torna_automatica():
    narrada = (
        f"## {MES}-02 — Consertar o lock\n\n**Estado:** concluído\n\n### O que foi feito\n\n- x\n"
        "\n<!-- fatos determinísticos do hook de fim de sessão -->\n"
        "<sub>Registro automático · branch `main` · 1 arquivo(s)</sub>\n"
    )
    assert not diario.e_automatica(narrada)


def test_mencao_no_corpo_nao_torna_a_entrada_automatica():
    narrada = (
        f"## {MES}-02 — Tirar ruído do diário\n\n**Estado:** concluído\n\n"
        "### Como (o não-óbvio)\n\n**Estado:** registro automático\n"
    )
    assert not diario.e_automatica(narrada)


# --------------------------------------------------------------------------- #
# Escolher a entrada
# --------------------------------------------------------------------------- #


def test_ultima_narrada_pula_as_automaticas_e_conta_as_que_vieram_depois(projeto: Path):
    _anexar(projeto, _automatica(projeto, 2), _automatica(projeto, 3, "09:15"))
    narrada, depois = diario.ultima_narrada(projeto / "docs" / "diario")
    assert narrada is not None
    assert "Entrada de teste" in narrada[1]
    assert [c.splitlines()[0][3:13] for _, c in depois] == [f"{MES}-03", f"{MES}-02"]


def test_ultima_narrada_atravessa_para_o_arquivo(projeto: Path):
    pasta = projeto / "docs" / "diario"
    (pasta / "arquivo").mkdir()
    (pasta / f"{MES}.md").rename(pasta / "arquivo" / "2000-01.md")
    (pasta / f"{MES}.md").write_text(
        f"# Diário · {MES}\n\n---\n\n{_automatica(projeto, 2)}\n", encoding="utf-8"
    )
    narrada, depois = diario.ultima_narrada(pasta)
    assert narrada is not None and narrada[0] == "arquivo/2000-01.md"
    assert len(depois) == 1


def test_ultima_entrada_continua_sendo_a_mais_nova_de_qualquer_tipo(projeto: Path):
    _anexar(projeto, _automatica(projeto, 2))
    ultima = diario.ultima_entrada(projeto / "docs" / "diario")
    assert ultima is not None and diario.e_automatica(ultima[1])


# --------------------------------------------------------------------------- #
# O bloco injetado
# --------------------------------------------------------------------------- #


def test_bloco_injeta_a_narrada_e_resume_as_automaticas(projeto: Path):
    _anexar(projeto, _automatica(projeto, 2, escritos=3))
    texto = SS.montar(projeto, _cfg(projeto), "startup")
    assert "Entrada de teste" in texto
    assert "Sessão registrada automaticamente" not in texto
    assert "1 registro(s) automático(s)" in texto
    assert f"{MES}-02 22:06 · 3 arquivo(s) escrito(s) · branch `main`" in texto
    assert SS.conferir_fidelidade(projeto, _cfg(projeto), texto) == 0


def test_seis_automaticas_viram_cinco_linhas_e_o_resto_contado(projeto: Path):
    _anexar(projeto, *(_automatica(projeto, d) for d in range(2, 8)))
    texto = SS.montar(projeto, _cfg(projeto), "startup")
    assert "6 registro(s) automático(s)" in texto
    assert texto.count("22:06 · 0 arquivo(s)") == SS.MAX_AUTOMATICAS_NO_BLOCO
    assert "e mais 1" in texto


def test_so_automaticas_injeta_a_mais_nova_e_aponta_a_skill(projeto: Path):
    arq = projeto / "docs" / "diario" / f"{MES}.md"
    arq.write_text(f"# Diário · {MES}\n\n---\n\n{_automatica(projeto, 2)}\n", encoding="utf-8")
    texto = SS.montar(projeto, _cfg(projeto), "startup")
    assert "última entrada do diário" in texto
    assert "Sessão registrada automaticamente" in texto
    assert "/encerrar-sessao" in texto
    assert SS.conferir_fidelidade(projeto, _cfg(projeto), texto) == 0


def test_fidelidade_reprova_bloco_que_esconde_as_automaticas(projeto: Path):
    _anexar(projeto, _automatica(projeto, 2))
    texto = SS.montar(projeto, _cfg(projeto), "startup")
    mutilado = texto.replace("1 registro(s) automático(s)", "")
    assert SS.conferir_fidelidade(projeto, _cfg(projeto), mutilado) == 1


# --------------------------------------------------------------------------- #
# Aviso de rotação
# --------------------------------------------------------------------------- #


def _rotacao_pendente(raiz: Path) -> None:
    (raiz / "docs" / "diario" / "2000-01.md").write_text("# Diário · 2000-01\n", encoding="utf-8")


def test_aviso_de_rotacao_no_bloco_completo_e_nao_no_reduzido(projeto: Path):
    _rotacao_pendente(projeto)
    cfg = _cfg(projeto)
    completo = SS.montar(projeto, cfg, "startup")
    assert "Rotação do diário pendente" in completo
    assert "/auditar-docs" in completo
    assert "Rotação do diário pendente" not in SS.montar(projeto, cfg, "startup", reduzido=True)
    assert SS.conferir_fidelidade(projeto, cfg, completo) == 0


def test_sem_acao_mecanica_nao_ha_aviso(projeto: Path):
    assert "Rotação do diário pendente" not in SS.montar(projeto, _cfg(projeto), "startup")


def test_fidelidade_reprova_rotacao_pendente_sem_aviso(projeto: Path):
    _rotacao_pendente(projeto)
    cfg = _cfg(projeto)
    sem_aviso = SS.montar(projeto, cfg, "startup").split(SS.SEPARADOR, 1)[1]
    assert SS.conferir_fidelidade(projeto, cfg, sem_aviso) == 1


def test_aviso_cabe_no_orcamento_com_corpus_grande(tmp_path: Path):
    from test_session_start import corpus

    raiz = corpus(tmp_path / "proj", adrs=60, becos=100)
    _rotacao_pendente(raiz)
    cfg = _cfg(raiz)
    texto = SS.montar(raiz, cfg, "startup")
    assert "Rotação do diário pendente" in texto
    assert len(texto) <= SS.TETO_PLATAFORMA_CHARS
    assert SS.conferir_fidelidade(raiz, cfg, texto) == 0
