---
type: regex
target: { source: file, path: .eval-diario.md }
# A pendência que a sessão fechou ("Aplicar a mesma correção … `scripts/frete.py`") não
# continua aberta: só a da entrada velha casa. Zero também reprova — é a entrada velha
# editada, e o diário é append-only. `frete` sozinho casava as pendências NOVAS que o agente
# acrescenta com razão (teste de `valor_do_frete`, commitar `scripts/frete.py`).
pattern: '^- \[ \] (?=.*[Aa]plica)(?=.*frete)'
flags: m
match: "count:1"
---
