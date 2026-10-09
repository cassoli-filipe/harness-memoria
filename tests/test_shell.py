"""O que um comando de shell ESCREVE — para o `SessionEnd` reconhecer o diário escrito assim."""

from __future__ import annotations

from harness_memoria.shell import alvos_de_escrita


def test_caminho_entre_aspas_no_redirecionamento_e_no_tee():
    cmd = "echo x >> \"docs/diario/2026-10.md\" && make | tee -a 'log.md'"
    assert alvos_de_escrita(cmd) == ["docs/diario/2026-10.md", "log.md"]


def test_alvos_na_ordem_sem_repetir():
    cmd = "echo a > um.md && echo b >> dois.md 2>/dev/null && cat um.md | tee tres.md um.md"
    assert alvos_de_escrita(cmd) == ["um.md", "dois.md", "/dev/null", "tres.md"]


def test_descritor_nao_e_alvo():
    assert alvos_de_escrita("pytest 2>&1 >&2") == []


def test_corpo_de_heredoc_nao_e_comando():
    cmd = "cat > notas.txt <<'EOF'\necho x >> docs/diario/2026-10.md\nEOF"
    assert alvos_de_escrita(cmd) == ["notas.txt"]


def test_ler_nao_e_escrever():
    assert alvos_de_escrita("grep -n '^## ' docs/diario/2026-10.md") == []
