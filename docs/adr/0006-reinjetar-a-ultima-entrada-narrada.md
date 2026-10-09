---
status: implemented
data: 2026-10-09
---

# ADR-0006 — Reinjetar a última entrada NARRADA do diário e só resumir os registros automáticos

## Contexto

Na sessão de 2026-10-09 deste repositório, o `SessionStart` injetou como "última entrada do
diário" o registro automático de 2026-09-08 22:06: "0 arquivo(s) escrito(s)", "Turnos do
usuário: 0", "transcript_path ausente" e um diffstat de 27 arquivos de trabalho já
commitado. A entrada narrada do mesmo dia — a que tinha o porquê da auto-hospedagem e o
único beco sem saída do repositório — ficou de fora.

A causa: `diario.ultima_entrada` devolve o último bloco `## AAAA-MM-DD` do arquivo mais novo,
sem olhar o tipo. Desde o ADR-0002 o piso automático é gravado em toda sessão que mudou
estado, então o slot mais caro do bloco injetado passou a ser ocupado, com frequência, pela
entrada de menor informação.

O mesmo dia mostrou um segundo buraco de memória: a rotação do diário estava pendente desde
o dia 1 e nada na sessão avisava — o primeiro sinal foi o CI vermelho (ADR-0005).

## Fatores de decisão

- A entrada injetada deve ser a que carrega o porquê e os becos.
- Registro automático mais novo que a narrada não pode sumir calado: o bloco não pode se
  apresentar como "última" sem dizer que existe coisa depois.
- O formato do diário e da entrada automática não muda — consumidores já têm meses de
  diário escritos.
- O aviso de rotação tem de chegar antes do dia em que o CI reprova, e não pode virar ruído
  permanente quando não há nada mecânico a fazer.

## Decisão

A entrada injetada é a **última narrada**. Os registros automáticos posteriores a ela entram
como uma linha cada (data e hora · escopo · ADRs tocados), até
`MAX_AUTOMATICAS_NO_BLOCO = 5`, com "… e mais N" acima disso. Sem nenhuma entrada narrada
no diário, injeta-se o registro automático mais novo, com uma linha apontando
`/encerrar-sessao` (ou `diario.skill_de_encerramento`).

O reconhecimento é por marca: `TITULO_AUTOMATICO`/`ESTADO_AUTOMATICO` viram constantes
usadas por quem escreve (`entrada_deterministica`, saída byte-idêntica) e por quem lê
(`e_automatica`), que casa `**Estado:** registro automático` só no cabeçalho da entrada — o
rodapé `<sub>Registro automático…` das entradas narradas pelo hook não conta.

Quando a rotação tem ação mecânica pendente, o bloco completo (não o reduzido do subagente)
abre com uma linha de aviso apontando `/auditar-docs`. `conferir_fidelidade` reprova bloco
que esconde registros automáticos posteriores e bloco sem o aviso quando a rotação está
pendente.

## Alternativas consideradas

### Parar de gravar entrada automática sem fatos

**Rejeitada porque** a entrada automática é o piso do ADR-0002: é o único rastro das sessões
que ninguém narrou. O defeito não era ela existir, era ela ocupar o lugar da narrada.

### Excluir as entradas automáticas da injeção

**Rejeitada porque** apagaria a informação de que houve trabalho depois da última narrada —
o agente leria uma entrada de setembro como se fosse o estado atual.

### Escolher a entrada pelo tamanho ou pela presença de seções

**Rejeitada porque** é heurística sobre conteúdo escrito por humano, que muda de forma entre
projetos; a marca é um contrato que o próprio harness escreve e pode verificar.

## Consequências

**Boas:** o slot da entrada volta a levar o porquê e os becos. A contagem de registros
automáticos vira sinal visível de sessões não narradas. O aviso de rotação chega dias antes
de o CI reprovar.

**Ruins, e aceitas:** o resumo das automáticas custa até ~600 ch da cota da entrada. Uma
entrada narrada antiga pode ser injetada enquanto várias sessões recentes aparecem só como
uma linha — a correção para isso é narrar, não injetar o piso. O aviso de rotação custa ~230
ch nas sessões em que está pendente.

## Quando revisitar

Se o piso automático passar a carregar informação que hoje só a narrada tem (por exemplo,
falhas observadas extraídas do transcript), a linha de resumo pode precisar de mais do que
data, escopo e ADRs.

## Plano de Implementação

Implementado no commit "Reinjetar a última entrada NARRADA e avisar da rotação pendente".

- **Arquivos a tocar:** `src/harness_memoria/diario.py` (`entradas`, `e_automatica`,
  `ultima_narrada`, `resumir_automatica`, constantes de marca),
  `src/harness_memoria/hooks/session_start.py` (`_entrada_a_injetar`, `_bloco_da_entrada`,
  `_resumo_das_automaticas`, `_aviso_de_rotacao`, `_orcar` com o aviso como peça fixa,
  cheques 3b e 3c de `conferir_fidelidade`).
- **Padrões a seguir:** peça fixa no orçamento como as invioláveis (`_orcar`).
- **Testes obrigatórios:** `tests/test_entrada_narrada.py`.
- **Não mexer em:** o formato de `entrada_deterministica` e o digest de becos.
