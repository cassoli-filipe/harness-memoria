#!/usr/bin/env python3
"""Hook SessionStart — reinjeta a memória do projeto no contexto.

Par do hook de fim de sessão. A evidência que sustenta o desenho é que aderência a
instrução decai DENTRO da sessão, não por causa do formato do arquivo de instruções —
portanto a contramedida é reinjeção, e o momento mais valioso é `source: compact`, quando
o contexto acabou de ser comprimido.

O autoteste confere **fidelidade**, não só que o hook roda: bloco injetado que se apresenta
como completo e não está é pior que bloco ausente, porque não gera gatilho de leitura. Cada
cheque em `conferir_fidelidade` corresponde a um defeito que existiu de verdade.

Autoteste:  python src/harness_memoria/hooks/session_start.py --autoteste [--projeto CAMINHO]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness_memoria import adr, diario  # noqa: E402
from harness_memoria.config import Config, invioaveis  # noqa: E402
from harness_memoria.hooks import _comum as C  # noqa: E402

ROTULO = "contexto"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    C.preparar(ROTULO)
    autoteste = "--autoteste" in argv

    if autoteste:
        alvo = _arg(argv, "--projeto") or os.getcwd()
        evento = {"source": "compact", "cwd": alvo, "hook_event_name": "SessionStart"}
    else:
        evento = C.ler_evento()

    ctx = C.contexto(evento, ROTULO)
    if ctx is None:
        if autoteste:
            print(
                f"[{ROTULO}] projeto sem `.claude/harness.json` — hook inerte por desenho",
                file=sys.stderr,
            )
        return 0
    raiz, cfg = ctx

    contexto_texto = montar(raiz, cfg, str(evento.get("source") or "startup"))
    if not contexto_texto:
        return 0

    C.emitir_contexto("SessionStart", contexto_texto)
    return conferir_fidelidade(raiz, cfg, contexto_texto) if autoteste else 0


def montar(raiz: Path, cfg: Config, origem: str) -> str:
    blocos: list[str] = []

    if cfg.diario.injetar_ultima_entrada:
        ultima = diario.ultima_entrada(cfg.pasta_diario)
        if ultima:
            nome, corpo = ultima
            onde = f"{cfg.diario.pasta}/{nome}"
            corpo = diario.recortar_entrada(corpo, cfg.diario, onde)
            blocos.append(f"## Memória do projeto — última entrada do diário (`{onde}`)\n\n{corpo}")

    becos, total = diario.becos_sem_saida(cfg.pasta_diario, cfg.diario)
    if becos:
        faltam = total - len(becos)
        resto = (
            f"\n\nOs outros {faltam} estão nas seções `### {diario.SECAO_BECOS}` de "
            f"`{cfg.diario.pasta}/` e `{cfg.diario.pasta}/arquivo/` — procure por esse título "
            f"antes de insistir numa abordagem que parece nova."
            if faltam > 0
            else ""
        )
        blocos.append(
            f"## Becos sem saída já explorados ({len(becos)} de {total}, "
            f"do mais recente para o mais antigo)\n\n"
            + "\n".join(f"- {item}" for item in becos)
            + resto
        )

    todos = adr.indice_para_injecao(cfg.pasta_adr)
    injetadas = todos if cfg.adr.limite_indice is None else todos[: cfg.adr.limite_indice]
    if injetadas:
        # O total vai em número de propósito: se esta lista for cortada, a divergência
        # entre o número anunciado e o que está em tela denuncia o corte.
        onde = f"{cfg.adr.pasta}/README.md"
        completo = "índice completo" if len(injetadas) == len(todos) else "índice PARCIAL"
        blocos.append(
            f"## Decisões arquiteturais vigentes ({completo}, {len(todos)} ADRs)\n\n"
            + "\n".join(f"- {linha}" for linha in injetadas)
            + f"\n\nDetalhe em `{cfg.adr.pasta}/`. Um ADR aceito tem precedência sobre o "
            "CLAUDE.md. Se sua tarefa contradiz um deles, PARE e pergunte. "
            "ADR `superseded` **não** se segue — siga o substituto indicado na linha."
            + adr.anunciar_corte(len(todos), len(injetadas), onde)
        )

    if origem == "compact":
        regras = invioaveis(raiz, cfg.reafirmacao)
        if regras:
            blocos.append(
                "## Aviso pós-compactação\n\n"
                "O contexto acabou de ser comprimido. Antes de continuar, reconfirme as "
                "invioláveis do `CLAUDE.md`:\n" + "\n".join(f"- {r}" for r in regras)
            )

    return "\n\n---\n\n".join(blocos)


def conferir_fidelidade(raiz: Path, cfg: Config, contexto_texto: str) -> int:
    """Confere que o que o bloco PROMETE é o que ele ENTREGA. Roda no CI."""
    falhas: list[str] = []
    todos = adr.indice_para_injecao(cfg.pasta_adr)

    # 1. o índice injetado é o índice inteiro — ou se declara PARCIAL e diz onde está o
    #    resto. O que não se admite é o silêncio: era um corte fixo em 20 derrubando 9 ADRs.
    if todos:
        if "índice PARCIAL" not in contexto_texto:
            for linha in todos:
                num = linha.split(maxsplit=1)[0]
                if num not in contexto_texto:
                    falhas.append(f"{num} está no índice de ADR e não chegou ao contexto")
        elif "este índice está cortado" not in contexto_texto:
            falhas.append("índice cortado sem a nota que diz quantos faltam e onde achá-los")
        elif f"{len(todos)} ADRs" not in contexto_texto:
            falhas.append(
                f"índice cortado sem anunciar o TOTAL real ({len(todos)}) — sem o total, "
                f"quem lê não tem como perceber a diferença"
            )

    # 2. ADR morto nunca aparece sem dizer o que seguir no lugar
    dados = adr.dados_dos_adrs(cfg.pasta_adr)
    for num, d in dados.items():
        if d["status"] in adr.STATUS_MORTOS and not d["substituido_por"]:
            falhas.append(
                f"ADR-{num} está {d['status']} e não declara `substituido-por:` — "
                f"o índice injetado não tem como dizer o que seguir no lugar"
            )

    # 3. o recorte da entrada preserva as seções de retomada, que é o que o diário serve
    if cfg.diario.injetar_ultima_entrada:
        ultima = diario.ultima_entrada(cfg.pasta_diario)
        if ultima:
            _, corpo = ultima
            _, secoes = diario.partir_em_secoes(corpo)
            presentes = [t for t, _ in secoes]
            for alvo in cfg.diario.prioridade_secoes[:3]:
                if any(t.startswith(alvo) for t in presentes) and alvo not in contexto_texto:
                    falhas.append(
                        f"a seção '{alvo}' existe na última entrada e o recorte a descartou"
                    )

    # 4. toda inviolável extraída cabe numa linha. Estourar não trunca — reprova, porque
    #    meia proibição lê como permissão.
    for r in invioaveis(raiz, cfg.reafirmacao):
        if len(r) > cfg.reafirmacao.teto_item_chars:
            falhas.append(
                f"inviolável com {len(r)} chars (teto {cfg.reafirmacao.teto_item_chars}): "
                f"{r[:70]}… — encurte a PRIMEIRA FRASE dela no CLAUDE.md; o resto do "
                f"raciocínio continua no item, só não entra na reafirmação"
            )

    for f in falhas:
        print(f"[{ROTULO}] FALHA: {f}", file=sys.stderr)
    if not falhas:
        print(
            f"[{ROTULO}] ok — {len(todos)} ADRs no índice, {len(contexto_texto)} chars "
            f"injetados, seções de retomada preservadas",
            file=sys.stderr,
        )
    return 1 if falhas else 0


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
        print(f"[{ROTULO}] hook falhou: {type(e).__name__}: {e}", file=sys.stderr)
        codigo = 0
    sys.exit(codigo)
