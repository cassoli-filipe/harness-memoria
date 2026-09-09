# Fundamentos do `harness-memoria`

> Análise do funcionamento, dos fundamentos e dos princípios de projeto deste repositório.
> Escrita a partir da leitura integral do código (5.638 linhas de `src/`, 364 casos de
> teste, sobre os mesmos 14 commits — o crescimento é trabalho ainda não commitado de uma
> passada de otimização orientada por diagnóstico), não a partir do README.
>
> Este arquivo é versionado de propósito (decisão deste commit: ficar, não apagar) e deve
> ser tratado como fonte OPERACIONAL do próprio repositório — isto é, entrar em
> `ConfigAuditoria.fontes_operacionais` (`src/harness_memoria/config.py`) junto com o
> `README.md`, para que referência a ADR morto ou script renomeado aqui também reprove a
> auditoria. Sem essa linha, este é o maior documento do repositório sem régua nenhuma — o
> próprio defeito que ele existe para descrever em outros arquivos. O README é o guia de
> uso; este arquivo é a leitura para quem vai mexer no mecanismo.
>
> Nota de carona para quem for mexer em `fontes_operacionais`: o default hoje varre
> `.claude/skills/*/SKILL.md` (a convenção do PROJETO CONSUMIDOR), não `skills/*/SKILL.md`
> (onde vivem as quatro skills DESTE plugin). Sem o segundo padrão, as próprias
> `skills/*/SKILL.md` do repositório continuam fora de todo cheque de ponteiro velho mesmo
> depois desta auto-hospedagem — acrescente-o junto com `FUNDAMENTOS.md`.

---

## 1. O problema que o repositório ataca

Um agente de código esquece. Não por defeito de memória de longo prazo — isso o `CLAUDE.md`
resolve — mas **dentro da sessão**: quanto mais passos ele dá, menos provável é que ainda
esteja obedecendo à instrução que leu no primeiro turno. E quando a sessão acaba, tudo que
foi aprendido nela (inclusive o que **não** funcionou) evapora, porque o único artefato que
sobrevive é o diff.

Disso saem três falhas distintas, que o repositório trata separadamente:

| Falha                       | Sintoma                                                | Contramedida aqui                                          |
| --------------------------- | ------------------------------------------------------ | ---------------------------------------------------------- |
| **Decaimento intra-sessão** | a regra lida no turno 1 é violada no turno 40           | reinjeção periódica (`reafirmar`, `session_start` em `compact`) |
| **Amnésia entre sessões**   | o mesmo beco sem saída é explorado de novo, meses depois | diário append-only + digest de becos reinjetado             |
| **Apodrecimento do ponteiro** | a documentação continua lá, mas mente                 | auditoria mecânica no CI                                    |

A terceira é a mais contra-intuitiva, e é o que dá ao projeto sua tese mais forte — ver §2.

---

## 2. A tese, e a evidência que a sustenta

O projeto não é uma coleção de boas práticas. Ele parte de três afirmações empíricas, cada
uma citada no ponto do código que ela justifica.

**(a) Aderência decai por passo, não por formato.**
`arXiv:2605.10039` — estudo fatorial sobre 1.650 sessões de Claude Code: cada função gerada
corresponde a ~5,6% menos chance de conformidade (OR 0,944), e **nenhuma** variável de
formato do arquivo de instrução tem efeito detectável.

*Consequência de projeto:* a contramedida não pode ser "escrever um `CLAUDE.md` melhor".
Tem de ser **reinjeção**. Daí `hooks/reafirmar.py` existir. Ele é registrado com
`async: true` em `hooks.json` — e a premissa que esta análise afirmava antes era **falsa**:
dizia que "saída de hook `async` é descartada pelo Claude Code", quando na verdade o binário
instalado colhe o resultado do hook assíncrono e entrega o `additionalContext` no turno
seguinte. O preço de `async` é um turno de atraso numa mensagem cuja função é combater
decaimento ao longo de dezenas de passos (aceitável); o ganho é não bloquear ~145 ms em cada
escrita, sendo que 14 de cada 15 execuções não emitem nada.

**(b) Documentação errada faz dano; documentação ausente quase não faz.**
`arXiv:2404.03114` — com comentário incorreto, o acerto medido cai de 78,5% para 68,1%; com
doc ausente, praticamente não muda.

*Consequência de projeto:* metade do auditor não procura o que falta, procura **o que
mente**. `auditar_referencias_a_adr_morto`, `auditar_mapa_de_adr_por_caminho`,
`auditar_coerencia_readme_claude`, `auditar_contagem_de_adr_no_readme`,
`auditar_scripts_citados` e `auditar_indice_por_dominio` são todos cheques de *ponteiro
velho*, não de cobertura.

**(c) Contexto longo degrada bem antes do limite nominal.**
Chroma, *Context Rot*, medido em 18 modelos.

*Consequência de projeto:* "leia o índice de ADR antes de mexer no schema" é uma instrução
que ninguém executa inteira, porque o corpus custa dezenas de milhares de tokens. A troca é
**retrieval por caminho**: o mapa `| Caminho | ADRs |` do `CLAUDE.md` reduz o corpus a 5–7
ADRs por tarefa. E porque um mapa que apodrece é pior que mapa nenhum (por (b)), o mapa é
auditado — caminho inexistente e ADR morto reprovam o build.

A frase que resume as três: **o mecanismo existe para reduzir o que o modelo precisa
lembrar, e para garantir que o pouco que ele lê seja verdade.**

---

## 3. As três camadas — a decisão estrutural

Este é o eixo de todo o repositório, declarado já no docstring do pacote
(`src/harness_memoria/__init__.py`):

| Camada        | Onde vive                                                   | Muda por projeto? | Natureza     |
| ------------- | ----------------------------------------------------------- | ----------------- | ------------ |
| **Mecanismo** | este repositório                                            | não               | código       |
| **Política**  | `.claude/harness.json` + seção de invioláveis do `CLAUDE.md` | sim               | **dado**     |
| **Conteúdo**  | `docs/adr/`, `docs/diario/` do projeto                      | é o projeto       | prosa humana |

A separação nasceu de um defeito concreto. Na primeira encarnação (`rede_inspira_app`), a
política morava em *string dentro do Python*: a mensagem de reafirmação, as extensões
proibidas, os formatadores. Isso tem duas consequências ruins e uma catastrófica:

1. o segundo projeto vira uma cópia — e duas cópias divergem na primeira correção;
2. o número mágico perde o comentário que o justificava;
3. **com o plugin habilitado no nível do usuário, a política do projeto A passa a ser
   reafirmada dentro do projeto B.** Ruído com cara de autoridade é pior que silêncio,
   porque o agente age sobre ele.

O item 3 é o que produz a invariante mais importante do repositório, o *gate* (§6.1).

Corolário honesto, e o README o assume: **o mecanismo instalado num projeto vazio é um
mecanismo vazio.** Ele só começa a pagar depois de ~10 sessões registradas, quando a seção
`### Tentativas descartadas` passa a ter o que dizer. A camada que dá valor é a de conteúdo;
as outras duas só a protegem.

---

## 4. Mapa do código

```
src/harness_memoria/
├── config.py     (658)  política como dado + o gate + extração das invioláveis
├── diario.py     (636)  leitura/escrita append-only, recorte, digest de becos, fatos
├── adr.py        (263)  frontmatter, status, supersessão, índice para injeção
├── hooks/               seis entry points, cada um executável e autotestável
│   ├── _comum.py        (180)  gate, leitura do evento, estado por sessão
│   ├── _leve.py         (114)  PRÉ-GATE: decide "adotou o harness?" sem importar `config`
│   ├── session_start.py (663)  reinjeção (SessionStart) + bloco reduzido (SubagentStart)
│   ├── session_end.py   (475)  piso determinístico; narração por LLM é OPT-IN
│   ├── pre_compact.py   (155)  instrui o sumarizador ANTES da compactação (PreCompact)
│   ├── reafirmar.py     (258)  reinjeção intra-sessão a cada N escritas (async)
│   ├── guardar.py       (491)  bloqueio determinístico (PreToolUse)
│   └── formatar.py      (193)  formatação silenciosa (PostToolUse, async)
└── auditar/      (1.088) 20+ cheques genéricos + carregamento dos cheques do projeto
```

Fora de `src/`: `hooks/hooks.json` (registro dos hooks no plugin — 6 scripts, 7 registros:
`session_start.py` atende `SessionStart` e `SubagentStart`), `skills/` (4 skills),
`template/` (esqueleto de `docs/` + `harness.json` mínimo), `.github/workflows/ci.yml`
(3 jobs) e `tests/` (364 casos).

**Zero dependências em runtime, e isso é requisito, não economia.** Os hooks rodam com o
`python` do `PATH`, fora do venv do projeto consumidor. Qualquer import de terceiro
transformaria "instalar o plugin" em "gerenciar um ambiente por projeto". O job
`autotestes` do CI existe precisamente para pegar uma violação disso: roda `python` puro,
sem venv — e por isso ninguém no repositório tinha notado, até um crítico externo medir,
que nada aqui declara o pré-requisito mais básico desse desenho: **o nome `python` precisa
resolver no PATH**. `grep -rn python3` no repositório inteiro dá zero — os cinco (agora
seis) registros usam `"command": "python"`, nunca `python3` (no Windows não há como usar a
outra grafia; o instalador oficial não cria `python3.exe`). Em macOS ≥ 12.3 e em
Debian/Ubuntu sem o pacote `python-is-python3`, esse nome não existe: o hook não roda, e o
resultado é **indistinguível do gate normal** — saída vazia, `.env` não bloqueado, nada
avisa. O job `autotestes` não pode pegar essa classe de regressão porque
`actions/setup-python` fabrica o nome `python` no PATH do runner; a ausência só existe fora
do CI. Ver o README, seção "O gate", para o pré-requisito por escrito onde o instalador lê.
`requires-python = ">=3.10"` no `pyproject.toml` (não `>=3.11`, que nunca correspondeu a
nada medido no código — ver `pyproject.toml` para a medição ao lado da linha).

---

## 5. O ciclo de vida de uma sessão

```
SessionStart (startup|resume|clear|compact|fork)
   └─ session_start.py  → montar(reduzido=False)
        ├─ última entrada do diário, recortada por prioridade de seção
        ├─ digest de becos sem saída (todos os meses, inclusive arquivo/)
        ├─ índice de ADR derivado dos ARQUIVOS (não da tabela do README)
        ├─ [só em compact] aviso pós-compactação com as invioláveis
        └─ tudo isso ORÇADO para caber em 10.000 ch (TETO_PLATAFORMA_CHARS) — ver §6.5

SubagentStart (todo tipo de subagente — matcher vazio, casa por `agent_type`)
   └─ session_start.py  → montar(reduzido=True)
        └─ bloco REDUZIDO: só invioláveis + digest de becos, teto próprio de 6.000 ch —
           o subagente escreve mais do que lê e não viu a sessão principal

PreCompact (manual|auto, casado por `trigger`, não por `source`)
   └─ pre_compact.py  → stdout CRU (não JSON): instrui o sumarizador ANTES da
      compactação a preservar invioláveis e IDs de ADR — custo de contexto ZERO, porque não
      injeta bloco novo, só influencia o que o próprio resumo decide guardar. `exit 2` aqui
      BLOQUEARIA a compactação (confirmado no binário instalado); por isso este é o único
      dos seis hooks cujo `except` de módulo tem de ser absoluto — não há ramo de código que
      produza outro código de saída.

... trabalho ...

PreToolUse  (Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell)
   └─ guardar.py  → permissionDecision: "deny" + motivo acionável

PostToolUse (Write|Edit|MultiEdit|NotebookEdit — dois registros com matchers quase iguais)
   ├─ formatar.py  (async, silencioso)
   └─ reafirmar.py (async — a cada 15 escritas, reinjeta as invioláveis; um turno de atraso)

SessionEnd (clear|logout|prompt_input_exit|resume|other — os CINCO motivos do enum real,
            extraído do binário instalado; `resume` faltava e era metade dos encerramentos
            in-session)
   └─ session_end.py
        ├─ fatos determinísticos (transcript + git diffstat) → PISO, sempre gravado
        └─ narração via `claude -p` — **OPT-IN**, ver §6.6; quando habilitada, cai para o
           piso em qualquer falha (executável ausente, timeout, resposta curta demais)
```

Quatro detalhes de engenharia que merecem nota:

- **Anti-recursão.** O `claude -p` que narra o diário *também* é uma sessão do Claude Code e
  dispararia `SessionEnd` (recursão) e `PostToolUse` (contador falso). A variável
  `HARNESS_MEMORIA_NARRANDO=1` marca o filho, e `_comum.narrando()` faz os hooks quentes
  saírem cedo.
- **Estado no temp do sistema**, não no repo nem em `${CLAUDE_PLUGIN_DATA}`: não exige
  entrada de `.gitignore` no consumidor, não depende de substituição de variável no
  `hooks.json`, e não vive num caminho que muda a cada atualização do plugin. Estado que se
  perde num reboot é aceitável — nenhuma sessão sobrevive a um.
- **Bootstrap de `sys.path` repetido nos seis scripts.** Não é descuido: `_comum.py` importa
  `..config`, então precisaria do path já resolvido para ser importado. O comentário no fim
  de `_comum.py` registra isso, para que ninguém "limpe" a duplicação. O bootstrap inteiro
  (path + import) agora vive DENTRO do `try/except Exception` de módulo em todos os seis —
  antes só o corpo de `main()` tinha rede, e um `src/` inconsistente (erro de sintaxe num
  `git pull` no meio) fazia os hooks quentes saírem com `rc=1` e traceback cru, sem nunca
  imprimir a mensagem rotulada desenhada para esse caso.
- **Pré-gate em cinco dos seis hooks** (`guardar`, `reafirmar`, `formatar`, `session_start`,
  `pre_compact`). `hooks/_leve.py`
  decide "este projeto adotou o harness?" com dois `os.path.exists` (0,05 ms), ANTES de
  importar `config`/`diario` (85,6 ms). Num projeto SEM `.claude/harness.json`, medido p25 de
  n=40: guardar Write 147,5→56,8 ms, reafirmar 135,4→49,5 ms, formatar 145,4→53,9 ms — uma
  sessão longa de 320 processos cai de 45,9 s para 17,1 s de bloqueio parado, contra um piso
  teórico de interpretador nu de 14,4 s. `session_end` é o único fora, e por medição: lá o
  pré-gate economiza ~88 ms UMA vez por sessão, no instante em que o usuário já saiu, contra
  os 440 processos por sessão que justificaram os outros — e entraria com as duas guardas
  (`__main__` e `--autoteste`) que cada hook pré-gateado carrega.

---

## 6. As invariantes do mecanismo

### 6.1 O gate — e sua assimetria deliberada

**Todo hook é inerte num projeto sem `.claude/harness.json`.** O gate não está no
`hooks.json`; está em `config.carregar()`, que devolve `None` (`src/harness_memoria/config.py:265`).
É isso que permite habilitar o plugin no nível do **usuário** sem que ele crie `docs/diario/`
em todo repositório aberto, e sem que a política de um projeto vaze para dentro de outro.

A consequência é deliberada e o README a assume: **nem as guardas universais (`.env`,
`--no-verify` e `git add --force`) valem sem opt-in.** São TRÊS — por muito tempo os lugares
que as listavam (README, `template/harness.json`, o docstring de `guardar.py`) citavam só
as duas primeiras, e a não anunciada é justamente a que mais surpreende: `git add -f` tem
uso legítimo para um humano. Negar uma tool call num repositório que nunca pediu o harness é
surpresa, e surpresa em bloqueio queima a confiança no mecanismo inteiro.

A auditoria faz **o oposto**: sem config, ela **reprova**
(`src/harness_memoria/auditar/__main__.py`). Quem a roda pediu por ela, e um passo de CI
verde que não auditou nada é o pior resultado possível para um cheque.

E há um terceiro estado, distinto dos dois: **config presente e inválida grita** no stderr e
desiste (`_comum.contexto`). Ausente é silêncio; inválida é ruído — porque alguém quis
habilitar e merece saber por que não funcionou. A validação de "config presente" agora cobre
três níveis: chave desconhecida no TOPO, chave desconhecida DENTRO de cada seção, e chave
**desconhecida ou FALTANTE** dentro de cada regra de `guardas` (`CHAVES_OBRIGATORIAS_DE_REGRA`
em `config.py`, verificada por `auditar_guardas` — não por `carregar()`, porque lançar na
leitura deixaria os seis hooks inertes num upgrade de plugin cuja config antiga não declarava
a chave nova; reprovar o build é proporcional, desligar o harness sem aviso não é).

O modo de falha mais perigoso desse desenho é o próprio gate sumir de um checkout novo. Foi
o que aconteceu na primeira instalação real (o `.gitignore` do consumidor era `.claude/*`
com exceções nomeadas uma a uma, e `harness.json` não estava entre elas): em disco o arquivo
existia, a auditoria passava, e no runner do CI os seis hooks ficariam silenciosamente
inertes. `auditar_config_versionada` (`src/harness_memoria/auditar/__init__.py:663`) roda
`git check-ignore` para fechar exatamente esse buraco.

Um segundo modo de falha, do mesmo formato mas fora do JSON: os hooks só rodam se o nome
`python` resolver no PATH — nenhum registro usa `python3`, e nada no repositório declarava
esse pré-requisito até esta análise (`grep -rn python3` dava zero ocorrências). Em macOS
≥ 12.3 e Debian/Ubuntu sem `python-is-python3` o resultado é o mesmo do gate fechado: saída
vazia, nenhuma guarda agindo, e nenhum sinal de qual dos dois é o motivo. O README documenta
o pré-requisito por escrito; aqui fica o registro de que é um segundo caminho para o mesmo
sintoma, e que o job `autotestes` do CI não pode detectar sua ausência porque
`actions/setup-python` sempre fabrica o nome no runner.

### 6.2 As invioláveis são **extraídas**, nunca copiadas

Contrato único, e é uma convenção de **escrita**, verificável por máquina:

> A primeira frase de cada item da seção de invioláveis **é** a regra.

```markdown
## Regras invioláveis

**NUNCA**

- Enviar `aluno.nome` — ou qualquer PII — para o LLM. O nome é re-anexado por Python…
  └───────────────── vira a reafirmação ─────────────────┘ └── fica só no CLAUDE.md
```

Refinamentos, cada um vindo de um caso real (`src/harness_memoria/config.py:503`):

- **negrito inicial ganha da primeira frase** (forma numerada: `1. **Nunca escreva no
  Pipedrive.** Detalhe…`), desde que tenha mais de 12 caracteres;
- **negrito terminado em `:` é rótulo, não regra** — `**Idempotência do sync:**` sozinho não
  proíbe nada, então entra junto com a frase seguinte;
- **`. ` só termina frase se o caractere seguinte for maiúsculo ou fim do texto** — senão
  `vw_aluno_publico (só anon_id).` partiria a regra no meio;
- **item que estoura o teto NÃO é truncado: reprova na auditoria.** Meia proibição lê como
  permissão;
- **nada dentro de bloco de código conta como seção, marcador ou item** (`_mascara_de_cerca`).
  Sem essa máscara, um CLAUDE.md que documenta o PRÓPRIO formato de invioláveis dentro de um
  bloco ```markdown tinha esse exemplo ganhando da seção real, e um `#` de comentário dentro
  de um bloco ```bash encerrava a seção no meio; a régua é o CommonMark (fecha só com o mesmo
  caractere, não mais curto que a abertura), e cerca aberta e nunca fechada devolve máscara
  toda `False` — perder a seção inteira por um `\`\`\`` esquecido é pior que o defeito que a
  máscara corrige;
- **sub-item de lista é continuação do pai, não item de primeira classe** (`_RECUO_DE_SUB_ITEM`
  = 2 colunas) — um sub-item de recuo raso estava ocupando vaga de proibição real e reafirmando
  um fragmento que, sozinho, não proíbe nada;
- **a mensagem tem teto de itens** (`max_itens`, default 8) e ele é orçamento da MENSAGEM, não
  filtro de leitura: quem audita extrai sem teto (`invioaveis(raiz, replace(cfg,
  max_itens=10**6))`) e reprova quando a seção real tem mais regras do que a reafirmação leva
  — antes desse cheque o 9º item de um CLAUDE.md desaparecia sem sinal algum, e ainda escapava
  do teto por item.

O ganho é que não existe duplicação para divergir. O custo é que o mecanismo passa a depender
de uma heurística de markdown — e a mitigação é `auditar_invioaveis`, que reprova quando a
extração devolve lista vazia, porque *um harness que silenciosamente não reafirma nada é pior
que nenhum: quem o instalou acha que está protegido*.

### 6.3 A fonte de verdade do índice de ADR são os **arquivos**

Mudança explícita em relação ao original, documentada em `src/harness_memoria/adr.py`. Antes,
o índice injetado era extraído por regex da **tabela** de `docs/adr/README.md`. Isso amarrava
a reinjeção à ordem das colunas de um markdown escrito à mão — e o segundo projeto sequer
tinha tabela.

Agora o índice vem do frontmatter de cada arquivo. O `README.md` continua obrigatório e
auditado (todo ADR tem de estar listado nele), mas deixou de poder discordar do que chega ao
contexto sem que nada acuse.

### 6.4 Nunca derrubar a sessão

Os seis hooks engolem toda exceção e saem com 0. `guardar.py` é explícito ao ponto de
imprimir *"hook falhou, liberando por segurança"*. É uma escolha de disponibilidade sobre
segurança, e o comentário do módulo a assume: um harness de memória que quebra o trabalho
custa mais do que entrega.

A rede cobre mais hoje do que cobria: o `try/except Exception` que implementa isto só
começava no `main()`, e o `sys.path.insert` + `from harness_memoria...` do topo do arquivo
ficavam FORA dela — a única linha sem rede em cada hook. Reproduzido antes da correção: um
erro de sintaxe no fim de `config.py` (o que um `git pull` no meio, ou um interpretador
incompatível, produzem) fazia os três hooks quentes saírem com `rc=1`, stdout vazio e
traceback cru no stderr — a mensagem `[hook] pacote não importável, liberando por segurança`
nunca chegava a ser impressa, porque o código que a imprimiria já tinha morrido. Agora o
bootstrap inteiro vive dentro do `try`, com uma flag de módulo (`_ERRO_DE_BOOTSTRAP`) que o
`main()` verifica antes de qualquer outra coisa.

O auditor tem a política inversa e igualmente explícita: um check que explode **não** passa
como verde — vira falha nomeada (`rodar`, `src/harness_memoria/auditar/__init__.py`), para
não esconder o resultado dos outros nem fingir aprovação. `pre_compact.py` é a única exceção
consciente a "nunca sair diferente de 0": `exit 2` em `PreCompact` bloqueia a compactação na
plataforma instalada, então este hook não tem NENHUM caminho de código que produza um código
de saída diferente de 0 — o oposto do que os outros cinco fariam se pudessem, mas aqui seria
o modo de falha mais caro possível.

### 6.5 O orçamento do bloco injetado

O bloco do `session_start` não tinha teto próprio, e a plataforma tem: `additionalContext`
tem um limite medido de **10.000 chars** (não documentado como constante, só observado — em
14 de 40 sessões de um consumidor real o bloco foi substituído por um preview truncado). O
bloco natural, sem orçamento, media 15.485 ch num consumidor real de 53 ADRs e 12.911 ch em
outro de 22-23 ADRs (reproduzidos em corpus sintético de 60 e 30 ADRs) — 55% e 29%
acima do teto. `TETO_PLATAFORMA_CHARS = 10_000` em `session_start.py` existe para que o
harness controle o corte, em vez de deixar a plataforma cortar por ele (que corta o bloco
INTEIRO, não uma parte dele).

O corte acontece em duas passadas: a primeira monta o bloco no tamanho natural; se ele já
cabe, é isso — zero corte, zero anúncio. Se não cabe, uma segunda passada reparte o espaço
entre três peças, em ORDEM DE GRANULARIDADE, do corte mais barato ao mais caro:

1. **Índice de ADR** — cede uma LINHA por vez, até um piso de `PISO_DO_INDICE_CHARS = 3.500`.
   É o corte mais barato: `docs/adr/README.md` já é o índice completo, e o bloco que corta se
   anuncia `índice PARCIAL` com a contagem real e o caminho do arquivo.
2. **Digest de becos** — cede um ITEM por vez, respeitando `teto_becos_chars` (4.500 ch por
   padrão), anunciando `{n} de {total}` e apontando para `docs/diario/` e
   `docs/diario/arquivo/`.
3. **Última entrada do diário** — cede por SEÇÃO INTEIRA (nunca corta texto no meio), por
   `prioridade_secoes`. É a peça que cai em degrau: perder só 70 ch de cota pode derrubar a
   entrada de 3.913 para 649 ch, porque a próxima seção inteira sai. Por isso ela cede por
   último — reordenar para "proporcional" custaria contexto não entregue a ninguém.

Medido depois do orçamento: o mesmo formato de corpus (30/60/120 ADRs sintéticos) fecha em
9.831–9.908 ch, sempre dentro do teto, com `conferir_fidelidade` devolvendo zero falhas —
nenhum item de beco da última entrada some sem aparecer em texto OU no digest, e o índice
cortado sempre se anuncia `PARCIAL` com o total real.

O `SubagentStart` recebe um bloco à parte, REDUZIDO por desenho (`reduzido=True` em
`montar()`): só invioláveis + digest de becos, com teto próprio `TETO_SUBAGENTE_CHARS =
6_000` — sem índice de ADR nem entrada de diário, porque o subagente escreve mais do que lê
e não herdou o contexto da sessão principal. O laço que ajusta o digest para o teto reduzido
descontou um detalhe: `teto_becos_chars` limita a soma do TEXTO dos itens, não a
renderização (`- ` + `\n` por item, 3 ch a mais cada) — sem o ajuste, um bloco de 11 itens
fechava em 6.031 ch para um teto de 6.000.

### 6.6 O piso do `SessionEnd`, e a narrativa como opt-in

Até esta análise, o hook `SessionEnd` tentava narrar a sessão por `claude -p` **sempre**, com
o piso determinístico como rede de segurança — e a rede vinha DEPOIS da tentativa, num hook
com 1.500 ms de orçamento na plataforma, enquanto `claude -p` mede 22–34 s. O resultado
medido em três projetos consumidores: **zero entradas com o rodapé do hook**. O piso nunca
chegava a rodar porque o processo morria antes, matado pelo timeout da plataforma — que
ignora o valor declarado em `hooks.json` (`"timeout": 160` não levanta nada para hook de
plugin; o valor que a plataforma lê é a variável de ambiente
`CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`, que não existia em nenhuma config real).

A correção inverte a ordem: **o piso é o caminho padrão, e a narrativa é opt-in.** No caminho
default, o hook grava fatos determinísticos — arquivos escritos, comandos, diffstat, ADRs
tocados — em p25 de 421 ms, sem gerar um processo `claude` sequer. A narrativa só é tentada
quando `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` está setada acima de ~21.000 ms no ambiente
do consumidor (`.claude/settings.json`); abaixo disso o hook nem gera o filho, porque o
estouro cairia de qualquer forma no piso — a aritmética do orçamento é `orçamento_do_filho =
orçamento_total − RESERVA_DO_PISO_MS`, garantindo que sobre tempo para o append mesmo se o
filho estourar.

Três consequências deste desenho, cada uma corrigindo algo que o comportamento antigo (nunca
gravar nada) escondia:

- **Todos os CINCO motivos do enum de `SessionEnd` agora registram**, não quatro. O enum
  real, extraído do binário instalado, é `["clear", "resume", "logout",
  "prompt_input_exit", "other"]` — `resume` faltava, e é metade dos encerramentos
  *in-session* (troca de sessão sem sair do processo).
- **A guarda de "houve mudança de estado" ficou mais barata de satisfazer**: `arquivos_escritos
  OR git['diffstat']`, não só o transcript. Um risco aceito conscientemente: `git diff --stat`
  persiste entre sessões enquanto o transcript reseta, então dois `/clear` seguidos num
  worktree com trabalho não commitado podem gravar DUAS entradas (a segunda dizendo "0
  arquivo(s) escrito(s)"). É preferível a zero entradas, e a alternativa óbvia (exigir pelo
  menos um tool call no transcript) contradiz o caso que o piso existe para cobrir.
- **`/encerrar-sessao` deixou de competir com o piso.** Como o hook agora grava SEMPRE (no
  caminho default), a sessão em que alguém roda a skill terminaria com DUAS entradas — a
  automática por cima da narrada. `_ja_registrada` dispensa o piso quando o transcript mostra
  escrita num arquivo de mês do diário na própria sessão: é exatamente "o piso não compete com
  escolha deliberada", que a skill já prometia por escrito antes de o piso funcionar de
  verdade.

`/encerrar-sessao` continua sendo o caminho recomendado para uma narrativa de qualidade —
roda DENTRO da sessão, com contexto completo e sem o orçamento apertado de um hook de
plataforma. O `SessionEnd` narrado é para quem prefere pagar 15–30 s na saída de toda sessão
em troca de nunca ter de lembrar de rodar a skill.

---

## 7. Os princípios de projeto

Estes são o conteúdo real da "visão". Cada um aparece repetido, quase palavra por palavra, em
vários pontos do código — o que indica que são critérios de decisão, não frases de efeito.

**1. Ponteiro velho é pior que ponteiro nenhum.**
Direto de `arXiv:2404.03114`. Aparece em: referência a ADR morto, mapa caminho→ADR, ponteiro
do diário no `CLAUDE.md`, `skill_de_encerramento` inexistente, script citado e renomeado. É o
princípio que mais gera cheques.

**2. Meia proibição lê como permissão.**
Nada que seja regra é truncado. Inviolável longa reprova; seção `## Regra` acima do teto
reprova. Truncar produziria uma proibição pela metade, que é pior que nenhuma.

**3. Truncar avisando cria gatilho de leitura; truncar calado remove o único sinal de que
falta algo.**
Um corte fixo em 20 ADRs escondia 9 dos 29 do projeto de origem — e entre os escondidos
estava justamente o que substituía a política de PII. Hoje `limite_indice` é `None` por
padrão, o bloco se anuncia `índice PARCIAL` quando corta, e `anunciar_corte` diz quantos
faltam e onde estão. O mesmo vale para o recorte da entrada do diário (`recortar_entrada`
nomeia as seções omitidas) e para o digest de becos (`{n} de {total}`).

**4. Descartar seção inteira, por prioridade, em vez de cortar texto.**
`ConfigDiario.prioridade_secoes` — "O que foi feito" sai **primeiro** porque é a única seção
reconstruível do `git log`. "Tentativas descartadas" sai por último, porque é a de maior
retorno.

**5. Aviso que ninguém lê equivale a cheque inexistente.**
`dia_limite_rotacao: 3` — a rotação pendente do diário é aviso até o dia 3 e **reprova** a
partir dele. A justificativa registrada: um aviso pendente por semanas foi o que deixou o
ponteiro do `CLAUDE.md` apontando para um arquivo cujo head já estava três arquivos atrás.

**6. Falso positivo é pior que cheque ausente — ele ensina a ignorar o auditor.**
Registrado em `_SCRIPT_CITADO`, depois que `python apps/web/scripts/gen-pwa-icons.py`
reprovou porque o `\b` descartava o prefixo do diretório. O commit `1c61df3` existe só para
isso.

**7. Config que mente reprova.**
Chave desconhecida no topo, dentro de seção **e dentro de cada regra de guarda** faz
`carregar()` lançar. Nasceu de um caso real: `permitido_em` entrou numa regra de `comandos` e
ficou meses sem efeito, porque o dicionário era livre e o hook não lia a chave — a config
afirmava uma exceção que não existia. Complemento: qualquer chave iniciada por `$` é anotação
(`_e_anotacao`), porque JSON não tem comentário e uma única `$comment` por seção não basta.
A metade que falta — chave OBRIGATÓRIA ausente numa regra (`padrao`/`regex`/`exemplo`) — não
lança em `carregar()`: vive em `auditar_guardas`, porque lançar na leitura desligaria os
seis hooks inteiros num upgrade de plugin cuja config antiga não previa o campo novo.
Reprovar o build é o preço proporcional; apagar a proteção sem aviso não é.

**8. Convenção e default no lugar de uma camada global de política.**
Commit `ce6dd4a`, o mais instrutivo do repositório. A pergunta era "com o plugin global, o
que governa os projetos?". Antes de criar uma camada global, foi **medido** quanto os dois
projetos configurados de fato repetiam: de ~13 campos, **um** era idêntico. Uma camada global
para um campo e meio custaria "de onde vem esse valor" ganhar três fontes — e política de
fora do projeto voltaria a poder agir dentro dele, que é o vazamento exato que o gate fecha.
Solução: `checks_do_projeto` é **descoberto** em `scripts/guardas_do_projeto.py` quando não
declarado, e `rodape` ganhou default. A distinção fina: *descoberto-e-ausente é silêncio;
declarado-e-ausente reprova*, porque aí alguém escreveu o caminho e o cheque não rodou.

**9. Convenção nova vale para frente; corpus antigo fica como está.**
`adr.primeiro_com_regra` e `adr.primeiro_com_template` são limiares numéricos, não flags. A
razão é dupla: corpo de ADR aceito é imutável *(e a regra vale também para quem a
implementa)*, e exigir tudo de todos reprovaria 21 de 23 ADRs num consumidor real — forçando
ou reescrita de história ou invenção de seções em ADRs que genuinamente nunca discutiram
alternativas. **O limiar é o que permite ter convenção sem falsificar história.**

**10. Derivar a convenção do artefato que já a declara.**
`auditar_conformidade_com_template` não tem lista de seções em config: ele lê o `template.md`
**do projeto**. O template *é* a declaração da convenção, então derivar dele custa zero
configuração e não apodrece — mexer no template muda o que é exigido, que é exatamente o
comportamento desejado. O mesmo raciocínio aparece no CI, onde o ADR de exemplo é **gerado a
partir do próprio template** em vez de escrito à mão (commit `e889dbc`).

**11. Proibição absoluta é hook, não frase.**
Regra que roda fora do raciocínio do modelo não decai ao longo da sessão. É a razão de
`guardar.py` existir em vez de mais uma linha no `CLAUDE.md`. Simetricamente: formatação é
responsabilidade do formatador, não do `CLAUDE.md` — regra de estilo em arquivo de instrução
gasta contexto para dizer o que uma ferramenta já garante.

**12. Semântica conservadora nas exceções.**
`permitido_em` exige que **todo** caminho citado esteja sob um prefixo permitido, não "algum"
— liberar pelo primeiro token permitido faria a exceção virar porta. O commit `4135ce8`
refina isso: a conta olha `m.group(0)` de cada casamento, não a linha inteira, porque comando
composto é a regra e o `cd` do começo da linha contava como caminho citado, anulando toda
exceção. Nota metodológica do próprio commit: *"os testes da versão anterior passavam porque
usavam comandos nus, sem `cd` — exatamente a forma que um agente nunca escreve."*

**13. Piso garantido: o LLM pode falhar, o registro não.**
`session_end` grava o piso SEMPRE, sem depender de LLM nenhum (§6.6) — o piso deixou de ser
a rede que a narrativa cai nela e passou a ser o caminho default. Quando a narrativa está
habilitada (opt-in), ela ainda cai para `entrada_deterministica` em qualquer falha
(executável ausente, timeout, exit ≠ 0, resposta fora de formato, resposta curta demais),
montada só de fatos, **declarando o motivo da queda dentro da própria entrada**. "O LLM
falhou" nunca deve significar "a sessão não deixou rastro" — e agora "o LLM nem foi chamado"
também não significa isso.

**14. O diário registra mudança de estado, não presença.**
Sem escrita, sem comando e sem `diffstat` do worktree, não há entrada. E o autoteste do
`session_end` deliberadamente **não escreve** — o diário é append-only, e rodá-lo sujaria o
mês com uma entrada de zero arquivo, que a própria regra do diário proíbe.

**15. Todo número anda com a medição que o produziu.**
`intervalo_escritas: 15` vem com "põe o custo amortizado de ~500 chars em ~34 chars por
escrita". `line-length = 100` vem com "prosa pt-BR mede ~15% mais que a mesma frase em
inglês; com 90, a maioria dos apontamentos era comentário estourando por 1 a 5 caracteres, o
que empurra para encurtar a explicação em vez de o código". O comentário não descreve o
código — ele carrega a evidência, porque *o número sem a medição que o produziu é o primeiro
a ser mexido por engano*.

**16. Duas coisas competindo pelo mesmo alvo, sem nada acusar, é um defeito.**
`diario.skill_de_encerramento` faz a skill `/encerrar-sessao` **ceder a vez** a um comando do
projeto que faça mais. O raciocínio: duas skills concorrentes pelo mesmo arquivo de diário
significam que chamar a errada produz "uma entrada pior, no lugar certo" — e nada acusa. O
hook `SessionEnd` continua valendo, porque *ele é o piso, não um concorrente*. O mesmo
raciocínio se aplica a ele próprio depois de §6.6: `_ja_registrada` faz o piso ceder a vez
quando a sessão já gravou uma entrada narrada, para as duas gravações não competirem.

**17. Simetria entre seções irmãs é parte da correção, não estilo.**
`guardas.caminhos` normaliza case (`fnmatch(nome.lower(), padrao.lower())`);
`guardas.comandos` não normalizava, e uma regex de projeto escrita em minúscula
simplesmente não casava `Set-Content .env`. A correção (`re.IGNORECASE` nas regras de
`comandos`) não foi "adicionar uma feature" — foi fechar uma assimetria entre duas seções
que deveriam se comportar igual e não se comportavam. O mesmo instinto vale para
pré-requisito de plataforma: `guardas.caminhos` e `guardas.comandos` sempre presumiram
`python` no PATH sem dizer isso em lugar nenhum — não é assimetria entre seções, mas é a
mesma classe de premissa não escrita que quebra em silêncio.

---

## 8. Os contratos com o projeto consumidor

O mecanismo é genérico, mas não é livre de premissas. Adotar o harness é aceitar seis
contratos — todos verificados por máquina, o que é o que os torna aceitáveis:

| Contrato                                                          | Verificado por                                                        |
| ----------------------------------------------------------------- | --------------------------------------------------------------------- |
| a primeira frase de cada inviolável **é** a regra, cabe em 150 chars, e a seção tem no máximo 8 itens | `auditar_invioaveis`                              |
| o diário é **cronológico** (entrada nova no fim)                   | `auditar_ordem_do_diario`                                             |
| toda entrada do diário abre com `## AAAA-MM-DD` — cabeçalho `## ` sem data não é fronteira de entrada | `diario._FRONTEIRA_ENTRADA`                        |
| a seção de becos se chama exatamente `### Tentativas descartadas`  | `diario.SECAO_BECOS` — nome fixo, contrato entre quem escreve e quem lê |
| a lição de um beco vai **depois** de `**Não repetir:**`, não depois de um ponto dentro do negrito | `diario._resumir_beco` — é a grafia que o digest preserva ao encurtar |
| supersessão e emenda são **bidirecionais** no frontmatter; só `superseded` exige `substituido-por:` (`deprecated` é o status de quem não tem substituto) | `_auditar_supersessao`, `_auditar_emenda`  |
| o `CLAUDE.md` tem a seção `Qual ADR ler` com tabela caminho→ADR    | `auditar_mapa_de_adr_por_caminho`                                     |
| toda regra de `guardas.caminhos`/`guardas.comandos` declara suas chaves obrigatórias (`padrao`/`regex`/`exemplo`) | `auditar_guardas`                                |
| checks do projeto expõem `registrar(ctx)`                          | `rodar()`                                                             |

O par **`emenda` / `emendado-por`** é uma contribuição conceitual própria e vale nomear: é o
meio-termo entre "vale inteiro" e "não siga". Quando um ADR novo muda **uma** das decisões de
um ADR que tem várias, marcar o antigo como `superseded` mentiria sobre as outras; não marcar
nada deixaria quem lê a decisão revogada achando que ela vale — o dano de ponteiro velho na
pior forma, porque a parte errada fica cercada de partes certas.

---

## 9. Distribuição: dois canais, um código

**Plugin** (marketplace `harness-casso`, plugin `harness-memoria`) entrega hooks e skills
para a sessão. **Pacote Python** (`git+https://…` — o repositório é público; `git+ssh` só
faz sentido se ele virar privado) entrega o motor de auditoria para o CI. A receita de
instalação precisa de `uv run` na frente do `python -m harness_memoria.auditar`: `uv add
--dev` põe o pacote dentro do `.venv` do consumidor, e o `python` do PATH não o enxerga —
reproduzido, `ModuleNotFoundError` sem `uv run`, funciona com ele.

A razão de serem dois: `${CLAUDE_PLUGIN_ROOT}` é efêmero e muda a cada atualização do plugin,
então o CI não pode depender dele. É o mesmo código consumido de duas formas — não são duas
implementações.

**Versionamento por SHA de commit, deliberadamente sem `version`** nem no `plugin.json` nem
no `marketplace.json`. Um número exigiria bump a cada correção para que ela chegasse a quem
já instalou; sem ele, o `plugin update` traz toda mudança nova e o CI dos consumidores pega o
commit sozinho. O job `manifestos` do CI **reprova se alguém adicionar `version`** — a
decisão está codificada, não só documentada.

Descoberta operacional registrada no README (medida em 2026-08-04): **commit é o que publica,
inclusive na fonte `directory`.** Mesmo apontando o marketplace para a pasta local, o
`install` copia para o cache por SHA; edição na árvore de trabalho não chega lá nem depois de
`marketplace update`. Quem quer iterar roda o código direto por `PYTHONPATH`.

Custo medido (`claude plugin details harness-memoria`, 2026-09-08): **~491 tokens sempre
ligados** (as 4 descrições de skill, 1.072 chars — a razão implícita, ~2,2 ch/token, é a que
este documento usa para toda conversão char→token, e não a estimativa genérica de 3,5
usada em análises anteriores). "Hooks (6) — no model context cost" no mesmo relatório é
verdade só para o REGISTRO: rodar o CÓDIGO de um hook não custa tokens, mas a SAÍDA de três
deles (`session_start`, `reafirmar`, `guardar`) entra no contexto como `additionalContext` —
ver §6.5 para o orçamento do maior deles. "Os hooks não custam contexto" é a frase que
enganava um leitor do README antes desta correção.

---

## 10. Como o repositório se prova

Três jobs de CI, cada um cobrindo uma classe distinta de regressão:

1. **`testes`** — pytest + ruff, em **matriz Windows e Linux**. Não é zelo: os pontos de
   divergência são reais e nomeados no YAML — `shutil.which` e o `.cmd`/`.exe` dos
   formatadores, o `os.open` do lock, e o `reconfigure` de stdout que existe por causa do
   cp1252.
2. **`autotestes`** — monta um projeto consumidor sintético a partir de `template/` e roda os
   seis hooks com `--autoteste`, mais a auditoria. Usa `python` puro, sem venv, que é como o
   Claude Code os executa: é este job que pega um import de terceiro entrando por engano —
   mas não pega a AUSÊNCIA do nome `python` no PATH, porque `actions/setup-python` sempre o
   fabrica no runner (ver §6.1). Inclui um cheque explícito de **gate**: os seis hooks contra
   um projeto sem `harness.json` não podem produzir saída nenhuma nem criar `docs/`.
3. **`manifestos`** — valida coerência entre `plugin.json`, `marketplace.json` e `hooks.json`:
   nomes batem, todo caminho de hook existe, são exatamente 7 registros, toda pasta de skill
   tem `SKILL.md`, e ninguém declarou `version`.

O autoteste do `session_start` é o mais interessante: ele confere **fidelidade**, não que o
hook roda, e faz isso para os DOIS blocos que ele produz (completo e reduzido, na mesma
chamada). Reprova se o bloco ultrapassar o teto de 10.000 ch da plataforma, se o índice
chegar cortado sem se declarar cortado, se um ADR `superseded` aparecer sem apontar
substituto, se o recorte descartar as seções de retomada, se uma inviolável estourar o teto,
ou se um item de beco da última entrada não chegar ao bloco nem em texto nem no digest. Cada
um desses cheques corresponde a um defeito que existiu de verdade.

**Uma lacuna medida, não hipotética: a suíte quase não exercitava os hooks EM PROCESSO.**
Um tracer de cobertura de stdlib (`sys.settrace`, escopado a `src/`) rodando a suíte inteira
mostrava, antes desta passada, 479/1.163 instruções (41,2%) — e os cinco hooks então
existentes em ZERO: `guardar` 0/106, `reafirmar` 0/74, `session_start` 0/70, `session_end`
0/79, `formatar` 0/60, além de `diario.anexar_entrada` 0/7 e `diario._lock.__exit__` 0/2.
A causa é estrutural, não desleixo: o tracer in-process não vê `subprocess`, e é assim que a
suíte historicamente tocava hook — só afirmando AUSÊNCIA de saída num projeto sem config,
nunca uma asserção funcional. "A suíte de 89 casos passa" não provava que uma mudança nesses
431 caminhos era segura; provava só que ela não quebrava o que já estava sem teste. Passada
esta rodada de correções, a mesma medição (agora com um tracer que atravessa subprocesso)
reporta 80–95% nos módulos que antes eram zero — `guardar` 87,0%, `reafirmar` 87,1%,
`formatar` 80,6%, `session_start` 87,0%, `session_end` 93,0%, `diario.py` 86,7%, `adr.py`
95,0% — com o caminho de escrita do diário (`anexar_entrada`, `_lock`, `fatos_do_transcript`)
coberto por casos que reproduzem os defeitos reais que a cobertura zero escondia. Fica o
método como nota permanente: **"os testes passam" não é evidência de segurança sobre código
sem cobertura — meça primeiro, e se a mudança toca um caminho descoberto, escreva o teste que
o cobre antes de confiar na mudança.**

As fixtures são **sintéticas de propósito** (`tests/conftest.py`): *"um teste que depende de um
repositório real passa a falhar quando aquele repositório muda por razões que nada têm a ver
com o harness — e a suíte que falha por motivo alheio é a suíte que se aprende a ignorar."*
Mesmo raciocínio do princípio 6.

Estado atual verificado nesta análise: **364 casos de teste passando**, contra os 89 da
versão anterior desta análise — o crescimento é majoritariamente cobertura nova dos seis
hooks e do caminho de escrita do diário, não funcionalidade nova.

---

## 11. Tensões, limites e riscos conhecidos

Análise crítica. Nada aqui é bug — são custos aceitos, e vale que estejam nomeados.

**1. As guardas falham abertas.** `guardar.py` engole exceção e libera. É coerente com "nunca
derrubar a sessão", mas significa que uma regex mal formada ou um erro inesperado degradam a
guarda **em silêncio para o usuário** (o aviso vai para stderr). Uma guarda que pode parar de
guardar sem avisar é categoria diferente de um hook de contexto que pode parar de injetar.
Mitigação existente: o autoteste do `guardar` exercita um caso positivo e um negativo por
regra configurada — *"guarda configurada e nunca exercitada é guarda que ninguém sabe se
funciona"*.

**2. (Resolvida nesta rodada) O repositório passou a se auto-hospedar.** Até esta análise não
havia `CLAUDE.md`, `.claude/harness.json`, `docs/adr/` nem `docs/diario/` aqui — o rigor
documental que o harness impõe aos consumidores era substituído, no próprio repo, por commit
messages excepcionalmente densas (o `ce6dd4a` é o exemplo citado por sete agentes de
diagnóstico diferentes). A tensão era real: o mecanismo que o repositório vende para outros —
reinjeção — não atuava sobre ele mesmo, e o job `autotestes` (que monta um consumidor
sintético a partir de `template/`) provava só o mecanismo, nunca a disciplina. `ADR-0001` em
`docs/adr/` registra a decisão de fechar essa lacuna; o histórico anterior a ela — os 14
commits densos — continua sendo a fonte da análise deste documento, não é retrofitado em ADR.

**3. (Reduzida nesta rodada) Dependência de `claude -p` no `SessionEnd`, agora opt-in.** Até
esta análise o hook tentava narrar por LLM em TODA sessão, com o piso como rede — e a rede
vinha depois da tentativa, dentro de um orçamento de 1.500 ms que a plataforma dá a hook de
plugin (o `"timeout": 160` do `hooks.json` nunca levantou nada). Medido: zero entradas com o
rodapé do hook em três projetos consumidores reais, porque o processo `claude -p` (22–34 s)
sempre estourava o orçamento antes do piso rodar. Agora o piso é o caminho default e a
narrativa só é tentada com opt-in explícito (§6.6) — a tensão que sobra é menor e aceita
conscientemente: quem habilita a narrativa paga 15–30 s a mais na saída de TODA sessão, não
só nas que valeriam a pena.

**4. Acoplamento ao formato do transcript.** `fatos_do_transcript` varre o JSONL
recursivamente procurando blocos `tool_use` — deliberadamente agnóstico ao aninhamento, e o
docstring diz por quê. Ainda assim, é uma superfície interna do Claude Code, e o `erro_parse`
entra como aviso dentro da entrada, não como falha.

**5. A extração das invioláveis é parsing de markdown escrito à mão.** Robusta e bem testada
(cobre prefixo de título, sub-bloco, rótulo com `:`, ponto no meio de expressão, cerca de
código, sub-item de lista, teto de itens), mas o contrato é uma convenção de escrita humana.
A defesa é a auditoria reprovar o silêncio — o que converte "extração falhou" em "build
vermelho" em vez de "reafirmação vazia". Um caso residual não coberto: `_mascara_de_cerca`
supõe cerca fora de item de lista; uma cerca INDENTADA dentro de um item de lista tem o
conteúdo corretamente ignorado, mas não fecha o item — não observado em corpus real, e sem
teste porque não há corpus que o produza ainda.

**5.1 Pré-requisitos de plataforma nunca escritos, dois deles.** `"command": "python"` em
todo `hooks.json` presume um nome que não existe em macOS ≥ 12.3 nem em Debian/Ubuntu sem
`python-is-python3` — e o resultado é indistinguível do gate fechado (§6.1). `uv add --dev`
seguido de `python -m harness_memoria.auditar` (sem `uv run`) presume um interpretador que
enxerga o `.venv` do consumidor — e o resultado é `ModuleNotFoundError` na primeira execução
do CI que a própria skill de instalação manda criar. Os dois eram, até esta análise, as
receitas documentadas; agora o README e as skills escrevem o pré-requisito e a receita
corrigida, mas o RISCO de premissa de plataforma não escrita — a mesma classe de defeito —
não desaparece por completo: é o preço de "zero dependências", que também significa "zero
camada de abstração sobre o interpretador".

**6. O harness impõe uma cultura documental, não só um mecanismo.** MADR adaptado ao pt-BR,
`docs/adr/README.md` com tabela e lista "Por domínio", `CLAUDE.md` com teto de 150 linhas e
seção "Qual ADR ler" **obrigatória por default**. Os limiares (`primeiro_com_template`,
`primeiro_com_regra`, `secao_plano: null`, `conformidade_com_template: false`) tornam a adoção
gradual possível, mas o formato-alvo é opinativo. Isso é intencional; só não é neutro.

**7. Detalhes menores.** (Corrigido) O digest de becos deduplicava por `item.lower()[:60]` —
20% do item mediano —, então becos distintos que compartilhassem o prefixo colapsavam; a
chave agora é o item inteiro. `auditar_contagem_de_adr_no_readme` olha só a primeira linha
que casa e retorna, e só no `README.md` da RAIZ do projeto — a mesma contagem escrita em
`docs/adr/README.md` não é auditada, e o índice de fábrica do `template/` evita afirmar uma
garantia que não tem. O contador de escritas vive no temp e não sobrevive a uma limpeza do
sistema — aceito e documentado. O lock do diário espera até 40×0,25 s = 10 s sob disputa
real; num hook de 1.500 ms de orçamento (`SessionEnd`) isso ainda pode perder a entrada — raro
(duas sessões terminando no mesmo instante no mesmo projeto), e não mitigado.

---

## 12. Em uma página

O `harness-memoria` é uma resposta de engenharia a um resultado empírico: **a aderência de um
agente decai por passo dentro da sessão, e nenhum formato de arquivo de instrução corrige
isso.** A resposta tem quatro movimentos:

1. **Reinjetar** o que importa, nos momentos em que importa (início, pós-compactação, a cada
   15 escritas).
2. **Registrar** o que a sessão aprendeu — especialmente os becos sem saída, que são a única
   coisa que nenhum `git log` reconstrói.
3. **Bloquear** deterministicamente o que não pode depender de o modelo lembrar.
4. **Auditar** mecanicamente, porque documentação que mente faz mais dano que documentação
   ausente.

E há uma disciplina única sustentando os quatro: **separar mecanismo de política, e nunca
duplicar o que pode ser extraído.** É essa disciplina que permite um único plugin habilitado
globalmente agir corretamente em N projetos — e é o *gate* de uma linha (`carregar() -> None`)
que garante que ele não aja em nenhum que não pediu.

O repositório vale menos pelo código que pelos critérios de decisão embutidos nele. Os
comentários não explicam o que o código faz; carregam a medição, o incidente e a alternativa
rejeitada que produziram cada escolha. Um leitor que só quisesse os princípios poderia ignorar
as 5.638 linhas e ler apenas os docstrings — e ainda assim sairia com o essencial.

Desde `docs/adr/0001-auto-hospedagem.md`, o repositório aplica essa régua a si mesmo: tem
`CLAUDE.md` com invioláveis, `.claude/harness.json`, `docs/adr/` e `docs/diario/` — a
reinjeção, a reafirmação e a auditoria descritas aqui agora também atuam sobre este próprio
código, não só sobre o que ele produz para outros projetos.

---

*Fontes desta análise: leitura integral de `src/`, `tests/`, `skills/`, `template/`,
`hooks/hooks.json`, `.github/workflows/ci.yml`, `pyproject.toml`, `CLAUDE.md`, `docs/adr/` e
`docs/diario/` deste próprio repositório, e dos 14 commits que sustentam o histórico anterior
à passada de otimização de 2026-09. Revisão de 2026-09-08: atualizada depois de uma passada
de diagnóstico e correção com 16 agentes — hooks `PreCompact` e `SubagentStart` novos, o
piso do `SessionEnd` corrigido para gravar sempre, o orçamento do bloco do `session_start`,
o pré-gate de latência, e a auto-hospedagem. Suíte executada localmente durante esta revisão:
364 casos, todos passando (`.venv/Scripts/python.exe -m pytest`, **sem `-q`** — o `addopts`
do `pyproject.toml` já o tem, e `-q -q` suprime o sumário, deixando só os pontinhos);
`ruff check .` e `ruff format --check .` limpos.*
