# Decisões Arquiteturais (ADR)

Índice das decisões deste projeto. **Leia antes de mudar stack, schema, auth, contrato de API
ou adicionar dependência.** Se sua tarefa contradiz um ADR vivo, PARE e pergunte.

Formato: MADR 4.0.0 adaptado ao pt-BR. Modelo em [`template.md`](template.md). Crie com a
skill `/novo-adr`.

Este índice é auditado só quanto à **PRESENÇA**: todo ADR precisa estar listado aqui pelo
nome do arquivo. O `Status` desta tabela **não** é comparado com o frontmatter — se
divergirem, é o frontmatter que vale, porque o hook `SessionStart` injeta o índice a partir
dos **arquivos**, nunca desta tabela. A contagem POR STATUS ("N ADRs, M `accepted`") é
auditada no `README.md` da **raiz** do projeto, não neste arquivo — escrever essa frase aqui
não é conferida por nada.

| ADR | Título                | Status   |
| --- | --------------------- | -------- |
| [0001](0001-exemplo.md) | {problema + solução} | proposed |
<!-- ↑ linha de exemplo, de propósito NÃO comentada. Já foi comentário HTML, e o cheque de
     presença do auditor lia o arquivo como texto puro — o comentário SATISFAZIA
     `f.name in texto_indice` sem nenhuma linha visível na tabela (medido: a auditoria
     aprovava com "índice sincronizado" e a tabela ficava com zero linhas). O auditor agora
     ignora comentário HTML antes desse cheque, então a linha comentada voltaria a reprovar
     — e o CI cria `0001-exemplo.md` a partir deste `template.md` para testar a auditoria de
     ponta a ponta, então o link é válido no consumidor sintético. Um projeto recém-clonado,
     sem nenhum ADR ainda, fica com este link sem arquivo correspondente: ao criar o
     ADR-0001 de verdade com `/novo-adr`, SUBSTITUA esta linha pela real — não adicione uma
     segunda. -->

## Status

| Status        | Significado                                                       |
| ------------- | ----------------------------------------------------------------- |
| `proposed`    | escrito, aguardando aprovação do humano                           |
| `accepted`    | aprovado, ainda não implementado                                  |
| `implemented` | aprovado e no código                                              |
| `superseded`  | **não siga** — outro ADR o substituiu, veja `substituido-por:`     |
| `deprecated`  | **não siga** — não vale mais, e nada o substituiu                  |

`superseded` **exige** `substituido-por:` no frontmatter — ADR morto sem substituto
declarado deixa o índice injetado sem ter o que apontar, e a auditoria reprova.
`deprecated` é o status de quem **não tem** substituto: não leva `substituido-por:`, e a
auditoria exige o motivo no CORPO do ADR em vez disso. Supersessão é **bidirecional**: o
novo declara `substitui:`, o antigo declara `substituido-por:`.

## Por domínio

<!-- Caminho natural de quem procura "os ADRs de tal assunto". ADR morto aqui precisa de
     marca explícita, derivada do frontmatter — `0007 (superada → 0023)` quando `superseded`
     com substituto, `0007 (deprecated)` quando não há substituto — senão o leitor recebe o
     morto e o vivo com o mesmo peso. A auditoria verifica. -->

<!-- - **{domínio}:** 0001 -->
<!-- ↑ linha de exemplo, comentada: nenhum domínio real existe ainda no template, e — ao
     contrário da linha do índice acima — nada no CI monta um consumidor que dependa desta
     lista estar preenchida. Descomente e ajuste ao classificar o primeiro ADR de verdade. -->

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
