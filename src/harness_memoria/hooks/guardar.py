#!/usr/bin/env python3
"""Hook PreToolUse — bloqueio determinístico das proibições absolutas.

Proibição absoluta é hook, não frase no CLAUDE.md: regra que roda fora do raciocínio do
modelo não decai ao longo da sessão.

Duas famílias de regra:

* **universais** — `.env`, `--no-verify` e `git add --force`. São TRÊS, e por muito tempo os
  lugares que as listavam citavam duas; a não anunciada era justamente a que mais surpreende.
  Valem em todo projeto e não têm caso legítimo: nenhum agente precisa escrever segredo,
  hook de commit que incomoda se corrige (não se pula) e passar por cima do .gitignore é
  passar por cima da barreira contra versionar segredo. Desligáveis por
  `guardas.universais: false`, para o caso que eu não previ.

  As três cobrem a rota de shell, não só a ferramenta de escrita: `echo X > .env`,
  `git commit -nm 'x'` e `Set-Content .env` são o passo obvio seguinte a um `Write` negado,
  e o agente os toma sem intenção adversária. Guarda que se contorna assim é pior que guarda
  ausente, porque quem a instalou conta com ela.
* **do projeto** — vêm de `guardas.caminhos` e `guardas.comandos` no `harness.json`. É onde
  mora "planilha com dado de aluno fora de fixtures" (rede_inspira_app) ou "escrita no
  Pipedrive" (ValidaNI).

O gate vale aqui também: num projeto sem `.claude/harness.json` este hook não bloqueia
nada, nem as universais. Negar tool call num repositório que nunca pediu o harness é
surpresa, e surpresa em bloqueio queima a confiança no mecanismo inteiro.

Autoteste:  python src/harness_memoria/hooks/guardar.py --autoteste [--projeto CAMINHO]
"""

from __future__ import annotations

import os
import sys

ROTULO = "guarda"
FERRAMENTAS_DE_ESCRITA = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
FERRAMENTAS_DE_SHELL = {"Bash", "PowerShell"}

#: Uma mensagem, duas portas. O `Write` em `.env` e o `echo ... > .env` são a MESMA
#: proibição, e o segundo é o passo obvio seguinte a um `Write` negado — o agente contorna
#: sem intenção adversária, porque o contorno é o próximo movimento natural.
MOTIVO_ENV = (
    "Bloqueado: `{nome}` guarda segredos e está no .gitignore. "
    "Edite `.env.example` (sem valores) e peça ao usuário para preencher o `.env`."
)

#: Arquivos `.env.*` SEM segredo — grafias que o agente DEVE poder editar livremente, porque
#: são o lugar certo para registrar uma variável nova. Uma constante ao lado de `MOTIVO_ENV`
#: porque a exceção já foi escrita DUAS VEZES, por extenso, em `_avaliar_caminho` e em
#: `_escrita_de_env_por_shell` — e as duas listas divergiram na primeira correção: uma
#: reconhecia só `.env.example`, a outra também só `.env.example`, e nenhuma sabia de
#: `.env.template`/`.env.sample`/`.env.dist`, grafias igualmente comuns do mesmo papel.
#: Medido: `cp .env.example .env.template` — cópia de um arquivo sem segredo para outro
#: arquivo sem segredo — passava a ser NEGADO.
_ENV_SEM_SEGREDO = frozenset({".env.example", ".env.sample", ".env.template", ".env.dist"})

#: Literais entre quotes, apagados ANTES de procurar `--no-verify`. Sem isto,
#: `git commit -m 'nunca use --no-verify'` era bloqueado: falso positivo em bloqueio ensina
#: a desligar a guarda inteira, que é o oposto do que ela existe para fazer.
_LITERAL = r"'[^']*'|\"[^\"]*\""

#: `--no-verify` no `commit`, incluindo as grafias curtas. `git commit -h` confirma
#: `-n, --no-verify`, e com a regex antiga (`\bgit\s+(commit|push)\b.*--no-verify`)
#: passavam `git commit -n -m 'x'` e `git commit -nm 'x'` — o bypass mais curto do teclado,
#: e o passo obvio seguinte a um commit reprovado por hook. O `[a-z]*` nas duas pontas
#: cobre o pacote de flags curtas (`-anm`); `-am`, `--amend` e `--no-gpg-sign` não casam,
#: porque nenhum tem `n` como flag curta solta.
_NO_VERIFY_COMMIT = r"\bgit\s+commit\b[^&|;]*(?:--no-verify|\s-[a-z]*n[a-z]*(?:\s|$))"

#: No `push` só a forma longa: `git push -n` é `--dry-run` e bloqueá-lo seria falso
#: positivo. O `[^&|;]*` (era `.*`) confina o casamento a um segmento — antes,
#: `git push origin main && echo 'nunca use --no-verify'` bloqueava o push.
_NO_VERIFY_PUSH = r"\bgit\s+push\b[^&|;]*--no-verify"

#: Gatilhos de escrita que recebem o alvo como ARGUMENTO, em qualquer posição do segmento:
#: `tee`, os cmdlets do PowerShell e as cópias. O redirecionamento é tratado à parte, em
#: `_escrita_de_env_por_shell`, porque nele o alvo é posicional.
#:
#: A lista é a das grafias medidas, não uma teoria completa de escrita em shell: `sed -i`,
#: `truncate` e um `python -c` que escreve continuam de fora. A porta principal é e continua
#: sendo `_avaliar_caminho`, na ferramenta de escrita; esta guarda fecha o contorno que o
#: agente toma por reflexo depois de um `Write` negado.
_GATILHO_COM_ALVO_EM_ARGUMENTO = (
    r"(?:\btee\b|\bset-content\b|\bout-file\b|\badd-content\b"
    r"|\bcp\b|\bmv\b|\bcopy-item\b|\bmove-item\b)"
)

#: Subconjunto do gatilho acima com dois argumentos de CAMINHO (origem, destino) — `cp` e
#: `mv`. Quando o `.env` casado não é o ÚLTIMO desses dois, ele é a ORIGEM, não o destino, e
#: o motivo de EDIÇÃO (`MOTIVO_ENV`, "edite `.env.example`") não se aplica a quem está
#: copiando. `tee`/`Set-Content`/`Out-File`/`Add-Content` ficam de fora deste subconjunto de
#: propósito: neles o segundo argumento é o CONTEÚDO a escrever, não um caminho
#: (`Set-Content .env 'A=1'` tem `.env` no PRIMEIRO argumento, e é o destino mesmo assim) —
#: a posição do último argumento só significa "destino" na família cópia/renomeio.
_GATILHO_DE_COPIA = r"(?:\bcp\b|\bmv\b|\bcopy-item\b|\bmove-item\b)"

#: Motivo próprio para `cp`/`mv` de `.env` cuja ORIGEM é o segredo. O bloqueio está certo —
#: `cp .env backup.txt` tira o segredo do caminho ignorado tanto quanto `cat .env >
#: backup.txt`, que já era bloqueado —, mas `MOTIVO_ENV` responde "edite `.env.example`" a
#: quem não estava editando nada. Medido pelo revisor: 36 comandos do dia a dia sondados,
#: único par que recebia decisões coerentes na ação e incoerentes na mensagem. Bloqueio
#: certo com remédio non-sequitur é o princípio 9 (falso positivo ensina a ignorar o
#: auditor) mesmo quando a decisão de bloquear estava certa.
MOTIVO_COPIA_ENV = (
    "Bloqueado: `cp`/`mv` de `{nome}` faria o segredo sair de um caminho ignorado pelo git "
    "para um que não é. Leia o valor sem copiar o arquivo (`cat {nome}`), ou copie apenas "
    "para outro `.env*`."
)

#: O token `.env` (ou `.env.algo`) com fronteira nas duas pontas. A fronteira é o que
#: impede o falso positivo: `.environment` e `.env-backup` NÃO casam. O `>` na classe de
#: separadores é por medição, não por simetria: `echo API_KEY=1 >.env`, sem espaço depois
#: do redirecionador, é grafia comum e passava.
_TOKEN_ENV = r"(?:^|[\s/\\\">'=])(\.env(?:\.[\w-]+)?)(?=[\s\"']|$)"

#: Erro do bootstrap, se houver. O `try/except` que implementa "nunca derrubar a sessão"
#: começava no `__main__`, e o `from harness_memoria...` ficava FORA dele — a única linha
#: sem rede. Reproduzido: com um erro de sintaxe no fim de `config.py` (o que um `git pull`
#: no meio, um arquivo truncado ou um interpretador incompatível produzem) este hook saía
#: com rc=1, stdout vazio e um traceback cru no stderr, e o `.env` NÃO era bloqueado — a
#: mensagem desenhada justamente para esse caso nunca era impressa.
_ERRO_DE_BOOTSTRAP: str | None = None

#: `_leve`, quando ele importar. Começa em `None` porque ele pode ser JUSTAMENTE o arquivo
#: quebrado, e aí o nome não existiria — ver o ramo de desistência em `main`.
L = None

try:
    # `os.path` e não `Path(__file__).resolve().parents[2]`: `pathlib` custa 7,2 ms e era o
    # PRIMEIRO import do arquivo, isto é, era pago antes de o pré-gate abaixo poder dizer
    # que este hook não tem nada a fazer neste projeto.
    _AQUI = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(_AQUI)))

    from harness_memoria.hooks import _leve as L  # noqa: E402

    # PRÉ-GATE. Num projeto sem `.claude/harness.json` este hook não bloqueia nada — nem as
    # universais —, e até aqui ele pagava 85,6 ms de import para descobrir isso. Agora a
    # pergunta é respondida com dois `os.path.exists` — `gate_barato()` custa 0,048 ms
    # medidos — antes de `json`, `pathlib` e `config` entrarem. Medido p25 de n=40 rodadas
    # intercaladas antes/depois, cenário sem config: Write 148,4 → 56,0 ms, Bash 149,9 →
    # 57,1 ms, contra um piso de 44,3 ms de interpretador nu.
    #
    # Duas guardas, e as duas têm incidente por trás:
    #
    # * `__name__ == "__main__"` — a suíte importa este módulo para chamar `avaliar()`
    #   direto. Sem esta guarda, um `pytest` rodado a partir de um diretório qualquer que
    #   tenha `CLAUDE.md` e não tenha config chamaria `sys.exit(0)` DENTRO da coleta.
    # * `--autoteste` — o autoteste recebe o projeto por `--projeto` e o cwd do processo não
    #   é ele. Sem esta guarda, `guardar.py --autoteste --projeto <com-config>` rodado de um
    #   diretório sem config devolvia saída VAZIA com rc=0, que é indistinguível de sucesso.
    if __name__ == "__main__" and "--autoteste" not in sys.argv and L.gate_barato() is False:
        L.sair_sem_fazer_nada()

    import json  # noqa: E402
    import posixpath  # noqa: E402
    import re  # noqa: E402

    from harness_memoria.config import ConfigGuardas  # noqa: E402
    from harness_memoria.hooks import _comum as C  # noqa: E402
except Exception as e:  # noqa: BLE001 — pacote inconsistente não derruba a sessão
    _ERRO_DE_BOOTSTRAP = f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    if _ERRO_DE_BOOTSTRAP is not None:
        aviso = f"[{ROTULO}] pacote não importável, liberando por segurança: {_ERRO_DE_BOOTSTRAP}"
        # Quando o arquivo quebrado é o próprio `_leve`, `L` não existe — e chamar
        # `L.sair_sem_fazer_nada` aqui TROCAVA a causa pela consequência: com `_leve.py`
        # truncado a mensagem saía `NameError: name 'L' is not defined` (medido nos três
        # hooks), mandando procurar bug neste arquivo em vez do arquivo pela metade. Esta é
        # a mensagem que existe para ser lida no dia do `git pull` no meio; ponteiro errado
        # aqui custa a hora que ele deveria economizar. `sys` é import do topo, fora do
        # `try`: é o único que não pode faltar.
        if L is None:
            print(aviso, file=sys.stderr)
            return 0
        L.sair_sem_fazer_nada(aviso)
    argv = list(argv if argv is not None else sys.argv[1:])
    C.preparar(ROTULO)
    if "--autoteste" in argv:
        return _autoteste(_arg(argv, "--projeto") or os.getcwd())

    evento = C.ler_evento()
    ctx = C.contexto(evento, ROTULO)
    if ctx is None:
        return 0
    _, cfg = ctx

    motivo = avaliar(
        str(evento.get("tool_name") or ""), evento.get("tool_input") or {}, cfg.guardas
    )
    if motivo:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": motivo,
                    }
                },
                ensure_ascii=False,
            )
        )
    return 0


def avaliar(ferramenta: str, entrada: dict, g: ConfigGuardas) -> str | None:
    """Motivo do bloqueio, ou `None` se estiver liberado."""
    if not isinstance(entrada, dict):
        return None
    if ferramenta in FERRAMENTAS_DE_ESCRITA:
        caminho = entrada.get("file_path") or entrada.get("notebook_path")
        if isinstance(caminho, str):
            return _avaliar_caminho(caminho, g)
    if ferramenta in FERRAMENTAS_DE_SHELL:
        comando = entrada.get("command")
        if isinstance(comando, str):
            return _avaliar_comando(comando, g)
    return None


def _avaliar_caminho(caminho: str, g: ConfigGuardas) -> str | None:
    # `normpath` antes de qualquer comparação: sem ele a exceção `permitido_em` virava
    # porta para qualquer caminho. Com a regra `{"padrao": "*.xlsx", "permitido_em":
    # ["tests/fixtures/"]}` passavam `tests/fixtures/../../dados/real.xlsx` e
    # `C:/proj/tests/fixtures/../../producao/alunos.xlsx` — e isso não exige intenção
    # adversária, basta o modelo escrever caminho relativo com `..`. É exatamente o desenho
    # que `_todo_caminho_permitido` rejeita explicitamente para comandos.
    norm = posixpath.normpath(caminho.replace("\\", "/"))
    nome = posixpath.basename(norm)
    baixo = norm.lower()

    variante_com_segredo = nome.startswith(".env.") and nome not in _ENV_SEM_SEGREDO
    if g.universais and (nome == ".env" or variante_com_segredo):
        return MOTIVO_ENV.format(nome=nome)

    if not g.caminhos:
        return None
    # Import local, e o número honesto: economiza ZERO. `config` importa `pathlib`, e
    # `pathlib` já importa `fnmatch` — medido, `import config` = 118,5 ms e
    # `import config; import fnmatch` = 118,3 ms. Fica aqui porque torna a dependência
    # honesta (só quem declara `guardas.caminhos` a usa) e porque o dia em que `pathlib`
    # sair da cadeia o custo apareceria; não fica aqui por ser caminho quente, e quem
    # medir de novo tem de achar zero.
    import fnmatch

    for regra in g.caminhos:
        padrao = str(regra.get("padrao") or "")
        if not padrao:
            continue
        casa = fnmatch.fnmatch(nome.lower(), padrao.lower()) or fnmatch.fnmatch(
            baixo, padrao.lower()
        )
        if not casa:
            continue
        permitido = tuple(regra.get("permitido_em") or ())
        if any(_sob_prefixo(baixo, p) for p in permitido):
            continue
        motivo = str(regra.get("motivo") or f"`{padrao}` é proibido neste projeto")
        onde = f" Permitido em: {', '.join(permitido)}." if permitido else ""
        return f"Bloqueado: `{nome}` — {motivo}{onde}"
    return None


def _sob_prefixo(caminho_baixo: str, prefixo: str) -> bool:
    """O caminho (já normalizado e minusculado) está DENTRO do diretório `prefixo`?

    Fronteira de caminho, não substring. Com o teste antigo (`p.lower() in baixo`), a barra
    final do prefixo é que decidia se a guarda funcionava, e nada dizia isso a quem escreve
    a config: `permitido_em: ["tests/fixtures/"]` barrava `tests/fixtures_antigos/x.xlsx`,
    e `permitido_em: ["tests/fixtures"]` — a grafia mais curta, a que se escreve sem pensar
    — liberava. Agora as duas grafias significam a mesma coisa, porque as barras de contorno
    são o que faz a fronteira: `/tests/fixtures/` dentro de `/c:/proj/tests/fixtures/x.xlsx`.

    `prefixo` é DIRETÓRIO, nunca arquivo — e isto AVISA, não corrige: `permitido_em:
    ["tests/fixtures/exemplo.xlsx"]` NÃO libera `tests/fixtures/exemplo.xlsx`, porque a
    fronteira acima exige algo depois de `/exemplo.xlsx/` no caminho, e um arquivo não tem
    nada depois de si mesmo. Achado do revisor: a troca substring→fronteira (parágrafo
    acima, ganho e fica) mudou essa semântica no mesmo commit, em silêncio — de liberado
    para bloqueado — para quem aponta `permitido_em` a um arquivo específico, e nada no
    `carregar()`, no `auditar_guardas` (`src/harness_memoria/auditar/__init__.py`) ou no
    `_autoteste` avisava. O cheque existe agora: `auditar_guardas` reprova `permitido_em`
    com extensão de arquivo, dizendo que prefixo é diretório — então a surpresa virou
    build vermelho com a frase que diz o que escrever no lugar.
    """
    limpo = prefixo.lower().replace("\\", "/").strip("/")
    if not limpo:
        return False
    return f"/{limpo}/" in f"/{caminho_baixo.lstrip('/')}"


def _avaliar_comando(comando: str, g: ConfigGuardas) -> str | None:
    c = " ".join(comando.split())
    baixo = c.lower()

    if g.universais:
        sem_literais = re.sub(_LITERAL, " ", baixo)
        if any(re.search(p, sem_literais) for p in (_NO_VERIFY_COMMIT, _NO_VERIFY_PUSH)):
            return (
                "Bloqueado: `--no-verify` pula os hooks de commit. "
                "Se um hook está falhando, corrija a causa."
            )
        if re.search(r"\bgit\s+add\b[^&|;]*(^|\s)\.env(\.\w+)?(\s|$)", baixo):
            return "Bloqueado: `.env` contém segredos e nunca deve ser versionado."
        if re.search(r"\bgit\s+add\b[^&|;]*\s-(-force|f)\b", baixo):
            return (
                "Bloqueado: `git add --force` ignora o .gitignore, que é a barreira contra "
                "versionar segredo. Adicione o caminho explicitamente sem `-f`."
            )
        # Escrever `.env` por shell. O hook só olhava `file_path` nas ferramentas de escrita
        # e regex de `git` no shell, então com `ConfigGuardas()` de fábrica passavam
        # `echo 'API_KEY=sk-real' > .env`, `printf ... >> .env`, `cp .env.example .env`,
        # `cat > .env <<'X'` e `Set-Content .env` — e nenhum deles exige má intenção: é o
        # movimento seguinte de quem acabou de ter um `Write` em `.env` negado.
        if motivo := _escrita_de_env_por_shell(baixo):
            return motivo

    for regra in g.comandos:
        padrao = str(regra.get("regex") or "")
        if not padrao:
            continue
        try:
            # Contra `c`, e não contra `baixo`, com `IGNORECASE`: era um furo que anulava a
            # regra inteira. Com `{"regex": "Set-Content[^&|;]*\\.env"}` o comando vinha
            # minusculado e o padrão não, então a regra não casava NADA — nem
            # `Set-Content .env` nem `set-content .env` —, e `Set-Content`, `Remove-Item`,
            # `Invoke-WebRequest` e `DROP TABLE` são as grafias naturais de quem escreve a
            # config. A seção irmã `guardas.caminhos` já normalizava os dois lados
            # (`fnmatch(nome.lower(), padrao.lower())`): a assimetria era só aqui.
            casos = [m.group(0) for m in re.finditer(padrao, c, re.IGNORECASE)]
        except re.error as e:
            print(
                f"[{ROTULO}] regex inválida em guardas.comandos: {padrao} ({e})",
                file=sys.stderr,
            )
            continue
        if not casos:
            continue
        permitido = tuple(regra.get("permitido_em") or ())
        if permitido and all(_todo_caminho_permitido(c, permitido) for c in casos):
            continue
        motivo = str(regra.get("motivo") or f"comando casa `{padrao}`")
        onde = f" Permitido em: {', '.join(permitido)}." if permitido else ""
        return f"Bloqueado: {motivo}{onde}"
    return None


def _escrita_de_env_por_shell(baixo: str) -> str | None:
    """Motivo do bloqueio quando um segmento escreve em `.env`, ou `None`.

    Segmento por segmento (`&`, `|`, `;`) para o gatilho e o alvo terem de estar no MESMO
    comando: senão `cat .env | grep KEY && echo ok > log.txt` bloquearia.

    E, dentro do segmento, o alvo do redirecionamento é o que vem DEPOIS do último `>`, não
    qualquer `.env` citado. A primeira versão olhava o segmento inteiro e bloqueava
    `echo "veja .env para detalhes" > README.md` — menção não é alvo, e falso positivo em
    bloqueio ensina a desligar a guarda. Para `tee` e os cmdlets o alvo é posicional demais
    para essa regra valer, então lá se olha o segmento todo — com uma exceção: em `cp`/`mv`
    (`_GATILHO_DE_COPIA`), se o `.env` casado não é o ÚLTIMO argumento do segmento, ele é a
    ORIGEM da cópia, não o destino, e o motivo devolvido é `MOTIVO_COPIA_ENV`, não
    `MOTIVO_ENV` — ver o porquê no comentário de `MOTIVO_COPIA_ENV`.

    `_ENV_SEM_SEGREDO` é a exceção explícita, a mesma que `_avaliar_caminho` já tinha: são
    os arquivos que o agente DEVE editar quando quer registrar uma variável nova.
    """
    for segmento in re.split(r"[&|;]", baixo):
        depois_do_redirecionador = re.split(r">>?", segmento)
        if len(depois_do_redirecionador) > 1:
            alvos = _alvos_env(depois_do_redirecionador[-1])
            if alvos:
                return MOTIVO_ENV.format(nome=alvos[0])

        if not re.search(_GATILHO_COM_ALVO_EM_ARGUMENTO, segmento):
            continue
        alvos = _alvos_env(segmento)
        if not alvos:
            continue
        if re.search(_GATILHO_DE_COPIA, segmento) and not _ultimo_argumento_e_env(segmento):
            return MOTIVO_COPIA_ENV.format(nome=alvos[0])
        return MOTIVO_ENV.format(nome=alvos[0])
    return None


def _alvos_env(trecho: str) -> list[str]:
    """`.env`/`.env.algo` citados em `trecho`, exceto os SEM segredo (`_ENV_SEM_SEGREDO`)."""
    return [t for t in re.findall(_TOKEN_ENV, trecho) if t not in _ENV_SEM_SEGREDO]


def _ultimo_argumento_e_env(segmento: str) -> bool:
    """O ÚLTIMO token (separado por espaço) do segmento é, ele mesmo, um alvo `.env`?

    Só decide o motivo em `cp`/`mv` (`_GATILHO_DE_COPIA`), onde o comando tem exatamente
    dois argumentos de caminho e o último É o destino. Isolado do resto do segmento porque
    `_TOKEN_ENV` teria de casar dentro de um único token, sem o resto do comando ao redor
    influenciando a fronteira.
    """
    tokens = segmento.split()
    if not tokens:
        return False
    ultimo = tokens[-1].strip("\"'")
    casamento = re.search(_TOKEN_ENV, ultimo)
    return bool(casamento) and casamento.group(1) not in _ENV_SEM_SEGREDO


def _todo_caminho_permitido(trecho: str, permitido: tuple[str, ...]) -> bool:
    """`permitido_em`: TODO caminho **do trecho que casou** está sob um dos prefixos?

    Recebe `m.group(0)`, e não o comando inteiro. A diferença não é detalhe: comando
    composto é a regra, e na primeira versão desta função o `cd "c:/users/..."` do
    começo da linha contava como "caminho citado", não estava sob prefixo nenhum, e a
    exceção nunca valia. O `[^&|;]*` que essas regras usam já confina o casamento a um
    segmento, então o trecho é exatamente o comando ofensor e nada mais.

    Semântica conservadora dentro do trecho — **todo**, não "algum". Um `git add` misto
    com um caminho permitido ao lado de um proibido continua bloqueado: os dois estão no
    mesmo segmento, então os dois entram na conta. Liberar pelo primeiro token permitido
    deixaria a exceção virar porta.

    "Caminho citado" é o token com separador ou extensão. `git`, `add` e `-u` não têm,
    então não contam — nenhum dos dois é caminho. Extensão sem diretório
    (`planilha.xlsx`, na raiz) conta e não está sob prefixo nenhum, então bloqueia: é o
    caso que a regra existe para pegar.

    O `trecho` chega com a caixa ORIGINAL do comando desde que as regras do projeto passaram
    a casar com `IGNORECASE` (ver `_avaliar_comando`); a comparação com o prefixo é que
    minusculiza, e é `_sob_prefixo` — a mesma fronteira de caminho de `_avaliar_caminho`,
    com `normpath` — quem decide. Sem normalizar aqui, `tests/fixtures/../../dados/real.xlsx`
    passaria pela exceção de `permitido_em: ["tests/fixtures/"]` exatamente como passava na
    guarda de caminho.
    """
    tokens = [t.strip("\"'") for t in trecho.split()]
    caminhos = [t for t in tokens if not t.startswith("-") and ("/" in t or "\\" in t or "." in t)]
    if not caminhos:
        return False
    return all(
        any(_sob_prefixo(posixpath.normpath(t.replace("\\", "/")).lower(), p) for p in permitido)
        for t in caminhos
    )


def _autoteste(projeto: str) -> int:
    """Casos universais sempre; casos do projeto derivados do `harness.json` dele."""
    from harness_memoria.config import ErroDeConfig, carregar, raiz_projeto

    raiz = raiz_projeto(projeto)
    try:
        cfg = carregar(raiz)
    except ErroDeConfig as e:
        print(f"FALHA config inválida: {e}")
        return 1
    if cfg is None:
        print(f"[{ROTULO}] {raiz} não tem `.claude/harness.json` — hook inerte por desenho")
        return 0
    g = cfg.guardas

    casos: list[tuple[str, dict, bool, str]] = [
        ("Write", {"file_path": "C:/proj/.env"}, g.universais, "universal"),
        ("Write", {"file_path": "C:/proj/.env.example"}, False, "universal"),
        ("Write", {"file_path": "C:/proj/.env.local"}, g.universais, "universal"),
        ("Write", {"file_path": "docs/adr/0001-x.md"}, False, "universal"),
        ("Bash", {"command": "git add ."}, False, "universal"),
        ("Bash", {"command": "git add -f dados/x.bin"}, g.universais, "universal"),
        ("Bash", {"command": "git add .env"}, g.universais, "universal"),
        ("Bash", {"command": "git commit -m 'x' --no-verify"}, g.universais, "universal"),
        ("Bash", {"command": "pnpm build"}, False, "universal"),
        # Um positivo e um negativo por regex, porque cada par abaixo é um furo que passava
        # com `ConfigGuardas()` de fábrica — ou um falso positivo que o conserto poderia
        # criar. O CI roda estes casos em todo push.
        ("Bash", {"command": "git commit -n -m 'x'"}, g.universais, "universal"),
        ("Bash", {"command": "git commit -nm 'x'"}, g.universais, "universal"),
        ("Bash", {"command": "git commit -am 'x'"}, False, "universal"),
        ("Bash", {"command": "git commit --amend --no-edit"}, False, "universal"),
        ("Bash", {"command": "git commit -m 'nunca use --no-verify'"}, False, "universal"),
        ("Bash", {"command": "git push --no-verify"}, g.universais, "universal"),
        ("Bash", {"command": "git push -n origin main"}, False, "universal"),
        ("Bash", {"command": "echo 'API_KEY=sk-real' > .env"}, g.universais, "universal"),
        ("Bash", {"command": "printf 'A=1\\n' >> .env"}, g.universais, "universal"),
        ("Bash", {"command": "cp .env.example .env"}, g.universais, "universal"),
        ("Bash", {"command": "cat > .env <<'X'"}, g.universais, "universal"),
        ("PowerShell", {"command": "Set-Content .env 'A=1'"}, g.universais, "universal"),
        ("Bash", {"command": "cp .env.example .env.example.bak"}, False, "universal"),
        ("Bash", {"command": "echo x > .environment"}, False, "universal"),
        ("Bash", {"command": "cat .env | grep KEY && echo ok > log.txt"}, False, "universal"),
        # Ressalva (a): `_ENV_SEM_SEGREDO` tem QUATRO grafias, não só `.env.example` — e a
        # exceção vale tanto em `Write` quanto na rota de shell, os dois sítios que a citam.
        ("Write", {"file_path": "C:/proj/.env.sample"}, False, "universal"),
        ("Write", {"file_path": "C:/proj/.env.template"}, False, "universal"),
        ("Write", {"file_path": "C:/proj/.env.dist"}, False, "universal"),
        ("Write", {"file_path": "C:/proj/.env.staging"}, g.universais, "universal"),
        ("Bash", {"command": "cp .env.example .env.template"}, False, "universal"),
        # Ressalva (c): o bloqueio de `cp .env backup.txt` é correto (mesmo dano do
        # redirecionamento já bloqueado abaixo); o autoteste só confere SE bloqueia — o
        # TEXTO do motivo (que muda de `MOTIVO_ENV` para `MOTIVO_COPIA_ENV`) é conferido em
        # `tests/test_guardar_ressalvas.py`, que o booleano aqui não alcança.
        ("Bash", {"command": "cp .env backup.txt"}, g.universais, "universal"),
        ("Bash", {"command": "cat .env > backup.txt"}, False, "universal"),
    ]

    # Um caso positivo e um negativo por regra do projeto: uma guarda configurada e nunca
    # exercitada é uma guarda que ninguém sabe se funciona.
    for regra in g.caminhos:
        padrao = str(regra.get("padrao") or "")
        exemplo = padrao.replace("*", "exemplo") if "*" in padrao else padrao
        casos.append(("Write", {"file_path": f"dados/{exemplo}"}, True, f"projeto:{padrao}"))
        for permitido in tuple(regra.get("permitido_em") or ())[:1]:
            base = permitido.rstrip("/")
            casos.append(
                (
                    "Write",
                    {"file_path": f"{base}/{exemplo}"},
                    False,
                    f"projeto:{padrao} liberado",
                )
            )
            # A exceção não pode virar porta. `{base}/../../` passava em qualquer grafia de
            # prefixo, porque a comparação era substring sem `normpath` — basta o modelo
            # escrever caminho relativo com `..`. E `{base}_antigos/` passava quando o
            # prefixo era escrito sem a barra final, que é a grafia mais curta. Os dois
            # casos são derivados das regras DESTE projeto: é o CI do consumidor que
            # confere a fronteira dele.
            casos.append(
                (
                    "Write",
                    {"file_path": f"{base}/../../{exemplo}"},
                    True,
                    f"projeto:{padrao} travessia",
                )
            )
            casos.append(
                (
                    "Write",
                    {"file_path": f"{base}_antigos/{exemplo}"},
                    True,
                    f"projeto:{padrao} vizinho",
                )
            )
    for regra in g.comandos:
        exemplo = str(regra.get("exemplo") or "")
        if exemplo:
            casos.append(("Bash", {"command": exemplo}, True, "projeto:comando"))

    falhas = 0
    for ferramenta, entrada, deve_bloquear, familia in casos:
        motivo = avaliar(ferramenta, entrada, g)
        ok = bool(motivo) == deve_bloquear
        falhas += 0 if ok else 1
        alvo = entrada.get("file_path") or entrada.get("command")
        print(
            f"{'ok   ' if ok else 'FALHA'} [{familia}] {ferramenta:<11} {alvo!r:<48} "
            f"{'bloqueado' if motivo else 'liberado'}"
        )
    print(f"\n{len(casos) - falhas}/{len(casos)} casos corretos")
    return 1 if falhas else 0


def _arg(argv: list[str], nome: str) -> str | None:
    if nome in argv:
        i = argv.index(nome)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception as e:  # noqa: BLE001
        print(
            f"[{ROTULO}] hook falhou, liberando por segurança: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        codigo = 0
    sys.exit(codigo)
