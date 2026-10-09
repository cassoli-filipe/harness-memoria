---
type: regex
target: { source: file, path: .eval-diario.md }
# A forma que o digest de becos preserva ao encurtar: a lição depois de `**Não repetir:**`.
pattern: '^- .*Decimal.* → falhou porque .+\*\*Não repetir:\*\* \S'
flags: m
---
