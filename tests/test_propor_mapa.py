"""Rascunho de divisão das linhas grossas do mapa "Qual ADR ler" (`--propor-mapa`).

O auditor avisa a linha com ADRs demais (ADR-0009), mas dividi-la à mão em cada projeto é o
tipo de tarefa que ninguém faz: no ValidaNI, `apps/web/src/` aponta 58 ADRs. O rascunho sai
dos caminhos que cada ADR cita; o que não dá para decidir sem julgamento sai à parte.
"""

from __future__ import annotations

from pathlib import Path

from harness_memoria.auditar import mapa
from harness_memoria.auditar.__main__ import main

ARQUIVOS = [
    "web/src/main.tsx",
    "web/src/styles/tokens.css",
    "web/src/styles/tema.css",
    "web/src/lib/api.ts",
    "web/src/lib/sync/fila.ts",
    "web/src/lib/sync/retry.ts",
    "web/src/components/Card.tsx",
    "web/src/components/a/index.ts",
    "web/src/components/b/index.ts",
    "web/src/components/c/index.ts",
    "web/src/components/d/index.ts",
    "README.md",
]


def _adr(raiz: Path, num: str, corpo: str) -> None:
    (raiz / "docs" / "adr" / f"{num}-x.md").write_text(
        f"---\nstatus: accepted\ndata: 2026-01-01\n---\n\n# ADR-{num} — Decisão {num}\n\n{corpo}\n",
        encoding="utf-8",
    )


def _corpus(raiz: Path) -> None:
    (raiz / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    _adr(raiz, "0010", "Os tokens moram em `styles/tokens.css`.")
    _adr(raiz, "0011", "Tema em `web/src/styles/tema.css` e em `src/styles/`.")
    _adr(raiz, "0012", "Cliente HTTP único: `lib/api.ts`.")
    _adr(raiz, "0013", "A fila de sync em `lib/sync/fila.ts`.")
    _adr(raiz, "0014", "Retry exponencial: `sync/retry.ts`, sem `lib/api.ts`.")
    _adr(raiz, "0015", "O cartão: `Card.tsx`.")
    _adr(raiz, "0016", "O ponto de entrada `main.tsx` registra o service worker.")
    _adr(raiz, "0017", "Controle de acesso: NI edita, não-NI é espectador.")
    _adr(raiz, "0018", "Todo componente exporta de `index.ts`.")  # 4 arquivos: ambíguo


def _proposta(raiz: Path, teto: int):
    nums = [f"{n:04d}" for n in range(10, 19)]
    return mapa.propor_divisao(raiz / "docs" / "adr", ["web/src/"], nums, ARQUIVOS, teto)


def test_divide_pelas_pastas_que_os_adrs_citam(tmp_path: Path):
    _corpus(tmp_path)
    p = _proposta(tmp_path, teto=10)
    assert dict(p.por_pasta) == {
        "web/src/components/": ["0015"],
        "web/src/lib/": ["0012", "0013", "0014"],
        "web/src/styles/": ["0010", "0011"],
    }


def test_pasta_ainda_grossa_desce_um_nivel(tmp_path: Path):
    _corpus(tmp_path)
    p = _proposta(tmp_path, teto=2)
    assert dict(p.por_pasta)["web/src/lib/sync/"] == ["0013", "0014"]
    assert dict(p.por_pasta)["web/src/lib/"] == ["0012", "0014"]
    assert "web/src/lib/sync/" in dict(p.por_pasta)


def test_pasta_que_nao_divide_mais_desce_ate_o_arquivo(tmp_path: Path):
    """Medido no ValidaNI: `styles/` tem 8 arquivos e 20 ADRs, que citam `bruma.css`,
    `tokens.css` e `global.css`. Pasta não basta; o arquivo basta. O ADR que cita a pasta
    inteira continua na linha da pasta, e não se repete na do arquivo."""
    _corpus(tmp_path)
    p = dict(_proposta(tmp_path, teto=1).por_pasta)
    assert p["web/src/lib/api.ts"] == ["0012", "0014"]
    assert p["web/src/lib/sync/fila.ts"] == ["0013"]
    assert p["web/src/lib/sync/retry.ts"] == ["0014"]
    assert p["web/src/styles/"] == ["0011"]
    assert p["web/src/styles/tokens.css"] == ["0010"]
    assert "web/src/styles/tema.css" not in p
    assert "web/src/lib/" not in p


def test_arquivo_solto_na_pasta_da_linha_sai_a_parte(tmp_path: Path):
    """Um arquivo citado direto na pasta da linha costuma ser o registro daquela mudança —
    como cada migração do ValidaNI —, não regra para o próximo arquivo da pasta."""
    _corpus(tmp_path)
    p = _proposta(tmp_path, teto=10)
    assert p.soltos == {"0016": ["web/src/main.tsx"]}


def test_link_markdown_relativo_conta_como_citacao(tmp_path: Path):
    """No ValidaNI, o ADR-0082 cita `writer.py` só num link `../../services/…/writer.py`."""
    _corpus(tmp_path)
    _adr(tmp_path, "0017", "Ver [o cliente](../../web/src/lib/api.ts#L10).")
    p = _proposta(tmp_path, teto=10)
    assert "0017" in dict(p.por_pasta)["web/src/lib/"]
    assert "0017" not in p.sem_caminho


def test_sem_caminho_e_token_ambiguo_vao_para_julgamento(tmp_path: Path):
    _corpus(tmp_path)
    p = _proposta(tmp_path, teto=10)
    assert p.sem_caminho == ["0017", "0018"]


def test_texto_da_proposta_traz_linhas_prontas_e_os_titulos_para_julgar(tmp_path: Path):
    _corpus(tmp_path)
    texto = mapa.formatar(_proposta(tmp_path, teto=10), tmp_path / "docs" / "adr")
    assert "| `web/src/lib/` | 0012, 0013, 0014 |" in texto
    assert "0017" in texto and "Decisão 0017" in texto
    assert "`web/src/main.tsx`" in texto


def test_cli_propoe_so_as_linhas_grossas_e_sai_com_zero(projeto: Path, capsys):
    _corpus(projeto)
    _adr(projeto, "0019", "Sem caminho.")
    _adr(projeto, "0020", "Sem caminho também.")  # 11 ADRs: acima do limite de 10
    for a in ARQUIVOS:
        (projeto / a).parent.mkdir(parents=True, exist_ok=True)
        (projeto / a).write_text("x\n", encoding="utf-8")
    nums = ", ".join(f"{n:04d}" for n in range(10, 21))
    claude = projeto / "CLAUDE.md"
    claude.write_text(
        claude.read_text(encoding="utf-8") + f"| `web/src/` | {nums} |\n", encoding="utf-8"
    )
    assert main(["--projeto", str(projeto), "--propor-mapa"]) == 0
    saida = capsys.readouterr().out
    assert "`web/src/`" in saida and "| `web/src/lib/` | 0012, 0013, 0014 |" in saida
    assert "`scripts/`" not in saida.split("Linhas grossas")[-1]


def test_cli_sem_linha_grossa_diz_que_nao_ha_o_que_propor(projeto: Path, capsys):
    assert main(["--projeto", str(projeto), "--propor-mapa"]) == 0
    assert "nenhuma linha" in capsys.readouterr().out.lower()


def test_sem_caminho_que_ja_esta_em_outra_linha_e_apontado(tmp_path: Path):
    """Medido no ValidaNI: dos 17 ADRs sem caminho em `apps/web/src/`, 14 já estão na linha
    da própria funcionalidade. Esses saem da linha grossa sem perda; o julgamento fica para
    os outros 3."""
    _corpus(tmp_path)
    grossa = [f"{n:04d}" for n in range(40, 50)] + ["0018"]  # 11: também vai ser dividida
    outras = [(["services/sync/"], ["0017"]), (["web/src/"], ["0018"]), (["api/"], grossa)]
    texto = mapa.formatar(_proposta(tmp_path, teto=10), tmp_path / "docs" / "adr", outras)
    linha_17 = next(x for x in texto.splitlines() if x.startswith("- 0017"))
    linha_18 = next(x for x in texto.splitlines() if x.startswith("- 0018"))
    assert "`services/sync/`" in linha_17
    # A linha em divisão não conta; outra linha grossa conta, marcada — ela pode ser dividida
    # também, e aí o ADR pode sair dela.
    assert "`web/src/`" not in linha_18
    assert "`api/` — linha grossa" in linha_18


def test_arquivo_ainda_grosso_nao_recebe_conselho_de_pasta(tmp_path: Path):
    _corpus(tmp_path)
    p = _proposta(tmp_path, teto=10)
    p.por_pasta.append(("web/src/styles/tokens.css", [f"{n:04d}" for n in range(30, 42)]))
    texto = mapa.formatar(p, tmp_path / "docs" / "adr")
    assert "`web/src/styles/tokens.css`" in texto.split("Ainda acima")[1]
    assert "arquivo NOVO" not in texto.split("Ainda acima")[1].split("\n\n")[0]
