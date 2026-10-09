"""Leitura de comando de shell compartilhada pela guarda e pelos fatos do transcript.

Somente biblioteca padrão: a guarda roda no caminho quente de toda escrita, e os fatos do
transcript no orçamento de 1,5 s do `SessionEnd`.
"""

from __future__ import annotations

import re

ABRE_HEREDOC = r"<<-?\s*(?P<q>['\"]?)(?P<marca>[A-Za-z_]\w*)(?P=q)"


def sem_corpo_de_heredoc(comando: str) -> str:
    """O comando sem os CORPOS de heredoc — eles são dado no stdin, não comando.

    Usada pela guarda (`hooks/guardar.py`) e pelo reconhecimento de escrita no diário pelo
    shell (`alvos_de_escrita`): uma cópia em cada lugar divergiria na primeira correção.

    Mesma razão do `_LITERAL`, e o caso que criou isto é o mesmo defeito uma camada
    adiante: `_avaliar_comando` faz `" ".join(comando.split())`, o que achata o heredoc
    inteiro numa linha só, então uma mensagem de commit que CITA a flag proibida vira
    comando aos olhos da regex. Aconteceu de verdade ao commitar a correção anterior deste
    arquivo: `git commit -F - <<'MSG'` com o texto que explica o bloqueio foi BLOQUEADO, e
    a mensagem sugeria corrigir a causa de um hook que não estava falhando. Falso positivo
    em bloqueio empurra para `guardas.universais: false`, que desliga as três guardas.

    Descarta só o CORPO. A linha de abertura fica, e é o que faz `cat > .env <<'X'`
    continuar bloqueado por `_escrita_de_env_por_shell` — o alvo do redirecionamento está
    antes do `<<`, não dentro dele.

    Heredoc sem terminador consome até o fim de propósito: nesse caso o shell também
    trataria as linhas seguintes como corpo, então elas nunca seriam executadas como
    comando. Descartar é o que corresponde ao que o shell faz.

    O que isto NÃO faz: inspecionar conteúdo. Um projeto que precise proibir texto dentro
    de heredoc está pedindo cheque de conteúdo, não de comando, e o lugar disso é
    `guardas.caminhos` sobre o arquivo escrito.
    """
    linhas = comando.splitlines()
    saida: list[str] = []
    i = 0
    while i < len(linhas):
        linha = linhas[i]
        saida.append(linha)
        m = re.search(ABRE_HEREDOC, linha)
        i += 1
        if not m:
            continue
        marca = m.group("marca")
        while i < len(linhas) and linhas[i].strip() != marca:
            i += 1
        i += 1  # descarta também a linha do terminador
    return "\n".join(saida)


#: Alvo de escrita num comando: o que vem depois de `>`, `>>` ou `>|`, e os argumentos de
#: `tee`. `2>&1` e `>&2` não contam (o alvo é um descritor), e o que está dentro de um corpo
#: de heredoc também não — ver `sem_corpo_de_heredoc`.
_REDIRECIONAMENTO = re.compile(r">>?\|?\s*(['\"]?)([^\s'\"<>|;&]+)\1")
_TEE = re.compile(r"\btee\b((?:\s+-{1,2}[A-Za-z-]+)*)((?:\s+['\"]?[^\s'\"<>|;&]+['\"]?)+)")


def alvos_de_escrita(comando: str) -> list[str]:
    """Os caminhos que o comando ESCREVE por redirecionamento ou `tee`, na ordem.

    Existe para o `SessionEnd` reconhecer a entrada do diário escrita pelo shell. Medido em
    2026-10-09 neste repositório: as entradas narradas da sessão saíram de
    `cat >> docs/diario/2026-10.md <<'EOF'`, o hook só olhava `Write`/`Edit` e anexou o piso
    por cima delas. Só o ALVO conta: `cat docs/diario/x.md > copia.md` lê o diário.
    """
    texto = sem_corpo_de_heredoc(comando)
    saida: list[str] = []
    for m in _REDIRECIONAMENTO.finditer(texto):
        saida.append(m.group(2))
    for m in _TEE.finditer(texto):
        saida += [a.strip("'\"") for a in m.group(2).split()]
    return list(dict.fromkeys(saida))
