# Diário de Engenharia

Registro append-only de sessões de trabalho neste repositório. Serve para **retomar
contexto**, não para provar esforço. Decisão arquitetural **não** mora aqui — mora em
[`docs/adr/`](../adr/README.md); aqui vai só o ID (`ADR-0001`).

Quem escreve: o hook `SessionEnd`, automaticamente, ao fim de cada sessão (grava o piso
determinístico: arquivos, comandos, diffstat e ADRs tocados). A skill `/encerrar-sessao`
permite registrar deliberadamente ANTES de sair, com o contexto ainda completo e a
narrativa da sessão — é o caminho primário para uma entrada rica, porque a narrativa por
LLM no próprio hook não cabe no orçamento de tempo que a plataforma dá a um hook de plugin.
Entrada escrita à mão também é bem-vinda.

Quem lê: o hook `SessionStart` reinjeta a última entrada no início de cada sessão —
inclusive depois de compactação de contexto — e, junto, um digest dos itens de **Tentativas
descartadas** de todos os meses, inclusive de `arquivo/`. É por isso que o diário tem função
em vez de ser arquivo morto.

Corolário prático: **o que você escrever em "Tentativas descartadas" é o que tem mais chance
de chegar ao contexto de uma sessão futura.** Escreva a lição em imperativo e curta, e ponha
a lição APÓS o negrito (`**Não repetir:** {lição}`) — é essa metade do item que o mecanismo
preserva quando o digest precisa encurtar o resto.

## Regras

1. **Um arquivo por mês**: `AAAA-MM.md`. Mês corrente nesta pasta; meses fechados em
   `arquivo/`.
2. **Teto de 400 linhas por arquivo.** Ao estourar, feche o mês e abra `AAAA-MMb.md`
   (depois `c`, `d`, … até `j`). Se até o décimo arquivo do mês estourar, não há próximo
   sufixo: mova os mais antigos do mês para `arquivo/` (o digest de becos varre `arquivo/`
   também, então a ordem não muda) ou suba `diario.teto_linhas` no `.claude/harness.json`.
3. **Máximo ~25 linhas por entrada.** Se precisar de mais, o conteúdo é ADR, não diário.
4. **Append-only, no FIM do arquivo.** Nunca edite entrada passada; corrija com nova entrada
   apontando para a antiga. A **ordem cronológica é obrigatória e auditada**: a reinjeção
   pega o último bloco `## AAAA-MM-DD` do arquivo, então entrada nova no topo faria a
   próxima sessão receber a mais velha, em silêncio.
5. **Datas absolutas.** `2026-08-04`, nunca "ontem" ou "semana passada". O cabeçalho de toda
   entrada é `## AAAA-MM-DD — …`: sem a data, o texto não abre entrada nova — cola na
   entrada anterior, em silêncio, e a auditoria reprova o cabeçalho sem data.
6. **Sem entrada para sessão sem resultado.** O diário registra mudança de estado, não
   presença.
7. **Sem segredo, token, URL interna ou dado pessoal.**
8. **Números, não adjetivos.** "142 testes passando" em vez de "funcionando bem".

## Formato de uma entrada

````markdown
## AAAA-MM-DD — {título imperativo do que mudou}

**Estado:** concluído | parcial | bloqueado
**Escopo:** `caminho/tocado/`
**ADRs:** ADR-0001 (implementa) · ADR-0003 (contradiz → superseded)

### O que foi feito

- {mudança concreta e verificável}

### Por quê

{1–3 frases. O gatilho. Se a justificativa for arquitetural, faça ADR e cite só o ID.}

### Como (o não-óbvio)

- {decisão de implementação que um leitor futuro não deduziria do diff}

### Tentativas descartadas

- {abordagem} → falhou porque {razão}. **Não repetir:** {lição em imperativo}

### Verificação

- {evidência com número; comandos rodados e resultado}

### Aberto / Próximo passo

- [ ] {ação seguinte, ordenada}
- [ ] Bloqueado por: {o quê}

### Retomar com

```bash
{comandos exatos para voltar a este ponto}
```
````

A seção **Tentativas descartadas** é a de maior retorno: é o que impede o próximo agente de
repetir um beco já explorado. O `SessionStart` a preserva mesmo quando a entrada não cabe
inteira no contexto — o recorte descarta seção inteira por prioridade, e "O que foi feito"
sai primeiro porque é a única reconstruível do `git log`.

## Rotação

No dia 1 de cada mês. A partir do dia 3 a auditoria **reprova o build** — aviso pendente por
semanas foi o que deixou o ponteiro do CLAUDE.md apontando para um arquivo cujo head já
estava três arquivos atrás:

```bash
git mv docs/diario/AAAA-MM*.md docs/diario/arquivo/
# criar docs/diario/AAAA-MM.md (mês novo) com o cabeçalho
# atualizar o ponteiro do mês corrente no CLAUDE.md
```
