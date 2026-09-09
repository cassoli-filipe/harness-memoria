# harness-memoria

Plugin do Claude Code + pacote Python que reinjeta memória de projeto (ADR + diário de
engenharia) no contexto, reafirma regras invioláveis dentro da sessão, bloqueia tool calls
proibidas e audita documentação no CI. Este repositório usa o próprio harness em si mesmo
desde `docs/adr/0001-auto-hospedagem.md`.

## Regras invioláveis

**NUNCA**

- Importar biblioteca de terceiro em `src/harness_memoria/`. Os hooks rodam com o `python`
  do PATH, fora do venv do consumidor — um import de terceiro transforma "instalar o
  plugin" em "gerenciar um ambiente por projeto".
- Deixar um hook sair sem capturar exceção em `main()`. Hook que derruba a sessão do
  usuário é o modo de falha mais caro do harness — todo `main()` engole `Exception` e sai
  com 0.
- Fazer um hook agir sem `.claude/harness.json` na raiz do projeto. Esse arquivo é o gate —
  sem ele, `config.carregar()` devolve `None` e TODO hook, inclusive as guardas
  universais, tem de ficar inerte.
- Escrever política específica de um projeto dentro de `src/`. Duas cópias divergem na
  primeira correção; a política vem do `harness.json`/`CLAUDE.md` do consumidor, nunca do
  código do harness.
- Truncar uma inviolável que estourou `reafirmacao.teto_item_chars`. Meia proibição lê
  como permissão — `auditar_invioaveis` reprova e pede para encurtar a primeira frase, em
  vez de cortar.

## Memória

- [Diário de engenharia](docs/diario/2026-09.md) — última sessão, becos sem saída.
- [Decisões arquiteturais](docs/adr/README.md) — o que já foi decidido e por quê.

### Qual ADR ler — por caminho que você vai tocar

| Caminho                | ADRs |
| ----------------------- | ---- |
| `.claude/harness.json`  | 0001 |
| `docs/adr/`             | 0001 |
| `docs/diario/`          | 0001 |
