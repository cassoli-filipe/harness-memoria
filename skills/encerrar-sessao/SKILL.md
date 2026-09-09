---
name: encerrar-sessao
description: Registrar esta sessão no diário de engenharia antes de sair, com o contexto ainda completo. É o caminho da entrada NARRADA — o hook SessionEnd só grava o piso determinístico. Use ao fim de qualquer sessão que mudou estado, e sobretudo quando houve tentativas descartadas.
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

**Se `.claude/harness.json` não existir, PARE também.** Sem ele o harness inteiro é inerte
neste projeto (é o gate): nenhum hook vai reinjetar o que você escrever, e a auditoria
REPROVA por falta de configuração. Ofereça `/harness-init` em vez de criar `docs/diario/`
por conta própria — diário que ninguém lê é pior que diário nenhum.

Se o campo não existir ou estiver vazio, siga.

## Por que esta skill é o caminho principal

O hook `SessionEnd` grava o **piso**: cabeçalho com data, lista de arquivos escritos,
comandos, ADRs tocados e o `git diff --stat`. Nada além disso — a plataforma dá **1,5 s**
a hook de plugin e narrar por LLM não cabe nesse orçamento (`claude -p` mede 14,5-33 s).
O piso existe para que "ninguém rodou comando nenhum no fim" nunca signifique "a sessão
não deixou rastro". Ele é o chão, não o teto.

Tudo o que o piso não tem — o **porquê**, o não-óbvio e sobretudo as **tentativas
descartadas** — só passa a existir se você escrever aqui, agora, com o contexto ainda
completo. A seção de tentativas descartadas é a de maior retorno do diário e a mais
difícil de reconstruir depois: é a única que o `SessionStart` reinjeta de **todos** os
meses, inclusive dos arquivados. O que você escrever ali é o que tem mais chance de chegar
ao contexto de uma sessão futura.

**Não vai sair entrada em dobro.** O hook enxerga, no transcript desta sessão, a escrita
que você fizer no arquivo do mês, e dispensa o piso — piso não compete com escolha
deliberada. Uma ressalva concreta: se você **delegar a escrita a um subagente**, o
transcript principal não a vê e o piso é anexado do mesmo jeito, ficando por último e
sendo ele o reinjetado. Escreva a entrada você mesmo.

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
     obrigatória e auditada: a reinjeção pega o último bloco `## AAAA-MM-DD` do arquivo,
     então entrada nova no topo faria a próxima sessão receber a mais velha.
   - **Cabeçalho com data absoluta: `## 2026-08-04 — Título`.** A data não é enfeite, é a
     fronteira de entrada: `## Sessão de terça` não abre entrada nenhuma — o texto fica
     colado na entrada anterior, em silêncio, e a auditoria reprova o arquivo.
   - Números, não adjetivos: "142 testes passando", não "testes ok".
   - **Sem segredo, sem token, sem dado pessoal.**

4. **Preencha "Tentativas descartadas" com honestidade**, uma linha por abordagem
   abandonada, exatamente nesta forma:

   ```
   - {abordagem} → falhou porque {razão}. **Não repetir:** {lição em imperativo}
   ```

   A lição vem **depois** do negrito porque é essa a grafia que o digest preserva quando
   precisa encurtar o item: com `**Não repetir.**` e a lição antes, o corte pela frente
   leva justamente a parte acionável (medido: item de 314 chars, teto de 240, saía com a
   lição ausente).

5. **Preencha "Aberto / Próximo passo"** de forma ordenada e acionável, e **"Retomar com"**
   com os comandos exatos para voltar ao ponto.

6. **Feche com a auditoria:**

   ```bash
   python -m harness_memoria.auditar
   ```

   Num projeto que instalou o harness com `uv`, o módulo não fica visível para o `python`
   do PATH: use `uv run python -m harness_memoria.auditar`.

7. Se algum ADR mudou de status nesta sessão, confirme que o índice reflete isso.

## O que não fazer

- Não escreva entrada para sessão sem mudança de estado — o diário registra mudança, não
  presença. O hook aplica a mesma regra: sem arquivo escrito e sem `git diff`, ele também
  não grava.
- Não repita no diário o que está no ADR. Cite o ID.
- Não descreva o diff linha por linha; descreva a mudança e o **porquê**.
- Não delegue a escrita da entrada a um subagente: além de perder o contexto que é a razão
  desta skill existir, o hook deixa de ver a escrita e anexa o piso por cima.
