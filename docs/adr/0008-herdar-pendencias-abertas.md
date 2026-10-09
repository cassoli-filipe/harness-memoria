---
status: proposed
data: 2026-10-09
---

# ADR-0008 — Herdar os itens abertos quando a última entrada narrada não traz a lista de pendências

## Contexto

Em 2026-10-09 este repositório gravou duas entradas narradas no mesmo dia. A primeira,
"Fechar o laço", terminou com três `- [ ]` em `### Aberto / Próximo passo`. A segunda,
"Promover os ADRs 0002–0007", fechou só o primeiro e não trouxe a seção. A sessão seguinte
recebeu do `SessionStart` "**Estado:** concluído" e nenhuma pendência. Os dois itens que
continuavam abertos (a linha de base das evals de `encerrar-sessao` e o roadmap) só
apareceram quando alguém abriu a entrada anterior à mão.

A causa é estrutural. O bloco injetado leva UMA entrada, a última narrada (ADR-0006), e o
diário é append-only: ninguém marca `[x]` numa entrada velha. Uma pendência sobrevive de
uma sessão para a outra só se cada entrada nova a copiar. A skill `/encerrar-sessao` mandava
"preencher" a seção, mas não mandava carregar a lista da entrada anterior. Numa sessão que
fecha tudo o que tinha planejado, omitir a seção parece correto.

## Fatores de decisão

- A pendência perdida custa uma sessão que acha que não há nada a fazer. Uma pendência já
  fechada que aparece de novo custa uma conferência.
- O bloco cabe em 10.000 ch (ADR-0004). Neste repositório a herança custa 531 ch e leva o
  bloco de 4.042 para 4.573.
- A entrada injetada continua sendo escolhida pela marca, não pelo conteúdo (ADR-0006).
- O formato do diário não muda: `### Aberto / Próximo passo` com `- [ ]` é o que o README
  do diário e a skill já prescrevem.

## Decisão

Quando a última entrada narrada não traz `### Aberto / Próximo passo`, o `SessionStart`
procura, da mais nova para a mais antiga, a primeira entrada narrada que traz a seção e
anexa à entrada injetada uma seção `### Aberto / Próximo passo (herdado)`. Essa seção tem
os itens não marcados `[x]` (cada um com as suas linhas de continuação) e uma linha que
nomeia a entrada de origem e o arquivo e manda conferir o que já foi feito. Registros
automáticos não contam nem como origem nem como a entrada mais nova. A seção presente é
autoritativa, inclusive quando diz que nada ficou aberto. Se todos os itens da origem estão
`[x]`, nada é herdado.

A herança entra como SEÇÃO da entrada, e não como peça nova do bloco. Assim o título,
que começa com `Aberto / Próximo passo`, cai na prioridade de retomada do recorte
(`prioridade_secoes`), e o cheque 3 de `conferir_fidelidade` reprova o bloco que a
descartar. Não há orçamento novo nem cheque novo.

A skill `/encerrar-sessao` e o README do diário passam a dizer que a seção da entrada mais
nova é a lista vigente. A entrada nova traz o que segue aberto, marca `- [x]` o que fechou
e, se nada ficou aberto, escreve a seção mesmo assim.

## Alternativas consideradas

### Só mudar a instrução da skill

**Rejeitada porque** a falha medida já foi uma instrução da skill não seguida: o passo 5
mandava preencher a seção, e uma sessão "concluída" a omitiu. Instrução sem mecanismo é o
que o diário de 2026-10-09 chamou de "harness só guia". A instrução muda também, mas como
complemento: é ela que evita mostrar como aberto o que já fechou.

### Reprovar na auditoria a entrada sem a seção quando a anterior tinha `- [ ]`

**Rejeitada porque** reprova o CI de projeto consumidor por uma omissão que o `SessionStart`
consegue compensar sozinho. E nem toda sessão roda a auditoria antes de sair. A falha só
aparece no CI, horas depois, quando o contexto que sabia quais itens fecharam já se perdeu.

### Juntar os `- [ ]` de todas as entradas do mês

**Rejeitada porque**, com o diário append-only, todo item já fechado continua `[ ]` na
entrada onde nasceu. Neste repositório o primeiro item de "Fechar o laço", fechado pela
entrada seguinte, voltaria em toda sessão do mês, e a lista cresceria até virar ruído
ignorado.

### Escolher como entrada injetada a última que tem a seção

**Rejeitada porque** é a alternativa que o ADR-0006 rejeitou: escolher a entrada pelo
conteúdo empurra para fora a entrada mais nova, que tem o porquê e os becos. Aqui a escolha
continua sendo pela marca, e a seção herdada é um acréscimo à entrada escolhida.

## Consequências

**Boas:** uma pendência sobrevive à entrada que a esqueceu. A origem vem nomeada, então quem
lê sabe onde conferir. O custo cabe na cota da entrada e cede pela máquina de corte que já
existe.

**Ruins, e aceitas:** item que a sessão seguinte fechou sem reescrever a lista aparece como
herdado até a próxima entrada trazer a seção. Neste repositório, a primeira injeção mostra
"Revisar e promover os ADRs 0002–0007", já feito. Num diário onde nenhuma entrada usa a
seção, o `SessionStart` lê o diário inteiro procurando-a. É o mesmo custo que
`becos_sem_saida` já paga em toda sessão.

## Quando revisitar

Se a herança passar a mostrar, com frequência, itens já fechados: o sinal é a entrada
seguinte ter de dizer "esse já foi feito" em mais de uma sessão. Nesse caso a correção é a
auditoria exigir a seção, não tirar a herança. Revisitar também se o diário ganhar um
formato de pendência que não seja `- [ ]` dentro de `### Aberto / Próximo passo`.

## Plano de Implementação

- **Arquivos a tocar:** `src/harness_memoria/diario.py` (`SECAO_ABERTO`, `aberto_herdado`),
  `src/harness_memoria/hooks/session_start.py` (`_entrada_a_injetar`,
  `_com_aberto_herdado`), `skills/encerrar-sessao/SKILL.md` (passo 5),
  `docs/diario/README.md` e `template/docs/diario/README.md`.
- **Padrões a seguir:** `ultima_narrada` para atravessar as entradas pulando as automáticas.
  A seção herdada vai como seção da entrada, para usar `recortar_entrada` e o cheque 3.
- **Testes obrigatórios:** `tests/test_entrada_narrada.py`, seção "Pendências herdadas":
  herda os não marcados, não herda quando a mais nova tem a seção, não herda quando tudo
  está `[x]`, item marcado sai com a continuação, e a fidelidade reprova o bloco que perde
  a seção herdada.
- **Não mexer em:** a escolha da entrada injetada (ADR-0006) e o formato do diário.
