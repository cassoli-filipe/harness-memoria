# Decisões Arquiteturais (ADR)

Índice das decisões deste repositório. **Leia antes de mudar contrato de config, formato do
diário, formato de ADR ou a divisão mecanismo/política do harness.** Se sua tarefa contradiz
um ADR vivo, PARE e pergunte.

Formato: MADR 4.0.0 adaptado ao pt-BR. Modelo em [`template.md`](template.md). Crie com a
skill `/novo-adr`.

Este índice é auditado contra os arquivos: todo ADR precisa estar listado aqui pelo nome do
arquivo. O que o hook `SessionStart` injeta no contexto vem dos **arquivos**, não desta
tabela — então uma tabela desatualizada não engana o agente, mas reprova o build.

| ADR                                                | Título                                                                    | Status      |
| -------------------------------------------------- | ------------------------------------------------------------------------- | ----------- |
| [0001](0001-auto-hospedagem.md)                     | Auto-hospedar o harness de memória neste repositório                      | accepted    |
| [0002](0002-piso-deterministico-no-session-end.md)  | Gravar o piso determinístico no SessionEnd e deixar a narrativa opt-in    | implemented |
| [0003](0003-reafirmacao-async.md)                   | Rodar a reafirmação intra-sessão como hook async                          | implemented |
| [0004](0004-orcamento-do-contexto-injetado.md)      | Orçar o bloco injetado pelo teto de 10.000 ch; SubagentStart reduzido     | implemented |
| [0005](0005-auditor-corrige-o-mecanico.md)          | Deixar o auditor corrigir o que é mecânico (`--corrigir`)                 | implemented |
| [0006](0006-reinjetar-a-ultima-entrada-narrada.md)  | Reinjetar a última entrada NARRADA e só resumir os registros automáticos  | implemented |
| [0007](0007-sensores-no-stop.md)                    | Verificar o turno com sensores do projeto no hook `Stop`                  | implemented |
| [0008](0008-herdar-pendencias-abertas.md)          | Herdar os itens abertos quando a última narrada não traz a lista          | implemented |

## Status

| Status        | Significado                                                       |
| ------------- | ----------- |
| `proposed`    | escrito, aguardando aprovação do humano                           |
| `accepted`    | aprovado, ainda não implementado                                  |
| `implemented` | aprovado e no código                                              |
| `superseded`  | **não siga** — outro ADR o substituiu, veja `substituido-por:`     |
| `deprecated`  | **não siga** — não vale mais, e nada o substituiu                  |

`superseded` exige `substituido-por:` no frontmatter — ADR morto sem substituto declarado
deixa o índice injetado sem ter o que apontar, e a auditoria reprova. `deprecated` é o
status de quem morreu SEM substituto: o motivo vai no corpo do ADR, não num campo.
Supersessão é **bidirecional**: o novo declara `substitui:`, o antigo declara
`substituido-por:`.

## Por domínio

<!-- Caminho natural de quem procura "os ADRs de tal assunto". ADR morto aqui precisa de
     marca explícita — `0007 (superada → 0023)` — senão o leitor recebe o morto e o vivo com
     o mesmo peso. A auditoria verifica. -->

- **Harness (auto-hospedagem):** 0001
- **Hooks de sessão:** 0002, 0004, 0006, 0008
- **Reafirmação:** 0003
- **Auditoria:** 0005
- **Sensores (verificação no loop):** 0007

## Regras

1. **Corpo de ADR `accepted` ou `implemented` é imutável.** Mudou de ideia? Crie um novo que
   o substitua. Editar o corpo apaga o registro de por que a decisão foi tomada com a
   informação da época.
2. **Numeração contígua**, 4 dígitos, a partir de `0001`.
3. **`## Regra` no topo** (até 5 linhas) a partir do número configurado em
   `adr.primeiro_com_regra`. Não se retrofita nos anteriores — isso violaria a regra 1. Hoje
   `adr.primeiro_com_regra` é `null`: a convenção ainda não começou.
4. **`## Plano de Implementação`** é seção obrigatória do `template.md` deste repositório,
   presente em todo ADR independentemente do status.
5. **Alternativa rejeitada precisa do porquê.** É a seção de maior valor: é o que impede a
   alternativa de voltar em seis meses.
