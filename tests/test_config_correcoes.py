"""Leitura da política: o que a extração de invioláveis perdia em silêncio, e a regra de
guarda que a config aceitava sem ninguém nunca exercitar.

Arquivo próprio porque cada caso abaixo FALHAVA antes da correção de mesmo nome em
`config.py`, e a suíte anterior (89 casos, 41,2% das instruções do `src/`) aprovava os
três CLAUDE.md daqui perdendo regra sem uma linha de aviso — a única classe de defeito que
este repositório chama de pior que não ter harness, porque quem instalou acha que está
protegido.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from conftest import escrever_config

from harness_memoria.config import (
    ConfigAuditoria,
    ConfigReafirmacao,
    carregar,
    invioaveis,
    raiz_projeto,
)

#: O `sub_bloco` que o `template/harness.json` distribui — logo, o caminho que a maioria
#: dos consumidores exercita.
NUNCA = ConfigReafirmacao(sub_bloco="**NUNCA**")


def _projeto_com(raiz: Path, corpo: str) -> Path:
    raiz.mkdir(parents=True, exist_ok=True)
    (raiz / "CLAUDE.md").write_text(corpo, encoding="utf-8")
    return raiz


# --------------------------------------------------------------------------- #
# Cerca de código: ilustração não é política, e `#` dentro dela não é título
# --------------------------------------------------------------------------- #

COM_CERCA_NO_MEIO = """\
# Projeto

## Regras invioláveis

**NUNCA**

- Escrever segredo no repositório. O `.env` está no .gitignore.
- Tratar identificador como número. Zero à esquerda é significativo.

Antes de commitar:

```bash
# checa antes
python scripts/checar.py
```

- Usar `service_role` no browser. A chave vaza no bundle.

## Outra coisa
"""


def test_cerca_de_codigo_nao_encerra_a_secao(tmp_path: Path):
    """`# checa antes` dentro de ```bash não é um `#` de título.

    Medido: a terceira inviolável ("Usar `service_role` no browser") desaparecia, e a
    auditoria aprovava — o corte não tem sinal nenhum. CLAUDE.md com bloco de comandos no
    meio da seção é a forma normal de escrever, não um caso de borda.
    """
    raiz = _projeto_com(tmp_path / "p", COM_CERCA_NO_MEIO)
    regras = invioaveis(raiz, NUNCA)
    assert len(regras) == 3
    assert any("service_role" in r for r in regras)


SECAO_ILUSTRADA = """\
# Projeto

## Como escrever a seção

Exemplo do formato esperado:

```markdown
## Regras invioláveis

**NUNCA**

- Isto é só ilustração do formato. Não é regra deste projeto.
```

## Regras invioláveis

**NUNCA**

- Escrever segredo no repositório. O `.env` está no .gitignore.
"""


def test_secao_dentro_de_cerca_nao_e_a_secao(tmp_path: Path):
    """A primeira ocorrência do título ganhava, mesmo dentro de bloco de código.

    O gatilho é provável justamente num CLAUDE.md que documenta o próprio formato — como
    o deste repositório. O resultado é o pior possível: a reafirmação sai com a frase de
    exemplo e a regra real do projeto nunca é reafirmada.
    """
    raiz = _projeto_com(tmp_path / "p", SECAO_ILUSTRADA)
    assert invioaveis(raiz, NUNCA) == ["Escrever segredo no repositório."]


CERCA_ABERTA = """\
## Regras invioláveis

**NUNCA**

```bash
# a cerca nunca fecha
- Escrever segredo no repositório. Detalhe.
"""


def test_cerca_nao_fechada_degrada_para_o_comportamento_antigo(tmp_path: Path):
    """Cerca sem fim faria a máscara esconder o resto do arquivo — e sumir com TUDO.

    Perder a seção inteira é pior que o defeito que a máscara corrige, então cerca
    desbalanceada é tratada como se não houvesse cerca. Aqui isso significa que o `#` do
    comentário volta a encerrar a seção: sobra o `**NUNCA**` sem itens, e não uma lista
    vazia por causa de um acento de digitação três blocos acima.
    """
    raiz = _projeto_com(tmp_path / "p", CERCA_ABERTA)
    assert invioaveis(raiz, NUNCA) == []


# --------------------------------------------------------------------------- #
# Sub-bloco: marcador abre bloco, prosa em negrito não
# --------------------------------------------------------------------------- #

PROSA_EM_NEGRITO = """\
## Regras invioláveis

**NUNCA**

- Escrever segredo no repositório. Detalhe.
- Tratar identificador como número. Detalhe.

**Isto vale para agentes e humanos.**

- Usar `service_role` no browser. Detalhe.
- Apagar migração já aplicada. Detalhe.

**SEMPRE**

- Rodar os testes antes de declarar trabalho concluído.
"""


def test_prosa_em_negrito_nao_encerra_o_sub_bloco(tmp_path: Path):
    """Medido: a frase de reforço no meio do bloco cortava 2 das 4 proibições.

    `**NUNCA**` é o `sub_bloco` que o `template/harness.json` distribui, e uma frase
    inteira em negrito dentro dele é redação comum — ela reforça a regra, não abre bloco
    novo. O critério é o ponto final: marcador é rótulo, prosa é frase.
    """
    raiz = _projeto_com(tmp_path / "p", PROSA_EM_NEGRITO)
    regras = invioaveis(raiz, NUNCA)
    assert len(regras) == 4
    assert any("service_role" in r for r in regras)


def test_marcador_sem_ponto_continua_encerrando_o_sub_bloco(tmp_path: Path):
    """A outra metade do contrato: `**SEMPRE**` tem de continuar cortando.

    Sem isto a correção acima levaria as regras de `**SEMPRE**` para dentro da
    reafirmação — e só proibição absoluta merece reafirmação.
    """
    raiz = _projeto_com(tmp_path / "p", PROSA_EM_NEGRITO)
    assert not any("testes" in r for r in invioaveis(raiz, NUNCA))


# --------------------------------------------------------------------------- #
# Sub-item é detalhe do item, não inviolável de primeira classe
# --------------------------------------------------------------------------- #

COM_SUB_ITEM = """\
## Regras invioláveis

**NUNCA**

- Escrever segredo no repositório. O `.env` está no .gitignore.
  - inclui `.env.local` e `.env.production`
- Tratar identificador como número. Zero à esquerda é significativo.
"""


def test_sub_item_indentado_e_continuacao_nao_inviolavel(tmp_path: Path):
    """Sub-item de 2 espaços entrava como regra e ocupava uma das `max_itens` vagas.

    Duplamente caro: rouba a vaga de uma proibição real (o corte em `max_itens` é
    silencioso no runtime) e reafirma como proibição absoluta um fragmento que não proíbe
    nada — "inclui `.env.local`" lido fora do item pai não é regra.
    """
    raiz = _projeto_com(tmp_path / "p", COM_SUB_ITEM)
    regras = invioaveis(raiz, NUNCA)
    assert len(regras) == 2
    assert not any(r.startswith("inclui") for r in regras)


UM_ESPACO = """\
## Regras invioláveis

**NUNCA**

- Escrever segredo no repositório. Detalhe.
 - Tratar identificador como número. Detalhe.
"""


def test_bullet_com_um_espaco_continua_sendo_item(tmp_path: Path):
    """O limiar é 2 espaços, não "qualquer recuo" — é o que o markdown renderiza.

    Com 1 espaço de recuo o CommonMark ainda desenha os dois no mesmo nível: quem escreveu
    vê duas regras na tela. Tratar isso como continuação apagaria uma inviolável em
    silêncio, que é exatamente o defeito que este bloco de testes existe para fechar.
    """
    raiz = _projeto_com(tmp_path / "p", UM_ESPACO)
    assert len(invioaveis(raiz, NUNCA)) == 2


# --------------------------------------------------------------------------- #
# O contrato de que a auditoria depende: extrair sem teto devolve tudo
# --------------------------------------------------------------------------- #


def test_extrair_sem_teto_devolve_todos_os_itens(tmp_path: Path):
    """`max_itens` é orçamento da reafirmação, não filtro de leitura.

    A auditoria audita o que a seção DIZ, não o que caberia na mensagem: ela extrai com
    `replace(cfg, max_itens=10**6)` e cobra o teto por item sobre todos. Este teste é o
    contrato dessa chamada — se `invioaveis` ganhar qualquer outro corte, o cheque de
    perda silenciosa passa a mentir junto.
    """
    corpo = "## Regras invioláveis\n\n" + "".join(
        f"- Regra número {i} deste projeto. Detalhe que não entra.\n" for i in range(12)
    )
    raiz = _projeto_com(tmp_path / "p", corpo)
    cfg = ConfigReafirmacao()
    assert len(invioaveis(raiz, cfg)) == 8
    assert len(invioaveis(raiz, replace(cfg, max_itens=10**6))) == 12


# --------------------------------------------------------------------------- #
# Regra de guarda: chave que falta é guarda que ninguém sabe se funciona — e
# quem denuncia isso é a AUDITORIA, não o carregamento
# --------------------------------------------------------------------------- #


def test_regra_de_comandos_sem_exemplo_carrega(projeto: Path):
    """Chave obrigatória ausente NÃO lança — quem denuncia é `auditar.auditar_guardas`.

    `exemplo` continua sendo exigido: `guardar.py:_autoteste` gera o caso positivo dentro
    de um `if exemplo`, então sem a chave a guarda do projeto não é exercitada em lugar
    nenhum. O que mudou é o SINAL. Lançar aqui era regressão no upgrade: `_comum.contexto`
    engole `ErroDeConfig`, então o consumidor com uma regra sem `exemplo` — config que
    fazia parse e funcionava — ficaria com os SEIS hooks inertes só por atualizar o
    plugin, sem reinjeção, sem reafirmação e sem a guarda de `.env`, com o aviso indo para
    um stderr que ninguém lê.

    Chave DESCONHECIDA continua lançando: aquela não tem interpretação válida nenhuma e
    aparece na hora em que alguém escreve a config. O `ctx.falhar` desta aqui está em
    `tests/test_auditar_correcoes.py`.
    """
    escrever_config(
        projeto,
        {"guardas": {"comandos": [{"regex": r"\bgit\s+add\b.*\.xlsx", "motivo": "m"}]}},
    )
    cfg = carregar(projeto)
    assert cfg is not None
    assert cfg.guardas.comandos[0]["motivo"] == "m"


def test_regra_sem_o_proprio_padrao_carrega(projeto: Path):
    """Regra sem `regex`/`padrao` é descartada pelo hook num `continue` calado.

    Mesma classe do `permitido_em` ignorado que criou `_CHAVES_DE_REGRA`: a config afirma
    uma guarda e o hook não aplica nenhuma. A diferença é que aqui não há nem chave errada
    para procurar — a regra simplesmente não faz nada. Dano real, e a auditoria o cobra;
    mas o preço de avisar não pode ser desligar as outras guardas e as duas injeções.
    """
    escrever_config(projeto, {"guardas": {"caminhos": [{"motivo": "sem padrao"}]}})
    assert carregar(projeto) is not None
    escrever_config(projeto, {"guardas": {"comandos": [{"motivo": "sem regex"}]}})
    assert carregar(projeto) is not None


def test_regra_de_caminhos_nao_exige_exemplo(projeto: Path):
    """`caminhos` não precisa de `exemplo`: o autoteste deriva o caso do próprio `padrao`.

    Exigir a chave nas duas seções seria simetria bonita e config repetida sem função.

    A assimetria em si é verificada onde o cheque passou a morar —
    `test_auditar_correcoes.py::test_regra_completa_nao_reprova` audita uma regra de
    `caminhos` sem `exemplo` e exige silêncio. Aqui só se afirma que a leitura aceita.
    """
    escrever_config(
        projeto,
        {"guardas": {"caminhos": [{"padrao": "*.xlsx", "permitido_em": ["tests/"]}]}},
    )
    cfg = carregar(projeto)
    assert cfg is not None
    assert cfg.guardas.caminhos[0]["padrao"] == "*.xlsx"


# --------------------------------------------------------------------------- #
# `.claude/rules/` também instrui o agente
# --------------------------------------------------------------------------- #


def _adr_morto(raiz: Path) -> None:
    (raiz / "docs" / "adr" / "0002-antiga.md").write_text(
        "---\nstatus: superseded\ndata: 2026-01-20\nsubstituido-por: 0001\n---\n\n"
        "# ADR-0002 — Decisão antiga\n",
        encoding="utf-8",
    )


def test_rule_do_claude_e_fonte_operacional(projeto: Path):
    """A plataforma carrega `.claude/rules/*.md` ao lado do CLAUDE.md, com `paths:`.

    São arquivos que INSTRUEM o agente, e nenhum dos seis cheques de ponteiro velho os
    enxergava: um ADR morto citado numa rule passava o CI. Preventivo — nenhum projeto
    desta máquina usa o recurso ainda, e é mais barato incluir o padrão antes do primeiro.
    """
    from harness_memoria.auditar import Contexto, auditar_referencias_a_adr_morto

    _adr_morto(projeto)
    pasta = projeto / ".claude" / "rules"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "src.md").write_text(
        '---\npaths: ["src/**"]\n---\n\nSiga o ADR-0002 ao mexer aqui.\n',
        encoding="utf-8",
    )
    ctx = Contexto(raiz=projeto, cfg=carregar(projeto))
    auditar_referencias_a_adr_morto(ctx)
    assert any(".claude/rules/src.md" in f for f in ctx.falhas)


def test_projeto_sem_pasta_de_rules_fica_em_silencio(projeto: Path):
    """Padrão que não casa nada não é falha: `glob` vazio é o caso comum, não a exceção."""
    from harness_memoria.auditar import Contexto, auditar_referencias_a_adr_morto

    _adr_morto(projeto)
    ctx = Contexto(raiz=projeto, cfg=carregar(projeto))
    auditar_referencias_a_adr_morto(ctx)
    assert ctx.falhas == []
    assert ".claude/rules/**/*.md" in ConfigAuditoria().fontes_operacionais


# --------------------------------------------------------------------------- #
# `raiz_projeto`: 0 de 10 instruções cobertas, e os seis hooks começam por ela
# --------------------------------------------------------------------------- #


def test_raiz_projeto_prefere_a_variavel_de_ambiente(tmp_path: Path, monkeypatch):
    """`CLAUDE_PROJECT_DIR` ganha do candidato: o cwd de um hook não é a raiz.

    Precedência do CAMINHO DE HOOK, onde o candidato é o `cwd` do evento e não uma escolha
    de ninguém. Quem passa um alvo explícito na linha de comando quer o oposto — ver o
    `--projeto` de `auditar/__main__.py`.
    """
    env = _projeto_com(tmp_path / "env", "# raiz do env\n")
    cand = _projeto_com(tmp_path / "cand", "# raiz do candidato\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(env))
    assert raiz_projeto(str(cand)) == env


def test_raiz_projeto_ignora_env_sem_claude_md(tmp_path: Path, monkeypatch):
    """Sem `CLAUDE.md` o diretório não é raiz de projeto — nem vindo do ambiente."""
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    cand = _projeto_com(tmp_path / "cand", "# raiz do candidato\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(vazio))
    assert raiz_projeto(str(cand)) == cand


def test_raiz_projeto_cai_no_primeiro_candidato_quando_ninguem_tem_claude_md(
    tmp_path: Path, monkeypatch
):
    """Sem `CLAUDE.md` em lugar nenhum, devolve o primeiro candidato em vez de lançar.

    O gate é a ausência de `.claude/harness.json`, não a de `CLAUDE.md`: `carregar()` é
    quem decide o silêncio, e para isso precisa de um caminho.
    """
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    a = tmp_path / "a"
    a.mkdir()
    monkeypatch.chdir(tmp_path)
    assert raiz_projeto(None, str(a)) == a


def test_raiz_projeto_sem_candidato_usa_o_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    _projeto_com(tmp_path / "cwd", "# raiz do cwd\n")
    monkeypatch.chdir(tmp_path / "cwd")
    assert raiz_projeto() == tmp_path / "cwd"
