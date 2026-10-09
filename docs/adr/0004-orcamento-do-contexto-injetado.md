---
status: proposed
data: 2026-09-09
---

# ADR-0004 — Orçar o bloco injetado pelo teto de 10.000 ch e dar ao SubagentStart um bloco reduzido

## Contexto

O `additionalContext` de um hook tem teto de **10.000 caracteres** na plataforma instalada.
Acima disso, o bloco inteiro é substituído por um preview mais o caminho de um arquivo — em
silêncio. O teto não aparecia como constante legível no binário; foi medido pelo efeito.

O bloco do `session_start` não tinha orçamento: media 15.485 ch num consumidor real de 53
ADRs e 12.911 ch em outro de 22–23 ADRs. Em 14 das últimas 40 sessões do primeiro, foi o
preview que chegou — a reinjeção, que é a tese do repositório, desligada em ~35% das
sessões. `grep 10_000 src/` não retornava nada, e o autoteste conferia a string que o hook
MONTAVA, não a que a plataforma ENTREGAVA.

Em paralelo, medido em 10 sessões reais: os subagentes fizeram 491–1.313 tool calls contra
32–350 da thread principal, e em 4 delas a maioria das ESCRITAS — numa, 92% — saiu de
agentes que não viram inviolável nenhuma.

## Fatores de decisão

- O bloco tem de caber em 10.000 ch em qualquer corpus, inclusive com centenas de ADRs.
- Todo corte é anunciado com o total real e com onde achar o resto; truncar calado remove o
  único gatilho de leitura.
- Invioláveis nunca são cortadas — meia proibição lê como permissão.
- O subagente precisa das invioláveis, mas multiplicar 10.000 ch por cada Task seria o
  Context Rot que o repositório cita como justificativa de desenho.

## Decisão

`TETO_PLATAFORMA_CHARS = 10_000` em `session_start.py` é estrutural, não um campo de config.
O bloco é montado em duas passadas: na primeira, no tamanho natural — se cabe, nada é
cortado. Se não cabe, a segunda reparte o espaço cortando em ordem de granularidade, cada
peça pela sua máquina de corte anunciado que já existia:

1. o **índice de ADR** cede primeiro, uma linha por vez, até `PISO_DO_INDICE_CHARS = 3.500`,
   anunciando `índice PARCIAL` com o total;
2. o **digest de becos** cede depois, um item por vez, anunciando `{n} de {total}`;
3. a **última entrada do diário** cede por último e por seção inteira, porque cai em degrau.

`conferir_fidelidade` ganhou o cheque do bloco contra o teto da PLATAFORMA.

O `SubagentStart` passa a ser registrado e recebe um bloco **reduzido** — invioláveis +
digest de becos, sem índice de ADR nem entrada de diário — com teto próprio
`TETO_SUBAGENTE_CHARS = 6.000`.

## Alternativas consideradas

### Campos de config `teto_contexto_injetado_chars` e `teto_indice_chars`

**Rejeitada porque** nasceriam `None` — inertes por default —, e o teto não é escolha do
projeto: é o limite da plataforma. Um knob que o consumidor pode subir acima de 10.000 só
reintroduz o defeito.

### Fatiar o texto montado no caractere 10.000

**Rejeitada porque** cortaria o índice DEPOIS do cabeçalho que promete o índice inteiro — o
falso completo que o hook existe para não produzir —, e poderia cortar uma inviolável no
meio.

### Repartição proporcional entre as três peças

**Rejeitada porque** a entrada do diário cai em degrau: medido no corpus de 60 ADRs, a
repartição proporcional derrubava a entrada de 3.913 para 649 ch e fechava o bloco em 8.437
— 1.563 ch de memória não entregues a ninguém.

### Bloco completo também no subagente

**Rejeitada porque** custaria o bloco inteiro a cada Task numa sessão de orquestração, para
um leitor que escreve mais do que lê e não precisa do índice para saber o que é proibido.

## Consequências

**Boas:** o bloco fecha em 9.831–9.908 ch em duas medições com geradores diferentes, e em
9.866 com 400 ADRs (14× o maior corpus real). Subagentes passam a receber as invioláveis.

**Ruins, e aceitas:** corpus grande de ADR perde parte do índice no bloco (anunciada, com o
caminho do README). O teto é uma medição, não uma constante documentada — se a plataforma
mudá-lo, o sinal é o preview voltar a aparecer no transcript. Cada Task paga ~700–6.000 ch a
mais de contexto.

## Quando revisitar

Se a plataforma documentar ou mudar o teto de `additionalContext`, ou se o preview voltar a
aparecer em transcripts de consumidores. Para o bloco reduzido: se medição mostrar que
subagentes repetem becos de forma que a entrada do diário teria evitado.

## Plano de Implementação

Implementado em `df617d7`.

- **Arquivos a tocar:** `src/harness_memoria/hooks/session_start.py` (`montar`, `_blocos`,
  `_orcar`, `conferir_fidelidade`), `src/harness_memoria/adr.py` (`indice_compactado`),
  `hooks/hooks.json` (registro do `SubagentStart`).
- **Padrões a seguir:** corte sempre pela máquina de corte anunciado da própria peça.
- **Testes obrigatórios:** `tests/test_session_start.py` — o bloco cabe no teto em corpus de
  10 a 400 ADRs, o que cabe não é cortado, o reduzido leva todas as invioláveis.
- **Não mexer em:** a seção de invioláveis, que não cede nunca.
