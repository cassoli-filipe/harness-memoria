---
name: harness-init
description: Instalar o harness de memória neste projeto — cria a configuração, a pasta de ADR e o diário, e adapta o CLAUDE.md existente. Use ao adotar o harness num projeto novo ou ao migrar um projeto que já tem ADRs ou diário em outro formato.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion
---

# Instalar o harness neste projeto

O harness tem três camadas: **mecanismo** (o plugin, já instalado se você está lendo isto),
**política** (`.claude/harness.json` + a seção de invioláveis do `CLAUDE.md`) e **conteúdo**
(`docs/adr/`, `docs/diario/`). Esta skill cria a política e o esqueleto do conteúdo.

**Nunca sobrescreva conteúdo existente em silêncio.** Um projeto com 22 ADRs e um diário de
253 linhas é o caso normal, não a exceção — e o histórico dele vale mais que a convenção do
harness.

## Fase 0 — Levantar o que já existe

Antes de escrever qualquer arquivo, meça:

```bash
ls docs/ 2>/dev/null
ls docs/adr/ docs/diario* 2>/dev/null
wc -l CLAUDE.md 2>/dev/null
```

Responda para si mesmo, com números:

1. **Existe `CLAUDE.md`?** Quantas linhas? Ele tem uma seção de regras/guardrails?
2. **Existem ADRs?** Quantos, em que pasta, e em que formato o cabeçalho está — frontmatter
   YAML ou prosa? Existe índice?
3. **Existe diário?** Arquivo único ou por mês? A entrada mais nova está no **topo** ou no
   **fim**?
4. **Que stack é?** (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`…) — decide os
   formatadores.
5. **Existe CI?** (`.github/workflows/`) — decide se a auditoria tem onde reprovar.

Se qualquer resposta indicar conteúdo existente em formato diferente, **pare e apresente um
plano de migração** antes de escrever. Migração de histórico é decisão do usuário, não sua.

## Fase 1 — A seção de invioláveis

Esta é a parte que não se automatiza sem ler. A reafirmação intra-sessão **extrai** as regras
do `CLAUDE.md`; o contrato é:

> A primeira frase de cada item da seção de invioláveis é a regra.

- **Já existe uma seção assim?** (`## Regras invioláveis`, `## Guardrails`, `## Regras`…)
  Configure `reafirmacao.secao` com o título dela — o casamento é por prefixo, então
  `## Regras invioláveis` acha `## Regras invioláveis (guardrails)`.
- **A seção tem sub-blocos?** Se ela divide em proibição / recomendação (`**NUNCA**` /
  `**SEMPRE**`), aponte `reafirmacao.sub_bloco` para o de proibição absoluta. Só proibição
  cuja violação é **silenciosa** merece reafirmação; o resto tem guarda mecânica ou não é
  urgente.
- **Alguma primeira frase não cabe em uma linha?** Rode a auditoria: ela diz quais e quantos
  chars. Corrija **encurtando a primeira frase** — normalmente é trocar um `;` por `.` e
  capitalizar. O resto do raciocínio continua no item.
- **Não existe seção nenhuma?** Não invente regra. Pergunte ao usuário quais são as
  proibições absolutas do projeto, uma por vez, e escreva com ele. Se ele não tiver
  nenhuma, configure `reafirmacao.habilitado: false` — melhor desligado que genérico.

## Fase 2 — Escrever a config

Crie `.claude/harness.json`. Comece **mínimo**: todo campo tem default, e config que repete
o default é config que mente sobre ter sido pensada. Escreva só o que difere.

```json
{
  "projeto": "Nome do projeto",
  "reafirmacao": { "sub_bloco": "**NUNCA**" },
  "formatadores": [{ "extensoes": [".py"], "comando": ["ruff", "format", "{arquivo}"] }]
}
```

Campos que costumam precisar de valor explícito na migração de projeto existente:

| Campo                          | Quando                                                         |
| ------------------------------ | -------------------------------------------------------------- |
| `adr.secao_plano: null`        | os ADRs existentes não têm `## Plano de Implementação`          |
| `adr.primeiro_com_regra`       | o número a partir do qual `## Regra` passa a valer (não retrofita) |
| `diario.injetar_ultima_entrada: false` | outro mecanismo do projeto já injeta a narrativa da sessão anterior |
| `guardas.caminhos`             | há tipo de arquivo que nunca deve ser versionado neste projeto  |
| `auditoria.checks_do_projeto`  | há fronteira estrutural própria a verificar                    |

**A presença deste arquivo é o gate**: sem ele todo hook do harness é inerte. Criá-lo é o
ato de adotar.

## Fase 3 — O esqueleto do conteúdo

Copie de `${CLAUDE_PLUGIN_ROOT}/template/` o que faltar, **sem sobrescrever**:

- `docs/adr/README.md` — índice em tabela `| ADR | Título | Status |`
- `docs/adr/template.md`
- `docs/diario/README.md` — as regras do diário
- `docs/diario/AAAA-MM.md` do mês corrente, com o cabeçalho

Se o projeto já tem ADRs sem índice, **gere o índice a partir dos arquivos** — não peça ao
usuário para escrever 22 linhas de tabela à mão.

## Fase 4 — O mapa caminho→ADR

Adicione ao `CLAUDE.md` a seção `### Qual ADR ler — por caminho que você vai tocar`, com uma
tabela `| Caminho | ADRs |`. Ela existe porque o corpus de ADR maduro custa dezenas de
milhares de tokens: "leia o índice antes de mexer no schema" é instrução que ninguém executa
inteira. Retrieval por caminho troca o corpus por 5 a 7.

Preencha lendo os ADRs, não adivinhando. Cada caminho tem de existir e cada ADR citado tem de
estar vivo — a auditoria verifica os dois.

## Fase 5 — Ligar o CI

Se o projeto tem CI, adicione o passo da auditoria **primeiro** no workflow: é barato, e se a
documentação dessincronizou não faz sentido gastar minuto de build.

```yaml
- name: Auditar documentação e fronteiras
  run: python -m harness_memoria.auditar
```

Precisa da dependência:

```bash
uv add --dev "harness-memoria @ git+ssh://git@github.com/cassoli-filipe/harness-memoria"
```

Se o projeto **não** tem CI, diga isso ao usuário explicitamente: a auditoria vai rodar só na
máquina dele, e cheque que não reprova nada é cheque que se aprende a ignorar.

## Fase 6 — Verificar de verdade

```bash
python -m harness_memoria.auditar
```

E os cinco autotestes, apontados para este projeto:

```bash
for h in session_start session_end reafirmar guardar formatar; do
  python "${CLAUDE_PLUGIN_ROOT}/src/harness_memoria/hooks/$h.py" --autoteste --projeto .
done
```

O do `session_start` confere **fidelidade** — que o bloco injetado entrega o que promete. O do
`reafirmar` imprime as invioláveis extraídas: **leia a lista** e confirme que cada linha é
uma regra de verdade, não um fragmento. É a única verificação desta instalação que precisa de
olho humano.

## Fase 7 — Registrar

Isto é adoção de padrão arquitetural: vale um ADR no projeto. Use `/novo-adr`. Se o projeto
já tinha um harness próprio, o ADR novo **estende ou substitui** o antigo — não deixe os dois
descrevendo mecanismos concorrentes sem dizer qual vale.
