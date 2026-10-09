---
status: implemented
data: 2026-09-09
---

# ADR-0002 — Gravar o piso determinístico no SessionEnd e deixar a narrativa por LLM opt-in

## Contexto

O hook `SessionEnd` foi desenhado para narrar a sessão com `claude -p` e, se a narrativa
falhasse, cair num registro montado só de fatos (o "piso"). Medido em três projetos
consumidores desde a virada para plugin: **zero** entradas com a assinatura do hook, contra
mais de 20 escritas pela skill `/encerrar-sessao`. O registro automático, mecanismo central
do diário, estava inerte em produção sem nada acusar.

A causa estava na plataforma, não no código do hook. Lendo o binário instalado: hook de
plugin recebe **1.500 ms** no `SessionEnd`, e o `"timeout": 160` declarado no `hooks.json`
é ignorado — hooks de plugin moram em `registeredHooks`, que a função de orçamento não
consulta; ela soma só `settings` e SDK. O `claude -p` mede 22–34 s. Como o piso vinha
DEPOIS da tentativa de narrar, o processo era morto antes de escrever qualquer coisa.

O enum real de motivos de `SessionEnd`, extraído do mesmo binário, é `clear`, `resume`,
`logout`, `prompt_input_exit`, `other` — e o hook não registrava `resume`, que é metade dos
encerramentos dentro do mesmo processo.

## Fatores de decisão

- O registro tem de caber em 1.500 ms com folga, no pior caso de disco e de transcript.
- "O LLM falhou" — ou "o LLM nem foi chamado" — nunca pode significar "a sessão não deixou
  rastro".
- A entrada narrada (a que tem o porquê e os becos) continua sendo a de maior valor, e o
  caminho para ela não pode depender de um orçamento que o consumidor não controla.
- Duas entradas para a mesma sessão (a narrada pela skill e a automática) competem pelo
  mesmo arquivo sem que nada acuse.

## Decisão

Inverter a ordem: **o piso determinístico é o caminho padrão e é gravado primeiro**, a partir
de fatos do transcript (arquivos escritos, comandos, ferramentas, turnos) e do git
(`diffstat`, branch), sem gerar processo `claude` nenhum. Medido: p25 de 288 ms dentro dos
1.500, e 25/25 entradas gravadas sob o kill de 1.500 ms emulado, contra 0/25 antes.

A narrativa por LLM sai do caminho crítico e vira **opt-in**: só é tentada quando
`CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` está acima de ~21.000 ms no ambiente do
consumidor, e o orçamento do filho é `orçamento_total − RESERVA_DO_PISO_MS`, para sobrar tempo
de gravar o piso se o filho estourar. O caminho primário da narrativa é a skill
`/encerrar-sessao`, que roda dentro da sessão com o contexto completo.

`_ja_registrada` dispensa o piso quando o transcript mostra escrita num arquivo de mês do
diário na própria sessão — a skill já registrou, e o piso não compete com escolha
deliberada. Os cinco motivos do enum registram.

## Alternativas consideradas

### Manter a narrativa primeiro, com o piso como rede

**Rejeitada porque** a rede nunca chegava a rodar: num orçamento de 1.500 ms, tudo o que
vem depois de um filho de 22–34 s é código morto. Foi exatamente o desenho que produziu zero
entradas em três consumidores.

### Narrar num processo destacado, que sobrevive ao hook

**Rejeitada porque** troca um defeito visível por um invisível: um processo órfão
escrevendo no diário depois que o usuário saiu, sem lock de sessão, podendo colidir com a
próxima sessão que abre e sem ninguém para ver a falha. E custa dinheiro em toda sessão,
inclusive nas que não valiam narrativa.

### Exigir ao menos um tool call no transcript para gravar

**Rejeitada porque** contradiz o caso que o piso existe para cobrir: transcript ausente ou
ilegível (`transcript_path ausente`) é justamente quando os fatos do git são o único rastro.
O critério ficou `arquivos_escritos OR git['diffstat']`, com uma impressão do diff para não
regravar o mesmo worktree duas vezes.

## Consequências

**Boas:** toda sessão que mudou estado deixa rastro, mesmo quando ninguém roda a skill. O
hook cabe no orçamento real da plataforma, não no declarado. A skill e o hook deixam de
competir pelo mesmo arquivo.

**Ruins, e aceitas:** a entrada automática não tem o porquê nem os becos — a seção de maior
retorno do diário continua dependendo da skill. Como `git diff --stat` persiste entre
sessões e o transcript não, dois `/clear` seguidos num worktree com trabalho não commitado
podem gravar duas entradas, a segunda com "0 arquivo(s) escrito(s)"; preferível a zero
entradas. Quem habilita a narrativa paga 15–30 s na saída de TODA sessão. (O efeito
colateral de a entrada automática ocupar o slot de "última entrada" é tratado no ADR-0006.)

## Quando revisitar

Se a plataforma passar a respeitar o `timeout` do `hooks.json` para hook de plugin, ou
expuser um evento pós-sessão sem orçamento curto — aí a narrativa pode voltar a ser padrão.
Também se a proporção de entradas automáticas sem narrativa correspondente passar da metade
do diário de um mês: é sinal de que a skill não está sendo usada e o piso virou a memória.

## Plano de Implementação

Implementado em `df617d7`.

- **Arquivos a tocar:** `src/harness_memoria/hooks/session_end.py` (`main`,
  `_motivo_para_nao_registrar`, `_ja_registrada`, `_janela_de_narrativa`),
  `src/harness_memoria/diario.py` (`entrada_deterministica`, `fatos_do_transcript`,
  `fatos_do_git`), `hooks/hooks.json`.
- **Padrões a seguir:** o orçamento como constante comentada com a medição
  (`ORCAMENTO_PISO_MS`, `RESERVA_DO_PISO_MS`, `MINIMO_PARA_NARRAR_MS`).
- **Testes obrigatórios:** `tests/test_session_end.py` — piso gravado sob o kill emulado,
  narrativa só com o orçamento levantado, piso dispensado quando a skill já registrou.
- **Não mexer em:** a skill `/encerrar-sessao`, que continua sendo o caminho da narrativa.
