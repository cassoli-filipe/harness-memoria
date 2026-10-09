"""CLI da auditoria.

    python -m harness_memoria.auditar [--projeto CAMINHO] [--silencioso] [--corrigir]

Roda no CI e falha o build. Saída 0 se passou, 1 se houve falha, 2 se a linha de comando
tem opção desconhecida; aviso não reprova.

`--corrigir` aplica ANTES da auditoria a parte mecânica do que ela reprovaria — hoje, a
rotação mensal do diário (`diario.rotacionar`) — e imprime cada ação. Nunca faz `git add`
nem commit, e o CI não deve rodá-lo: o CI é a rede que pega quem esqueceu, não quem conserta.

Este é o segundo canal de entrega do harness, e a razão de ele existir: o plugin instala os
hooks para a sessão, mas `${CLAUDE_PLUGIN_ROOT}` é efêmero e muda a cada atualização, então
o CI não pode depender dele. Aqui o mesmo código é consumido como pacote —
`uv add --dev "harness-memoria @ git+…"` — e vira um passo de workflow.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from ..config import NOME_ARQUIVO, ErroDeConfig, carregar, raiz_projeto
from ..diario import forcar_utf8, rotacionar
from . import Contexto, relatar, rodar

USO = "uso: python -m harness_memoria.auditar [--projeto CAMINHO] [--silencioso] [--corrigir]"

#: Opção desconhecida REPROVA (rc 2) em vez de ser ignorada. O motivo é a distribuição em
#: dois canais: o plugin atualiza por commit e o pacote do consumidor fica preso no
#: `uv.lock`. Uma skill nova mandando rodar `--corrigir` contra um pacote velho, que
#: ignorava argumento desconhecido, produziria uma auditoria comum, sem correção nenhuma e
#: sem erro — exatamente o tipo de sucesso silencioso que este pacote existe para impedir.
_OPCOES = {"--projeto": True, "--silencioso": False, "--corrigir": False}


def main(argv: list[str] | None = None) -> int:
    forcar_utf8()
    argv = list(argv if argv is not None else sys.argv[1:])
    desconhecida = _opcao_desconhecida(argv)
    if desconhecida:
        print(f"x opção desconhecida: `{desconhecida}`\n{USO}")
        return 2
    silencioso = "--silencioso" in argv

    alvo = _arg(argv, "--projeto")
    # `--projeto` é escolha EXPLÍCITA de quem chamou e ganha da variável de ambiente.
    # Medido: `raiz_projeto(alvo)` põe `CLAUDE_PROJECT_DIR` na frente dos candidatos, e
    # dentro de uma sessão do Claude Code ela está SEMPRE setada — então
    # `--projeto <outro>` auditava o projeto CORRENTE. O caso caro é o silencioso: com o
    # corrente verde, a saída é "Auditoria aprovada" sobre o alvo errado, que é exatamente
    # o resultado que o comentário do `cfg is None` abaixo chama de "o pior resultado
    # possível para um cheque". Sem argumento, a descoberta continua env-primeiro, e no
    # caminho de hook (`_comum.contexto`) também: lá o candidato é o cwd do evento, não uma
    # escolha de ninguém.
    raiz = Path(alvo) if alvo else raiz_projeto()

    try:
        cfg = carregar(raiz)
    except ErroDeConfig as e:
        print(f"x config inválida: {e}")
        return 1

    if cfg is None:
        # Aqui a ausência de config REPROVA, ao contrário dos hooks. Quem roda a auditoria
        # pediu explicitamente por ela: devolver 0 silencioso deixaria um passo de CI verde
        # que não auditou nada — o pior resultado possível para um cheque.
        print(
            f"x {raiz} não tem `.claude/{NOME_ARQUIVO}` — nada para auditar. "
            f"Rode a skill `/harness-init` para criar a configuração."
        )
        return 1

    if "--corrigir" in argv:
        # Impresso mesmo com `--silencioso`: mudança em arquivo nunca é silenciosa.
        acoes = rotacionar(raiz, cfg.diario, datetime.now())
        print("Correções mecânicas:")
        for a in acoes or ["(nada a corrigir)"]:
            print(f"  ~ {a}")
        if acoes:
            print("  Só o `git mv` entra no stage (é como o git move); revise o resto e commite.")

    ctx = Contexto(raiz=raiz, cfg=cfg)
    if not silencioso:
        print(f"Auditando `{cfg.projeto}` em {raiz}")
    rodar(ctx)
    return relatar(ctx, silencioso)


def _opcao_desconhecida(argv: list[str]) -> str | None:
    i = 0
    while i < len(argv):
        atual = argv[i]
        if atual not in _OPCOES:
            return atual
        i += 2 if _OPCOES[atual] else 1
    return None


def _arg(argv: list[str], nome: str) -> str | None:
    if nome in argv:
        i = argv.index(nome)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    sys.exit(main())
