"""Hooks do Claude Code. Cada módulo é executável direto e tem `--autoteste`.

Todo hook aqui obedece três regras:

1. **Nunca derruba a sessão.** Exceção é engolida no `__main__` e o processo sai com 0.
2. **Gate por `.claude/harness.json`.** Sem config no projeto, sai sem fazer nada.
3. **Autotestável sem o Claude Code.** `--autoteste [--projeto CAMINHO]` roda o hook contra
   um projeto de verdade e imprime o que ele faria — é o que o CI executa.
"""
