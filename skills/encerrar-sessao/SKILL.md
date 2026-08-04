---
name: encerrar-sessao
description: Registrar deliberadamente esta sessão no diário de engenharia antes de sair, com o contexto ainda completo. Use quando a sessão teve decisões, becos sem saída ou descobertas que valem mais que o registro automático do hook SessionEnd.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Encerrar a sessão com registro deliberado

## Fase 0 — o projeto tem um comando melhor que este?

**Antes de qualquer coisa**, leia `.claude/harness.json` e procure
`diario.skill_de_encerramento`.

**Se o campo estiver preenchido, PARE.** Diga ao usuário para usar aquele comando e não
escreva nada. Ele existe porque o projeto tem um fechamento de sessão que faz mais do que
este — no ValidaNI, o `/handoff` escreve o handoff curado que é reinjetado na próxima sessão,
o deep-dive de marco em `docs/sessions/` e julga se cabe ADR, além da entrada do diário.

Duas skills competindo pelo mesmo arquivo significa que chamar a errada produz uma entrada
**pior, no lugar certo** — e nada acusa depois. Ceder a vez é a única coisa correta aqui.

O hook `SessionEnd` continua valendo nesse caso: ele é o **piso**, para a sessão que acabar
sem ninguém rodar comando nenhum. Piso não compete com escolha deliberada.

Se o campo não existir ou estiver vazio, siga.

## Quando esta skill vale

O hook `SessionEnd` grava uma entrada automaticamente. Esta skill existe para quando você
ainda tem o contexto completo na cabeça e a sessão merece mais do que o automático — em
particular quando houve **tentativas descartadas**, que é a seção de maior retorno do diário
e a mais difícil de reconstruir depois.

Concretamente: é a seção que o `SessionStart` da próxima sessão vai reinjetar, de todos os
meses, inclusive dos arquivados. O que você escrever ali é o que tem mais chance de chegar
ao contexto de uma sessão futura. Escreva a lição em imperativo e curta.

## Passos

1. **Reúna os fatos, não os invente.**

   ```bash
   git status --porcelain
   git diff --stat
   git log --oneline -5
   ```

   Liste os arquivos que você de fato criou ou alterou nesta sessão.

2. **Verifique antes de declarar.** Não escreva "funcionando" sem evidência. Rode o que se
   aplicar ao projeto e registre a saída real. Se algo falhou, o **Estado** da entrada é
   `parcial` ou `bloqueado` — não `concluído`.

3. **Escreva a entrada** no arquivo do mês corrente, no formato do `README.md` da pasta do
   diário. Regras que valem aqui:
   - Máximo ~25 linhas. Se precisar de mais, o conteúdo é ADR — crie com `/novo-adr` e
     cite o ID.
   - **Append-only, no FIM do arquivo.** Nunca edite entrada anterior; se precisar
     corrigir, escreva nova entrada apontando para a antiga. A ordem cronológica é
     obrigatória e auditada: a reinjeção pega o último bloco do arquivo, então entrada nova
     no topo faria a próxima sessão receber a mais velha.
   - Números, não adjetivos: "142 testes passando", não "testes ok".
   - Data absoluta no cabeçalho (`## 2026-08-04 — …`).
   - **Sem segredo, sem token, sem dado pessoal.**

4. **Preencha "Tentativas descartadas" com honestidade.** Toda abordagem que você tentou e
   abandonou, com o motivo e um `**Não repetir.**` no fim — a lição vai no fim porque é ali
   que o digest a preserva quando precisa encurtar o item.

5. **Preencha "Aberto / Próximo passo"** de forma ordenada e acionável, e **"Retomar com"**
   com os comandos exatos para voltar ao ponto.

6. **Feche com a auditoria:**

   ```bash
   python -m harness_memoria.auditar
   ```

7. Se algum ADR mudou de status nesta sessão, confirme que o índice reflete isso.

## O que não fazer

- Não escreva entrada para sessão sem mudança de estado — o diário registra mudança, não
  presença.
- Não repita no diário o que está no ADR. Cite o ID.
- Não descreva o diff linha por linha; descreva a mudança e o **porquê**.
