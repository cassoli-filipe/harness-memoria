"""CLI da auditoria.

    python -m harness_memoria.auditar [--projeto CAMINHO] [--silencioso]

Roda no CI e falha o build. Saída 0 se passou, 1 se houve falha; aviso não reprova.

Este é o segundo canal de entrega do harness, e a razão de ele existir: o plugin instala os
hooks para a sessão, mas `${CLAUDE_PLUGIN_ROOT}` é efêmero e muda a cada atualização, então
o CI não pode depender dele. Aqui o mesmo código é consumido como pacote —
`uv add --dev "harness-memoria @ git+…"` — e vira um passo de workflow.
"""

from __future__ import annotations

import sys

from ..config import NOME_ARQUIVO, ErroDeConfig, carregar, raiz_projeto
from ..diario import forcar_utf8
from . import Contexto, relatar, rodar


def main(argv: list[str] | None = None) -> int:
    forcar_utf8()
    argv = list(argv if argv is not None else sys.argv[1:])
    silencioso = "--silencioso" in argv

    alvo = _arg(argv, "--projeto")
    raiz = raiz_projeto(alvo) if alvo else raiz_projeto()

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

    ctx = Contexto(raiz=raiz, cfg=cfg)
    if not silencioso:
        print(f"Auditando `{cfg.projeto}` em {raiz}")
    rodar(ctx)
    return relatar(ctx, silencioso)


def _arg(argv: list[str], nome: str) -> str | None:
    if nome in argv:
        i = argv.index(nome)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    sys.exit(main())
