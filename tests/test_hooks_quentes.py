"""Os três hooks do caminho quente: pré-gate, imports e as guardas determinísticas.

Este arquivo existe porque a cobertura medida com um tracer de stdlib dava **zero** para os
cinco hooks — 431 instruções, nenhuma executada em processo pela suíte (`guardar` 0/106,
`reafirmar` 0/74, `formatar` 0/60). Os quatro hooks fora de `guardar` só apareciam na lista
parametrizada de `test_hook_e_inerte_em_projeto_sem_config`, cuja asserção é AUSÊNCIA de
saída: eram testados não fazendo nada, nunca fazendo algo. "Os testes passam" não era prova
de nada sobre este caminho.

Duas famílias de teste, e a divisão é deliberada:

* **subprocesso** — é como o Claude Code roda os hooks, e é a única forma de exercitar o
  bootstrap de `sys.path`, o pré-gate (que roda em tempo de import) e o `__main__`.
* **em processo** — para as funções puras de decisão (`avaliar`, `gate_barato`), onde 40
  casos custam menos que um subprocesso.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import escrever_config

from harness_memoria.config import NOME_ARQUIVO, ConfigGuardas
from harness_memoria.hooks import _leve
from harness_memoria.hooks.guardar import avaliar

SRC = Path(__file__).resolve().parents[1] / "src"
HOOKS = SRC / "harness_memoria" / "hooks"
QUENTES = ("guardar.py", "reafirmar.py", "formatar.py")


def _evento(raiz: Path, ferramenta: str = "Write", **entrada: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": ferramenta,
            "session_id": "s-teste",
            "cwd": str(raiz),
            "tool_input": entrada or {"file_path": str(raiz / "x.py")},
        }
    )


def _rodar(hook: Path, evento: str, cwd: Path, env_extra: dict | None = None, args=()):
    """O hook como o Claude Code o roda: subprocesso, evento no stdin, cwd no projeto."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(hook), *args],
        input=evento,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        env=env,
        timeout=120,
    )


@pytest.fixture
def alheio(tmp_path: Path) -> Path:
    """Projeto que NÃO adotou o harness. O cenário que pagava 48,5 s por sessão."""
    raiz = tmp_path / "alheio"
    raiz.mkdir()
    (raiz / "CLAUDE.md").write_text("# Projeto que não usa o harness\n", encoding="utf-8")
    return raiz


# --------------------------------------------------------------------------- #
# Pré-gate: o hook decide antes de importar (lote 2)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("hook", QUENTES)
def test_pre_gate_nao_importa_o_pacote_em_projeto_sem_config(alheio: Path, hook: str):
    """A prova direta do lote 2: em projeto sem config, `config` nunca é importado.

    Não é um teste de tempo — tempo mede a máquina. É um teste do que foi carregado, com
    `-X importtime`, que é a causa: 85,6 ms de cada hook eram import, contra 0,24 ms de
    `carregar()`. Antes desta mudança `harness_memoria.config` aparecia aqui em todos os
    três, junto com `dataclasses`, `inspect`, `tempfile` e `shutil`.
    """
    r = subprocess.run(
        [sys.executable, "-X", "importtime", str(HOOKS / hook)],
        input=_evento(alheio),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(alheio),
        env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"{hook} produziu saída em projeto sem config"
    carregados = r.stderr
    assert "harness_memoria.hooks._leve" in carregados, "o pré-gate não rodou"
    for modulo in ("harness_memoria.config", "harness_memoria.diario", "dataclasses", "tempfile"):
        assert modulo not in carregados, f"{hook} importou {modulo} para não fazer nada"


@pytest.mark.parametrize("hook", QUENTES)
def test_com_config_o_hook_importa_o_pacote_inteiro(projeto: Path, hook: str):
    """O outro lado, e ele é obrigatório: o pré-gate não pode ter matado o caminho normal.

    Um hook silenciosamente inerte também devolve rc=0 e stdout vazio — é o modo de falha
    próprio desta mudança, e o único jeito de distingui-lo de sucesso é exigir que o
    trabalho tenha acontecido.
    """
    r = subprocess.run(
        [sys.executable, "-X", "importtime", str(HOOKS / hook)],
        input=_evento(projeto),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(projeto),
        env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "harness_memoria.config" in r.stderr, f"{hook} ficou inerte em projeto COM config"


def test_guardar_bloqueia_env_em_projeto_com_config(projeto: Path):
    """Saída NÃO VAZIA com config: o complemento do cheque de gate do CI.

    O job `Gate` do `ci.yml` exige saída vazia sem config, e rc=0 é o que um hook morto
    devolve também. Sem este par, um pré-gate que matasse o hook em TODO projeto passaria
    no CI inteiro.
    """
    r = _rodar(HOOKS / "guardar.py", _evento(projeto, file_path=str(projeto / ".env")), projeto)
    assert r.returncode == 0, r.stderr
    assert '"permissionDecision": "deny"' in r.stdout
    assert ".env" in r.stdout


def test_pre_gate_honra_claude_project_dir_contra_o_cwd(projeto: Path, alheio: Path):
    """`CLAUDE_PROJECT_DIR` ganha do cwd — é aí que o pré-gate é EXATO, não aproximado.

    A plataforma seta essa variável em todo hook, e `config.raiz_projeto` também a consulta
    primeiro. Se o pré-gate olhasse só o cwd, um `claude` aberto num subdiretório (ou um cwd
    herdado de outro projeto) deixaria o harness silenciosamente inerte — que é o modo de
    falha mais caro desta mudança, porque não faz ruído nenhum.
    """
    r = _rodar(
        HOOKS / "guardar.py",
        _evento(projeto, file_path=str(projeto / ".env")),
        cwd=alheio,
        env_extra={"CLAUDE_PROJECT_DIR": str(projeto)},
    )
    assert r.returncode == 0, r.stderr
    assert '"permissionDecision": "deny"' in r.stdout


def test_pre_gate_nao_mata_o_autoteste(projeto: Path, alheio: Path):
    """`--autoteste` recebe o projeto por argumento; o cwd não é ele.

    Sem a guarda, `guardar.py --autoteste --projeto <com-config>` rodado de um diretório sem
    `harness.json` devolvia saída VAZIA com rc=0 — o CI ficaria verde tendo executado zero
    casos.
    """
    r = _rodar(
        HOOKS / "guardar.py", "", cwd=alheio, args=("--autoteste", "--projeto", str(projeto))
    )
    assert r.returncode == 0, r.stderr
    assert "casos corretos" in r.stdout
    assert "[universal]" in r.stdout


def test_autoteste_de_reafirmar_passa_com_cwd_em_projeto_sem_config(projeto: Path, alheio: Path):
    """O autoteste de `reafirmar` re-executa o próprio script, e o filho passa pelo pré-gate.

    Sem `cwd=raiz` no `subprocess.run` do autoteste o filho herda o cwd do PAI: rodado de
    dentro de um projeto sem `harness.json`, o resultado passava de "todos os casos
    corretos" para "1 caso(s) com falha · sai em [15, 30], saiu em []". Hoje o `ci.yml` não
    pegaria isso porque a raiz do harness não tem `CLAUDE.md`; no dia em que tiver (a
    auto-hospedagem), o job ficaria vermelho pelo motivo errado.
    """
    r = _rodar(
        HOOKS / "reafirmar.py", "", cwd=alheio, args=("--autoteste", "--projeto", str(projeto))
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert "todos os casos corretos" in r.stdout, r.stdout


@pytest.mark.parametrize("hook", QUENTES)
def test_importar_o_modulo_do_hook_nao_encerra_o_processo(alheio: Path, hook: str, monkeypatch):
    """Importar o hook a partir de um projeto sem config NÃO pode chamar `sys.exit`.

    O pré-gate roda em tempo de import. Sem a guarda `__name__ == "__main__"`, um `pytest`
    lançado de qualquer diretório que tenha `CLAUDE.md` e não tenha `.claude/harness.json`
    mataria a própria coleta — e a suíte importa estes módulos para testar `avaliar()`.
    """
    monkeypatch.chdir(alheio)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    for nome in [m for m in list(sys.modules) if m.startswith("harness_memoria.hooks")]:
        del sys.modules[nome]
    __import__(f"harness_memoria.hooks.{hook[:-3]}")  # não deve levantar SystemExit


# --------------------------------------------------------------------------- #
# `_leve`: o módulo que não pode importar nada
# --------------------------------------------------------------------------- #


def test_leve_nao_importa_nada_alem_de_os_e_sys():
    """A invariante do módulo. Um import a mais aqui devolve o custo que ele existe para
    evitar, e devolve no caminho que roda 320 vezes por sessão."""
    fonte = (HOOKS / "_leve.py").read_text(encoding="utf-8")
    importados = [
        linha.strip()
        for linha in fonte.splitlines()
        if linha.startswith(("import ", "from ")) and "__future__" not in linha
    ]
    assert importados == ["import os", "import sys"], importados


def test_nome_do_arquivo_de_config_nao_divergiu():
    """`_leve` reescreve o nome do `harness.json` em vez de importar `config.NOME_ARQUIVO`.

    A cópia é deliberada — importar a constante custaria os 27,7 ms de `config`, que é o
    ponto do módulo. Este teste é o que impede as duas de divergirem: se elas divergirem, o
    pré-gate passa a responder `False` num projeto que ADOTOU o harness, e todo hook fica
    silenciosamente inerte.
    """
    assert _leve.NOME_CONFIG == NOME_ARQUIVO


def test_gate_barato_e_tri_estado(tmp_path: Path, monkeypatch):
    """`False` só quando achou a raiz e ela não adotou. Sem raiz, `None` — não `False`.

    A distinção é a segurança do desenho: só o `False` encurta o caminho, então só ele
    precisa estar certo. `None` significa ignorância e devolve a decisão para
    `config.raiz_projeto`, que é a autoridade.
    """
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

    sem_claude = tmp_path / "nada"
    sem_claude.mkdir()
    monkeypatch.chdir(sem_claude)
    assert _leve.gate_barato() is None

    sem_config = tmp_path / "alheio"
    sem_config.mkdir()
    (sem_config / "CLAUDE.md").write_text("# x\n", encoding="utf-8")
    monkeypatch.chdir(sem_config)
    assert _leve.gate_barato() is False

    (sem_config / ".claude").mkdir()
    (sem_config / ".claude" / NOME_ARQUIVO).write_text("{}", encoding="utf-8")
    assert _leve.gate_barato() is True

    # A variável é o primeiro candidato, mas quando ela não é raiz o cwd ainda vale: é a
    # mesma ordem de `config.raiz_projeto`, e é o que faz `claude` aberto num subdiretório
    # continuar funcionando.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(sem_claude))
    assert _leve.gate_barato() is True
    monkeypatch.chdir(sem_claude)
    assert _leve.gate_barato() is None
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(sem_config))
    assert _leve.gate_barato() is True


def test_sair_sem_fazer_nada_drena_o_stdin(monkeypatch, capsys):
    """Drenar não é higiene: o Claude Code escreve o evento no pipe do hook.

    Um processo que sai sem ler deixa a escrita do outro lado sem leitor. E o código de
    saída tem de ser 0, que é a política de todos os hooks.
    """
    import io

    falso = io.StringIO('{"cwd": "/x"}')
    monkeypatch.setattr(sys, "stdin", falso)
    with pytest.raises(SystemExit) as e:
        _leve.sair_sem_fazer_nada("[teste] aviso")
    assert e.value.code == 0
    assert falso.read() == "", "o stdin não foi drenado"
    assert "[teste] aviso" in capsys.readouterr().err


def test_sair_sem_fazer_nada_sobrevive_a_stdin_ausente(monkeypatch):
    """`pythonw` e alguns runners entregam `sys.stdin is None`. Sair com 0 mesmo assim."""
    monkeypatch.setattr(sys, "stdin", None)
    with pytest.raises(SystemExit) as e:
        _leve.sair_sem_fazer_nada()
    assert e.value.code == 0


def test_forcar_utf8_de_leve_equivale_ao_de_diario(tmp_path: Path):
    """A cópia de `forcar_utf8` em `_leve` tem de se comportar como a de `diario`.

    São duas implementações da mesma coisa, com mecanismos de supressão diferentes
    (`contextlib.suppress` lá, `try/except` aqui, porque `import contextlib` custa 14,8 ms
    no ponto em que `_leve` roda). Duas implementações divergem na primeira correção — este
    teste é o que faz a divergência aparecer.
    """
    prog = "\n".join(
        [
            f"import sys; sys.path.insert(0, {str(SRC)!r})",
            "from harness_memoria.hooks._leve import forcar_utf8 as a",
            "from harness_memoria.diario import forcar_utf8 as b",
            "a(); x = sys.stdout.encoding",
            "b(); y = sys.stdout.encoding",
            "class Mudo: pass",
            "orig = sys.stdout; sys.stdout = Mudo()",
            # Nenhuma das duas pode levantar num stream sem `reconfigure`.
            "a(); b()",
            "sys.stdout = orig",
            "print(x, y)",
        ]
    )
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    x, y = r.stdout.split()
    assert x == y == "utf-8"


# --------------------------------------------------------------------------- #
# Imports do caminho quente (lote 3)
# --------------------------------------------------------------------------- #


def test_comum_nao_arrasta_diario_nem_tempfile():
    """`import _comum` custava 143,5 ms contra 120,8 de `config`, e os 23 ms eram estes.

    `tempfile` (18,2 ms, arrastando `shutil`) para uma função que `guardar` e `formatar`
    nunca chamam, e `..diario` (9,1 ms, arrastando `subprocess` e `datetime`) para trazer
    uma função de 4 linhas que reconfigura o stdout.
    """
    suspeitos = ("harness_memoria.diario", "tempfile", "shutil", "subprocess")
    prog = "\n".join(
        [
            f"import sys; sys.path.insert(0, {str(SRC)!r})",
            "from harness_memoria.hooks import _comum",
            f"print(' '.join(m for m in {suspeitos!r} if m in sys.modules))",
        ]
    )
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"_comum ainda arrasta: {r.stdout.strip()}"


def test_contador_de_sessao_funciona_com_tempfile_local(projeto: Path):
    """`pasta_estado` passou a importar `tempfile` dentro da função — o contador tem de
    continuar contando. É o caminho que `reafirmar` usa a cada escrita e que tinha 0/42 de
    cobertura."""
    from harness_memoria.hooks import _comum as C

    sessao = "teste-tempfile-local"
    C.apagar_contador(projeto, sessao)
    assert C.ler_contador(projeto, sessao) == 0
    assert C.incrementar_contador(projeto, sessao) == 1
    assert C.incrementar_contador(projeto, sessao) == 2
    assert C.ler_contador(projeto, sessao) == 2
    C.apagar_contador(projeto, sessao)
    assert C.ler_contador(projeto, sessao) == 0


def test_um_which_por_formatador(projeto: Path, monkeypatch):
    """Eram três `shutil.which` por regra (`nome`, `.cmd`, `.exe`) e as duas extras nunca
    achavam nada que a primeira não achasse — `which` já expande `PATHEXT` sozinho. Custam
    9,6 ms cada quando não acham."""
    from harness_memoria.hooks import formatar

    chamadas: list[str] = []

    def espiao(nome, *a, **k):
        chamadas.append(nome)
        return None

    monkeypatch.setattr(shutil, "which", espiao)
    formatar._talvez_formatar(
        {"extensoes": [".py"], "comando": ["formatador-que-nao-existe", "{arquivo}"]},
        projeto / "scripts" / "checar.py",
        projeto,
    )
    assert chamadas == ["formatador-que-nao-existe"], chamadas


def test_formatar_nao_importa_shutil_quando_a_extensao_nao_casa(projeto: Path):
    """`_talvez_formatar` é chamada para TODA regra do projeto, antes do teste de extensão.

    Uma escrita em `.md` num projeto que só configura `.py` não tem por que carregar
    `shutil` (10,0 ms) nem `subprocess` (6,8 ms). Pôr os imports no topo da função não
    capturava nada: eles têm de vir DEPOIS do `return` da extensão.
    """
    regra = {"extensoes": [".py"], "comando": ["ruff", "{arquivo}"]}
    prog = "\n".join(
        [
            f"import sys; sys.path.insert(0, {str(SRC)!r})",
            "from pathlib import Path",
            "from harness_memoria.hooks import formatar",
            f"formatar._talvez_formatar({regra!r}, Path({str(projeto / 'README.md')!r}),"
            f" Path({str(projeto)!r}))",
            "print(' '.join(m for m in ('shutil', 'subprocess') if m in sys.modules))",
        ]
    )
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"importou {r.stdout.strip()} para uma extensão que não casa"


# --------------------------------------------------------------------------- #
# Achado do crítico: o import do pacote sob a mesma rede que o resto do hook
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("hook", QUENTES)
def test_pacote_quebrado_nao_derruba_a_sessao(tmp_path: Path, projeto: Path, hook: str):
    """Erro de sintaxe em `config.py` → rc=0 e mensagem ROTULADA, não traceback cru.

    O `try/except Exception` que implementa "nunca derrubar a sessão" começava no
    `__main__`, e o `from harness_memoria...` ficava fora dele — a única linha sem rede,
    num arquivo cujo docstring promete o contrário. Com `config.py` truncado (o que um `git
    pull` no meio ou um arquivo pela metade produzem), os três hooks saíam com **rc=1**,
    stdout vazio e `SyntaxError` cru no stderr, a cada tool call, e o `.env` não era
    bloqueado. A mensagem desenhada para esse caso nunca era impressa.
    """
    src = tmp_path / "src"
    shutil.copytree(SRC, src, ignore=shutil.ignore_patterns("__pycache__"))
    alvo = src / "harness_memoria" / "config.py"
    alvo.write_text(alvo.read_text(encoding="utf-8") + "\ndef quebrado(:\n", encoding="utf-8")

    r = _rodar(
        src / "harness_memoria" / "hooks" / hook,
        _evento(projeto, file_path=str(projeto / ".env")),
        cwd=projeto,
    )
    assert r.returncode == 0, f"{hook} saiu com {r.returncode}"
    assert r.stdout.strip() == ""
    assert "Traceback" not in r.stderr, r.stderr
    assert hook[:-3].replace("guardar", "guarda") in r.stderr, r.stderr


@pytest.mark.parametrize("hook", QUENTES)
def test_leve_quebrado_reporta_a_causa_e_nao_a_consequencia(
    tmp_path: Path, projeto: Path, hook: str
):
    """O arquivo truncado é o próprio `_leve` — o caso que o pré-gate criou.

    `_leve` é importado DENTRO do `try` de bootstrap, então quando ele é o quebrado o nome
    `L` nunca chega a existir, e o ramo que reporta o erro chamava `L.sair_sem_fazer_nada`.
    Medido antes da correção: `guardar` e `reafirmar` diziam `NameError: name 'L' is not
    defined` — mandando procurar bug NO HOOK em vez do arquivo pela metade —, e `formatar`
    era pior, porque o `except` do `__main__` dele engole sem imprimir: stderr
    completamente vazio, hook silenciosamente inerte.

    A mensagem é o produto deste ramo. `rc=0` já era verdade antes (o `except` do `__main__`
    pegava o `NameError`), então um teste que só olhasse o código de saída passaria nas duas
    árvores e não testaria nada.
    """
    src = tmp_path / "src"
    shutil.copytree(SRC, src, ignore=shutil.ignore_patterns("__pycache__"))
    alvo = src / "harness_memoria" / "hooks" / "_leve.py"
    alvo.write_text(alvo.read_text(encoding="utf-8") + "\ndef quebrado(:\n", encoding="utf-8")

    r = _rodar(
        src / "harness_memoria" / "hooks" / hook,
        _evento(projeto, file_path=str(projeto / ".env")),
        cwd=projeto,
    )
    assert r.returncode == 0, f"{hook} saiu com {r.returncode}"
    assert r.stdout.strip() == ""
    assert "NameError" not in r.stderr, f"reportou a consequência, não a causa: {r.stderr}"
    assert "SyntaxError" in r.stderr, f"não nomeou a causa: {r.stderr!r}"
    assert "_leve.py" in r.stderr, f"não nomeou o arquivo quebrado: {r.stderr!r}"
    assert hook[:-3].replace("guardar", "guarda") in r.stderr, r.stderr


# --------------------------------------------------------------------------- #
# Guardas universais: `--no-verify` (lote 8.1)
# --------------------------------------------------------------------------- #

_G = ConfigGuardas()


@pytest.mark.parametrize(
    "comando",
    [
        "git commit -n -m 'x'",
        "git commit -nm 'x'",
        "git commit -anm 'ajuste'",
        "git commit --no-verify -m 'x'",
        "git commit -m 'x' --no-verify",
        "git push --no-verify",
        "git push origin main --no-verify",
    ],
)
def test_no_verify_em_todas_as_grafias_bloqueia(comando: str):
    """`git commit -h` confirma `-n, --no-verify`. A regex antiga só olhava a forma longa.

    `-n` e `-nm` são o bypass mais curto do teclado e o passo obvio seguinte a um commit
    reprovado por hook — não exigem intenção adversária, só pressa.
    """
    assert avaliar("Bash", {"command": comando}, _G) is not None


@pytest.mark.parametrize(
    "comando",
    [
        "git commit -am 'x'",
        "git commit --amend --no-edit",
        "git commit -m 'x' --no-gpg-sign",
        "git push -n origin main",
        "git push --dry-run",
        "git commit -m 'nunca use --no-verify neste projeto'",
        'git commit -m "documenta o --no-verify"',
        "git push origin main && echo 'nunca use --no-verify'",
    ],
)
def test_no_verify_nao_produz_falso_positivo(comando: str):
    """Falso positivo em bloqueio ensina a desligar a guarda inteira.

    Três classes aqui: `-am`/`--amend`/`--no-gpg-sign` não têm `n` como flag curta solta;
    `git push -n` é `--dry-run` e por isso o `push` só casa a forma longa; e a menção a
    `--no-verify` DENTRO de um literal (mensagem de commit, ou outro comando depois de
    `&&`) não é uso — daí apagar os literais e trocar `.*` por `[^&|;]*`.
    """
    assert avaliar("Bash", {"command": comando}, _G) is None


# --------------------------------------------------------------------------- #
# Guardas universais: escrever `.env` por shell (lote 8.1)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "comando",
    [
        "echo 'API_KEY=sk-real' > .env",
        "echo API_KEY=1 >.env",
        "printf 'A=1\\n' >> .env",
        "cat > .env <<'X'",
        "cp .env.example .env",
        "cp .env .env.bak",
        "mv /tmp/segredos .env",
        "echo x | tee .env",
        "Set-Content .env 'A=1'",
        "Out-File -FilePath .env",
        'echo "DB=1" > "C:\\proj\\.env"',
        "echo x > config/.env",
        "echo x > .env.local",
        "npm run seed && echo 'A=1' > .env",
    ],
)
def test_escrita_de_env_por_shell_bloqueia(comando: str):
    """O hook só olhava `file_path` nas ferramentas de escrita e regex de `git` no shell.

    Com `ConfigGuardas()` de fábrica, todos estes passavam batido — e escrever o `.env` por
    shell é literalmente o próximo movimento de quem acabou de ter um `Write` em `.env`
    negado. Guarda que se contorna assim é pior que guarda ausente, porque quem a instalou
    conta com ela.
    """
    assert avaliar("Bash", {"command": comando}, _G) is not None


@pytest.mark.parametrize(
    "comando",
    [
        "echo 'A=' > .env.example",
        "cp .env.example .env.example.bak",
        "echo x > .environment",
        "echo x > .env-backup",
        "cat .env",
        "grep KEY .env",
        "cat .env | grep KEY && echo ok > log.txt",
        "echo ok > log.txt",
        "rm .env",
        'echo "veja .env para detalhes" > README.md',
        'printf "copie .env.example para .env" >> docs/setup.md',
    ],
)
def test_escrita_de_env_por_shell_nao_produz_falso_positivo(comando: str):
    """`.env.example` é a exceção explícita — é o arquivo que o agente DEVE editar.

    `.environment` e `.env-backup` não são `.env`: é a fronteira do token que os separa.
    Leitura não é escrita, e o gatilho e o alvo têm de estar no MESMO segmento, senão
    `cat .env | grep KEY && echo ok > log.txt` bloquearia.

    Os dois últimos são a classe que a primeira versão desta guarda bloqueava: um `.env`
    CITADO num texto que vai para outro arquivo. Menção não é alvo — daí o alvo do
    redirecionamento ser o que vem depois do último `>`, e não qualquer `.env` do segmento.
    """
    assert avaliar("Bash", {"command": comando}, _G) is None


def test_universais_desligaveis_valem_para_a_guarda_nova(projeto: Path):
    """`guardas.universais: false` desliga as TRÊS famílias, inclusive a rota de shell.

    Quem escreve `false` aqui está dizendo "eu assumo"; a guarda nova não pode virar uma
    quarta coisa que ele não consegue desligar.
    """
    desligadas = ConfigGuardas(universais=False)
    assert avaliar("Bash", {"command": "echo 'A=1' > .env"}, desligadas) is None
    assert avaliar("Bash", {"command": "git commit -nm 'x'"}, desligadas) is None


# --------------------------------------------------------------------------- #
# Guardas do projeto: caixa da regex (lote 8.2)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("grafia", ["Set-Content dados/x.csv", "set-content dados/x.csv"])
def test_regra_com_maiuscula_casa_as_duas_grafias(grafia: str):
    """O comando vinha minusculado e o padrão não: a regra não casava NADA.

    Com `{"regex": "Set-Content[^&|;]*\\\\.csv"}` passavam `Set-Content dados/x.csv` E
    `set-content dados/x.csv` — a config afirmava uma guarda que não existia em nenhuma
    grafia. A seção irmã `guardas.caminhos` já normalizava os dois lados
    (`fnmatch(nome.lower(), padrao.lower())`); a assimetria era só em `comandos`, e
    `Set-Content`, `Remove-Item`, `Invoke-WebRequest` e `DROP TABLE` são as grafias
    naturais de quem escreve a config.
    """
    g = ConfigGuardas(
        comandos=(
            {
                "regex": r"Set-Content[^&|;]*\.csv",
                "motivo": "planilha não se escreve por shell",
                "exemplo": "Set-Content dados/x.csv",
            },
        )
    )
    assert avaliar("PowerShell", {"command": grafia}, g) is not None


# --------------------------------------------------------------------------- #
# `permitido_em`: a exceção não pode virar porta (lote 8.3)
# --------------------------------------------------------------------------- #

#: As DUAS grafias de prefixo, porque a barra final decidia o comportamento e ninguém
#: sabia: com `tests/fixtures/` o teste de substring já barrava `tests/fixtures_antigos/`,
#: com `tests/fixtures` liberava. A config aceita as duas e nada dizia que elas diferiam —
#: e a segunda é a grafia mais curta, portanto a que se escreve sem pensar.
PREFIXOS = ["tests/fixtures/", "tests/fixtures"]


def _planilha(prefixo: str) -> ConfigGuardas:
    return ConfigGuardas(
        caminhos=(
            {
                "padrao": "*.xlsx",
                "permitido_em": [prefixo],
                "motivo": "planilha com dado de aluno não entra no repositório",
            },
        ),
        comandos=(
            {
                "regex": r"\bgit\s+add\b[^&|;]*\.xlsx(\s|$)",
                "permitido_em": [prefixo],
                "motivo": "planilha não entra no repositório",
                "exemplo": "git add dados/roster.xlsx",
            },
        ),
    )


@pytest.mark.parametrize("prefixo", PREFIXOS)
@pytest.mark.parametrize(
    "caminho",
    [
        "tests/fixtures/../../dados/real.xlsx",
        "C:/proj/tests/fixtures/../../producao/alunos.xlsx",
        "tests\\fixtures\\..\\..\\dados\\real.xlsx",
        "tests/fixtures_antigos/alunos.xlsx",
        "tests/fixtures2/alunos.xlsx",
    ],
)
def test_permitido_em_nao_libera_travessia_nem_vizinho(caminho: str, prefixo: str):
    """Duas falhas na mesma comparação, e nenhuma exige intenção adversária.

    A comparação era `prefixo.lower() in caminho.lower()`. Sem `normpath`,
    `tests/fixtures/../../dados/real.xlsx` contém `tests/fixtures/` e passava nas duas
    grafias — basta o modelo escrever caminho relativo com `..`. E sem fronteira de
    caminho, `tests/fixtures_antigos/` contém `tests/fixtures`, então com o prefixo escrito
    sem a barra final um diretório que ninguém autorizou herdava a exceção.

    Parametrizado pelas duas grafias porque a barra final não pode ser o que decide se a
    guarda funciona.
    """
    assert avaliar("Write", {"file_path": caminho}, _planilha(prefixo)) is not None


@pytest.mark.parametrize("prefixo", PREFIXOS)
@pytest.mark.parametrize(
    "caminho",
    [
        "tests/fixtures/alunos.xlsx",
        "tests/fixtures/sub/alunos.xlsx",
        "C:/proj/tests/fixtures/alunos.xlsx",
        "tests\\fixtures\\alunos.xlsx",
        "tests/outro/../fixtures/alunos.xlsx",
    ],
)
def test_permitido_em_continua_liberando_o_caminho_declarado(caminho: str, prefixo: str):
    """O outro lado do 8.3: endurecer a fronteira não pode fechar a porta declarada.

    O último caso é o que só passa por causa do `normpath` — `tests/outro/../fixtures/` É
    `tests/fixtures/`, e com comparação de substring crua ele estaria bloqueado.
    """
    assert avaliar("Write", {"file_path": caminho}, _planilha(prefixo)) is None


@pytest.mark.parametrize("prefixo", PREFIXOS)
def test_permitido_em_de_comando_nao_libera_travessia(prefixo: str):
    """O mesmo furo na função irmã, que decide `permitido_em` para `guardas.comandos`.

    `_todo_caminho_permitido` comparava substring sem normalizar, então
    `git add tests/fixtures/../../dados/real.xlsx` liberava — a exceção virava porta, que é
    exatamente o desenho que o docstring dela rejeita. O conserto é reusar `_sob_prefixo`,
    para as duas seções irmãs terem UMA definição de "está sob o prefixo".
    """
    g = _planilha(prefixo)
    assert avaliar("Bash", {"command": "git add tests/fixtures/alunos.xlsx"}, g) is None
    assert (
        avaliar("Bash", {"command": "git add tests/fixtures/../../dados/real.xlsx"}, g) is not None
    )
    assert avaliar("Bash", {"command": "git add tests/fixtures_antigos/x.xlsx"}, g) is not None


def test_autoteste_exercita_a_travessia_das_regras_do_projeto(projeto: Path):
    """O autoteste deriva os casos das regras do projeto — inclusive os dois furos do 8.3.

    É o que faz o CI de um consumidor real exercitar a fronteira de `permitido_em` dele, e
    não só a do fixture desta suíte. Guarda configurada e nunca exercitada é guarda que
    ninguém sabe se funciona.
    """
    escrever_config(
        projeto,
        {
            "guardas": {
                "caminhos": [
                    {
                        "padrao": "*.xlsx",
                        "permitido_em": ["tests/fixtures/"],
                        "motivo": "planilha não entra",
                    }
                ]
            }
        },
    )
    r = _rodar(HOOKS / "guardar.py", "", cwd=projeto, args=("--autoteste",))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "travessia" in r.stdout, r.stdout
    assert "vizinho" in r.stdout, r.stdout
    assert "FALHA" not in r.stdout, r.stdout


# --------------------------------------------------------------------------- #
# `formatar` de ponta a ponta: o hook com 0/92 de cobertura
# --------------------------------------------------------------------------- #

#: Um "formatador" que não depende de nada instalado na máquina: o próprio interpretador
#: que roda a suíte, em maiúsculas. `sys.executable` é caminho absoluto, e `shutil.which`
#: resolve caminho com diretório sem consultar o PATH — então este teste não fica à mercê
#: de `ruff` morar no `.venv`, que é justamente o caso comum que o hook trata em silêncio.
_MAIUSCULAS = (
    "import pathlib, sys; p = pathlib.Path(sys.argv[1]); "
    "p.write_text(p.read_text(encoding='utf-8').upper(), encoding='utf-8')"
)


def test_formatar_roda_o_formatador_e_muda_o_arquivo(projeto: Path):
    """O caminho que nenhum teste percorria: `subprocess.run` do formatador de verdade.

    `formatar.py` tinha 0/92 linhas cobertas — era exercitado só NÃO fazendo nada, num
    projeto sem config. Um hook cuja única prova é o silêncio não tem prova.
    """
    alvo = projeto / "scripts" / "checar.py"
    alvo.write_text("x = 1\n", encoding="utf-8")
    escrever_config(
        projeto,
        {
            "formatadores": [
                {
                    "extensoes": [".py"],
                    "comando": [sys.executable, "-c", _MAIUSCULAS, "{arquivo}"],
                }
            ]
        },
    )
    r = _rodar(HOOKS / "formatar.py", _evento(projeto, file_path=str(alvo)), projeto)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", "formatar é silencioso por desenho"
    assert alvo.read_text(encoding="utf-8") == "X = 1\n"


def test_exigencia_ausente_nao_roda_o_formatador(projeto: Path):
    """`exige` existe porque `prettier` sem `node_modules` falha em TODA escrita.

    A guarda tem de vencer mesmo com o executável presente — é o único jeito de o hook
    continuar silencioso num checkout sem dependências instaladas.
    """
    alvo = projeto / "scripts" / "checar.py"
    alvo.write_text("x = 1\n", encoding="utf-8")
    escrever_config(
        projeto,
        {
            "formatadores": [
                {
                    "extensoes": [".py"],
                    "comando": [sys.executable, "-c", _MAIUSCULAS, "{arquivo}"],
                    "exige": "node_modules",
                }
            ]
        },
    )
    r = _rodar(HOOKS / "formatar.py", _evento(projeto, file_path=str(alvo)), projeto)
    assert r.returncode == 0, r.stderr
    assert alvo.read_text(encoding="utf-8") == "x = 1\n"


def test_autoteste_de_formatar_declara_o_estado_de_cada_regra(projeto: Path):
    """O autoteste é o que o CI roda; ele tem de distinguir os três estados.

    "ausente no PATH" e "exigência ausente" são os dois motivos legítimos de o hook não
    fazer nada, e confundi-los com "ok" é o que faria alguém procurar bug no formatador.
    """
    escrever_config(
        projeto,
        {
            "formatadores": [
                {"extensoes": [".py"], "comando": ["formatador-que-nao-existe", "{arquivo}"]},
                {
                    "extensoes": [".ts"],
                    "comando": [sys.executable, "-c", "pass", "{arquivo}"],
                    "exige": "node_modules",
                },
                {"extensoes": [".md"], "comando": [sys.executable, "-c", "pass", "{arquivo}"]},
            ]
        },
    )
    r = _rodar(HOOKS / "formatar.py", "", cwd=projeto, args=("--autoteste",))
    assert r.returncode == 0, r.stderr
    assert "ausente no PATH" in r.stdout, r.stdout
    assert "exigência ausente" in r.stdout, r.stdout
    assert ": ok" in r.stdout, r.stdout
