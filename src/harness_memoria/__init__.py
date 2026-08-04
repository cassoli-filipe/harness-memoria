"""Harness de memória: ADR + diário de engenharia como contexto reinjetado, com guardas.

Três camadas, e a separação entre elas é o ponto do pacote:

* **Mecanismo** (este pacote) — igual em todo projeto, uma fonte só.
* **Política** (`.claude/harness.json` + a seção de invioláveis do `CLAUDE.md` do projeto)
  — dado, nunca código. Ver `config.py`.
* **Conteúdo** (`docs/adr/`, `docs/diario/`) — nasce no projeto e é o que dá valor: o
  mecanismo instalado num projeto vazio é um mecanismo vazio.
"""

__version__ = "0.1.0"
