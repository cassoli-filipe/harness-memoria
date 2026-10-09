"""Rascunho de divisão das linhas grossas do mapa "Qual ADR ler" (`--propor-mapa`).

O auditor avisa a linha do mapa com mais de `MAX_ADRS_POR_LINHA_DO_MAPA` ADRs (ADR-0009),
porque o `PreToolUse` entrega os ADRs dela aos poucos, ao longo de várias escritas. Dividir
a linha à mão é o tipo de tarefa que ninguém faz: medido no ValidaNI, `apps/web/src/` aponta
58 ADRs. Este módulo propõe a divisão a partir dos caminhos que cada ADR CITA (entre crases),
casados contra os arquivos reais do repositório, e separa o que não dá para decidir sem
julgamento:

* **arquivo com data no nome** — o ADR cita só uma migração (`20260805160000_x.sql`) da
  pasta da linha. No ValidaNI são 20 dos 35 ADRs de `supabase/migrations/`: cada um registra
  aquela mudança e, em geral, não é regra para a próxima migração;
* **sem caminho** — o ADR não cita nada reconhecível sob a linha: ou é regra geral da pasta,
  ou está no mapa por engano.

Só imprime. Nunca escreve no `CLAUDE.md`: o mapa é política do projeto (CLAUDE.md, regra
"política vem do consumidor"), e o rascunho é para alguém revisar e colar.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..adr import MAX_ADRS_POR_LINHA_DO_MAPA, dados_dos_adrs, ler_mapa

_TOKEN = re.compile(r"`([^`\s]+)`")

#: Destino de link markdown, relativo à pasta do ADR (`../../services/app/writer.py`). Os
#: `../` iniciais saem e o resto casa como qualquer citação — medido no ValidaNI, o ADR-0082
#: cita `writer.py` só assim. Palavra solta ("writer", "storage") NÃO conta: é ambígua demais.
_LINK = re.compile(r"\]\(([^)\s]+)\)")

#: Um token que casa mais arquivos que isto é ambíguo (`index.ts`, `__init__.py`) e não diz
#: a qual pasta o ADR pertence — tratado como não citado, em vez de espalhar o ADR por todas.
_MAX_CASAMENTOS_POR_TOKEN = 3

#: Arquivo que se cria uma vez e não se edita: a migração (`20260805160000_x.sql`). O ADR que
#: cita só um desses registra aquela mudança e, em geral, não é regra para o próximo arquivo
#: da pasta — vai para julgamento. Sem a data, o arquivo citado direto na pasta da linha é
#: módulo vivo (no rede-inspira, `ingest/bronze.py`) e ganha linha própria.
_COM_DATA_NO_NOME = re.compile(r"\d{8,}[_-]")

_PASTAS_IGNORADAS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


@dataclass
class Proposta:
    linha: list[str]
    total: int
    por_pasta: list[tuple[str, list[str]]] = field(default_factory=list)
    soltos: dict[str, list[str]] = field(default_factory=dict)
    sem_caminho: list[str] = field(default_factory=list)


def propor_divisao(
    pasta_adr: Path,
    linha: list[str],
    nums: list[str],
    arquivos: list[str],
    teto: int = MAX_ADRS_POR_LINHA_DO_MAPA,
) -> Proposta:
    """Divide a linha `linha → nums` pelas pastas que os ADRs citam.

    Cada ADR vai para a subpasta (um nível abaixo da pasta da linha) de cada caminho que
    cita; uma subpasta que ainda passa de `teto` desce mais um nível, e nela o ADR que cita
    um arquivo direto da subpasta fica na linha da própria subpasta.
    """
    dados = dados_dos_adrs(pasta_adr)
    # Pasta é a entrada com `/` no fim ou com algum arquivo do repositório sob ela; a lista
    # de arquivos é a fonte, não o disco, para o rascunho valer sobre o que está versionado.
    bases = [
        c.strip().rstrip("/") + "/"
        for c in linha
        if c.strip().endswith("/") or any(a.startswith(c.strip() + "/") for a in arquivos)
    ]
    # As entradas da linha que são ARQUIVO entram como candidatas a citação e saem com linha
    # própria. Sem isto, a linha `ai/`, `meta.py`, … do rede-inspira perdia os arquivos.
    da_linha = [c.strip() for c in linha if c.strip().rstrip("/") + "/" not in bases]
    sob = sorted({a for a in arquivos if any(a.startswith(b) for b in bases)} | set(da_linha))
    pastas = sorted({a[: i + 1] for a in sob for i, ch in enumerate(a) if ch == "/"})
    pastas = [p for p in pastas if any(p.startswith(b) and p != b for b in bases)]

    proposta = Proposta(linha=linha, total=len(nums))
    citacoes: dict[str, set[str]] = {}
    for num in nums:
        texto = dados.get(num, {}).get("texto", "")
        cits = _citados(texto, sob, pastas)
        if cits:
            citacoes[num] = cits
        else:
            proposta.sem_caminho.append(num)

    grupos: dict[str, set[str]] = {}
    for base in bases:
        linhas, soltos = _dividir(base, citacoes, teto, raiz_da_linha=True)
        for pasta, ns in linhas:
            grupos.setdefault(pasta, set()).update(ns)
        for num, arqs in soltos.items():
            proposta.soltos.setdefault(num, []).extend(arqs)
    for arquivo in da_linha:
        ns = {n for n, cits in citacoes.items() if arquivo in cits}
        if ns:
            grupos.setdefault(arquivo, set()).update(ns)
    proposta.por_pasta = [(p, sorted(ns)) for p, ns in sorted(grupos.items())]
    proposta.soltos = {n: sorted(set(a)) for n, a in sorted(proposta.soltos.items())}
    return proposta


def _citados(texto: str, sob: list[str], pastas: list[str]) -> set[str]:
    """Arquivos e pastas (com `/` no fim) sob a linha que o texto do ADR cita entre crases."""
    saida: set[str] = set()
    brutos = _TOKEN.findall(texto) + [re.sub(r"^(?:\.\./)+", "", x) for x in _LINK.findall(texto)]
    for bruto in brutos:
        tok = bruto.strip().rstrip(".,:;)").removeprefix("./").split("#")[0]
        tok = re.sub(r":\d+(?:-\d+)?$", "", tok)
        if len(tok) < 4 or ("/" not in tok and "." not in tok):
            continue
        alvo = tok.rstrip("/")
        achados = [a for a in sob if a == alvo or a.endswith("/" + alvo)]
        achados += [p for p in pastas if p[:-1] == alvo or p[:-1].endswith("/" + alvo)]
        if 0 < len(achados) <= _MAX_CASAMENTOS_POR_TOKEN:
            saida.update(achados)
    return saida


def _dividir(
    base: str, citacoes: dict[str, set[str]], teto: int, *, raiz_da_linha: bool
) -> tuple[list[tuple[str, set[str]]], dict[str, list[str]]]:
    """`(linhas, soltos)` das citações que caem sob `base`.

    Fora da pasta da linha original, um arquivo citado direto em `base` leva o ADR para a
    linha de `base` — ou, quando essa linha passaria de `teto`, para uma linha do próprio
    arquivo. O ADR que cita a pasta inteira fica na linha da pasta e não se repete na do
    arquivo, que o prefixo já cobre.
    """
    da_pasta: set[str] = set()
    por_arquivo: dict[str, set[str]] = {}
    soltos: dict[str, list[str]] = {}
    filhos: dict[str, set[str]] = {}
    for num, cits in citacoes.items():
        for c in cits:
            if not c.startswith(base):
                continue
            resto = c[len(base) :]
            if not resto:
                da_pasta.add(num)
            elif "/" in resto:
                filhos.setdefault(base + resto.split("/")[0] + "/", set()).add(num)
            elif raiz_da_linha and _COM_DATA_NO_NOME.match(resto):
                soltos.setdefault(num, []).append(c)
            else:
                por_arquivo.setdefault(c, set()).add(num)

    linhas: list[tuple[str, set[str]]] = []
    # Na pasta da linha original, juntar os arquivos na linha da pasta recriaria a linha grossa.
    if not raiz_da_linha and len(da_pasta.union(*por_arquivo.values())) <= teto:
        da_pasta = da_pasta.union(*por_arquivo.values())
        por_arquivo = {}
    if da_pasta:
        linhas.append((base, da_pasta))
    for arquivo, nums in sorted(por_arquivo.items()):
        if nums - da_pasta:
            linhas.append((arquivo, nums - da_pasta))
    for filho, nums in sorted(filhos.items()):
        if len(nums) <= teto:
            linhas.append((filho, nums))
            continue
        sub = {n: {c for c in citacoes[n] if c.startswith(filho)} for n in nums}
        mais, _ = _dividir(filho, sub, teto, raiz_da_linha=False)
        linhas.extend(mais)
    return linhas, soltos


def formatar(
    proposta: Proposta,
    pasta_adr: Path,
    mapa: list[tuple[list[str], list[str]]] | None = None,
) -> str:
    """O rascunho em markdown: linhas prontas para colar e as listas para julgar.

    Com `mapa`, o ADR que está para julgar e já aparece noutra linha diz qual: tirá-lo da
    linha grossa não o tira do mapa. Medido no ValidaNI, 14 dos 17 ADRs sem caminho de
    `apps/web/src/` já estavam na linha da própria funcionalidade.
    """
    dados = dados_dos_adrs(pasta_adr)
    outras = [(c, ns) for c, ns in (mapa or []) if c != proposta.linha]

    def titulo(n: str) -> str:
        nome = dados.get(n, {}).get("titulo") or "(arquivo não encontrado)"
        # Prefere uma linha que fica; uma linha grossa vai marcada, porque também pode ser
        # dividida e o ADR pode sair dela.
        onde = sorted((len(ns) > MAX_ADRS_POR_LINHA_DO_MAPA, c) for c, ns in outras if n in ns)
        if not onde:
            return nome
        grossa, caminhos = onde[0]
        marca = " — linha grossa, também pode ser dividida" if grossa else ""
        return f"{nome} (também em {', '.join(f'`{x}`' for x in caminhos)}{marca})"

    linha = ", ".join(f"`{c}`" for c in proposta.linha)
    partes = [f"### {linha} — {proposta.total} ADRs"]
    if proposta.por_pasta:
        partes.append("Linhas por pasta ou arquivo, para pôr no mapa no lugar da original:")
        partes.append("\n".join(f"| `{p}` | {', '.join(ns)} |" for p, ns in proposta.por_pasta))
        grossas = [p for p, ns in proposta.por_pasta if len(ns) > MAX_ADRS_POR_LINHA_DO_MAPA]
        pastas = ", ".join(f"`{p}`" for p in grossas if p.endswith("/"))
        arquivos = ", ".join(f"`{p}`" for p in grossas if not p.endswith("/"))
        conselhos = []
        if pastas:
            conselhos.append(f"na pasta {pastas}, deixe só os que restringem arquivo NOVO nela")
        if arquivos:
            conselhos.append(
                f"no arquivo {arquivos}, deixe só os que valem hoje — um ADR posterior pode ter "
                f"trocado a regra de um anterior sem marcá-lo"
            )
        if conselhos:
            partes.append(
                f"Ainda acima de {MAX_ADRS_POR_LINHA_DO_MAPA} ADRs: " + "; ".join(conselhos) + "."
            )
    if proposta.soltos:
        partes.append(
            "Citam só arquivo com data no nome (migração) na pasta da linha. Em geral registram "
            "aquela mudança e não são regra para o próximo arquivo; ponha numa linha só os que "
            "forem:"
        )
        partes.append(
            "\n".join(
                f"- {n} {titulo(n)} — {', '.join(f'`{a}`' for a in arqs)}"
                for n, arqs in proposta.soltos.items()
            )
        )
    if proposta.sem_caminho:
        partes.append(
            "Não citam caminho reconhecível sob a linha. Decida um a um: regra geral da pasta "
            '(fica numa linha só com a pasta da linha original) ou fora desta linha. "Também '
            'em" diz onde o ADR continua no mapa se sair daqui — quem edita esta pasta é que '
            "deixa de recebê-lo:"
        )
        partes.append("\n".join(f"- {n} {titulo(n)}" for n in proposta.sem_caminho))
    return "\n\n".join(partes)


def propor_para_o_projeto(raiz: Path, pasta_adr: Path) -> str:
    """O rascunho de todas as linhas grossas do `CLAUDE.md` de `raiz`."""
    mapa, origem = ler_mapa(raiz)
    if not mapa:
        return "O CLAUDE.md não tem o mapa 'Qual ADR ler' — nada a propor."
    grossas = [(c, n) for c, n in mapa if len(n) > MAX_ADRS_POR_LINHA_DO_MAPA]
    if not grossas:
        return f"Nenhuma linha do mapa passa de {MAX_ADRS_POR_LINHA_DO_MAPA} ADRs — nada a propor."
    arquivos = arquivos_do_repositorio(raiz)
    blocos = [
        f"Linhas grossas do mapa em `{origem.relative_to(raiz).as_posix()}` (mais de "
        f"{MAX_ADRS_POR_LINHA_DO_MAPA} ADRs): {len(grossas)}. "
        f"Rascunho a partir dos caminhos que cada ADR cita — revise antes de colar."
    ]
    for caminhos, nums in grossas:
        p = propor_divisao(pasta_adr, caminhos, list(dict.fromkeys(nums)), arquivos)
        blocos.append(formatar(p, pasta_adr, mapa))
    return "\n\n".join(blocos)


def arquivos_do_repositorio(raiz: Path) -> list[str]:
    """`git ls-files`; sem git, uma varredura que pula as pastas de dependência e as ocultas."""
    try:
        r = subprocess.run(
            ["git", "ls-files"],
            cwd=raiz,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        pass
    saida: list[str] = []
    for pasta, subpastas, nomes in os.walk(raiz):
        subpastas[:] = [
            s for s in subpastas if s not in _PASTAS_IGNORADAS and not s.startswith(".")
        ]
        rel = Path(pasta).relative_to(raiz).as_posix()
        saida += [n if rel == "." else f"{rel}/{n}" for n in nomes]
    return saida
