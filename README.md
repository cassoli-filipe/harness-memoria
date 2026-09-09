# harness-memoria

Harness de memória de contexto para projetos: ADR e diário de engenharia reinjetados no
início de cada sessão, invioláveis reafirmadas dentro dela, guardas determinísticas e
auditoria mecânica da documentação no CI.

Extraído do `rede_inspira_app`, onde nasceu como seis hooks e um auditor de 790 linhas
acoplados àquele projeto. O que este repositório faz é separar o que é **mecanismo** do que
é **política**.

Este README é o guia de uso. Para a análise de fundamentos — a tese empírica por trás de
cada mecanismo, o mapa do código, os princípios de projeto e as tensões conhecidas — ver
[`FUNDAMENTOS.md`](FUNDAMENTOS.md).

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
uv add --dev "harness-memoria @ git+https://github.com/cassoli-filipe/harness-memoria"
uv run python -m harness_memoria.auditar
```

`git+https`, não `git+ssh`: o repositório é público (`gh repo view` confirma), e um runner
de CI recém-configurado não tem chave — a receita com `ssh://` falha com `Permission denied
(publickey)` no primeiro `uv sync` do projeto que acabou de adotar o harness. Troque para
`git+ssh` só se o repositório virar privado e a máquina que roda o `uv add` tiver a chave.

**`uv run`, não `python` nu, na segunda linha.** `uv add --dev` instala o pacote dentro do
`.venv` do projeto; o `python` do PATH não o enxerga. Reproduzido: `uv init` + `uv add --dev
"harness-memoria @ file:///…"` seguido de `python -m harness_memoria.auditar` (sem `uv run`)
devolve `ModuleNotFoundError: No module named 'harness_memoria'`; com `uv run` na frente,
funciona — é o mesmo binário `harness-auditar` que o `pyproject.toml` expõe como script, então
`uv run harness-auditar` também serve. Onde o projeto consumidor não usa `uv`, a forma
equivalente é `python -m harness_memoria.auditar` com o venv do projeto **ativo** — a falha
não é do módulo, é de qual interpretador o invoca.

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

`claude plugin details harness-memoria` mostra o inventário e o custo. Medido em 2026-09-08,
depois das mudanças descritas neste README:

```
Component inventory
  Skills (4)  auditar-docs, encerrar-sessao, harness-init, novo-adr
  Hooks (6)   SessionStart, SubagentStart, PreCompact, SessionEnd, PreToolUse, PostToolUse
              (harness-only — no model context cost)

Projected token cost
  Always-on:   ~491 tok   added to every session
```

**"no model context cost" é verdade para o REGISTRO dos hooks, e falso para a SAÍDA deles.**
O CLI conta 6 porque lista *tipos de evento* (`hooks.json` tem 7 registros, 6 scripts
distintos — `session_start.py` atende `SessionStart` e `SubagentStart`). Rodar o CÓDIGO de
um hook não custa tokens, mas quatro dos seis produzem texto que a plataforma injeta no
contexto — três como `additionalContext` e o `pre_compact` como `customInstructions` do
sumarizador —, e isso entra na conta do modelo como qualquer outro texto:

| Hook           | Quando emite            | Chars por disparo (medido)                          |
| -------------- | ------------------------ | ---------------------------------------------------- |
| `session_start` | todo `startup/resume/clear/compact/fork` | até 10.000 — ver "O orçamento do bloco injetado" abaixo |
| `session_start` | todo `SubagentStart` (bloco reduzido: invioláveis + digest de becos, sem índice de ADR) | até 6.000 por subagente (teto) — medido: 733 ch neste repositório (5 invioláveis) e 5.099–5.315 ch em corpus sintético de 60 ADRs, duas medições com geradores diferentes — multiplica pelo número de Tasks da sessão |
| `reafirmar`     | a cada 15 escritas       | 550 ch no CLAUDE.md deste repositório, 5 invioláveis (~37 ch/escrita amortizados) |
| `guardar`       | a cada bloqueio          | 133 ch na guarda universal de `.env`                  |
| `pre_compact`   | toda compactação (`manual`/`auto`) | 452 ch neste repositório (5 invioláveis) e 170 ch no consumidor sintético (1) — vira `customInstructions` do sumarizador, não `additionalContext` |

Meça o seu projeto com os dois comandos que a fidelidade confere:

```bash
python src/harness_memoria/hooks/session_start.py --autoteste --projeto .
python src/harness_memoria/hooks/reafirmar.py --autoteste --projeto .
```

**Sobre os "tokens" acima:** não há tokenizador na dependência (zero deps é requisito — ver
"Desenvolvimento"), então todo número de token deste documento deriva da razão calibrada
`chars-de-descrição / tokens-sempre-ligados` que o próprio `claude plugin details` reporta:
1.072 ch (as 4 descrições de skill, medidas) / ~491 tok ≈ **2,2 ch/token** para prosa pt-BR.
Isso é mais baixo que a estimativa genérica de ~3,5 ch/token usada em análises anteriores
deste projeto (calibrada em inglês) — pt-BR com acentuação tokeniza mais denso. Onde este
README cita "~tok", é `chars / 2,3`, arredondado, e o número em CHARS é sempre o que foi de
fato medido.

## O gate

Todo hook é **inerte** num projeto sem `.claude/harness.json`. É isso que permite habilitar
o plugin no nível do usuário sem que ele crie `docs/diario/` em todo repositório que você
abrir, e sem que a reafirmação de um projeto apareça dentro de outro.

Consequência deliberada: nem as guardas universais (`.env`, `--no-verify` e `git add
--force`) valem sem opt-in. São **três**, não duas — por muito tempo os lugares que as
listavam citavam só as duas primeiras, e a não anunciada é justamente a que mais surpreende
(`git add -f` tem uso legítimo para um humano). Negar uma tool call num repositório que
nunca pediu o harness é surpresa, e surpresa em bloqueio queima a confiança no mecanismo
inteiro.

A auditoria faz o oposto: sem config ela **reprova**. Quem a roda pediu por ela, e um passo
de CI verde que não auditou nada é o pior resultado possível para um cheque.

**Pré-requisito silencioso: o nome `python` precisa resolver no PATH.** Os cinco (e agora
seis) registros de `hooks.json` usam `"command": "python"`, nunca `python3` — no Windows o
instalador oficial não cria um `python3.exe`, então não há como usar as duas grafias. Em
macOS ≥ 12.3 e em Debian/Ubuntu sem o pacote `python-is-python3`, `python` não existe: o
hook não roda, o `.env` não é bloqueado, e nada avisa — é indistinguível do gate normal
(inerte por falta de config). Se a instalação parecer não fazer nada, rode `command -v
python` (ou `where python` no Windows) antes de suspeitar do harness.

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

## O orçamento do bloco injetado

O bloco do `session_start` (última entrada do diário + digest de becos + índice de ADR) tem
ORÇAMENTO: fecha em no máximo **10.000 chars**, porque é o teto que `additionalContext`
aplica na plataforma instalada — sem esse limite, 14 de 40 sessões medidas num consumidor
real chegavam com o bloco INTEIRO substituído por um preview truncado, porque o bloco
natural media 15.485 ch num consumidor real de 53 ADRs e 12.911 ch em outro de 22-23 ADRs
(reproduzidos em corpus sintético de 60 e 30 ADRs) — 55% e 29% acima do teto. Depois do
orçamento, ele fecha entre **9.831 e 9.908 ch** — duas medições independentes, com
geradores de corpus diferentes, sobre 30, 60 e 120 ADRs — e em **9.866 ch com 400 ADRs**,
14x o maior corpus real observado. Dentro do teto em todos os casos, sem que
`conferir_fidelidade` acuse uma seção sumida.

Quando o bloco cabe no tamanho natural, nada é cortado. Quando não cabe, três mecanismos
cedem em ORDEM, cada um anunciando o corte (truncar calado remove o único sinal de que falta
algo):

1. **O índice de ADR** cede primeiro, uma linha por vez, até um piso de 3.500 ch — é o corte
   mais barato porque `docs/adr/README.md` já é o índice completo, só um clique de distância.
   O bloco se anuncia `índice PARCIAL` e diz quantos ADRs faltam e onde estão.
2. **O digest de becos** cede depois, um item por vez, respeitando o teto de
   `teto_becos_chars` (4.500 ch por padrão) — anuncia `{n} de {total}` e aponta para
   `docs/diario/` e `docs/diario/arquivo/`.
3. **A última entrada do diário** cede por último e por SEÇÃO inteira (nunca corta texto no
   meio), por `prioridade_secoes` — é a peça que cai em degrau, então cede menos ordinariamente.

O bloco do `SubagentStart` é REDUZIDO por desenho: só invioláveis + digest de becos, teto
próprio de 6.000 ch, sem índice de ADR nem entrada de diário — o subagente escreve mais do
que lê e não precisa do corpus inteiro para saber o que é proibido.

## Componentes

Seis scripts, sete registros em `hooks/hooks.json` (`session_start.py` atende dois eventos):

| Hook            | Evento                     | O que faz                                                          |
| --------------- | --------------------------- | ------------------------------------------------------------------- |
| `session_start` | SessionStart                | injeta última entrada do diário, digest de becos, índice de ADR — orçado para caber em 10.000 ch (ver acima) |
| `session_start` | SubagentStart                | injeta o bloco REDUZIDO (invioláveis + digest de becos, teto 6.000 ch) para o subagente que nunca leu a sessão principal |
| `pre_compact`   | PreCompact                  | instrui o sumarizador a preservar invioláveis e IDs de ADR ANTES da compactação — stdout cru, custo de contexto ZERO |
| `session_end`   | SessionEnd                  | grava o **piso determinístico** da sessão (arquivos, comandos, diffstat, ADRs tocados); narrativa por `claude -p` é **opt-in** (ver abaixo) |
| `reafirmar`     | PostToolUse (`async`)       | reafirma as invioláveis a cada N escritas                            |
| `guardar`       | PreToolUse                  | bloqueia `.env`, `--no-verify`, `git add --force` e os caminhos proibidos do projeto |
| `formatar`      | PostToolUse (`async`)       | roda os formatadores configurados no arquivo editado                 |

| Skill               | Para quê                                            |
| ------------------- | --------------------------------------------------- |
| `/harness-init`     | instalar o harness num projeto (lê o CLAUDE.md dele) |
| `/novo-adr`         | criar ADR com frontmatter e índice atualizado        |
| `/encerrar-sessao`  | registrar a sessão NARRADA no diário antes de sair — o caminho primário da narrativa, agora que o hook só grava o piso |
| `/auditar-docs`     | rodar a auditoria e corrigir o que falhar            |

**`SessionEnd` não narra por default.** Ele só tenta o `claude -p` quando a variável de
ambiente `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` está setada acima de ~21.000 (é a
variável que a PRÓPRIA plataforma lê para esse hook; o `timeout` do `hooks.json` não
levanta nada para hook de plugin — a plataforma dá 1.500 ms e ignora o valor declarado, que
é como o hook chegou a nunca gravar nada em produção). Para habilitar, no
`.claude/settings.json` do **consumidor**:

```json
{ "env": { "CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS": "60000" } }
```

Isso assina 15–30 s a mais na saída de cada sessão — o custo do caminho feliz de antes,
agora opcional em vez de obrigatório. Sem a variável, o hook grava só o piso (fatos
determinísticos, sem LLM) em ~421 ms medidos. `/encerrar-sessao` continua sendo o caminho
recomendado para uma narrativa de qualidade: roda dentro da sessão, com contexto completo e
sem orçamento de 1.500 ms.

Cada hook tem `--autoteste`, roda sem o Claude Code e é o que o CI executa:

```bash
for h in session_start session_end reafirmar guardar formatar pre_compact; do
  python "src/harness_memoria/hooks/$h.py" --autoteste --projeto /caminho/do/projeto
done
```

O autoteste do `session_start` confere **fidelidade**, não só que o hook roda: reprova se o
bloco ultrapassar o teto de 10.000 ch da plataforma, se o índice de ADR chegar cortado sem
se declarar cortado, se um ADR morto (`superseded`) aparecer sem apontar substituto, se o
recorte da entrada do diário descartar as seções de retomada, ou se um beco da última
entrada não chegar ao bloco nem em texto nem no digest. Ele confere os DOIS blocos —
completo e reduzido — na mesma chamada, porque os dois são injetados em produção.

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

`requires-python = ">=3.10"` — medido rodando a auditoria e os seis autotestes com o
3.10.11 desta máquina, todos aprovados; nenhum módulo usa API 3.11+. Não é `>=3.11` porque
esse número nunca correspondeu a nada no código e bloqueava `uv add` num consumidor em
3.10, versão comum de produção.
