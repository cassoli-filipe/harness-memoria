"""O auditor reprovando o que deve, e não reprovando o que não deve.

Arquivo próprio porque cada caso aqui corresponde a um estado em que o auditor ENSINAVA a
ser ignorado — falha sem correção possível, ou falso positivo em documentação correta —, e
porque `auditar/__main__.py` tinha cobertura ZERO (0 de 18 instruções) até o caso de
`--projeto` no fim deste arquivo.

Os dois estados são simétricos e o projeto já tinha nome para eles: "auditor que produz
falha sem correção é o jeito mais rápido de ensinar a ignorá-lo" e "falso positivo é pior
que cheque ausente". A suíte anterior (126 casos) aprovava os dois.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from conftest import escrever_config

from harness_memoria.auditar import Contexto, rodar
from harness_memoria.auditar.__main__ import main
from harness_memoria.config import carregar

MES = datetime.now().strftime("%Y-%m")


def auditar(raiz: Path) -> Contexto:
    cfg = carregar(raiz)
    assert cfg is not None, "fixture sem harness.json"
    ctx = Contexto(raiz=raiz, cfg=cfg)
    rodar(ctx)
    return ctx


def falhas_com(ctx: Contexto, trecho: str) -> list[str]:
    return [f for f in ctx.falhas if trecho.lower() in f.lower()]


def _adr(projeto: Path, nome: str, frontmatter: str, titulo: str) -> None:
    """ADR novo mais a linha dele no índice, para o cheque de índice não virar ruído."""
    num = nome[:4]
    (projeto / "docs" / "adr" / nome).write_text(
        f"---\n{frontmatter}---\n\n# ADR-{num} — {titulo}\n",
        encoding="utf-8",
    )
    idx = projeto / "docs" / "adr" / "README.md"
    idx.write_text(
        idx.read_text(encoding="utf-8") + f"| [{num}]({nome}) | {titulo} | ? |\n",
        encoding="utf-8",
    )


def _claude_md_com_invioaveis(projeto: Path, itens: list[str]) -> None:
    corpo = "# Projeto\n\n## Regras invioláveis\n\n" + "".join(f"- {i}\n" for i in itens)
    (projeto / "CLAUDE.md").write_text(corpo, encoding="utf-8")


# --------------------------------------------------------------------------- #
# `guardas`: o cheque de chave obrigatória mudou de lugar, não desapareceu
# --------------------------------------------------------------------------- #


def test_regra_de_comandos_sem_exemplo_reprova_na_auditoria(projeto: Path):
    """A seção `guardas` era o ponto cego do auditor: `grep guardas` dava 0 linhas nele.

    Por isso `carregar()` era o único lugar que podia pegar a chave que falta — e lançar lá
    deixava os CINCO hooks inertes no consumidor que só atualizou o plugin. O cheque agora
    vive aqui: reprova o build, que é o sinal proporcional, e o harness continua ligado.

    A mensagem tem de dizer a consequência CONCRETA, não só "chave ausente": sem `exemplo`,
    `guardar.py --autoteste` não gera caso positivo para a regra (`if exemplo:`) e imprime
    aprovação sobre uma regex que pode estar quebrada.
    """
    escrever_config(
        projeto,
        {"guardas": {"comandos": [{"regex": r"\bgit\s+add\b.*\.xlsx", "motivo": "m"}]}},
    )
    achado = falhas_com(auditar(projeto), "não declara `exemplo`")
    assert achado, "auditoria muda sobre guarda que nenhum autoteste exercita"
    assert "guardas.comandos[0]" in achado[0]
    assert "git" in achado[0], "a falha tem de identificar QUAL regra"
    assert "autoteste" in achado[0]


def test_regra_de_caminhos_sem_padrao_reprova_na_auditoria(projeto: Path):
    """Sem `padrao` a regra é descartada num `continue` calado dentro de `guardar.py`.

    Não há nem chave errada para procurar: a guarda está escrita na config, o hook não
    bloqueia nada, e até aqui nada dizia isso em lugar nenhum.
    """
    escrever_config(projeto, {"guardas": {"caminhos": [{"motivo": "sem padrao"}]}})
    achado = falhas_com(auditar(projeto), "não declara `padrao`")
    assert achado
    assert "guardas.caminhos[0]" in achado[0]
    assert "continue" in achado[0]


def test_regra_completa_nao_reprova(projeto: Path):
    """Guarda de conteúdo declarado inteiro passa — o cheque é de ausência, não de forma.

    Medido nas três configs reais desta máquina: 3 de 3 regras de `comandos` declaram
    `exemplo`, então este é o caso comum e ele não pode virar vermelho.
    """
    escrever_config(
        projeto,
        {
            "guardas": {
                "caminhos": [{"padrao": "*.xlsx", "motivo": "planilha não entra"}],
                "comandos": [
                    {
                        "regex": r"\bgit\s+add\b.*\.xlsx",
                        "motivo": "planilha não entra",
                        "exemplo": "git add dados/roster.xlsx",
                    }
                ],
            }
        },
    )
    assert falhas_com(auditar(projeto), "não declara") == []


# --------------------------------------------------------------------------- #
# `deprecated` é o status de quem morreu SEM substituto — e não passava
# --------------------------------------------------------------------------- #


def test_adr_deprecated_sem_substituto_passa(projeto: Path):
    """Nenhum ADR `deprecated` passava na auditoria, e é o status que a doc manda usar.

    Reproduzido nos dois ramos possíveis: sem `substituido-por:` reprovava aqui, com
    `substituido-por:` reprovava no cheque de status. O autor que consertasse o primeiro
    caía no segundo, e a saída racional dele era contornar o cheque. O próprio motor já
    pressupunha morto-sem-substituto nos fallbacks "(sem substituto declarado)".
    """
    _adr(projeto, "0002-morta.md", "status: deprecated\ndata: 2026-02-01\n", "Sem sucessor")
    ctx = auditar(projeto)
    assert falhas_com(ctx, "0002") == [], "deprecated sem substituto é o caso normal dele"


def test_adr_deprecated_com_substituto_pede_superseded(projeto: Path):
    """O outro lado do par continua valendo, e agora tem saída: trocar o status.

    Se algo o substituiu, o status é `superseded` — senão o índice injetado anuncia
    "não vale mais" e esconde para onde ir. A diferença é que esta falha é corrigível.
    """
    _adr(
        projeto,
        "0002-morta.md",
        "status: deprecated\ndata: 2026-02-01\nsubstituido-por: [ADR-0001]\n",
        "Com sucessor",
    )
    assert falhas_com(auditar(projeto), "esperado 'superseded'")


def test_indice_por_dominio_pede_marca_que_existe(projeto: Path):
    """A marca cobrada é derivada do frontmatter, não fixa.

    Mandar escrever `0002 (superada → NNNN)` num `deprecated` — que por definição não tem
    NNNN — era instruir o impossível, e era exatamente o segundo cheque em que caía quem
    consertava o primeiro.
    """
    _adr(projeto, "0002-morta.md", "status: deprecated\ndata: 2026-02-01\n", "Sem sucessor")
    idx = projeto / "docs" / "adr" / "README.md"
    idx.write_text(
        idx.read_text(encoding="utf-8") + "\n## Por domínio\n\n- **dados:** 0002\n",
        encoding="utf-8",
    )
    achado = falhas_com(auditar(projeto), "lista por domínio")
    assert achado
    assert "`0002 (deprecated)`" in achado[0]
    assert "NNNN" not in achado[0]


def test_mapa_por_caminho_com_adr_sem_substituto_oferece_saida(projeto: Path):
    """ "Troque por (sem substituto declarado)" não é instrução; é a falta de uma."""
    (projeto / "docs" / "adr" / "0001-primeira.md").write_text(
        "---\nstatus: deprecated\ndata: 2026-01-15\n---\n\n"
        "# ADR-0001 — Primeira decisão do projeto\n",
        encoding="utf-8",
    )
    achado = falhas_com(auditar(projeto), "mapa de ADR por caminho")
    assert achado
    assert "remova a linha" in achado[0]
    assert "sem substituto declarado" not in achado[0]


# --------------------------------------------------------------------------- #
# Colisão de número de ADR: o arquivo sombreado era invisível para o auditor
# --------------------------------------------------------------------------- #


def test_dois_arquivos_com_o_mesmo_numero_reprovam(projeto: Path):
    """`dados_dos_adrs` indexa por `f.name[:4]` e a segunda leitura sobrescreve a primeira.

    Medido: com dois `0001-*.md`, `arquivos_adr` acha 2, `dados_dos_adrs` devolve 1 chave e
    a auditoria inteira saía com falhas=[] avisos=[] — o arquivo sombreado não é cobrado do
    índice, o status dele não é validado e a supersessão dele não é checada. Duas branches
    criando ADR ao mesmo tempo é o caminho normal para cá.
    """
    _adr(
        projeto,
        "0001-guardar-segredo-no-git.md",
        "status: superseded\ndata: 2026-01-10\n",
        "Decisão sombreada",
    )
    ctx = auditar(projeto)
    assert len(ctx.adrs) == 1, "a premissa do defeito: um dos dois arquivos não é lido"
    achado = falhas_com(ctx, "tem 2 arquivos")
    assert achado
    assert "0001-guardar-segredo-no-git.md" in achado[0]
    assert "0001-primeira.md" in achado[0]


# --------------------------------------------------------------------------- #
# CLAUDE.md: ilustração não é ponteiro, e título de link não é caminho
# --------------------------------------------------------------------------- #


def test_link_com_titulo_nao_reprova(projeto: Path):
    """`[texto](caminho "Título")` é markdown válido e o título não faz parte do caminho."""
    (projeto / "docs" / "guia.md").write_text("# Guia\n", encoding="utf-8")
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8") + '\n- [o guia](docs/guia.md "O guia")\n',
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "aponta para") == []


def test_link_quebrado_dentro_de_cerca_nao_reprova(projeto: Path):
    """Bloco que DOCUMENTA o formato do mapa não é o mapa.

    Reprovar o build por documentação correta é o pior defeito que um auditor pode ter, e o
    gatilho é provável justamente neste harness, cujo CLAUDE.md documenta formatos com
    exemplos. A máscara é a mesma que `invioaveis()` usa — uma implementação só de "isto
    aqui é ilustração".
    """
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8")
        + "\nO formato de uma linha do mapa:\n\n"
        + "```markdown\n- [decisão de schema](docs/adr/0042-schema.md)\n```\n",
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "aponta para") == []


def test_link_quebrado_fora_de_cerca_continua_reprovando(projeto: Path):
    """A máscara não pode virar anistia: fora da cerca o cheque é o de antes."""
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8") + "\n- [decisão](docs/adr/0042-schema.md)\n",
        encoding="utf-8",
    )
    achado = falhas_com(auditar(projeto), "aponta para")
    assert achado
    assert "docs/adr/0042-schema.md" in achado[0]


def test_ponteiro_do_mes_dentro_de_cerca_nao_conta(projeto: Path):
    """Ponteiro que só existe num exemplo não é ponteiro: ninguém o segue.

    Mesma máscara, mesmo motivo, sinal invertido — aqui ela faz o cheque reprovar, e é o
    cheque cuja falha o repositório mais teme (`ponteiro velho é pior que ponteiro nenhum`).
    """
    p = projeto / "CLAUDE.md"
    p.write_text(
        p.read_text(encoding="utf-8").replace(
            f"- [diário](docs/diario/{MES}.md) — mês corrente.",
            f"```markdown\n- [diário](docs/diario/{MES}.md) — mês corrente.\n```",
        ),
        encoding="utf-8",
    )
    ctx = auditar(projeto)
    assert [m for m in ctx.falhas + ctx.avisos if "diário do mês corrente" in m]


# --------------------------------------------------------------------------- #
# Invioláveis: auditar a SEÇÃO, não o recorte que a mensagem leva
# --------------------------------------------------------------------------- #


def test_secao_com_mais_itens_que_a_mensagem_reprova(projeto: Path):
    """O corte em `max_itens` era silencioso, ao contrário do índice de ADR.

    O índice se anuncia PARCIAL quando corta; a seção de invioláveis perdia o 9º item sem
    uma linha. Aviso que não existe equivale a cheque inexistente.
    """
    _claude_md_com_invioaveis(
        projeto, [f"Regra número {i} deste projeto. Detalhe que não entra." for i in range(10)]
    )
    achado = falhas_com(auditar(projeto), "seção de invioláveis tem")
    assert achado
    assert "10 itens" in achado[0]
    assert "leva 8" in achado[0]


def test_inviolavel_longa_na_cauda_reprova(projeto: Path):
    """Item de 218 chars em nono lugar passava sem UMA LINHA de aviso.

    Era perda dupla: o 9º item não é reafirmado E o `teto_item_chars` deixava de existir a
    partir dele, porque a auditoria extraía com o mesmo corte da mensagem. Meia proibição
    lê como permissão, então o teto tem de valer para todos.
    """
    longa = (
        "Rodar migração de schema direto em produção sem backup verificado, "
        + "porque rollback sem backup é dado que ninguém tem mais em lugar nenhum, " * 2
    ).strip()
    assert len(longa) > 150
    itens = [f"Regra número {i} deste projeto." for i in range(8)] + [longa]
    _claude_md_com_invioaveis(projeto, itens)
    achado = falhas_com(auditar(projeto), f"item com {len(longa)} chars")
    assert achado, "o teto por item tem de alcançar o item que a mensagem não leva"


def test_secao_no_teto_nao_reprova(projeto: Path):
    """Exatamente `max_itens` passa: o cheque é do que EXCEDE, não do tamanho da seção."""
    _claude_md_com_invioaveis(projeto, [f"Regra número {i} deste projeto." for i in range(8)])
    assert falhas_com(auditar(projeto), "invioláveis") == []


# --------------------------------------------------------------------------- #
# Diário: a remediação impossível, e o `## ` sem data que ficaria mudo
# --------------------------------------------------------------------------- #


def _arquivo_de_diario_no_teto(projeto: Path, nome: str) -> None:
    corpo = (
        f"# Diário · {MES}\n\n---\n\n## {MES}-01 — Entrada de teste\n\n"
        "**Estado:** concluído\n\n### O que foi feito\n\n"
        + "".join(f"- linha {i}\n" for i in range(410))
    )
    (projeto / "docs" / "diario" / nome).write_text(corpo, encoding="utf-8")


def test_teto_no_ultimo_arquivo_do_mes_manda_arquivar(projeto: Path):
    """ "Feche e abra o próximo sufixo" é impossível no décimo arquivo do mês.

    Com os 10 no teto (`AAAA-MM.md` + os 9 sufixos), `caminho_mes` devolve `AAAA-MMj.md` e
    não existe próximo. A remediação vem de `diario.remediacao_do_teto`, uma frase num
    lugar só, e a mesma que `anexar_entrada` imprime.
    """
    _arquivo_de_diario_no_teto(projeto, f"{MES}b.md")
    _arquivo_de_diario_no_teto(projeto, f"{MES}j.md")
    ctx = auditar(projeto)
    ultimo = falhas_com(ctx, f"{MES}j.md tem")
    assert ultimo
    assert "não há próximo sufixo" in ultimo[0]
    assert "`arquivo/`" in ultimo[0]
    anterior = falhas_com(ctx, f"{MES}b.md tem")
    assert anterior
    assert "a próxima entrada abre um novo arquivo" in anterior[0]


def test_cabecalho_sem_data_no_diario_reprova(projeto: Path):
    """`diario._FRONTEIRA_ENTRADA` passou a exigir `## AAAA-MM-DD`; o resto ficaria mudo.

    Sem este cheque, `## Sessão de terça` deixa de abrir entrada e o texto vai para o
    contexto colado na entrada anterior, em silêncio. Não é convenção nova: o regex de
    `auditar_ordem_do_diario` já exigia a data — só não denunciava quem não a escrevia.
    """
    p = projeto / "docs" / "diario" / f"{MES}.md"
    p.write_text(
        p.read_text(encoding="utf-8") + "\n## Sessão de terça\n\nalgo aconteceu\n",
        encoding="utf-8",
    )
    achado = falhas_com(auditar(projeto), "sem data")
    assert achado
    assert "Sessão de terça" in achado[0]


def test_cabecalho_sem_data_dentro_de_cerca_nao_reprova(projeto: Path):
    """Entrada que documenta o formato do diário não é entrada malformada.

    Dentro da cerca o cabeçalho não é fronteira nem para o mecanismo nem para quem lê, e
    era esse o corpus que motivou a mudança de `_FRONTEIRA_ENTRADA` — reprová-lo aqui
    trocaria uma perda silenciosa por um falso positivo.
    """
    p = projeto / "docs" / "diario" / f"{MES}.md"
    p.write_text(
        p.read_text(encoding="utf-8")
        + "\nO cabeçalho de uma entrada tem esta forma:\n\n"
        + "```markdown\n## Sessão de terça\n```\n",
        encoding="utf-8",
    )
    assert falhas_com(auditar(projeto), "sem data") == []


# --------------------------------------------------------------------------- #
# CLI: `--projeto` é escolha explícita e ganha da variável de ambiente
# --------------------------------------------------------------------------- #


def test_projeto_explicito_ganha_da_variavel_de_ambiente(
    projeto: Path, tmp_path: Path, monkeypatch, capsys
):
    """Medido: `--projeto <outro>` auditava o projeto corrente, e aprovava.

    `raiz_projeto` põe `CLAUDE_PROJECT_DIR` na frente dos candidatos — dentro de uma sessão
    do Claude Code ela está SEMPRE setada —, então com o projeto corrente verde a saída era
    "Auditoria aprovada" sobre o alvo errado: o resultado que o comentário do próprio
    `__main__.py` chama de "o pior resultado possível para um cheque".

    No caminho de hook a precedência continua env-primeiro, porque lá o candidato é o cwd
    do evento e não uma escolha de quem chamou.
    """
    quebrado = tmp_path / "quebrado"
    (quebrado / ".claude").mkdir(parents=True)
    (quebrado / "CLAUDE.md").write_text("# Quebrado\n", encoding="utf-8")
    escrever_config(quebrado, {})

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(projeto))
    codigo = main(["--projeto", str(quebrado)])
    saida = capsys.readouterr().out

    assert codigo == 1, "auditou o projeto da variável de ambiente, não o do argumento"
    assert str(quebrado) in saida
    assert "docs/adr/ não existe" in saida


def test_sem_projeto_a_descoberta_continua_env_primeiro(
    projeto: Path, tmp_path: Path, monkeypatch, capsys
):
    """Sem argumento, nada muda: quem manda é `CLAUDE_PROJECT_DIR`, depois o cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(projeto))
    codigo = main([])
    saida = capsys.readouterr().out
    assert codigo == 0, saida
    assert str(projeto) in saida


def test_permitido_em_apontando_para_arquivo_reprova(projeto: Path):
    """`permitido_em` é prefixo de DIRETÓRIO, e apontá-lo a um arquivo bloqueia aquele arquivo.

    A troca de substring por fronteira de caminho em `guardar._sob_prefixo` corrigiu um furo
    real e, no mesmo commit, mudou de liberado para BLOQUEADO quem aponta `permitido_em` a um
    arquivo específico — em silêncio. Config que afirma uma exceção que o hook nega é a mesma
    classe de `_CHAVES_DE_REGRA`; o lugar de acusar é o auditor.
    """
    escrever_config(
        projeto,
        {
            "guardas": {
                "caminhos": [
                    {
                        "padrao": "*.xlsx",
                        "permitido_em": ["tests/fixtures/exemplo.xlsx"],
                        "motivo": "planilha",
                    }
                ]
            }
        },
    )
    falhas = falhas_com(auditar(projeto), "parece um ARQUIVO")
    assert falhas


def test_permitido_em_com_diretorio_passa(projeto: Path):
    """Diretório, com ou sem barra final, e nome com ponto que não é extensão."""
    for alvo in ("tests/fixtures/", "tests/fixtures", "dados.brutos/"):
        escrever_config(
            projeto,
            {
                "guardas": {
                    "caminhos": [{"padrao": "*.xlsx", "permitido_em": [alvo], "motivo": "planilha"}]
                }
            },
        )
        falhas = falhas_com(auditar(projeto), "parece um ARQUIVO")
        assert not falhas, (alvo, falhas)


def test_os_dois_templates_de_adr_nao_podem_divergir():
    """`docs/adr/template.md` é cópia de `template/docs/adr/template.md` — e já divergiu.

    O ADR-0001 afirma que os dois são o mesmo arquivo. Uma onda copiou antes de outra editar
    o distribuído, e a divergência passou por aprovada: nada a compara. Sem este caso, a
    afirmação do ADR volta a poder ficar falsa em silêncio — o princípio 6 no próprio repo.
    """
    raiz = Path(__file__).resolve().parents[1]
    distribuido = (raiz / "template" / "docs" / "adr" / "template.md").read_bytes()
    proprio = (raiz / "docs" / "adr" / "template.md").read_bytes()
    assert proprio == distribuido, (
        "docs/adr/template.md divergiu de template/docs/adr/template.md — "
        "rode `cp template/docs/adr/template.md docs/adr/template.md`"
    )
