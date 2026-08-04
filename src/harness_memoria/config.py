"""Configuração do harness: política do projeto lida como DADO, não como código.

Por que este módulo existe
--------------------------
Na primeira encarnação deste harness (rede_inspira_app) a política morava em string
dentro do Python: a mensagem de reafirmação com as invioláveis, o bloco pós-compactação,
as extensões proibidas, os formatadores. Funcionava para um projeto e tornava o segundo
uma cópia — e duas cópias divergem na primeira correção.

Pior que divergir: um harness habilitado no nível do usuário, com política do projeto A
gravada no código, reafirma as regras do projeto A dentro do projeto B. Ruído com cara de
autoridade é pior que silêncio, porque o agente age sobre ele.

Daí duas invariantes:

1. **O gate é a presença de `.claude/harness.json`.** Sem esse arquivo, `carregar()`
   devolve `None` e todo hook sai com 0 sem escrever nada. É o que permite habilitar o
   plugin globalmente sem que ele crie `docs/diario/` em todo repositório que você abrir.

2. **As invioláveis NÃO são copiadas para cá.** São extraídas do `CLAUDE.md`, que já é a
   fonte de verdade. Ver `invioaveis()` para o contrato exato — ele é uma convenção de
   escrita, verificável por máquina, em vez de uma duplicação de conteúdo.

Somente biblioteca padrão: os hooks rodam com o `python` do PATH, fora do venv do projeto.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

NOME_ARQUIVO = "harness.json"

#: Onde os cheques de fronteira do projeto ficam, por convenção. Descoberto quando
#: `auditoria.checks_do_projeto` não é declarado — foi o único campo que os dois primeiros
#: projetos escreveram com valor idêntico, e convenção não se repete em config.
CAMINHO_CONVENCIONAL_CHECKS = "scripts/guardas_do_projeto.py"

#: Chaves aceitas no topo do `harness.json`. Chave desconhecida REPROVA em vez de ser
#: ignorada: config silenciosamente inerte por causa de um typo é a classe de bug mais
#: caça-fantasma que existe — o hook "roda", não faz nada, e nada indica o porquê.
_CHAVES_TOPO = {
    "projeto",
    "diario",
    "adr",
    "reafirmacao",
    "guardas",
    "formatadores",
    "auditoria",
}


@dataclass(frozen=True)
class ConfigDiario:
    pasta: str = "docs/diario"
    teto_linhas: int = 400
    #: A partir deste dia do mês, rotação pendente deixa de ser aviso e reprova o build.
    #: Aviso que ninguém lê equivale a cheque inexistente.
    dia_limite_rotacao: int = 3
    limite_injecao_chars: int = 5_000
    teto_becos_chars: int = 4_500
    teto_item_beco_chars: int = 240
    #: Proibições extras no prompt do narrador, além das universais (segredo, token).
    #: rede_inspira_app: "nome de aluno, RA, trecho de planilha real".
    proibicoes: tuple[str, ...] = ()
    #: Ordem de descarte quando a entrada não cabe no limite de injeção: a PRIMEIRA da
    #: tupla é a última a sair. O default põe "O que foi feito" para sair primeiro porque
    #: é a única seção reconstruível do `git log`.
    prioridade_secoes: tuple[str, ...] = (
        "Tentativas descartadas",
        "Aberto / Próximo passo",
        "Retomar com",
        "Como (o não-óbvio)",
        "Verificação",
        "Por quê",
        "O que foi feito",
    )
    #: `False` quando outro mecanismo do projeto já injeta a narrativa da última sessão
    #: (no ValidaNI o `context-history.mjs` injeta o handoff curado). O harness então
    #: contribui só o que o outro não cobre — índice de ADR e digest de becos — em vez
    #: de dizer a mesma coisa duas vezes no mesmo contexto.
    injetar_ultima_entrada: bool = True
    #: Nome do comando/skill DO PROJETO que fecha a sessão, quando existe um melhor que o
    #: `/encerrar-sessao` genérico — ex.: `"/handoff"`. Quando preenchido, a skill do plugin
    #: **cede a vez** em vez de competir.
    #:
    #: Existe porque o ValidaNI ficou com três coisas escrevendo no mesmo arquivo de diário:
    #: o `/handoff` (que faz mais — handoff curado, deep-dive de marco, julgamento de ADR),
    #: o `/encerrar-sessao` do plugin e o hook `SessionEnd`. Duas skills concorrentes para o
    #: mesmo alvo significam que chamar a errada produz uma entrada pior, no lugar certo —
    #: e nada acusa.
    #:
    #: O hook `SessionEnd` **continua** valendo: ele é o piso, não um concorrente. Quem cede
    #: é só a skill.
    skill_de_encerramento: str | None = None


@dataclass(frozen=True)
class ConfigAdr:
    pasta: str = "docs/adr"
    #: Seção obrigatória em ADR com status vivo. `None` desliga o cheque — os 22 ADRs do
    #: ValidaNI nasceram sem ela e o corpo de ADR aceito não se reescreve por conveniência
    #: de auditor.
    secao_plano: str | None = "## Plano de Implementação"
    #: A partir deste número, todo ADR novo abre com `## Regra` de até `teto_linhas_regra`
    #: linhas. `None` desliga. Não retrofita os anteriores: corpo de ADR aceito é imutável.
    primeiro_com_regra: int | None = None
    teto_linhas_regra: int = 5
    #: ADR agregado, substituído em partes por vários outros: a supersessão unilateral
    #: nele vira aviso em vez de falha. Números de 4 dígitos.
    agregados: tuple[str, ...] = ()
    #: Todo ADR tem os mesmos campos de frontmatter e as mesmas seções `##` que o
    #: `template.md` da pasta. `False` desliga, para corpus que nunca teve convenção fixa.
    #:
    #: O template É a declaração da convenção, então derivar dele custa zero config e não
    #: apodrece. O cheque nasceu de um erro concreto: um ADR escrito nesta migração saiu com
    #: 3 dos 7 campos e uma estrutura de seções inventada, porque foi redigido a partir do
    #: template genérico do harness em vez do template DO PROJETO. Nada acusou — e "genérico
    #: no lugar do específico" é a regressão que uma extração como esta mais arrisca causar.
    #:
    #: `Regra` fica fora: ela tem cheque próprio, com limiar próprio (`primeiro_com_regra`).
    conformidade_com_template: bool = True
    #: A partir de qual número a conformidade é exigida. `None` = todos, correto para corpus
    #: que já é uniforme (medido no rede_inspira_app: 32 de 32 conformes).
    #:
    #: Existe para o caso oposto, que é o comum ao adotar o harness num projeto com história:
    #: no ValidaNI, medido, só `Contexto` e `Decisão` aparecem nos 23, `Consequências` em 20,
    #: e a mesma seção tem DOIS nomes no corpus (`Alternativas descartadas` em 10,
    #: `Alternativas consideradas` em 6). Exigir tudo de todos reprovaria 21 de 23, e
    #: retrofitar exigiria reescrever corpo de ADR aceito — ou pior, inventar seções de
    #: alternativas em 7 ADRs que genuinamente nunca discutiram nenhuma.
    #:
    #: Mesma forma de `primeiro_com_regra`: a convenção nova vale para frente, e o corpus
    #: antigo fica como está. O limiar é o que permite ter convenção sem falsificar história.
    primeiro_com_template: int | None = None
    #: Teto de ADRs no índice injetado. `None` = todos, que é o correto até o corpus
    #: crescer: um corte fixo em 20 escondia 9 dos 29 ADRs do projeto de origem, e entre
    #: os escondidos estava o que substituía a política de PII. Se um dia precisar cortar,
    #: o número vem para cá — e o bloco injetado passa a se anunciar PARCIAL, com o resto
    #: localizável. Truncar avisando cria gatilho de leitura; truncar calado remove o
    #: único sinal de que falta algo.
    limite_indice: int | None = None


@dataclass(frozen=True)
class ConfigReafirmacao:
    #: A cada quantas escritas a reafirmação sai. 15 põe o custo amortizado de uma
    #: mensagem de ~500 chars em ~34 chars por escrita. Intervalo curto vira ruído, e
    #: ruído repetido é ignorado — o oposto do objetivo.
    intervalo_escritas: int = 15
    #: Título da seção do CLAUDE.md de onde as invioláveis são extraídas. Casado por
    #: prefixo, então "## Regras invioláveis" pega "## Regras invioláveis (guardrails)".
    secao: str = "## Regras invioláveis"
    #: Sub-bloco a isolar dentro da seção, quando ela tem mais de um. rede_inspira_app
    #: divide em `**NUNCA**` / `**PERGUNTE ANTES**` / `**SEMPRE**`, e só o primeiro é
    #: proibição absoluta — que é o único critério para entrar na reafirmação.
    sub_bloco: str | None = None
    #: Teto por inviolável extraída. Estourar não trunca: REPROVA na auditoria, com a
    #: instrução de encurtar a primeira frase. Truncar geraria regra pela metade, e
    #: meia proibição lida como permissão.
    teto_item_chars: int = 150
    max_itens: int = 8
    #: Linha final da mensagem, para mandar ao retrieval por caminho em vez de repetir regra
    #: de domínio. `None` omite.
    #:
    #: O default não é vazio porque os dois primeiros projetos escreveram a MESMA frase com
    #: palavras diferentes ("vai mudar padrão" / "vai mexer"), e ela é segura em qualquer
    #: projeto: o mapa caminho→ADR que ela cita é exigido por `auditar_mapa_de_adr_por_caminho`,
    #: então não há como o rodapé apontar para algo que não existe.
    rodape: str | None = (
        "Vai mexer em algum caminho? O mapa caminho→ADR do CLAUDE.md diz qual ADR ler."
    )
    habilitado: bool = True


@dataclass(frozen=True)
class ConfigGuardas:
    #: Caminhos cuja ESCRITA é bloqueada. Cada item: {padrao, permitido_em, motivo}.
    #: `padrao` é glob de nome de arquivo (`*.xlsx`) ou nome exato (`.env`).
    caminhos: tuple[dict, ...] = ()
    #: Comandos de shell bloqueados. Cada item: {regex, motivo}.
    comandos: tuple[dict, ...] = ()
    #: `.env` e `--no-verify` são bloqueados sempre, sem configuração: valem em todo
    #: projeto e não há caso legítimo de um agente escrever segredo ou pular hook.
    universais: bool = True


@dataclass(frozen=True)
class ConfigAuditoria:
    #: Globs dos arquivos que INSTRUEM um agente, e por isso não podem mandar seguir ADR
    #: morto. Corpo de ADR e entrada de diário ficam fora de propósito: os dois são
    #: imutáveis por regra, então não haveria como corrigir o que o cheque reprovasse.
    fontes_operacionais: tuple[str, ...] = (
        "CLAUDE.md",
        "AGENTS.md",
        "README.md",
        ".claude/settings.json",
        ".claude/hooks/*",
        ".claude/skills/*/SKILL.md",
        ".claude/commands/*.md",
        ".claude/agents/*.md",
        "scripts/*.py",
        "scripts/*.mjs",
        ".github/workflows/*.yml",
    )
    teto_claude_md: int = 150
    #: Fatos que README.md e CLAUDE.md descrevem os dois, para leitores diferentes. Não dá
    #: para eliminar a repetição; dá para proibir que discordem. Cada item: {rotulo, regex}
    #: com um grupo de captura.
    fatos_compartilhados: tuple[dict, ...] = ()
    #: Módulo Python com checks extra do projeto, resolvido a partir da raiz. Deve expor
    #: `registrar(ctx)`.
    #:
    #: `None` NÃO significa "sem checks de projeto": significa "descubra por convenção". Se
    #: `CAMINHO_CONVENCIONAL_CHECKS` existir na raiz, ele é usado. Foi o único campo que os
    #: dois primeiros projetos declararam com valor idêntico — então é convenção, e convenção
    #: não se repete em config.
    #:
    #: A distinção que importa: descoberto-e-ausente é silêncio (projeto sem fronteira própria
    #: é normal); DECLARADO-e-ausente reprova, porque alguém escreveu o caminho e o cheque não
    #: rodou. Fazer o default apontar para o caminho convencional quebraria todo projeto novo.
    checks_do_projeto: str | None = None
    exigir_mapa_por_caminho: bool = True


@dataclass(frozen=True)
class Config:
    raiz: Path
    projeto: str
    diario: ConfigDiario = field(default_factory=ConfigDiario)
    adr: ConfigAdr = field(default_factory=ConfigAdr)
    reafirmacao: ConfigReafirmacao = field(default_factory=ConfigReafirmacao)
    guardas: ConfigGuardas = field(default_factory=ConfigGuardas)
    auditoria: ConfigAuditoria = field(default_factory=ConfigAuditoria)
    #: Lista, não dataclass: cada item é uma regra {extensoes, comando, cwd?, exige?} e o
    #: número de regras varia por projeto. Ver `hooks/formatar.py` para o contrato.
    formatadores: tuple[dict, ...] = ()

    @property
    def pasta_diario(self) -> Path:
        return self.raiz / self.diario.pasta

    @property
    def pasta_adr(self) -> Path:
        return self.raiz / self.adr.pasta

    @property
    def indice_adr(self) -> Path:
        return self.pasta_adr / "README.md"


class ErroDeConfig(Exception):
    """Config presente e inválida. Distinta de config ausente, que é o gate."""


def caminho_config(raiz: Path) -> Path:
    return raiz / ".claude" / NOME_ARQUIVO


def carregar(raiz: Path) -> Config | None:
    """Config do projeto, ou `None` se o harness não está habilitado nele.

    `None` é o caminho normal e silencioso, não um erro: é o gate que permite o plugin
    ficar habilitado no nível do usuário. Config PRESENTE e inválida, ao contrário, lança
    — porque nesse caso alguém quis habilitar e merece saber por que não funcionou.
    """
    p = caminho_config(raiz)
    if not p.exists():
        return None
    try:
        bruto = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ErroDeConfig(f"{p} não é JSON válido: {e}") from e
    if not isinstance(bruto, dict):
        raise ErroDeConfig(f"{p} deveria ser um objeto JSON")

    desconhecidas = {k for k in bruto if k not in _CHAVES_TOPO and not _e_anotacao(k)}
    if desconhecidas:
        raise ErroDeConfig(
            f"{p}: chave(s) desconhecida(s) {sorted(desconhecidas)} — "
            f"aceitas: {sorted(_CHAVES_TOPO)}"
        )

    auditoria = _montar(ConfigAuditoria, bruto.get("auditoria"), "auditoria", p)
    if auditoria.checks_do_projeto is None and (raiz / CAMINHO_CONVENCIONAL_CHECKS).exists():
        # Descoberta por convenção. Só quando NÃO declarado: caminho declarado e ausente
        # continua reprovando, porque aí alguém escreveu o caminho e o cheque não rodou.
        auditoria = replace(auditoria, checks_do_projeto=CAMINHO_CONVENCIONAL_CHECKS)

    return Config(
        raiz=raiz,
        projeto=str(bruto.get("projeto") or raiz.name),
        diario=_montar(ConfigDiario, bruto.get("diario"), "diario", p),
        adr=_montar(ConfigAdr, bruto.get("adr"), "adr", p),
        reafirmacao=_montar(ConfigReafirmacao, bruto.get("reafirmacao"), "reafirmacao", p),
        guardas=_montar(ConfigGuardas, bruto.get("guardas"), "guardas", p),
        auditoria=auditoria,
        formatadores=tuple(bruto.get("formatadores") or ()),
    )


def _e_anotacao(chave: str) -> bool:
    """Chave de anotação, ignorada pela validação: qualquer uma que comece com `$`.

    Não é só `$comment`: JSON não tem comentário, então a única forma de justificar uma
    escolha ao lado dela é uma chave inventada — e uma por seção não basta. Isto foi medido
    na primeira config escrita a sério, que precisou de duas na mesma seção e foi reprovada
    por `$comment2`. Convenção de `$schema`/`$id`, estendida.
    """
    return chave.startswith("$")


def _montar(classe, bruto, secao: str, arquivo: Path):
    """Instancia uma dataclass de config, reprovando chave desconhecida na seção."""
    if bruto is None:
        return classe()
    if not isinstance(bruto, dict):
        raise ErroDeConfig(f"{arquivo}: `{secao}` deveria ser um objeto")
    campos = {f.name for f in classe.__dataclass_fields__.values()}
    desconhecidas = {k for k in bruto if k not in campos and not _e_anotacao(k)}
    if desconhecidas:
        raise ErroDeConfig(
            f"{arquivo}: `{secao}` tem chave(s) desconhecida(s) {sorted(desconhecidas)} "
            f"— aceitas: {sorted(campos)}"
        )
    limpo = {k: v for k, v in bruto.items() if not _e_anotacao(k)}
    # Tupla em vez de lista: as dataclasses são frozen e usadas como valor.
    for k, v in list(limpo.items()):
        if isinstance(v, list):
            limpo[k] = tuple(v)
    try:
        return classe(**limpo)
    except TypeError as e:
        raise ErroDeConfig(f"{arquivo}: `{secao}` inválida: {e}") from e


def raiz_projeto(*candidatos: str | None) -> Path:
    """Raiz do projeto: o primeiro candidato que contenha `CLAUDE.md`.

    `CLAUDE_PROJECT_DIR` primeiro, porque o cwd de um hook não é garantidamente a raiz.
    """
    import os

    for c in (os.environ.get("CLAUDE_PROJECT_DIR"), *candidatos, os.getcwd()):
        if not c:
            continue
        p = Path(c)
        if (p / "CLAUDE.md").exists():
            return p
    for c in (*candidatos, os.getcwd()):
        if c:
            return Path(c)
    return Path.cwd()


# --------------------------------------------------------------------------- #
# Invioláveis: extraídas do CLAUDE.md, nunca copiadas
# --------------------------------------------------------------------------- #

#: Marcadores de fim de um item na primeira frase. `. ` só conta como fim de frase se o
#: caractere seguinte for maiúsculo ou fim do texto — senão `vw_aluno_publico (só
#: anon_id).` e abreviações partiriam a regra no meio.
_FIM_DE_FRASE = re.compile(r"(?<=[.:;!?])(?=\s+[A-ZÀ-Þ(`*]|\s*$)")


def invioaveis(raiz: Path, cfg: ConfigReafirmacao) -> list[str]:
    """As proibições absolutas do projeto, uma linha cada, lidas do `CLAUDE.md`.

    O contrato — e é uma convenção de ESCRITA, verificada por máquina, não uma
    duplicação de conteúdo:

        A primeira frase de cada item da seção de invioláveis É a regra.

    Os dois projetos que originaram este harness já escreviam assim, sem combinar:

        - Enviar `aluno.nome` — ou qualquer PII — para o LLM. O nome é re-anexado...
          └────────────────── a regra ──────────────────┘ └── o porquê, que não entra

        1. **Fluxo unidirecional: Pipedrive → App. NUNCA escreva no Pipedrive.** Qualquer...
           └──────────────────────── a regra ────────────────────────────────┘

    Quando o item abre em negrito, o negrito ganha da primeira frase: é ele que delimita
    a regra na forma numerada. Item que estoure `teto_item_chars` NÃO é truncado — a
    auditoria reprova, pedindo para encurtar a primeira frase. Meia proibição lê como
    permissão, então truncar seria pior que falhar.
    """
    p = raiz / "CLAUDE.md"
    if not p.exists():
        return []
    texto = p.read_text(encoding="utf-8", errors="replace")

    corpo = _secao(texto, cfg.secao)
    if corpo is None:
        return []
    if cfg.sub_bloco:
        corpo = _sub_bloco(corpo, cfg.sub_bloco)
        if corpo is None:
            return []

    itens: list[str] = []
    for cru in _itens_de_lista(corpo):
        regra = _primeira_frase(cru)
        if regra:
            itens.append(regra)
    return itens[: cfg.max_itens]


def _secao(texto: str, titulo: str) -> str | None:
    """Corpo de uma seção `##`, casada por PREFIXO do título.

    Prefixo e não igualdade: `## Regras invioláveis` tem de achar
    `## Regras invioláveis (guardrails)`, que é como o ValidaNI escreve.
    """
    linhas = texto.splitlines()
    alvo = titulo.strip()
    nivel = len(alvo) - len(alvo.lstrip("#"))
    for i, linha in enumerate(linhas):
        if not linha.startswith(alvo):
            continue
        fim = len(linhas)
        for j in range(i + 1, len(linhas)):
            atual = linhas[j]
            if atual.startswith("#"):
                n = len(atual) - len(atual.lstrip("#"))
                if n <= nivel:
                    fim = j
                    break
        return "\n".join(linhas[i + 1 : fim])
    return None


def _sub_bloco(corpo: str, marcador: str) -> str | None:
    """Trecho entre um marcador em negrito e o próximo marcador do mesmo tipo."""
    linhas = corpo.splitlines()
    inicio = None
    for i, linha in enumerate(linhas):
        if linha.strip() == marcador.strip():
            inicio = i + 1
            break
    if inicio is None:
        return None
    for j in range(inicio, len(linhas)):
        s = linhas[j].strip()
        # outro marcador de bloco: negrito sozinho na linha
        if s != marcador.strip() and re.fullmatch(r"\*\*[^*]+\*\*", s):
            return "\n".join(linhas[inicio:j])
    return "\n".join(linhas[inicio:])


def _itens_de_lista(corpo: str) -> list[str]:
    """Itens de lista com ou sem número, cada um com suas linhas de continuação."""
    itens: list[str] = []
    atual: list[str] | None = None
    for linha in corpo.splitlines():
        m = re.match(r"^\s{0,3}(?:[-*+]|\d{1,2}[.)])\s+(.*)$", linha)
        if m:
            if atual:
                itens.append(" ".join(atual))
            atual = [m.group(1).strip()]
        elif atual is not None:
            if linha.strip():
                atual.append(linha.strip())
            else:
                itens.append(" ".join(atual))
                atual = None
    if atual:
        itens.append(" ".join(atual))
    return [" ".join(i.split()) for i in itens if i.strip()]


def _primeira_frase(item: str) -> str:
    """A regra: o negrito inicial se houver, senão a primeira frase.

    Exceção medida no ValidaNI: negrito terminado em `:` é RÓTULO, não regra — em
    "**Idempotência do sync:** o sync escreve SÓ colunas que vêm do Pipedrive" o negrito
    sozinho não proíbe nada. Nesse caso o rótulo fica e a primeira frase seguinte entra
    com ele. Sem isto a reafirmação sairia com "Idempotência do sync:" e mais nada.
    """
    item = item.strip()
    m = re.match(r"^\*\*(.+?)\*\*", item)
    if m:
        negrito = m.group(1).strip()
        if negrito.endswith(":"):
            resto = item[m.end() :].strip()
            corte = _FIM_DE_FRASE.search(resto)
            return f"{negrito} {(resto[: corte.start()] if corte else resto)}".strip()
        if len(negrito) > 12:
            return negrito
    corte = _FIM_DE_FRASE.search(item)
    return (item[: corte.start()] if corte else item).strip()
