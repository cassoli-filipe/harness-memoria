---
name: novo-adr
description: Criar um Architecture Decision Record novo neste repositório. Use quando for adicionar dependência ou serviço externo, criar padrão arquitetural que outros arquivos vão imitar, escolher entre alternativas não-óbvias, contradizer decisão existente, ou quando estiver escrevendo um comentário "por quê" com mais de 5 linhas.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Criar um ADR

Formato: MADR 4.0.0 adaptado ao pt-BR. As regras do projeto estão em `docs/adr/README.md`
(ou na pasta que `adr.pasta` do `.claude/harness.json` indicar — leia a config antes de
supor o caminho).

## Fase 0 — Varrer antes de escrever

**Não escreva nada ainda.** Primeiro:

1. Leia o índice de ADR e liste os que tocam o assunto.
2. Leia os relacionados por inteiro. Se algum já cobre a decisão, **não crie um novo** —
   diga qual e pare.
3. Se a decisão **contradiz** um ADR vivo, este é um caso de supersessão: o novo ganha
   `substitui: [ADR-NNNN]` e o antigo ganha `substituido-por: [ADR-MMMM]` +
   `status: superseded`. **Os dois lados são obrigatórios** — a auditoria falha se só um
   existir, e um ADR morto sem substituto declarado também reprova, porque o índice
   injetado no início da sessão fica sem ter o que apontar.
4. Procure no código o padrão atual (`Grep`) para descrever o estado real, não o presumido.

## Fase 1 — Extrair a decisão do usuário, uma pergunta por vez

Não escreva o ADR com base em suposição. Pergunte até ter:

- **O gatilho:** o que forçou a decisão agora? (fato verificável, não opinião)
- **Fatores mensuráveis:** quais restrições existem? Cite requisito numerado quando houver.
  "Precisa ser rápido" não serve; "p95 abaixo de 500 ms" serve.
- **Alternativas reais:** ao menos duas, e inclua "não fazer nada" quando for real.
- **Por que cada rejeitada foi rejeitada.** Esta é a parte de maior valor: é o que impede a
  alternativa de ser reproposta em seis meses.
- **Quando revisitar:** a condição concreta que invalida a decisão.

Faça **uma pergunta por vez**. Não despeje um formulário.

## Fase 2 — Escrever

1. Número = maior existente + 1, com 4 dígitos. Confirme com `Glob docs/adr/[0-9]*.md`.
2. Nome do arquivo: `NNNN-titulo-com-hifens.md`. Título curto, em pt-BR, descrevendo
   **problema + solução escolhida** — não só o problema.
3. Copie o `template.md` da pasta de ADR e preencha. Seja específico e verificável:
   "Polars 1.x com engine calamine", não "uma lib rápida de planilha".
4. **`## Regra`** — até 5 linhas, imperativo, logo após o título. Obrigatória a partir do
   número em `adr.primeiro_com_regra`; a auditoria falha sem ela. Existe para que um leitor
   decida se precisa abrir o ADR inteiro, porque o corpus completo custa dezenas de
   milhares de tokens.
5. **`## Plano de Implementação`** — obrigatória quando o status é `accepted` ou
   `implemented`, se `adr.secao_plano` estiver configurada. Deve conter o suficiente para
   outro agente implementar sem perguntas de acompanhamento: arquivos a tocar, padrões a
   seguir, testes obrigatórios, o que **não** mexer.
6. Atualize o índice: linha na tabela **e** na lista "Por domínio", se ela existir. ADR
   morto na lista por domínio precisa de marca — `0007 (superada → 0023)`.
7. Se houver supersessão, edite o ADR antigo: `status: superseded` + `substituido-por:`.

## Fase 3 — Verificar

```bash
python -m harness_memoria.auditar
```

Precisa sair com 0. Se falhar, corrija antes de terminar.

## Fase 4 — Aprovação

**Nunca marque um ADR como `accepted` por conta própria.** Escreva com `status: proposed`,
apresente o resumo (decisão, alternativas rejeitadas, consequência ruim aceita) e pergunte
se aprova. Só o usuário promove.

## Não crie ADR para

Bugfix · refactor local · implementação rotineira de algo já decidido · escolha reversível
em minutos. Nesses casos, o registro certo é uma entrada no diário, ou nada.
