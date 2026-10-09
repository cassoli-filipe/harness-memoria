---
status: proposed
data: 2026-10-09
---

# ADR-0005 — Deixar o auditor corrigir o que é mecânico (`--corrigir`)

## Contexto

O CI do `main` ficou vermelho desde 2026-10-08 (run 37844763094) num commit que mudou uma
linha do README. A causa era o calendário: a partir do dia `diario.dia_limite_rotacao` (3)
de cada mês, a auditoria reprova enquanto o diário do mês anterior não é rotacionado, e
ninguém o tinha rotacionado.

A remediação era 100% derivável — mover `AAAA-MM*.md` do mês fechado para `arquivo/`, criar
o mês novo com o cabeçalho que `diario._cabecalho_mes` já escreve, trocar o ponteiro do
`CLAUDE.md` —, e mesmo assim dependia de alguém fazê-la à mão. A receita vivia em prosa em
dois lugares (a mensagem do auditor e a skill `/auditar-docs`), mais o comentário do
`ci.yml`. Vermelho por calendário ensina a ignorar o vermelho, que é o defeito que o auditor
existe para evitar (FUNDAMENTOS, princípio 9).

Havia ainda um buraco no cheque: o `anexar_entrada` do SessionEnd cria o arquivo do mês na
primeira entrada, e isso bastava para a auditoria passar com o mês velho ainda fora de
`arquivo/` e o ponteiro defasado.

## Fatores de decisão

- Só pode ser automática a correção que não exige julgamento: dada a mesma árvore, o mesmo
  resultado, e rodar duas vezes não faz nada na segunda.
- Nada pode reescrever o que é imutável por regra: corpo de ADR aceito e entrada passada do
  diário.
- A decisão de commitar é do humano — um auditor que commita sozinho tira dele a última
  leitura.
- O CI continua sendo a rede que pega quem esqueceu; corrigir dentro do CI esconderia o
  esquecimento num commit que ninguém revisa.
- Plugin e pacote atualizam por canais diferentes (commit × `uv.lock`), então uma skill nova
  pode chamar uma flag que o pacote instalado não conhece.

## Decisão

A CLI da auditoria ganha `--corrigir`: antes de auditar, aplica a parte **mecânica** do que
ela reprovaria e imprime cada ação sob `Correções mecânicas:`. "Mecânico" quer dizer
derivável sem julgamento, idempotente, sem tocar corpo de ADR nem entrada passada, sem
`git add` nem commit (só o rename que o próprio `git mv` registra). O CI nunca roda
`--corrigir`.

A primeira correção mecânica é a rotação do diário (`diario.planejar_rotacao`, que só lê, e
`diario.rotacionar`, que aplica): `git mv` quando o arquivo é rastreado, `rename` quando
não; mês novo criado sob lock; ponteiro do `CLAUDE.md` trocado só fora de cerca de código,
com o ponteiro com âncora (que cita uma entrada) indo para `arquivo/`; CRLF preservado.
Conflito em `arquivo/` e `CLAUDE.md` sem ponteiro nenhum ficam na lista de falhas para
decisão humana.

Opção desconhecida na CLI passa a sair com código 2, em vez de ser ignorada. Mês fechado
esquecido no topo da pasta passa a contar como rotação pendente.

## Alternativas consideradas

### O hook `SessionStart` rotaciona sozinho no primeiro arranque do mês

**Rejeitada porque** move arquivos versionados e reescreve o `CLAUDE.md` sem ninguém pedir,
no meio de qualquer trabalho em andamento — surpresa em escrita queima a confiança no
mecanismo do mesmo jeito que surpresa em bloqueio. O hook passa a AVISAR (ADR-0006); quem
corrige é um comando que alguém roda.

### Rebaixar a rotação para aviso, sem reprovar

**Rejeitada porque** troca CI vermelho por ponteiro defasado permanente — o incidente que
criou o dia limite foi justamente um aviso pendente por semanas, com o `CLAUDE.md` apontando
para um arquivo três arquivos atrás.

### Manter a receita manual, só melhorando o texto

**Rejeitada porque** a receita já estava escrita, em três lugares, e não foi seguida por um
mês. Instrução que depende de alguém lembrar é o que o harness inteiro existe para não
precisar.

## Consequências

**Boas:** a falha de calendário vira um comando. O plano de rotação é um objeto só, lido
pela auditoria, pelo `--corrigir` e pelo aviso do `SessionStart` — três descrições escritas
à parte divergiriam na primeira correção. O padrão fica disponível para a próxima correção
mecânica.

**Ruins, e aceitas:** o auditor passa a escrever no disco, o que ele nunca fazia. Consumidor
com mês fechado esquecido no topo passa a ver aviso, e falha a partir do dia 3, onde antes
passava. Um pacote anterior a esta mudança, chamado com `--corrigir`, agora falha com
"opção desconhecida" em vez de seguir — e a skill manda atualizar o pacote nesse caso.

## Quando revisitar

Quando aparecer uma segunda candidata a correção mecânica (é o momento de conferir se a
definição de "mecânico" aguenta), ou se um consumidor relatar uma rotação que precisou de
julgamento que o plano não previu.

## Plano de Implementação

Implementado no commit "Fazer a rotação do diário pela auditoria, com --corrigir".

- **Arquivos a tocar:** `src/harness_memoria/diario.py` (`PlanoDeRotacao`,
  `planejar_rotacao`, `rotacionar`, `_git_mv`, `_trocar_ponteiros`),
  `src/harness_memoria/auditar/__init__.py` (`Contexto.hoje`, `plano_de_rotacao`,
  `auditar_diario`, `auditar_claude_md`), `src/harness_memoria/auditar/__main__.py`.
- **Padrões a seguir:** `config._mascara_de_cerca` para decidir o que é ponteiro, a mesma
  régua que a auditoria usa.
- **Testes obrigatórios:** `tests/test_rotacao.py`.
- **Não mexer em:** corpo de ADR, entradas passadas do diário, `README.md` e `AGENTS.md`
  (ponteiro fora do `CLAUDE.md` fica para quem o escreveu).
