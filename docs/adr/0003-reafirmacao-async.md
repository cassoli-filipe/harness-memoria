---
status: proposed
data: 2026-09-09
---

# ADR-0003 — Rodar a reafirmação intra-sessão como hook async

## Contexto

O hook `reafirmar` (PostToolUse em `Write|Edit|MultiEdit|NotebookEdit`) reinjeta as
invioláveis do `CLAUDE.md` a cada `reafirmacao.intervalo_escritas` escritas (15 por
padrão). Ele existe por causa de `arXiv:2605.10039`: em 1.650 sessões de Claude Code, cada
função gerada corresponde a ~5,6% menos chance de conformidade (OR 0,944), e nenhuma
variável de formato do arquivo de instrução tem efeito — a contramedida é reinjeção, não um
`CLAUDE.md` melhor.

O hook era síncrono, e o docstring que o mantinha assim afirmava que "saída de hook async é
descartada pelo Claude Code". Lendo o binário instalado, isso é **falso**: a plataforma colhe
o resultado do hook assíncrono e entrega o `additionalContext` no turno seguinte. Enquanto
isso, o hook síncrono bloqueava ~145 ms em CADA escrita, e 14 de cada 15 execuções não
emitiam nada — só incrementavam o contador.

## Fatores de decisão

- O alvo da mensagem é decaimento ao longo de DEZENAS de passos; o que importa é ela
  chegar, não chegar colada à escrita que a disparou.
- Bloqueio por escrita multiplica: uma sessão de 120 escritas pagava ~15 s parada.
- A saída precisa de fato chegar ao modelo — um hook async cuja saída fosse descartada
  seria um hook desligado.

## Decisão

Registrar o `reafirmar` com `"async": true` no `hooks/hooks.json`. A mensagem chega um
turno depois da escrita que completou o intervalo; o contador e o texto não mudam.

A regra que sai daqui para o resto do harness: **`async` para o que é lembrete; síncrono só
para o que precisa chegar colado ao resultado da ferramenta** (bloqueio de guarda, por
exemplo, nunca pode ser async).

## Alternativas consideradas

### Manter síncrono

**Rejeitada porque** pagava ~145 ms em toda escrita para emitir em 1 de cada 15, e o ganho
de chegar no mesmo turno é nulo para uma mensagem cujo papel é recitação periódica. A razão
registrada para mantê-lo síncrono era uma premissa falsa sobre a plataforma.

### Reinjetar em `UserPromptSubmit` em vez de por escrita

**Rejeitada porque** o decaimento medido é por PASSO de trabalho, não por mensagem do
usuário: uma única instrução pode render 40 escritas sem nenhum prompt novo, e é
exatamente nesse trecho que a aderência cai.

### Abandonar a reafirmação e confiar no `SessionStart` e no `PreCompact`

**Rejeitada porque** os dois atuam nos pontos de compactação e de início, e o estudo mede a
queda entre eles. A reafirmação é a única peça que age no meio de uma sessão longa sem
compactação.

## Consequências

**Boas:** ~15 s a menos de bloqueio numa sessão de 120 escritas. O hook deixa de estar no
caminho crítico de toda escrita.

**Ruins, e aceitas:** um turno de atraso na mensagem. A ordem relativa entre a reafirmação
e o resultado da ferramenta deixa de ser garantida. E a premissa passa a depender de um
comportamento da plataforma que não está documentado — se ele mudar, o hook vira inerte em
silêncio.

## Quando revisitar

Se uma versão da plataforma voltar a descartar saída de hook async — o sinal é a
reafirmação sumir do transcript de uma sessão longa —, ou se medição mostrar que o turno de
atraso coincide com violações que a reafirmação deveria ter evitado.

## Plano de Implementação

Implementado em `df617d7`.

- **Arquivos a tocar:** `hooks/hooks.json` (`"async": true` no registro do `reafirmar`),
  `src/harness_memoria/hooks/reafirmar.py` (docstring com a premissa corrigida).
- **Padrões a seguir:** o `formatar`, que já era async pelo mesmo raciocínio.
- **Testes obrigatórios:** o autoteste do `reafirmar` e `tests/test_hooks_quentes.py`.
- **Não mexer em:** `guardar`, que tem de continuar síncrono — bloqueio que chega um turno
  depois não bloqueia nada.
