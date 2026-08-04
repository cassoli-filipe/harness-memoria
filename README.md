# harness-memoria

Harness de memória de contexto para projetos: ADR e diário de engenharia reinjetados no
início de cada sessão, invioláveis reafirmadas dentro dela, guardas determinísticas e
auditoria mecânica da documentação no CI.

Extraído do `rede_inspira_app`, onde nasceu como seis hooks e um auditor de 790 linhas
acoplados àquele projeto. O que este repositório faz é separar o que é **mecanismo** do que
é **política**.

## As três camadas

| Camada        | Onde vive                                                     | Muda por projeto? |
| ------------- | ------------------------------------------------------------- | ----------------- |
| **Mecanismo** | este repositório                                              | não               |
| **Política**  | `.claude/harness.json` + seção de invioláveis do `CLAUDE.md`   | sim               |
| **Conteúdo**  | `docs/adr/`, `docs/diario/` do projeto                        | é o projeto       |

A camada de conteúdo é a que dá valor. O mecanismo instalado num projeto vazio é um
mecanismo vazio: ele começa a pagar depois de umas dez sessões registradas, quando a seção
`### Tentativas descartadas` do diário passa a ter o que dizer.

## Dois canais de entrega, e por quê

**Plugin** — entrega os hooks e as skills para a sessão do Claude Code. O marketplace se
chama `harness-casso`; o plugin, `harness-memoria`. Duas formas de registrar, e **só uma por
vez**: um usuário registra um único marketplace por nome, então o segundo `add` substitui o
primeiro.

```bash
# a) pasta local — aponta para este clone, sem autenticação nenhuma
claude plugin marketplace add C:/Users/casso/projetos/harness-memoria

# b) GitHub — o que funciona em outra máquina
claude plugin marketplace add cassoli-filipe/harness-memoria

claude plugin install harness-memoria@harness-casso --scope user
```

**Pacote Python** — entrega o motor de auditoria para o CI.

```bash
uv add --dev "harness-memoria @ git+ssh://git@github.com/cassoli-filipe/harness-memoria"
python -m harness_memoria.auditar
```

Dois canais porque `${CLAUDE_PLUGIN_ROOT}` é efêmero e muda a cada atualização do plugin:
o CI não pode depender dele. É o mesmo código, consumido de duas formas — não são duas
implementações.

## Editar o harness

**Commit é o que publica, inclusive na fonte `directory`.** Medido em 2026-08-04: mesmo
apontando o marketplace para esta pasta, o `install` **copia** para
`~/.claude/plugins/cache/harness-casso/harness-memoria/<sha>/`, e a versão é o SHA do commit.
Edição na árvore de trabalho não chega ao cache nem depois de `marketplace update` — quem quer
iterar sem commitar roda o código direto, por `PYTHONPATH`:

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .

# contra um projeto de verdade, que é o que o pytest não cobre
python src/harness_memoria/hooks/session_start.py --autoteste --projeto /caminho/do/projeto
PYTHONPATH=src python -m harness_memoria.auditar --projeto /caminho/do/projeto

git commit && git push

# São DOIS comandos, e o primeiro sozinho não faz nada visível:
claude plugin marketplace update harness-casso        # só recarrega o catálogo
claude plugin update harness-memoria@harness-casso    # é este que troca a versão
# depois, reinicie a sessão
```

O **id qualificado é obrigatório** no `plugin update`: `claude plugin update harness-memoria`
falha com `Plugin "harness-memoria" not found`. O cache guarda uma pasta por SHA e mantém a
anterior por ~2 semanas, então rollback é trocar a versão instalada de volta.

O CI dos projetos consumidores pega o commit novo sozinho, sem `version` para bumpar — só a
sessão do Claude Code precisa dos dois comandos acima.

`claude plugin details harness-memoria` mostra o inventário e o custo: **~469 tokens sempre
ligados** (as 4 descrições de skill), mais 1,1k–2,8k quando uma skill é invocada. Os 5 hooks
não custam contexto — rodam fora do modelo.

## O gate

Todo hook é **inerte** num projeto sem `.claude/harness.json`. É isso que permite habilitar
o plugin no nível do usuário sem que ele crie `docs/diario/` em todo repositório que você
abrir, e sem que a reafirmação de um projeto apareça dentro de outro.

Consequência deliberada: nem as guardas universais (`.env`, `--no-verify`) valem sem opt-in.
Negar uma tool call num repositório que nunca pediu o harness é surpresa, e surpresa em
bloqueio queima a confiança no mecanismo inteiro.

A auditoria faz o oposto: sem config ela **reprova**. Quem a roda pediu por ela, e um passo
de CI verde que não auditou nada é o pior resultado possível para um cheque.

## As invioláveis não são copiadas

A reafirmação intra-sessão e o aviso pós-compactação **extraem** as regras do `CLAUDE.md` do
projeto, com um contrato só:

> A primeira frase de cada item da seção de invioláveis é a regra.

```markdown
## Regras invioláveis

**NUNCA**

- Enviar `aluno.nome` — ou qualquer PII — para o LLM. O nome é re-anexado por Python…
  └───────────────── vira a reafirmação ─────────────────┘ └── fica só no CLAUDE.md
```

Negrito inicial ganha da primeira frase, para a forma numerada (`1. **Nunca escreva no
Pipedrive.** Detalhe…`). Negrito terminado em `:` é rótulo, não regra: entra junto com a
frase seguinte. Item que não cabe em uma linha **reprova na auditoria** em vez de ser
truncado — meia proibição lê como permissão.

## Componentes

| Hook          | Evento          | O que faz                                                            |
| ------------- | --------------- | -------------------------------------------------------------------- |
| `session_start` | SessionStart  | injeta última entrada do diário, digest de becos, índice de ADR       |
| `session_end`   | SessionEnd    | narra a sessão por `claude -p`, com queda determinística garantida    |
| `reafirmar`     | PostToolUse   | reafirma as invioláveis a cada N escritas                            |
| `guardar`       | PreToolUse    | bloqueia `.env`, `--no-verify` e os caminhos proibidos do projeto     |
| `formatar`      | PostToolUse   | roda os formatadores configurados no arquivo editado                 |

| Skill               | Para quê                                            |
| ------------------- | --------------------------------------------------- |
| `/harness-init`     | instalar o harness num projeto (lê o CLAUDE.md dele) |
| `/novo-adr`         | criar ADR com frontmatter e índice atualizado        |
| `/encerrar-sessao`  | registrar a sessão no diário antes de sair           |
| `/auditar-docs`     | rodar a auditoria e corrigir o que falhar            |

Cada hook tem `--autoteste`, roda sem o Claude Code e é o que o CI executa:

```bash
python src/harness_memoria/hooks/session_start.py --autoteste --projeto /caminho/do/projeto
```

O autoteste do `session_start` confere **fidelidade**, não só que o hook roda: reprova se o
índice de ADR chegar cortado sem se declarar cortado, se um ADR morto aparecer sem apontar
substituto, ou se o recorte da entrada do diário descartar as seções de retomada.

## Por que reinjeção

Aderência a instrução decai **por passo dentro da sessão**, não por causa do formato do
arquivo de instruções: no estudo fatorial que originou o hook de reafirmação
(arXiv:2605.10039, 1.650 sessões de Claude Code) cada função gerada corresponde a ~5,6%
menos chance de conformidade (OR 0,944), e nenhuma variável de formato tem efeito
detectável. Daí a contramedida ser reinjeção, e não um CLAUDE.md melhor escrito.

Ponteiro velho é pior que ponteiro nenhum: com comentário incorreto o acerto medido cai de
78,5% para 68,1%, enquanto doc ausente praticamente não muda nada (arXiv:2404.03114). É por
isso que metade da auditoria existe para caçar referência a ADR morto e ponteiro defasado —
o dano não está no que falta, está no que mente.

## Desenvolvimento

```bash
uv sync --extra dev
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Zero dependências em runtime, e isso é requisito: os hooks rodam com o `python` do PATH,
fora do venv do projeto consumidor.
