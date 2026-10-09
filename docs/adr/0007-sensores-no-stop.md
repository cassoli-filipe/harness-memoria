---
status: implemented
data: 2026-10-09
---

# ADR-0007 — Verificar o turno com sensores do projeto no hook `Stop`

## Contexto

Na taxonomia de *harness engineering* (Böckeler/Fowler, abr/2026: guias × sensores,
computacionais × inferenciais), o harness era quase só **guia**: reinjeção de ADR e diário,
reafirmação de invioláveis, instrução ao sumarizador. O único sensor no loop era a guarda
`PreToolUse`, preventiva; a auditoria é sensor, mas roda no CI, depois do push, e só olha
documentação. Nada conferia o trabalho do agente antes de ele dizer "pronto" — e o
autoelogio do agente que avalia a própria saída é um modo de falha documentado (Anthropic,
"Harness design for long-running application development", mar/2026). O resultado que mais
se aproxima disto na literatura: um checklist que intercepta a saída do agente e exige
verificação foi um dos ajustes que levaram o Terminal Bench 2.0 de 52,8 para 66,5 sem trocar
o modelo (LangChain, fev/2026).

A plataforma oferece o mecanismo: o hook `Stop` pode devolver `decision: block` com um
`reason`, e o agente continua o turno com o motivo como próxima instrução. A dúvida era o
orçamento, porque o `SessionEnd` de plugin ignora o `timeout` declarado e mata o hook em
1.500 ms (ADR-0002). Medido em 2026-10-09 com um plugin descartável (`claude -p` 2.1.295, sonda
que dorme N s e bloqueia uma vez), em 9 combinações de N ∈ {5, 30, 90} × `timeout` ∈
{ausente, 30, 120}: o `Stop` **respeita** o `timeout` declarado — 90 s rodaram até o fim com
120 s ou sem valor (default 600), e o bloqueio fez o modelo continuar; com 30 s, o de 90 s
morreu aos 30 e a sessão terminou normalmente. O `Stop` dispara de novo depois do bloqueio,
com `stop_hook_active: true`, e o motivo entra no transcript como `user` com `isMeta: true`.

## Fatores de decisão

- Quais comandos verificam um projeto é política do projeto, não do harness (inviolável:
  nenhuma política de projeto em `src/`).
- O turno que só leu não pode pagar testes; o turno que escreveu código não pode terminar
  sem eles.
- O sensor nunca pode prender a sessão por defeito próprio: timeout, executável ausente e
  erro do harness liberam.
- O laço tem fim: a plataforma corta em 8 continuações; antes disso a palavra volta ao
  usuário.
- O motivo do bloqueio é texto para o agente, dentro do teto de 10.000 ch (ADR-0004).

## Decisão

Novo hook `Stop` (`hooks/verificar.py`, lógica em `harness_memoria/sensores.py`), com a
política em `sensores` no `harness.json`: `comandos` (cada um `{nome, comando, extensoes?,
cwd?, exige?, timeout_s?, remediacao?, bloquear?}`), `orcamento_total_s` (120),
`max_bloqueios` (3), `cauda_chars` (2.500). Vazio por padrão — o hook é inerte até o projeto
declarar um sensor. Registro com `timeout: 180`.

- **Quando roda:** se o turno — do último prompt humano até agora — escreveu arquivo que
  casa `extensoes`. A janela vem do transcript (`Write`/`Edit`/…) somada ao `git status`
  com mtime desde o início do turno, que pega escrita por Bash e por subagente. Na
  continuação de um bloqueio, roda também o sensor que reprovou antes, mesmo sem escrita
  nova — senão o agente encerraria o laço só por responder.
- **Como roda:** em série, na ordem da config, dentro do orçamento; argv sem shell; saída
  para arquivo temporário (um neto segurando o pipe travaria o `communicate()`); timeout mata
  a árvore de processos.
- **O que devolve:** reprovação → `decision: block` com a cauda da saída sem ANSI, os
  arquivos que acionaram e a `remediacao`, num motivo de até 8.000 ch. Depois de
  `max_bloqueios` tentativas seguidas, ou quando a última mensagem do agente é uma pergunta
  ao usuário, só `systemMessage`. `bloquear: false` só avisa.
- **Memória:** o estado por sessão (bloqueios, último resultado de cada sensor) vai para o
  piso do `SessionEnd`, como primeira linha de "Falhas observadas": `sensor \`testes\`
  reprovou 2×, não resolvido`. A mesma seção passa a listar, extraídos do transcript, os
  comandos que falharam e as negações de guarda e de permissão — só a linha do comando e o
  código de saída, nunca a saída, porque o diário é versionado.

A auditoria ganha `auditar_sensores` (chave obrigatória, argv como lista, nome duplicado,
timeout acima do orçamento, `cwd` inexistente, `{arquivo}` no comando); o `--autoteste` do
hook confere que cada executável existe na máquina onde ele vai rodar.

## Alternativas consideradas

### Estado de "arquivos sujos" gravado por um `PostToolUse`

**Rejeitada porque** os `PostToolUse` do harness são `async` (ADR-0003), então o `Stop` pode
ler o estado antes de a última escrita gravá-lo; torná-lo síncrono custaria 56–150 ms por
escrita; e ele ainda não veria escrita feita por Bash.

### Rodar o sensor a cada escrita, no `PostToolUse`

**Rejeitada porque** uma suíte de 7 s a cada uma de 120 escritas é 14 minutos de sessão
parada, e o estado intermediário de uma refatoração em vários arquivos reprova de propósito.
O momento de verificar é quando o agente diz que terminou.

### Deixar para o hook de pre-commit do git

**Rejeitada porque** age só quando alguém commita — o agente que diz "pronto" sem commitar
nunca é verificado — e a falha volta como erro de comando, não como instrução ao agente com
o que fazer.

### Instruir no `CLAUDE.md` ("rode os testes antes de concluir")

**Rejeitada porque** é exatamente o tipo de instrução cuja aderência decai por passo
(`arXiv:2605.10039`, a razão de o `reafirmar` existir); o sensor roda fora do raciocínio do
modelo.

### Hook `Stop` do tipo `prompt` ou `agent` (LLM julgando se o trabalho está pronto)

**Rejeitada porque** é sensor inferencial, caro e não determinístico, onde um computacional
resolve; fica como passo seguinte, para o que teste não cobre (aderência a ADR, por
exemplo).

## Consequências

**Boas:** "pronto" passa a significar "os sensores do projeto passaram" nos turnos que
escreveram código. A falha volta ao agente com o que fazer, no mesmo turno. Sessões que
terminaram vermelhas deixam rastro no diário mesmo sem narrativa.

**Ruins, e aceitas:** todo turno que escreve código espera os sensores (~7 s neste
repositório). Falha anterior à sessão ou instável cobra do agente até o teto de tentativas —
a mitigação é o teto, o `bloquear: false` e a instrução de dizer ao usuário. O formato do
transcript (prompt humano, `isMeta`, `tool_use`) é interno da plataforma e pode mudar. O
modo interativo não foi medido no spike, só `claude -p`.

## Quando revisitar

Se a plataforma passar a cortar o `Stop` de plugin num orçamento curto (o sinal: sensores
reportando timeout sem motivo); se o teto de bloqueios estiver sendo atingido com
frequência (sensor instável ou falha crônica — é o lugar para `bloquear: false`, não para
subir o teto); ou quando houver sensor inferencial a acrescentar ao lado dos
computacionais.

## Plano de Implementação

- **Arquivos a tocar:** `src/harness_memoria/sensores.py` (novo),
  `src/harness_memoria/hooks/verificar.py` (novo), `src/harness_memoria/config.py`
  (`ConfigSensores`, `_validar_sensores`), `src/harness_memoria/auditar/__init__.py`
  (`auditar_sensores`), `src/harness_memoria/diario.py` (`linhas_de_falhas` com sensor),
  `src/harness_memoria/hooks/session_end.py` (estado do sensor no piso),
  `src/harness_memoria/hooks/_comum.py` (`_ESTADO_QUE_EXPIRA`), `hooks/hooks.json`,
  `.github/workflows/ci.yml`.
- **Padrões a seguir:** esqueleto e pré-gate de `formatar.py`; validação de config de
  `_validar_regras_de_guarda` × `auditar_guardas`.
- **Testes obrigatórios:** `tests/test_verificar.py`, `tests/test_sensores_config.py`,
  `tests/test_diario_falhas.py`, e `verificar.py` nas listas paramétricas de robustez e de
  gate.
- **Não mexer em:** o contrato de `### Tentativas descartadas` — falha observada é fato, e
  só vira beco quando alguém narra o porquê.
