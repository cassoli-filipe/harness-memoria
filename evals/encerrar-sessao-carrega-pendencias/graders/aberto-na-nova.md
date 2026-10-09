---
type: regex
target: { source: file, path: .eval-diario.md }
# A entrada nova traz a própria lista — sem ela, a próxima sessão herda a da anterior.
pattern: '^### Aberto / Próximo passo'
flags: m
match: "count:2"
---
