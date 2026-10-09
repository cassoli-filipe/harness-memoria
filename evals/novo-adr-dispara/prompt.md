---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Decidimos trocar o `urllib` pelo `httpx` como cliente HTTP deste projeto. O motivo: a API do fornecedor de pagamentos exige HTTP/2, e duas sincronizações já ficaram penduradas porque o `urllib` não tem timeout por requisição. Avaliamos o `requests` (rejeitado: sem HTTP/2 e sem cliente assíncrono) e continuar no `urllib` com timeout manual por socket (rejeitado: foi exatamente o que falhou duas vezes). Vale revisitar se o fornecedor deixar de exigir HTTP/2. Registre essa decisão no projeto do jeito que o projeto registra decisões. Não me faça perguntas: tudo o que eu sei está aqui.
