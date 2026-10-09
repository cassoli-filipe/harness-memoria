---
status: implemented
data: 2026-10-09
---

# ADR-0009 — Injetar no PreToolUse de escrita os ADRs que o mapa por caminho aponta

## Contexto

O `CLAUDE.md` de todo consumidor tem a seção "Qual ADR ler — por caminho que você vai
tocar", e o auditor reprova o mapa quando ele aponta caminho ou ADR que não existe. Mas
quem lê o mapa é o agente, e só se ele lembrar. A instrução é do tipo que o próprio auditor
descreve como "a instrução que ninguém executa". O `SessionStart` injeta o índice dos ADRs
(um título por linha), não a decisão. Quem edita `diario.py` recebe os títulos dos ADRs 0002,
0005, 0006, 0007 e 0008, e nenhuma linha do que eles decidem.

Medido em 2026-10-09 com `claude -p` 2.1.295 e um hook descartável: um `PreToolUse` que
devolve só `hookSpecificOutput.additionalContext`, sem `permissionDecision`, chega ao modelo
e a escrita segue. A documentação diz que o texto entra "junto do resultado da ferramenta" e
é lido na chamada seguinte ao modelo. Esse é o mesmo momento de um `PostToolUse` síncrono,
mas o `PreToolUse` também dispara quando o `Edit` falha e o agente vai tentar de novo. O
evento traz `session_id`, `tool_input.file_path` absoluto e, dentro de subagente,
`agent_id`.

## Fatores de decisão

- Custo por escrita: o `guardar.py` já roda síncrono no `PreToolUse` de toda escrita
  (p25 de 21,5 ms por escrita nesta máquina, n=30). Um hook novo seria um segundo processo
  Python, que paga de novo o interpretador e o import do pacote.
- Teto de 10.000 ch por `additionalContext` (ADR-0004).
- Meia decisão lê como permissão: um ADR cortado no meio não pode chegar como se estivesse
  inteiro.
- Subagentes fazem a maioria das escritas em sessões de orquestração (ADR-0004) e não veem o
  contexto da thread principal.
- A política (qual caminho leva a qual ADR) mora no `CLAUDE.md` do consumidor. O código só
  lê.

## Decisão

No processo do `guardar.py`, depois das guardas, quando a escrita (`Write`, `Edit`,
`MultiEdit`, `NotebookEdit`) não foi negada:

1. O caminho, relativo à raiz, é casado contra o mapa "Qual ADR ler" do `CLAUDE.md`. Uma linha
   que termina em `/` ou aponta um diretório casa por prefixo; as outras casam o arquivo
   exato. Todas as linhas que casam somam seus ADRs.
2. Cada ADR que casou e ainda não foi mostrado a ESTE agente nesta sessão (chave
   `session_id` + `agent_id`) entra no `additionalContext`. Entra com uma linha de cabeçalho
   (número, status, título, caminho) e com, nesta ordem de preferência: a `## Regra`, se o
   ADR tem; a `## Decisão` inteira, se cabe em `TETO_DECISAO_CHARS = 1.500`; ou só o
   cabeçalho, com o tamanho da decisão e a ordem de ler o arquivo antes de editar. Nunca
   texto pela metade.
3. O bloco tem teto de `TETO_ADRS_POR_CAMINHO_CHARS = 6.000`. Os ADRs entram na ordem do
   mapa enquanto cabem. O primeiro que não cabe e os seguintes são nomeados numa linha e não
   contam como mostrados: a próxima escrita no caminho os entrega inteiros.
4. ADR `superseded` ou `deprecated` não é injetado (o auditor já reprova o mapa que os cita).
5. A compactação esquece o contexto, então o `SessionStart` com `source: compact` apaga o
   registro de ADRs mostrados daquela sessão.

`adr.injetar_por_caminho` (padrão `true`) desliga o mecanismo. O parser do mapa sai do
auditor para `adr.mapa_por_caminho`, que passa a ser usado pelo auditor e pelo hook. O
auditor passa a AVISAR (sem reprovar) a linha do mapa com mais de
`MAX_ADRS_POR_LINHA_DO_MAPA = 10` ADRs.

Medido no ValidaNI (93 ADRs, mapa de 12 linhas) antes de fixar o corte: a primeira versão
rebaixava todos os ADRs a ponteiro antes de cortar, e uma escrita em `apps/web/src/` (58
ADRs) receberia 20 ponteiros e nenhuma `## Regra`. Com o preenchimento na ordem do mapa, a
mesma escrita recebe 9 ADRs (6 pela Regra, 1 pela decisão inteira, 2 como ponteiro), e os 58 chegam ao longo de 10 escritas, com
4 a 9 por escrita e ~55 mil ch no total. É esse custo que o aviso do auditor torna visível.

## Alternativas consideradas

### Hook `PreToolUse` próprio, separado do `guardar.py`

**Rejeitada porque** dobra o custo de processo em toda escrita para ler o mesmo evento que
o `guardar.py` já leu. O código fica separado: o `guardar.py` chama
`adr.contexto_por_caminho` depois de decidir que não bloqueia.

### Injetar no `reafirmar` (`PostToolUse` assíncrono)

**Rejeitada porque** a saída assíncrona chega um turno depois (ADR-0003), e a regra do
ADR-0003 é: assíncrono só para lembrete. O ADR do arquivo que está sendo editado precisa
chegar junto da edição. Além disso, `PostToolUse` não dispara no `Edit` que falhou.

### Negar a primeira escrita no caminho até o agente ler o ADR

**Rejeitada porque** é bloqueio para o que é informação. Bloqueio que o agente não tem como
satisfazer de forma verificável ("leu?") vira falso positivo, e falso positivo ensina a
desligar a guarda.

### Injetar a seção `## Decisão` cortada no teto

**Rejeitada porque** corta exatamente a parte que restringe. Medido em 2026-10-09: neste
repositório as decisões têm de 381 a 2.016 ch (mediana 983; 8 de 9 cabem em 1.500). No
ValidaNI são 93 ADRs, de 512 a 21.487 ch (mediana 2.669), e só 19 cabem em 1.500, mas 71
têm `## Regra`. Quando não cabe, o ponteiro com o tamanho é honesto. O resumo curto que cabe
sempre é a `## Regra`, que já é a convenção para isso (`adr.primeiro_com_regra`).

### Rebaixar tudo a ponteiro antes de cortar

**Rejeitada porque** foi a primeira versão e, medida no ValidaNI, entregava 20 ponteiros e
nenhuma regra numa escrita em `apps/web/src/`. Ponteiro serve para o ADR cuja decisão não
cabe, não para o que só não coube nesta escrita.

### Mostrar os ADRs em toda escrita

**Rejeitada porque** uma sessão que edita `diario.py` vinte vezes pagaria 20 × ~5.000 ch
pela mesma informação. Uma vez por agente e por sessão, renovada na compactação, cobre o
decaimento sem repetir.

## Consequências

**Boas:** a decisão chega ao agente, subagente incluído, no momento em que ele toca o
caminho, sem depender de ele ler o mapa. O mapa, que já era auditado, ganha um leitor
mecânico. Um mapa podre passa a custar contexto errado, o que dá mais peso ao cheque do
auditor.

**Ruins, e aceitas:** toda escrita paga ler o `CLAUDE.md` e o mapa, e a que cai num caminho
mapeado paga também o estado da sessão e os ADRs. Medido contra a versão anterior (p25,
n=30, intercalado): +0,6 ms fora do mapa, +2,0 ms em caminho já visto, +2,8 ms na primeira
vez, sobre 21,5 ms. O bloco de `diario.py` neste repositório tem 5.208 ch. A primeira
escrita já foi composta quando o ADR chega, então o que ele corrige são as
seguintes. Projetos sem `## Regra` recebem a `## Decisão` inteira ou só o ponteiro. Bash
que escreve arquivo não passa pelo mapa.

## Quando revisitar

Se a plataforma passar a entregar o `additionalContext` do `PreToolUse` antes de o modelo
compor a chamada, a primeira escrita também passa a ser corrigida, e o desenho continua o
mesmo. Se a medição de uma sessão longa mostrar que o agente ignora o bloco, a próxima
alavanca é a `## Regra` em todos os ADRs mapeados, não repetir a injeção.

## Plano de Implementação

Implementado no commit "Injetar no PreToolUse de escrita os ADRs que o mapa por caminho
aponta". Aprovado pelo usuário em 2026-10-09.

- **Arquivos a tocar:** `src/harness_memoria/adr.py` (`mapa_por_caminho`,
  `contexto_por_caminho`), `src/harness_memoria/auditar/__init__.py` (usar
  `mapa_por_caminho`), `src/harness_memoria/hooks/guardar.py` (emitir depois das guardas),
  `src/harness_memoria/hooks/_comum.py` (estado `adrs_vistos_*`, com expiração),
  `src/harness_memoria/hooks/session_start.py` (apagar o estado na compactação),
  `src/harness_memoria/config.py` (`adr.injetar_por_caminho`).
- **Padrões a seguir:** estado por sessão como o contador do `reafirmar`; corte anunciado
  como o índice de ADR; `emitir_contexto` de `_comum`.
- **Testes obrigatórios:** `tests/test_adr_por_caminho.py`. Casamento por prefixo e por
  arquivo; uma vez por agente e por sessão; `agent_id` diferente recebe de novo; Regra >
  Decisão inteira > ponteiro; o que não cabe vai para a escrita seguinte; ADR morto fora;
  escrita negada não injeta; desligado pela config; compactação zera; aviso do mapa grosso.
  Os testes do auditor que já existiam continuam passando sem mudança.
- **Não mexer em:** a decisão de bloqueio do `guardar.py`. A injeção só roda depois de ela
  liberar.
