"""Testes do caminho de ESCRITA do diário e das três perdas silenciosas do digest.

Este arquivo existe por uma medição, não por gosto: um tracer de stdlib (`sys.settrace`
escopado a `src/harness_memoria`) rodando a suíte inteira em processo deu 41,2% do `src/`
e `diario.py` em 76/213 instruções — com o caminho de escrita INTEIRO em zero
(`anexar_entrada` 0/7, `_lock.__enter__/__exit__` 0/9+0/2, `caminho_mes` 0/9,
`fatos_do_transcript` 0/47, `entrada_deterministica` 0/19, `_cabecalho_mes` 0/1). Onde a
cobertura era zero é exatamente onde os achados de corretude acharam bug real, então "os
89 testes passam" não era prova de nada aqui.

Cinco dos casos abaixo FALHAVAM antes das correções deste commit (dedup por prefixo de 60,
split de entrada por `^## ` sem data, mensagem de rotação impossível, `__exit__` do lock
apagando o lock alheio, recorte que come a própria nota de omissão). Os outros são rede:
prendem o contrato do piso determinístico, que o hook `SessionEnd` passa a exercitar.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from harness_memoria import diario
from harness_memoria.config import ConfigDiario

MES = datetime.now().strftime("%Y-%m")


def _diario_com(pasta: Path, entradas: list[str], mes: str = MES) -> Path:
    """Arquivo de mês no formato que `anexar_entrada` produz: cabeçalho e entradas no fim."""
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / f"{mes}.md"
    alvo.write_text(f"# Diário · {mes}\n\n---\n" + "".join(entradas), encoding="utf-8")
    return alvo


# --------------------------------------------------------------------------- #
# Dedup do digest de becos
# --------------------------------------------------------------------------- #


def test_becos_que_divergem_depois_dos_60_chars_sobrevivem(tmp_path: Path):
    """A chave era `item.lower()[:60]`, e o formato canônico põe a ABORDAGEM primeiro.

    `template/docs/diario/README.md:58` prescreve
    `- {abordagem} → falhou porque {razão}. **Não repetir.**`: quem escreve repete a frase
    de abertura e diverge no fim. Medido no corpus sintético do diagnóstico: 100 becos
    distintos sobre 7 subsistemas colapsavam em 7 (93% de perda) e 2.160 becos todos
    distintos sobreviviam 175 (91,9%) — sem truncamento nenhum envolvido, os itens medem
    207 ch contra o teto de 240. Pior que perder: `total` é contado PÓS-dedup, então o
    bloco anunciava "7 de 7" e o rodapé "os outros 0" — o aviso de corte mentia na mesma
    taxa do corte.
    """
    abertura = "reprocessar o lote inteiro a cada chamada do worker de importação"
    assert len(abertura) > 60, "a fixture só reproduz o defeito se o prefixo comum passa de 60"
    subsistemas = ("cobrança", "matrícula", "boletim", "frequência", "turma", "aluno", "sala")
    itens_crus = [
        f"{abertura} de {s} → falhou porque o job estoura o timeout de 30 s. "
        f"**Não repetir:** processe {s} em janelas de 500 registros."
        for s in subsistemas
    ]
    assert len({i.lower()[:60] for i in itens_crus}) == 1, "os 60 primeiros chars são iguais"

    pasta = tmp_path / "diario"
    corpo = "".join(f"- {i}\n" for i in itens_crus)
    _diario_com(
        pasta, [f"\n## {MES}-20 — Sete becos distintos\n\n### {diario.SECAO_BECOS}\n\n{corpo}"]
    )

    itens, total = diario.becos_sem_saida(pasta, ConfigDiario())
    assert total == len(subsistemas), f"7 becos distintos, {total} contados"
    assert len(itens) == len(subsistemas)
    for s in subsistemas:
        assert any("janelas de 500" in i and s in i for i in itens), f"{s} desapareceu"


def test_dois_becos_com_a_mesma_abertura_e_licoes_diferentes_nao_colapsam(tmp_path: Path):
    """O caso mínimo: divergir só na lição, que é a única parte acionável do item."""
    pasta = tmp_path / "diario"
    abertura = "invalidar o cache do relatório de frequência na mão a cada gravação"
    _diario_com(
        pasta,
        [
            f"\n## {MES}-01 — A\n\n### {diario.SECAO_BECOS}\n\n"
            f"- {abertura} → falhou. **Não repetir:** use TTL de 60 s.\n",
            f"\n## {MES}-20 — B\n\n### {diario.SECAO_BECOS}\n\n"
            f"- {abertura} → falhou. **Não repetir:** invalide por evento de gravação.\n",
        ],
    )
    itens, total = diario.becos_sem_saida(pasta, ConfigDiario())
    assert total == 2, f"as duas lições são distintas: {itens}"
    assert any("TTL de 60 s" in i for i in itens)
    assert any("evento de gravação" in i for i in itens)


def test_becos_identicos_continuam_deduplicando(tmp_path: Path):
    """A rede do lado oposto: `test_becos_deduplicam` continua valendo com a chave inteira."""
    pasta = tmp_path / "diario"
    igual = "mesmíssima abordagem repetida em duas sessões → falhou. **Não repetir.**"
    _diario_com(
        pasta,
        [
            f"\n## {MES}-01 — A\n\n### {diario.SECAO_BECOS}\n\n- {igual}\n",
            f"\n## {MES}-20 — B\n\n### {diario.SECAO_BECOS}\n\n- {igual}\n",
        ],
    )
    _, total = diario.becos_sem_saida(pasta, ConfigDiario())
    assert total == 1


# --------------------------------------------------------------------------- #
# `**Não repetir.**` — o ponto dentro do negrito
# --------------------------------------------------------------------------- #


def test_beco_longo_com_ponto_dentro_do_negrito_preserva_a_licao(tmp_path: Path):
    """`\\*\\*Não repetir:?\\*\\*` não casava `**Não repetir.**`, a grafia que o repo ensina.

    A skill `/encerrar-sessao`, o bloco canônico do template e o fixture do CI escrevem o
    ponto DENTRO do negrito. Medido com teto 240: item de 314 ch terminando em
    `**Não repetir.** …` saía com 241 ch cortados no meio da palavra e a lição AUSENTE,
    enquanto o mesmo item com dois-pontos saía com a lição intacta. A instrução de autoria
    prometia o oposto do que o mecanismo fazia.
    """
    pasta = tmp_path / "diario"
    longo = "contexto que não cabe " * 20 + "→ falhou porque Z. **Não repetir.** faça W."
    _diario_com(pasta, [f"\n## {MES}-01 — A\n\n### {diario.SECAO_BECOS}\n\n- {longo}\n"])
    itens, _ = diario.becos_sem_saida(pasta, ConfigDiario(teto_item_beco_chars=120))
    assert itens[0].endswith("faça W."), itens[0]
    assert len(itens[0]) <= 120 + len(f"{MES}-01 · ")


def test_nao_repetir_sem_licao_depois_cai_no_truncamento_em_vez_de_clausula_vazia(tmp_path: Path):
    """Tolerar `[.:]?` alarga o casamento; com grupo VAZIO o certo é truncar.

    Emitir `… **Não repetir:** ` sem nada depois seria um beco em branco no contexto —
    pior que truncar avisando (princípio 8).
    """
    pasta = tmp_path / "diario"
    longo = "contexto que não cabe " * 20 + "→ falhou porque Z. **Não repetir.**"
    _diario_com(pasta, [f"\n## {MES}-01 — A\n\n### {diario.SECAO_BECOS}\n\n- {longo}\n"])
    itens, _ = diario.becos_sem_saida(pasta, ConfigDiario(teto_item_beco_chars=120))
    assert itens[0].endswith("…"), itens[0]
    assert not itens[0].rstrip().endswith("**Não repetir:**")


# --------------------------------------------------------------------------- #
# Partição da entrada: `## ` exige data
# --------------------------------------------------------------------------- #


ENTRADA_QUE_DOCUMENTA_O_FORMATO = """
## 2026-09-20 — Documentar o formato da entrada no próprio diário

**Estado:** concluído

### Como (o não-óbvio)

O formato canônico, para quem escrever à mão:

````markdown
## AAAA-MM-DD — {título imperativo do que mudou}

**Estado:** concluído | parcial | bloqueado
````

### Tentativas descartadas

- copiar o formato do outro projeto → falhou porque as seções divergiam. \
**Não repetir:** derive do template.
"""


def test_ultima_entrada_ignora_cabecalho_de_exemplo_dentro_de_cerca(tmp_path: Path):
    """`re.split(r"^## ")` partia a entrada no exemplo de formato que ela mesma documenta.

    Reproduzido: entrada de 440 ch com um bloco ```markdown devolvia 210 ch começando no
    MEIO da cerca, com a data PLACEHOLDER (`AAAA-MM-DD`), sem `**Estado:**` e sem
    `### O que foi feito`. O bloco injetado se anuncia "última entrada do diário" e
    entregava fragmento com data falsa — a forma exata do dano de arXiv:2404.03114 que o
    repositório cita como razão de existir, e o cheque 3 de `conferir_fidelidade` é cego a
    isso porque só procura o TÍTULO das seções.
    """
    pasta = tmp_path / "diario"
    _diario_com(pasta, [ENTRADA_QUE_DOCUMENTA_O_FORMATO], mes="2026-09")

    nome, corpo = diario.ultima_entrada(pasta)
    assert nome == "2026-09.md"
    assert corpo.startswith("## 2026-09-20 —"), corpo[:80]
    assert "**Estado:** concluído" in corpo
    assert "### Tentativas descartadas" in corpo


def test_becos_mantem_a_data_real_quando_a_entrada_tem_cerca_de_exemplo(tmp_path: Path):
    """O outro lado do mesmo split: o beco perdia o prefixo de data (`2026-09-20 · `)."""
    pasta = tmp_path / "diario"
    _diario_com(pasta, [ENTRADA_QUE_DOCUMENTA_O_FORMATO], mes="2026-09")

    itens, total = diario.becos_sem_saida(pasta, ConfigDiario())
    assert total == 1
    assert itens[0].startswith("2026-09-20 · "), itens[0]


def test_entrada_sem_data_no_cabecalho_nao_e_lida_como_entrada(tmp_path: Path):
    """Consequência declarada da mudança: `## ` sem data deixa de ser fronteira de entrada.

    Quem escreve `## Sessão de terça` perde a entrada na injeção — por isso a mesma
    convenção é auditada (`auditar_diario` reprova `^## ` sem data), e não fica muda.
    """
    pasta = tmp_path / "diario"
    _diario_com(
        pasta,
        [
            f"\n## {MES}-01 — Com data\n\n- a\n",
            "\n## Sessão sem data\n\n- b\n",
        ],
    )
    _, corpo = diario.ultima_entrada(pasta)
    assert "Com data" in corpo
    assert "Sessão sem data" in corpo, "o texto órfão fica colado na última entrada com data"


# --------------------------------------------------------------------------- #
# Escrita: `anexar_entrada`, `caminho_mes`, desdobramento
# --------------------------------------------------------------------------- #


def test_anexar_entrada_grava_duas_em_ordem_com_cabecalho_e_sem_deixar_lock(tmp_path: Path):
    """Cobertura do caminho que estava em 0/7 e que o `SessionEnd` volta a exercitar.

    A ordem CRONOLÓGICA não é estilo: `ultima_entrada` pega o último bloco do arquivo.
    """
    cfg = ConfigDiario()
    pasta = tmp_path / "docs" / "diario"  # não existe ainda: tem de ser criada
    quando = datetime(2026, 9, 8, 10, 30)

    p1 = diario.anexar_entrada(pasta, cfg, "## 2026-09-08 — Primeira\n\n- a\n\n", quando)
    p2 = diario.anexar_entrada(pasta, cfg, "## 2026-09-08 — Segunda\n\n- b", quando)

    assert p1 == p2 == pasta / "2026-09.md"
    texto = p1.read_text(encoding="utf-8")
    assert texto.startswith("# Diário · 2026-09\n")
    assert "[`README.md`](README.md)" in texto, "o cabeçalho aponta as regras do formato"
    assert texto.index("Primeira") < texto.index("Segunda"), "append-only: a nova no FIM"
    assert not list(pasta.glob("*.lock")), "o lock tem de ser liberado por quem o detém"
    _, corpo = diario.ultima_entrada(pasta)
    assert "Segunda" in corpo


def test_desdobramento_abre_o_sufixo_seguinte_e_avisa(tmp_path: Path, capsys):
    """O outro ramo da mesma frase: até o penúltimo sufixo a promessa é verdadeira."""
    cfg = ConfigDiario(teto_linhas=10)
    pasta = tmp_path / "diario"
    pasta.mkdir()
    (pasta / f"{MES}.md").write_text("x\n" * 40, encoding="utf-8")
    destino = diario.anexar_entrada(pasta, cfg, "## 2026-09-08 — Nova\n\n- a")
    assert destino.name == f"{MES}b.md"

    # com o arquivo do mês (sem sufixo) estourando o teto DEPOIS da escrita, o aviso é o
    # antigo — a próxima entrada de fato abre `AAAA-MMb.md`
    outra = tmp_path / "outro"
    outra.mkdir()
    (outra / f"{MES}.md").write_text("x\n" * 4, encoding="utf-8")
    diario.anexar_entrada(outra, ConfigDiario(teto_linhas=5), "## 2026-09-08 — Nova\n\n- a")
    err = capsys.readouterr().err
    assert "a próxima entrada abre um novo arquivo." in err


def test_ultimo_sufixo_esgotado_manda_arquivar_em_vez_de_prometer_arquivo_novo(
    tmp_path: Path, capsys
):
    """Auditor/aviso que produz falha sem correção é o jeito mais rápido de ser ignorado.

    Reproduzido: com os 10 arquivos do mês no teto, `caminho_mes` devolve `AAAA-MMj.md`,
    `anexar_entrada` o leva a 404 e 408 linhas e imprimia DUAS VEZES "a próxima entrada
    abre um novo arquivo" — não abre, não há próximo sufixo (princípio 9).
    """
    cfg = ConfigDiario(teto_linhas=10)
    pasta = tmp_path / "diario"
    pasta.mkdir()
    for sufixo in ("", *diario.SUFIXOS_DESDOBRAMENTO):
        (pasta / f"{MES}{sufixo}.md").write_text("x\n" * 40, encoding="utf-8")

    destino = diario.anexar_entrada(pasta, cfg, "## 2026-09-08 — Nova\n\n- a")

    assert destino.name == f"{MES}{diario.SUFIXOS_DESDOBRAMENTO[-1]}.md"
    err = capsys.readouterr().err
    assert "abre um novo arquivo" not in err, "a promessa falsa"
    assert "arquivo/" in err, "a instrução verdadeira: mover os mais ANTIGOS do mês"
    assert "teto_linhas" in err, "a outra saída: aumentar o teto no harness.json"
    assert str(len(diario.SUFIXOS_DESDOBRAMENTO) + 1) in err


# --------------------------------------------------------------------------- #
# Lock
# --------------------------------------------------------------------------- #


def test_quem_desiste_do_lock_nao_apaga_o_lock_de_quem_o_detem(tmp_path: Path):
    """O `__exit__` estava em 0/2 de cobertura e apagava lock alheio.

    Medido no Windows: `PermissionError [WinError 32]` depois de 10,0 s (40 × 0,25 s), com
    o corpo JÁ gravado — e o `session_end` imprimindo a mensagem falsa "hook falhou sem
    gravar". No Linux (metade da matriz do CI) o unlink de arquivo aberto SUCEDE, e a
    exclusão mútua entre duas sessões terminando junto simplesmente deixava de existir.

    Ancorado no arquivo de lock, não em tempo: duas instâncias no mesmo processo são, para
    o `O_EXCL`, dois processos — e o teste não fica instável em runner lento.
    """
    destino = tmp_path / f"{MES}.md"
    detentor = diario._lock(destino)
    detentor.__enter__()
    try:
        assert detentor.fd is not None, "A tem de adquirir"
        assert detentor.caminho.exists()

        desistente = diario._lock(destino, tentativas=2, espera=0.01)
        desistente.__enter__()
        assert desistente.fd is None, "B tem de desistir e seguir sem lock"
        assert desistente.__exit__() is False, "sair sem lock não pode levantar"

        assert detentor.caminho.exists(), "B apagou o lock de A"
    finally:
        detentor.__exit__()
    assert not detentor.caminho.exists(), "quem detém libera"


def test_lock_orfao_de_processo_morto_continua_expirando_em_60_s(tmp_path: Path):
    """Rede em volta da mudança: restringir o unlink a quem detém não pode matar o reaper.

    Sem o reaper, um processo morto no meio da gravação deixaria toda sessão seguinte
    esperando 10,0 s (40 × 0,25 s) e escrevendo sem lock, para sempre.
    """
    destino = tmp_path / f"{MES}.md"
    orfao = destino.with_suffix(destino.suffix + ".lock")
    orfao.write_text("", encoding="utf-8")
    velho = time.time() - 120
    os.utime(orfao, (velho, velho))

    lock = diario._lock(destino, tentativas=2, espera=0.01)
    lock.__enter__()
    try:
        assert lock.fd is not None, "lock órfão de mais de 60 s tem de ser recolhido"
    finally:
        lock.__exit__()


# --------------------------------------------------------------------------- #
# Recorte: a nota de omissão sobrevive ao truncamento
# --------------------------------------------------------------------------- #


def _entrada_com_secao_gigante(chars_beco: int) -> str:
    return (
        "## 2026-09-08 — Entrada com uma seção que não cabe sozinha\n\n"
        "**Estado:** concluído\n\n"
        "### O que foi feito\n\n" + "- item reconstruível do git log\n" * 12 + "\n"
        "### Verificação\n\n- 89 testes\n\n"
        "### Retomar com\n\n```bash\npytest -q\n```\n\n"
        f"### {diario.SECAO_BECOS}\n\n" + "- beco com bastante texto\n" * (chars_beco // 25)
    )


def test_recorte_preserva_a_nota_e_o_caminho_mesmo_quando_trunca():
    """O docstring prometia "o que sai é sempre nomeado na nota final" e a nota era comida.

    Reproduzido com `ConfigDiario()` de fábrica: entrada de 7.655 ch produzia saída de
    5.045 ch — 45 ACIMA do limite declarado — sem `Aberto / Próximo passo`, sem
    `Retomar com`, sem a nota de omissão e sem o caminho do arquivo. Truncar calado remove
    o único sinal de que existe mais (princípio 8), e o excesso sobre o limite ainda torna
    inútil qualquer orçamento montado sobre `limite_injecao_chars`.
    """
    cfg = ConfigDiario(limite_injecao_chars=2_000)
    corpo = _entrada_com_secao_gigante(4_000)
    assert len(corpo) > cfg.limite_injecao_chars * 2

    saida = diario.recortar_entrada(corpo, cfg, "docs/diario/2026-09.md")

    assert len(saida) <= cfg.limite_injecao_chars, f"{len(saida)} > {cfg.limite_injecao_chars}"
    assert "Seções omitidas por espaço" in saida, "recorte silencioso vira falso completo"
    assert "O que foi feito" in saida, "o que saiu tem de ser NOMEADO"
    assert "docs/diario/2026-09.md" in saida, "e o caminho da entrada inteira tem de sobrar"
    assert "truncada" in saida


def test_recorte_respeita_o_limite_em_tres_tamanhos():
    """Abaixo, no limite e muito acima — o contrato é `len(saida) <= limite` nos três."""
    cfg = ConfigDiario(limite_injecao_chars=1_500)
    pequena = "## 2026-09-08 — Curta\n\n### Verificação\n\n- ok\n"
    assert diario.recortar_entrada(pequena, cfg) == pequena

    cabeca = pequena + "\n### Por quê\n\n"
    no_limite = cabeca + "x" * (cfg.limite_injecao_chars - len(cabeca))
    assert len(no_limite) == cfg.limite_injecao_chars
    assert diario.recortar_entrada(no_limite, cfg) == no_limite

    for tamanho in (3_000, 20_000):
        saida = diario.recortar_entrada(
            _entrada_com_secao_gigante(tamanho), cfg, "docs/diario/2026-09.md"
        )
        assert len(saida) <= cfg.limite_injecao_chars, (tamanho, len(saida))
        assert "docs/diario/2026-09.md" in saida


def test_nota_de_omissao_encurta_a_lista_em_vez_de_comer_o_corpo():
    """Piso da nota: com limite pequeno, a lista vira "as N primeiras e mais K"."""
    cfg = ConfigDiario(limite_injecao_chars=500)
    corpo = "## 2026-09-08 — Sete seções\n\n" + "".join(
        f"### {titulo}\n\n" + f"- conteúdo de {titulo} com texto suficiente\n" * 4 + "\n"
        for titulo in reversed(cfg.prioridade_secoes)
    )
    saida = diario.recortar_entrada(corpo, cfg, "docs/diario/2026-09.md")
    assert len(saida) <= cfg.limite_injecao_chars
    assert "e mais " in saida, saida
    assert "docs/diario/2026-09.md" in saida


def test_com_limite_absurdo_a_marca_vence_a_nota():
    """Ordem de precedência quando nem a moldura cabe: marca > nota > corpo.

    Configuração que ninguém deveria escrever (o default é 5.000 e o menor exercitado no
    projeto é 1.200), mas o contrato `len(saida) <= limite` vale nela também, senão o
    orçamento do bloco injetado tem uma exceção não declarada.
    """
    cfg = ConfigDiario(limite_injecao_chars=120)
    saida = diario.recortar_entrada(
        _entrada_com_secao_gigante(2_000), cfg, "docs/diario/2026-09.md"
    )
    assert len(saida) <= cfg.limite_injecao_chars, saida
    assert "truncada" in saida, "o sinal é o último a cair"


def test_recorte_de_entrada_sem_secao_avisa_e_cabe():
    """Entrada fora do formato (sem `###`): o corte cego também precisa caber e avisar."""
    cfg = ConfigDiario(limite_injecao_chars=800)
    corpo = "## 2026-09-08 — Sem seções\n\n" + "prosa corrida " * 200
    saida = diario.recortar_entrada(corpo, cfg, "docs/diario/2026-09.md")
    assert len(saida) <= cfg.limite_injecao_chars
    assert "truncada" in saida
    assert "docs/diario/2026-09.md" in saida


# --------------------------------------------------------------------------- #
# Fatos determinísticos: transcript e piso
# --------------------------------------------------------------------------- #


def test_fatos_do_transcript_le_escritas_comandos_e_reporta_ausencia(tmp_path: Path):
    """0/47 instruções de cobertura, e é o insumo de toda entrada automática do diário."""
    p = tmp_path / "sessao.jsonl"
    linhas = [
        json.dumps({"type": "user", "message": {"role": "user", "content": "conserte o lock"}}),
        "isto não é json e tem de ser ignorado em silêncio",
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/x.py"}},
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/x.py"}},
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "pytest -q\nsegunda linha ignorada"},
                        },
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "pronto"}]},
            }
        ),
    ]
    p.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    fatos = diario.fatos_do_transcript(str(p))
    assert fatos["arquivos_escritos"] == ["src/x.py"], "o mesmo arquivo duas vezes conta uma"
    assert fatos["ferramentas"] == {"Edit": 2, "Bash": 1}
    assert fatos["comandos"] == ["pytest -q"], "só a primeira linha do comando"
    assert fatos["turnos_usuario"] == 1
    assert fatos["primeiro_pedido"] == "conserte o lock"
    assert fatos["erro_parse"] is None

    assert diario.fatos_do_transcript(None)["erro_parse"] == "transcript_path ausente"
    ausente = diario.fatos_do_transcript(str(tmp_path / "nao-existe.jsonl"))
    assert "não encontrado" in ausente["erro_parse"]
    assert ausente["arquivos_escritos"] == [], "nunca lança: devolve fatos vazios"


def test_entrada_deterministica_e_o_piso_e_nomeia_o_que_faltou(tmp_path: Path):
    """O piso existe para que "o LLM falhou" nunca signifique "a sessão não deixou rastro".

    Estava em 0/19 e é o que o `SessionEnd` passa a gravar ANTES de qualquer tentativa de
    narração — este teste prende o contrato que o lote 1 depende.
    """
    escrito = str(tmp_path / "docs" / "adr" / "0007-decisao.md")
    fatos = {
        "ferramentas": {"Edit": 3, "Bash": 1},
        "arquivos_escritos": [escrito],
        "comandos": ["pytest -q"],
        "turnos_usuario": 4,
        "primeiro_pedido": "conserte o lock",
        "excerto": "",
        "erro_parse": "transcript não encontrado: x.jsonl",
    }
    git = {
        "branch": "main",
        "status": " M src/x.py",
        "diffstat": " src/x.py | 2 +-",
        "ultimo_commit": "abc1234 algo",
    }
    corpo = diario.entrada_deterministica(
        tmp_path,
        tmp_path / "docs" / "adr",
        fatos,
        git,
        datetime(2026, 9, 8, 10, 30),
        "orçamento de 1.500 ms do hook",
    )
    assert corpo.startswith("## 2026-09-08 — Sessão registrada automaticamente (10:30)")
    assert "**Estado:** registro automático" in corpo
    assert "1 arquivo(s) escrito(s) · branch `main`" in corpo
    assert "ADR-0007" in corpo, "o ADR tocado é o gancho entre diário e decisão"
    assert "`docs/adr/0007-decisao.md`" in corpo
    assert "- `pytest -q`" in corpo
    assert "Ferramentas usadas: Edit×3, Bash×1" in corpo
    assert "resumo-narrativo: indisponível" in corpo
    assert "orçamento de 1.500 ms do hook" in corpo
    assert "Aviso do parser de transcript" in corpo, "o diagnóstico não pode ser jogado fora"
