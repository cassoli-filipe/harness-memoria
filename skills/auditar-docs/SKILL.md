---
name: auditar-docs
description: Rodar a auditoria da documentação e das fronteiras estruturais do projeto, e corrigir o que falhar. Use antes de abrir PR, depois de criar ou mudar status de ADR, ao virar o mês (rotação do diário), ou quando o CI reprovar na etapa de auditoria.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Auditar a documentação

```bash
python -m harness_memoria.auditar
```

Saída 0 = aprovado. Aviso não reprova o build; **falha reprova**. Corrija as falhas, não as
silencie.

## Como corrigir cada família de falha

**`não está no índice`** — o ADR existe e o `README.md` da pasta não o lista. Adicione a
linha na tabela e, se houver, na lista "Por domínio".

**`status '...' inválido`** — o frontmatter aceita `proposed`, `accepted`, `implemented`,
`superseded`, `deprecated`. O vocabulário pt-BR (`aceito`, `implementado`, …) é normalizado
automaticamente, então este erro significa que o valor não é nenhum dos dois.

**`supersessão unilateral`** — os dois lados são obrigatórios. O novo declara
`substitui: [ADR-NNNN]`; o antigo declara `substituido-por: [ADR-MMMM]` **e**
`status: superseded`.

**`está superseded e não declara substituido-por`** — ADR morto sem substituto deixa o
índice injetado no início da sessão sem ter o que apontar. Declare o substituto, ou use
`deprecated` com o motivo no corpo se nada o substituiu.

**`manda seguir ADR-NNNN, que está superseded`** — um arquivo que instrui um agente aponta
para decisão morta. Troque pelo substituto. Se a menção é histórica, escreva na própria
linha que houve substituição (a palavra "substituiu" na vizinhança libera o cheque) — é ela
que avisa o leitor, não a mera presença do número novo em outro lugar do arquivo.

**`mapa de ADR por caminho: ... não existe`** — o mapa da seção "Qual ADR ler" do CLAUDE.md
apodreceu. Corrija o caminho ou remova a linha. Mapa que apodrece é pior que mapa nenhum.

**`invioláveis: item com N chars`** — a primeira frase de uma inviolável não cabe em uma
linha. Encurte **a primeira frase** no CLAUDE.md; o resto do raciocínio continua no item.
Não trunque na config: só a primeira frase entra na reafirmação, e meia proibição lê como
permissão.

**`não achei nenhuma inviolável`** — a seção nomeada em `reafirmacao.secao` não existe ou não
tem lista. Sem ela a reafirmação intra-sessão e o aviso pós-compactação ficam **mudos**, o
que é pior que não ter o harness: quem o instalou acha que está protegido.

**`entradas fora de ordem cronológica`** — o diário está do mais recente para o mais antigo.
A reinjeção pega o último bloco do arquivo, então nessa ordem ela injeta a entrada mais
velha em toda sessão. Inverta a ordem das entradas.

**`rotação pendente`** — virou o mês. Mova os arquivos do mês anterior para `arquivo/`, crie
o do mês novo com o cabeçalho, e atualize o ponteiro no CLAUDE.md. A partir do dia
`diario.dia_limite_rotacao` isso deixa de ser aviso e reprova.

**`CLAUDE.md tem N linhas (teto M)`** — mova conteúdo para ADR ou para `docs/`. O custo de
um arquivo de instrução é pago em toda sessão.

**`checks_do_projeto ... NÃO rodaram`** — o módulo de cheques de fronteira do projeto está
apontado e não foi carregado. Isto reprova de propósito: um passo de CI verde que não
auditou nada é o pior resultado possível para um cheque.

## Depois de corrigir

Rode de novo até sair 0. Se uma falha parecer errada — o cheque acusando algo correto —
**não contorne**: diga qual é, com o texto exato, e discuta. Cheque errado se corrige no
harness, não no projeto.
