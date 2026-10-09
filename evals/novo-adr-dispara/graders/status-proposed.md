---
type: regex
target: trace
# O ADR nasce `proposed`: a skill proíbe o agente de aprovar a própria decisão. O nome do
# arquivo não é conhecido de antemão, então o grader olha a escrita no trace (JSON-escapado:
# a quebra de linha do conteúdo aparece como `\n` literal).
pattern: '0002-[a-z0-9-]+\.md","content":"-{3}\\nstatus: proposed'
---
