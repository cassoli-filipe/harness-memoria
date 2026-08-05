#!/usr/bin/env python3
"""Hook PreToolUse — bloqueio determinístico das proibições absolutas.

Proibição absoluta é hook, não frase no CLAUDE.md: regra que roda fora do raciocínio do
modelo não decai ao longo da sessão.

Duas famílias de regra:

* **universais** — `.env` e `--no-verify`. Valem em todo projeto e não têm caso legítimo:
  nenhum agente precisa escrever segredo, e hook de commit que incomoda se corrige, não se
  pula. Desligáveis por `guardas.universais: false`, para o caso que eu não previ.
* **do projeto** — vêm de `guardas.caminhos` e `guardas.comandos` no `harness.json`. É onde
  mora "planilha com dado de aluno fora de fixtures" (rede_inspira_app) ou "escrita no
  Pipedrive" (ValidaNI).

O gate vale aqui também: num projeto sem `.claude/harness.json` este hook não bloqueia
nada, nem as universais. Negar tool call num repositório que nunca pediu o harness é
surpresa, e surpresa em bloqueio queima a confiança no mecanismo inteiro.

Autoteste:  python src/harness_memoria/hooks/guardar.py --autoteste [--projeto CAMINHO]
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness_memoria.config import ConfigGuardas  # noqa: E402
from harness_memoria.hooks import _comum as C  # noqa: E402

ROTULO = "guarda"
FERRAMENTAS_DE_ESCRITA = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
FERRAMENTAS_DE_SHELL = {"Bash", "PowerShell"}


def main(argv: list[str] | None = None) -> int:
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
    norm = caminho.replace("\\", "/")
    nome = PurePosixPath(norm).name
    baixo = norm.lower()

    if g.universais and (nome == ".env" or (nome.startswith(".env.") and nome != ".env.example")):
        return (
            f"Bloqueado: `{nome}` guarda segredos e está no .gitignore. "
            "Edite `.env.example` (sem valores) e peça ao usuário para preencher o `.env`."
        )

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
        if any(p.lower() in baixo for p in permitido):
            continue
        motivo = str(regra.get("motivo") or f"`{padrao}` é proibido neste projeto")
        onde = f" Permitido em: {', '.join(permitido)}." if permitido else ""
        return f"Bloqueado: `{nome}` — {motivo}{onde}"
    return None


def _avaliar_comando(comando: str, g: ConfigGuardas) -> str | None:
    c = " ".join(comando.split())
    baixo = c.lower()

    if g.universais:
        if re.search(r"\bgit\s+(commit|push)\b.*--no-verify", baixo):
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

    for regra in g.comandos:
        padrao = str(regra.get("regex") or "")
        if not padrao:
            continue
        try:
            if not re.search(padrao, baixo):
                continue
        except re.error as e:
            print(
                f"[{ROTULO}] regex inválida em guardas.comandos: {padrao} ({e})",
                file=sys.stderr,
            )
            continue
        permitido = tuple(regra.get("permitido_em") or ())
        if permitido and _todo_caminho_permitido(baixo, permitido):
            continue
        motivo = str(regra.get("motivo") or f"comando casa `{padrao}`")
        onde = f" Permitido em: {', '.join(permitido)}." if permitido else ""
        return f"Bloqueado: {motivo}{onde}"
    return None


def _todo_caminho_permitido(comando: str, permitido: tuple[str, ...]) -> bool:
    """`permitido_em` de `guardas.comandos`: TODO caminho citado está sob um prefixo?

    Semântica deliberadamente conservadora — **todo**, não "algum". Um comando misto
    como `git add tests/fixtures/ok.xlsx dados/roster.xlsx` continua bloqueado, porque
    liberar pelo primeiro token permitido deixaria a exceção virar porta: bastaria
    citar um caminho inocente ao lado do proibido.

    "Caminho citado" é o token que tem separador ou extensão. `git`, `add` e `-u` não
    têm, então não contam — só flag e subcomando ficariam de fora, e nenhum dos dois é
    caminho. Extensão sem diretório (`planilha.xlsx`, na raiz) conta e não está sob
    prefixo nenhum, então bloqueia: é o caso que a regra existe para pegar.
    """
    tokens = [t.strip("\"'") for t in comando.split()]
    caminhos = [t for t in tokens if not t.startswith("-") and ("/" in t or "\\" in t or "." in t)]
    if not caminhos:
        return False
    prefixos = tuple(p.lower().replace("\\", "/") for p in permitido)
    return all(any(p in t.replace("\\", "/") for p in prefixos) for t in caminhos)


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
    ]

    # Um caso positivo e um negativo por regra do projeto: uma guarda configurada e nunca
    # exercitada é uma guarda que ninguém sabe se funciona.
    for regra in g.caminhos:
        padrao = str(regra.get("padrao") or "")
        exemplo = padrao.replace("*", "exemplo") if "*" in padrao else padrao
        casos.append(("Write", {"file_path": f"dados/{exemplo}"}, True, f"projeto:{padrao}"))
        for permitido in tuple(regra.get("permitido_em") or ())[:1]:
            casos.append(
                (
                    "Write",
                    {"file_path": f"{permitido.rstrip('/')}/{exemplo}"},
                    False,
                    f"projeto:{padrao} liberado",
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
