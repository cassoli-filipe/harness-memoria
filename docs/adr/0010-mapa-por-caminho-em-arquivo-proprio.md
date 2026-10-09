---
status: implemented
data: 2026-10-09
emenda: [ADR-0009]
---

# ADR-0010 — Deixar o mapa por caminho morar num arquivo próprio, apontado pelo CLAUDE.md

## Contexto

O ADR-0009 passou a entregar, a cada escrita, os ADRs que o mapa "Qual ADR ler" aponta para
o caminho, e o auditor avisa a linha do mapa com mais de 10 ADRs. A divisão dessas linhas
grossas foi aplicada em 2026-10-09 nos três consumidores que as tinham, e o mapa fino não
coube no `CLAUDE.md`:

| Projeto | `CLAUDE.md` antes | com o mapa fino | teto |
| --- | --- | --- | --- |
| rede-inspira | 150 | 203 | 150 |
| slice | 150 | 173 | 150 |
| ValidaNI | 91 | 146 | 150 |

O teto existe porque o `CLAUDE.md` é carregado em toda sessão. Um mapa de 60 linhas ali paga
contexto o tempo todo para servir o hook, que só precisa dele na hora da escrita.

Também medido no mesmo dia: chave desconhecida em qualquer seção do `harness.json` invalida a
config inteira (`adr tem chave(s) desconhecida(s) ['mapa']`), e com a config inválida todo
hook da versão instalada fica inerte. A guarda deixou passar uma escrita em `.env`.

## Fatores de decisão

- O mapa fino tem de caber sem estourar o teto de 150 linhas do `CLAUDE.md`.
- Um consumidor que adota o mapa em arquivo não pode desligar os hooks de quem ainda roda o
  plugin antigo.
- O hook, o auditor e o `--propor-mapa` leem o mesmo mapa (ADR-0009).
- Quem lê o `CLAUDE.md` continua sabendo que o mapa existe e onde ele está.

## Decisão

A seção "Qual ADR ler" continua obrigatória no `CLAUDE.md`, e passa a poder trazer, no lugar
da tabela, um ponteiro para o arquivo que a traz: um link markdown ou um caminho entre crases
terminando em `.md` (por convenção, `docs/adr/mapa-por-caminho.md`). `adr.ler_mapa` usa a
tabela da seção quando ela existe; senão, segue o primeiro ponteiro e lê a seção "Qual ADR
ler" do arquivo apontado, ou a tabela do arquivo inteiro. O hook, o auditor e o
`--propor-mapa` passam a usar `ler_mapa`.

O auditor reprova o ponteiro para arquivo que não existe e confere o mapa no arquivo
apontado, com o nome dele nas mensagens.

## Alternativas consideradas

### Campo `adr.mapa` no `harness.json`

**Rejeitada porque** a versão instalada do plugin reprova chave desconhecida e, com a config
inválida, todos os hooks ficam inertes até alguém atualizar o plugin. Medido: a guarda deixou
passar escrita em `.env`. A convenção do ponteiro não muda o formato da config.

### Subir `auditoria.teto_claude_md` nos consumidores

**Rejeitada porque** o mapa passaria a ser carregado em toda sessão, que é o custo que o teto
existe para evitar. E o teto valeria menos em todo projeto que precisasse subi-lo.

### Manter as linhas grossas

**Rejeitada porque** é o custo que o ADR-0009 mediu: no ValidaNI, `apps/web/src/` com 58 ADRs
entrega ~54 mil caracteres ao longo de 10 escritas, quase tudo sem relação com o arquivo
editado.

### Pôr o mapa no `docs/adr/README.md`

**Rejeitada porque** o README é o índice auditado dos ADRs. Uma segunda tabela no mesmo
arquivo misturaria dois contratos verificados por cheques diferentes.

## Consequências

**Boas:** o mapa pode ser tão fino quanto o código pede, e o `CLAUDE.md` encolhe: a tabela
sai e fica uma linha. Quem roda o plugin antigo não é afetado: a versão anterior ao ADR-0009
não lê o mapa.

**Ruins, e aceitas:** o auditor de um consumidor que ainda usa o pacote anterior a esta
mudança no CI vê a seção sem tabela e reprova com "tabela vazia" até o pacote ser atualizado
(`uv lock --upgrade-package harness-memoria`). O agente não tem mais o mapa no contexto desde o
início da sessão; recebe os ADRs do caminho na hora da escrita (ADR-0009) e pode abrir o
arquivo.

## Quando revisitar

Se o `CLAUDE.md` deixar de ser carregado inteiro em toda sessão, ou se a plataforma passar a
carregar arquivos por caminho (regras com `paths:`), o mapa pode ir para lá.

## Plano de Implementação

Implementado no commit "Deixar o mapa por caminho morar num arquivo próprio, apontado pelo
CLAUDE.md". Aprovado pelo usuário em 2026-10-09.

- **Arquivos a tocar:** `src/harness_memoria/adr.py` (`ler_mapa`, `_linhas_do_mapa`),
  `src/harness_memoria/hooks/guardar.py`, `src/harness_memoria/auditar/__init__.py` (cheque do
  mapa), `src/harness_memoria/auditar/mapa.py` (`--propor-mapa`), skills `/harness-init` e
  `/auditar-docs`, `README.md`.
- **Padrões a seguir:** um leitor só do mapa para os três consumidores dele (ADR-0009).
- **Testes obrigatórios:** `tests/test_adr_por_caminho.py`: o ponteiro é seguido, a tabela no
  `CLAUDE.md` continua valendo, o hook entrega pelo mapa em arquivo, o auditor confere os
  caminhos do arquivo e reprova o ponteiro para arquivo inexistente.
- **Não mexer em:** o formato do `harness.json` e a obrigatoriedade da seção no `CLAUDE.md`.
