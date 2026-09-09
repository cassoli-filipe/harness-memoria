---
status: accepted
data: 2026-09-08
---

# ADR-0001 — Auto-hospedar o harness de memória neste repositório

## Contexto

Até esta mudança, `python -m harness_memoria.auditar --projeto .` respondia "nada para
auditar" e os seis hooks do próprio harness saíam vazios contra a raiz do repositório que
os desenvolve: não existia `CLAUDE.md`, `.claude/harness.json`, `docs/adr/` nem
`docs/diario/`. O projeto que audita a documentação de outros nunca auditava a própria.

Os sete commits mais recentes do repositório — "Contar só os caminhos do trecho que casou,
não os do comando inteiro", "Honrar `permitido_em` em guardas.comandos, e reprovar chave
desconhecida em regra", "Convenção e default no lugar de uma camada global de política",
"Dar limiar à conformidade com template, para corpus que já tem história", "Derivar o ADR
de exemplo do CI a partir do próprio template" — são decisões arquiteturais de verdade
(mudam contrato de config, mudam o que a auditoria exige) que hoje só sobrevivem como
assunto de commit. Nenhuma tem registro em ADR, e nada neste repositório força a disciplina
que o próprio pacote vende a quem o instala.

## Fatores de decisão

- O plugin já fica habilitado no nível do usuário durante o desenvolvimento deste próprio
  repositório, então os seis hooks já rodam a cada sessão — hoje contra um projeto que
  "não adotou o harness", exatamente o caminho de gate que o `ci.yml` testa contra
  `/tmp/alheio`.
- Custo medido por escrita com o plugin habilitado e SEM config: 361 ms (processo já é
  gerado de qualquer forma). COM config: 461 ms — ~100 ms de diferença, não os ~360 ms que
  a primeira estimativa presumia. O lote 2 (pré-gate) reduz isso ainda mais.
- Com `CLAUDE.md` viabilizando a reafirmação intra-sessão, a primeira frase de cada
  inviolável tem de caber em `reafirmacao.teto_item_chars` (150 chars) e a seção não pode
  passar de `reafirmacao.max_itens` (8) sem que a auditoria denuncie o corte.
- A partir do dia `diario.dia_limite_rotacao` (3) do mês, a rotação pendente do diário
  reprova o build — a régua que o harness aplica a todo consumidor passa a valer para ele
  mesmo.

## Decisão

Adotar o harness em duas etapas, na mesma sessão: **etapa 1** — `.claude/harness.json`
mínimo, `CLAUDE.md` com as invioláveis extraídas dos princípios já documentados nos
docstrings do pacote, `docs/diario/` com o mês corrente — e **etapa 2** — `docs/adr/` com
este ADR-0001 e o passo de auditoria no CI (`PYTHONPATH=src python -m
harness_memoria.auditar --projeto .`). As duas entram juntas porque a seção "Qual ADR ler"
do `CLAUDE.md`, que a etapa 1 já expõe, reprova com "tabela vazia"
(`auditar_mapa_de_adr_por_caminho`) sem nenhum ADR vivo para apontar — adiar a etapa 2
adiaria o mesmo trabalho, com uma auditoria vermelha no meio do caminho.

Este ADR fica em `status: proposed`: a skill `/novo-adr` proíbe que um agente marque um ADR
como `accepted` por conta própria, e esta instalação não é exceção — cabe ao humano
promover o status quando revisar a adoção.

## Alternativas consideradas

### Não adotar

**Rejeitada porque** deixaria o harness sem o teste mais direto da própria promessa: os
seis hooks e o motor de auditoria só são exercitados contra um corpus real, com história e
becos sem saída de verdade, quando o corpus é este repositório. Até aqui o único corpus
real usado nos testes era a fixture sintética que o `ci.yml` monta em `/tmp/proj`.

### Etapa 1 sem etapa 2 (sem `docs/adr/`)

**Rejeitada porque** a seção "Qual ADR ler" do `CLAUDE.md`, necessária para a etapa 1 se
sustentar sozinha, reprova com "tabela vazia" enquanto não houver nenhum ADR vivo para
apontar — a etapa 2 não é opcional, é a etapa 1 completa.

## Consequências

**Boas:** o harness passa a auditar a si mesmo em todo `git push`. A extração de
invioláveis, o mapa caminho→ADR e o cheque de conformidade com template deixam de rodar só
contra a fixture sintética do CI e passam a rodar contra um corpus real que cresce com o
projeto.

**Ruins, e aceitas:** a partir do dia 3 de cada mês, esquecer a rotação do diário
(`git mv docs/diario/AAAA-MM*.md docs/diario/arquivo/` + criar o mês novo) reprova o build
deste próprio repositório — o mesmo incômodo que o harness impõe a todo consumidor que o
adota.

## Quando revisitar

Se a seção de invioláveis do `CLAUDE.md` deste repositório precisar de mais de 8 itens para
descrever o projeto com honestidade, ou se `CLAUDE.md` estourar 150 linhas — sinal de que a
política cresceu além do que a reafirmação intra-sessão consegue carregar por escrita, e
parte do conteúdo deveria virar um novo ADR em vez de crescer ali.

## Plano de Implementação

- **Arquivos a tocar:** `CLAUDE.md`, `.claude/harness.json`, `docs/adr/README.md`,
  `docs/adr/template.md`, `docs/adr/0001-auto-hospedagem.md`, `docs/diario/README.md`,
  `docs/diario/2026-09.md`, `.github/workflows/ci.yml` (passo de auditoria do próprio
  repositório).
- **Padrões a seguir:** o mesmo `template/` que o harness distribui para consumidores —
  este repositório não inventa um formato próprio de ADR ou de diário.
- **Testes obrigatórios:** `python -m harness_memoria.auditar --projeto .` saindo 0 (com
  `PYTHONPATH=src`); os seis autotestes de hook (`--autoteste --projeto .`) sem falha de
  fidelidade.
- **Não mexer em:** o conteúdo de `template/` — é o instalador para outros projetos, não a
  config deste repositório.
