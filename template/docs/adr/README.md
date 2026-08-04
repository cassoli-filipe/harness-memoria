# Decisões Arquiteturais (ADR)

Índice das decisões deste projeto. **Leia antes de mudar stack, schema, auth, contrato de API
ou adicionar dependência.** Se sua tarefa contradiz um ADR vivo, PARE e pergunte.

Formato: MADR 4.0.0 adaptado ao pt-BR. Modelo em [`template.md`](template.md). Crie com a
skill `/novo-adr`.

Este índice é auditado contra os arquivos: todo ADR precisa estar listado aqui, e a contagem
por status precisa bater. O que o hook `SessionStart` injeta no contexto vem dos **arquivos**,
não desta tabela — então uma tabela desatualizada não engana o agente, mas reprova o build.

| ADR                        | Título                | Status   |
| -------------------------- | --------------------- | -------- |
| [0001](0001-exemplo.md)    | {problema + solução}  | proposed |

## Status

| Status        | Significado                                                       |
| ------------- | ----------------------------------------------------------------- |
| `proposed`    | escrito, aguardando aprovação do humano                           |
| `accepted`    | aprovado, ainda não implementado                                  |
| `implemented` | aprovado e no código                                              |
| `superseded`  | **não siga** — outro ADR o substituiu, veja `substituido-por:`     |
| `deprecated`  | **não siga** — não vale mais, e nada o substituiu                  |

`superseded` e `deprecated` exigem `substituido-por:` no frontmatter — ADR morto sem
substituto declarado deixa o índice injetado sem ter o que apontar, e a auditoria reprova.
Supersessão é **bidirecional**: o novo declara `substitui:`, o antigo declara
`substituido-por:`.

## Por domínio

<!-- Caminho natural de quem procura "os ADRs de tal assunto". ADR morto aqui precisa de
     marca explícita — `0007 (superada → 0023)` — senão o leitor recebe o morto e o vivo com
     o mesmo peso. A auditoria verifica. -->

- **{domínio}:** 0001

## Regras

1. **Corpo de ADR `accepted` ou `implemented` é imutável.** Mudou de ideia? Crie um novo que
   o substitua. Editar o corpo apaga o registro de por que a decisão foi tomada com a
   informação da época.
2. **Numeração contígua**, 4 dígitos, a partir de `0001`.
3. **`## Regra` no topo** (até 5 linhas) a partir do número configurado em
   `adr.primeiro_com_regra`. Não se retrofita nos anteriores — isso violaria a regra 1.
4. **`## Plano de Implementação`** obrigatória em status vivo, se configurada.
5. **Alternativa rejeitada precisa do porquê.** É a seção de maior valor: é o que impede a
   alternativa de voltar em seis meses.
