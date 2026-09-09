---
name: auditar-docs
description: Rodar a auditoria da documentação e das fronteiras estruturais do projeto, e corrigir o que falhar. Use antes de abrir PR, depois de criar ou mudar status de ADR, ao virar o mês (rotação do diário), ou quando o CI reprovar na etapa de auditoria.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Auditar a documentação

```bash
uv run python -m harness_memoria.auditar
```

(`uv run`, não `python` nu: se o pacote foi instalado com `uv add --dev`, ele vive no
`.venv` do projeto, e o `python` do PATH não o enxerga — `uv run` resolve o interpretador
certo. Onde o projeto não usa `uv`, ative o venv e rode `python -m harness_memoria.auditar`.)

Saída 0 = aprovado. Aviso não reprova o build; **falha reprova**. Corrija as falhas, não as
silencie.

## Como corrigir as falhas mais comuns

A lista abaixo cobre as mensagens mais frequentes, não **todas** — o auditor tem dezenas de
cheques. Se você bater numa mensagem que não está aqui, leia o texto dela com atenção: cada
uma foi escrita para dizer o que fazer, não só o que está errado. Se mesmo assim parecer
errada, é a seção "Depois de corrigir" abaixo que se aplica — não contorne, discuta.

**`não está no índice`** — o ADR existe e o `README.md` da pasta não o lista. Adicione a
linha na tabela e, se houver, na lista "Por domínio".

**`status '...' inválido`** — o frontmatter aceita `proposed`, `accepted`, `implemented`,
`superseded`, `deprecated`. O vocabulário pt-BR (`aceito`, `implementado`, …) é normalizado
automaticamente, então este erro significa que o valor não é nenhum dos dois.

**`supersessão unilateral`** — os dois lados são obrigatórios. O novo declara
`substitui: [ADR-NNNN]`; o antigo declara `substituido-por: [ADR-MMMM]` **e**
`status: superseded`.

**`está superseded e não declara substituido-por: ... Se nada o substituiu, o status é
deprecated`** — ADR morto sem substituto deixa o índice injetado no início da sessão sem ter
o que apontar. Isto só se aplica a `superseded`: se a decisão simplesmente não vale mais e
NADA a substituiu, o status certo é `deprecated`, com o motivo no CORPO do ADR — `deprecated`
sem `substituido-por:` **passa** na auditoria por desenho.

**`emenda unilateral: ADR-NNNN declara emenda/emendado-por: [...], mas ADR-MMMM não declara
o par`** — os dois lados de uma emenda (mudar UMA decisão de um ADR com várias, sem revogar
as outras) são obrigatórios, como na supersessão. Adicione o campo que falta no ADR antigo
ou no novo. Ver `/novo-adr` para quando usar emenda em vez de supersessão.

**`manda seguir ADR-NNNN, que está superseded`** — um arquivo que instrui um agente aponta
para decisão morta. Troque pelo substituto. Se a menção é histórica, escreva na própria
linha que houve substituição (a palavra "substituiu" na vizinhança libera o cheque) — é ela
que avisa o leitor, não a mera presença do número novo em outro lugar do arquivo.

**`frontmatter sem [...]` / `sem a(s) seção(ões) [...] do template.md`** (conformidade com
template) — o ADR não tem todos os campos/seções que `docs/adr/template.md` declara. Corrija
o ADR (campo extra é permitido; faltar não). Se o corpus é legado e nunca teve convenção
fixa, configure `adr.primeiro_com_template` com o número do primeiro ADR NOVO — não
retrofita os anteriores, e corpo de ADR aceito é imutável.

**`mapa de ADR por caminho: ... não existe`** — o mapa da seção "Qual ADR ler" do CLAUDE.md
apodreceu. Corrija o caminho ou remova a linha. Mapa que apodrece é pior que mapa nenhum.

**`invioláveis: item com N chars`** — a primeira frase de uma inviolável não cabe em uma
linha. Encurte **a primeira frase** no CLAUDE.md; o resto do raciocínio continua no item.
Não trunque na config: só a primeira frase entra na reafirmação, e meia proibição lê como
permissão.

**`a seção de invioláveis tem N itens e a reafirmação leva M`** — a seção tem mais regras do
que `reafirmacao.max_itens` (default 8) leva na mensagem; os itens do fim não são
reafirmados, e o corte não se anuncia sozinho. Tire da seção o que não é proibição absoluta,
ou suba `reafirmacao.max_itens` no `harness.json` — mas isso alonga a mensagem em TODA
escrita, então prefira reduzir a seção.

**`não achei nenhuma inviolável`** — a seção nomeada em `reafirmacao.secao` não existe ou não
tem lista. Sem ela a reafirmação intra-sessão e o aviso pós-compactação ficam **mudos**, o
que é pior que não ter o harness: quem o instalou acha que está protegido.

**`entradas fora de ordem cronológica`** — o diário está do mais recente para o mais antigo.
A reinjeção pega o último bloco `## AAAA-MM-DD` do arquivo, então nessa ordem ela injeta a
entrada mais velha em toda sessão. Inverta a ordem das entradas.

**`cabeçalho '## ...' sem data`** — uma linha `## algo` no diário que não é `## AAAA-MM-DD`.
Sem a data ela não é fronteira de entrada para o mecanismo, e o texto entra colado na
entrada anterior em silêncio. Corrija o cabeçalho para `## AAAA-MM-DD — título`, ou, se é um
exemplo de formato, ponha-o dentro de uma cerca de código (` ``` `) — dentro de cerca este
cheque não olha.

**`rotação pendente`** — virou o mês. Mova os arquivos do mês anterior para `arquivo/`, crie
o do mês novo a partir de `template/docs/diario/AAAA-MM.md` (renomeado — o cabeçalho já vem
pronto dele), e atualize o ponteiro no CLAUDE.md. A partir do dia `diario.dia_limite_rotacao`
isso deixa de ser aviso e reprova.

**`é o último dos N arquivos do mês e não há próximo sufixo`** — o mês bateu no teto dos 10
arquivos possíveis (`AAAA-MM.md` + os sufixos de desdobramento). Mova os arquivos MAIS
ANTIGOS do mês para `arquivo/` (o digest de becos continua enxergando lá) ou suba
`diario.teto_linhas`. Não há um 11º sufixo para abrir.

**`CLAUDE.md tem N linhas (teto M)`** — mova conteúdo para ADR ou para `docs/`. O custo de
um arquivo de instrução é pago em toda sessão.

**`guardas.X[i] não declara chave`** — uma regra de `guardas.caminhos` ou `guardas.comandos`
não tem o campo sem o qual ela não age (`padrao`/`regex` fazem `guardar.py` descartar a
regra em silêncio; `exemplo` faz o autoteste não exercitá-la). Preencha o campo — a regra
existe na config e hoje não bloqueia nada.

**`está no .gitignore, mas é o GATE do harness`** — `.claude/harness.json` está sendo
ignorado pelo git. Sem ele versionado, todo checkout novo (o CI inclusive) fica com os hooks
inertes em silêncio, e a própria auditoria acusa "projeto não adotou o harness" — diagnóstico
enganoso. Se o `.gitignore` usa `.claude/*` com exceções, adicione `!.claude/harness.json`.

**`checks_do_projeto ... NÃO rodaram`** — o módulo de cheques de fronteira do projeto está
apontado e não foi carregado. Isto reprova de propósito: um passo de CI verde que não
auditou nada é o pior resultado possível para um cheque.

## Mensagens do autoteste do `session_start` (não da auditoria, mas do mesmo passo de CI)

O autoteste (`session_start.py --autoteste`) confere **fidelidade** do bloco injetado, e as
duas mensagens abaixo só aparecem em corpus grande — o `/tmp/proj` sintético do CI nunca as
exercita, então se você as vir, é real:

**`bloco com N chars, acima do teto de 10000 que a plataforma ENTREGA`** — o bloco do
`session_start` ultrapassou o que `additionalContext` aceita; acima do teto a plataforma
substitui o bloco INTEIRO por um preview. As três peças de memória (índice, digest, última
entrada) já cedem espaço por orçamento; se ainda assim estoura, a única peça que não é
cortada é a seção de invioláveis — reduza o número de itens dela.

**`o beco '...' está na última entrada e não chegou ao bloco — nem em texto nem no digest`**
— um item de `### Tentativas descartadas` da última entrada sumiu do bloco injetado sem
aviso. Normalmente é um efeito colateral de mexer em `diario._resumir_beco` ou no orçamento
do digest; não é algo que se corrija editando o diário.

## Depois de corrigir

Rode de novo até sair 0. Se uma falha parecer errada — o cheque acusando algo correto —
**não contorne**: diga qual é, com o texto exato, e discuta. Cheque errado se corrige no
harness, não no projeto.
