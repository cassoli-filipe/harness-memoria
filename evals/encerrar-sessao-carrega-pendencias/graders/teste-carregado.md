---
type: regex
target: { source: file, path: .eval-diario.md }
# A pendência que a sessão não tocou continua aberta na entrada nova. Por conteúdo, não por
# palavra solta: medido, o agente acrescenta "teste para `valor_do_frete`" — pendência nova
# legítima que `[Tt]est` sozinho contava como a carregada.
pattern: '^- \[ \] (?=.*desconto)(?=.*[Tt]est)'
flags: m
match: "count:2"
---
