# Evals das skills

Casos do `claude plugin eval` para as skills deste plugin. Rodam **localmente, à mão** — não
no CI: cada caso é uma sessão `claude -p` de verdade, três vezes, com e sem o plugin, na sua
credencial (decisão de 2026-10-09; ver o diário).

Por que existem: as skills nunca tinham sido medidas. O gatilho do `/novo-adr` incluía
"comentário 'por quê' com mais de 5 linhas", o `src/` tinha 64 blocos assim e o repositório
tinha 1 ADR — sem eval, não havia como saber se a skill não dispara ou se o critério está
errado.

## Casos

| Caso                           | O que mede                                                                   |
| ------------------------------ | ---------------------------------------------------------------------------- |
| `novo-adr-dispara`             | decisão de dependência em linguagem natural → `/novo-adr` dispara, cria só o 0002, `proposed`, no índice, auditoria verde |
| `novo-adr-quase`               | bugfix com a isca "decidi" → a skill **não** dispara e o bug é consertado     |
| `novo-adr-comentario-longo`    | pedido de código com um "por quê" de três alternativas medidas, sem a palavra decisão → `/novo-adr` dispara, cria o 0002 e o código aponta para ele |
| `encerrar-sessao-registra`     | fim de sessão com mudança e abordagem abandonada → uma entrada nova, beco no formato `→ falhou porque … **Não repetir:** …`, `### Retomar com` |
| `encerrar-sessao-sem-mudanca`  | fim de sessão só de leitura → nenhuma entrada, e a resposta diz por quê       |
| `encerrar-sessao-cede`         | projeto com `diario.skill_de_encerramento` → a skill cede a vez e aponta o comando do projeto |
| `encerrar-sessao-carrega-pendencias` | entrada anterior com dois `- [ ]`, a sessão fecha um → a entrada nova traz `Aberto / Próximo passo` com o outro ainda aberto e o fechado fora da lista aberta (ADR-0008) |

Cada caso monta um consumidor sintético com `_comum/base.sh` — o mesmo montador
(`_comum/consumidor.sh`) que o job `autotestes` do CI usa — e copia o pacote para a raiz do
workspace, porque a sessão da eval não recebe `PYTHONPATH` (`env` só aceita `EVAL_*`) e o
passo de auditoria das skills precisa dele. `.eval-diario.md` é um symlink para o arquivo do
mês: o nome real depende de quando a eval roda, e os graders precisam de um caminho fixo.

## Linha de base (2026-10-09, Claude Code 2.1.295)

| Caso | Com plugin | Sem plugin | O que a diferença é |
| --- | --- | --- | --- |
| `novo-adr-dispara` | 1,0 — 3/3, skill disparou 3/3, ~10 turnos | 0,8 — 0/3, ~20 turnos | sem o plugin o agente também cria o ADR (o índice do projeto ensina), mas grava `status: accepted` — aprova a própria decisão — e gasta o dobro de turnos. Conferido no trace de uma rodada com `--keep-temp` |
| `novo-adr-quase` | 1,0 — nenhum falso disparo em 3 | 1,0 | — |
| `novo-adr-comentario-longo` | 1,0 — skill disparou 3/3 | 0,33 — nenhum ADR em 3 | com a skill, o porquê vai para o ADR e o código fica com 4 linhas e o caminho dele; sem ela, o porquê fica só no comentário |
| `encerrar-sessao-registra` | 1,0 — 3/3 | 0,0 | sem o plugin, nenhuma entrada nova no arquivo do diário em 3 de 3 — onde o agente registrou não foi conferido |
| `encerrar-sessao-cede` | 1,0 — 3/3 | 0,0 | sem o plugin não há o que ceder: o agente escreve a entrada em vez de apontar o `/handoff` |
| `encerrar-sessao-sem-mudanca` | 1,0 — 3/3 | 1,0 | — (o agente não registra sessão só de leitura, com ou sem a skill) |
| `encerrar-sessao-carrega-pendencias` | 1,0 — 3/3 | 1,0 | — o README do diário do consumidor e a seção da entrada anterior já bastam; o caso guarda o comportamento contra regressão (ADR-0008) |

Custo da rodada com baseline dos dois casos de `novo-adr`: US$ 3,19. O gatilho de 64 blocos
"por quê" com 1 ADR, que motivou estas evals, NÃO é explicado por a skill não disparar: ela
disparou em todas as rodadas em que a decisão foi dita.

`novo-adr-comentario-longo` (2026-10-09, mais US$ 2,51 entre rodadas de ajuste) testou o
critério "comentário com mais de 5 linhas" e não conseguiu isolá-lo: em 7 rodadas, com e sem
plugin, nenhum agente escreveu comentário com mais de 5 linhas — o mesmo porquê de três
fatos cabe em 3 ou 4. O que dispara a skill é a escolha entre alternativas descrita no
pedido (6 de 7 rodadas com o plugin). **Em aberto, para decidir antes de mexer na descrição:**
a própria skill manda não criar ADR para "escolha reversível em minutos", e um tamanho de
lote é isso — o disparo aqui pode ser falso positivo, e o caso hoje o trata como acerto.

Custo da rodada com baseline dos quatro casos de `encerrar-sessao`: US$ 3,87, mais US$ 2,21 do
ajuste e da nova rodada de `sem-mudanca` e `carrega-pendencias`. A primeira rodada de `sem-mudanca` com
plugin estourou 300 s nas três execuções por queda de rede (os juízes falharam com
`ENOTFOUND` na mesma janela), não pelo plugin.

## Rodar

Sempre `--no-publish` (o relatório HTML é publicado no claude.ai por padrão) e sempre um teto
de custo. `--scaffold` executa os `scaffold.sh` daqui como você; `--trust-plugin` pula a
confirmação de diretório de plugin.

```bash
# fumaça: valida scaffolds e graders, uma rodada, sem baseline, modelo barato
claude plugin eval . --scaffold --trust-plugin --allow-tools Write Edit Bash \
  --runs 1 --ablation none --no-publish --model haiku --max-cost-usd 3 -j 3

# disparo do /novo-adr contra o baseline sem plugin (o Δ é o que a skill contribui)
claude plugin eval . --case 'novo-adr-*' --scaffold --trust-plugin --allow-tools Write Edit Bash \
  --no-publish --max-cost-usd 5 -j 3
```

O código de saída olha só o braço COM plugin (`--threshold`, 1.0 por padrão); o Δ não muda o
código de saída. Para comparar, leia o `aggregate-result.json` em `evals/results/<data>/`
(ignorado pelo git).

## Ao escrever um caso

- O prompt fala como um usuário fala — não nomeia a skill — e traz todos os insumos: o modo
  `-p` não tem como responder pergunta.
- Grader grátis primeiro (`regex`, `file_exists`, `tool_used`); no máximo um `llm` por caso.
- `---` dentro de um `pattern` quebra o frontmatter do grader: escreva `-{3}`.
- `file_exists` só vê arquivo CRIADO na run; arquivo modificado se lê com
  `target: { source: file, path: … }`.
- "Não disparou" é `tool_used` com `min: 0`, `max: 0` e `arm: both`, senão ele é excluído da
  nota nos dois braços.
