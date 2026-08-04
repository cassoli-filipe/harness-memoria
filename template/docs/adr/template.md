---
status: proposed
data: AAAA-MM-DD
# substitui: [ADR-NNNN]          # se este ADR aposenta outro — o outro precisa do par
# substituido-por: [ADR-NNNN]    # preenchido quando ESTE for aposentado
---

# ADR-NNNN — {problema + solução escolhida, em pt-BR}

## Regra

<!-- Até 5 linhas, imperativo, o que seguir na prática. Existe para o leitor decidir se
     precisa abrir o resto: o corpus completo de ADR custa dezenas de milhares de tokens.
     Obrigatória a partir do número em `adr.primeiro_com_regra`. -->

- {o que fazer}
- {o que não fazer}

## Contexto

{O gatilho: o fato verificável que forçou a decisão AGORA. Não opinião, não "seria bom".
Cite requisito numerado quando houver. Descreva o estado real do código, medido — não o
presumido.}

## Fatores de decisão

- {restrição mensurável: "p95 abaixo de 500 ms", não "precisa ser rápido"}
- {restrição mensurável}

## Decisão

{O que foi escolhido, específico e verificável. "Polars 1.x com engine calamine", não "uma
lib rápida de planilha".}

## Alternativas consideradas

### {Alternativa A}

**Rejeitada porque** {razão concreta}.

### {Alternativa B — inclua "não fazer nada" quando for real}

**Rejeitada porque** {razão concreta}.

<!-- Esta seção é a de maior valor do ADR: é o que impede a alternativa de ser reproposta em
     seis meses. Um "rejeitada porque não gostamos" não serve. -->

## Consequências

**Boas:** {o que fica melhor}

**Ruins, e aceitas:** {o custo real que escolhemos pagar — se não houver nenhum, a decisão
provavelmente não era uma decisão}

## Quando revisitar

{A condição concreta que invalida esta decisão. "Se o volume passar de 5M linhas por carga",
não "se as coisas mudarem".}

## Plano de Implementação

<!-- Obrigatória quando o status é `accepted` ou `implemented` (se `adr.secao_plano` estiver
     configurada). Deve bastar para outro agente implementar sem perguntas de acompanhamento. -->

- **Arquivos a tocar:** {lista}
- **Padrões a seguir:** {qual código existente imitar}
- **Testes obrigatórios:** {o que precisa estar verde}
- **Não mexer em:** {o que está fora de escopo}
