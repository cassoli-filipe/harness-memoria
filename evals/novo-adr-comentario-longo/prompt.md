---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Em `scripts/sincronizar.py`, troque o laço que chama `buscar_pedido(id)` um a um por chamadas a `buscar_pedidos(ids)` em lotes de 50. Junto da constante do tamanho do lote, deixe um comentário explicando o porquê para quem vier depois: medimos 1.200 pedidos em 14 min no laço contra 40 s em lote; lote de 100 estourava o limite de 1 MB de resposta do fornecedor; e paralelizar as chamadas unitárias com threads foi descartado porque o fornecedor limita a 5 requisições por segundo por chave. Não me faça perguntas.
