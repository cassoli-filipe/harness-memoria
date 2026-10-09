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
| `encerrar-sessao-registra`     | fim de sessão com mudança e abordagem abandonada → uma entrada nova, beco no formato `→ falhou porque … **Não repetir:** …`, `### Retomar com` |
| `encerrar-sessao-sem-mudanca`  | fim de sessão só de leitura → nenhuma entrada, e a resposta diz por quê       |
| `encerrar-sessao-cede`         | projeto com `diario.skill_de_encerramento` → a skill cede a vez e aponta o comando do projeto |

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
| os três de `encerrar-sessao` | 1,0 (fumaça, haiku, 1 rodada, sem baseline) | — | ainda sem baseline |

Custo da rodada com baseline dos dois casos de `novo-adr`: US$ 3,19. O gatilho de 64 blocos
"por quê" com 1 ADR, que motivou estas evals, NÃO é explicado por a skill não disparar: ela
disparou em todas as rodadas em que a decisão foi dita. O mais provável é o critério do
gatilho ("comentário com mais de 5 linhas") não corresponder ao estilo da casa, onde todo
comentário longo carrega medição — vale um caso de eval com esse gatilho antes de mexer na
descrição da skill.

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
