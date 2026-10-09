---
type: regex
target: { source: file, path: scripts/sincronizar.py }
# O porquê vai para o ADR e o código aponta para ele. Medido em 2026-10-09: com a skill, o
# agente deixa 4 linhas e o caminho do ADR; nenhuma das 7 rodadas escreveu comentário com
# mais de 5 linhas — a cláusula do gatilho sozinha não se isola com este prompt.
pattern: '0002'
---
