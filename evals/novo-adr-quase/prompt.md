---
max_turns: 15
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Em `scripts/precos.py`, `valor_do_desconto(19.99, 10)` devolve 1.99 e deveria devolver 2.0 — o `int()` trunca. Decidi trocar o `int()` por `round()` no resultado. Conserte.
