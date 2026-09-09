"""Três ressalvas do `guardar.py`, todas no princípio 9 — e as três em BLOQUEIO, o pior
lugar: bloqueio surpresa em escrita legítima empurra para `guardas.universais: false`, que
desliga as TRÊS guardas de uma vez. O autoteste (`_autoteste`, exercitado pelo CI) cobre um
positivo e um negativo por regra; este arquivo cobre o que o booleano do autoteste não
alcança — o TEXTO do motivo — e fixa em teste as medições dos dois revisores que abriram as
ressalvas.

(a) `.env.example` era a única exceção reconhecida em DOIS mecanismos que a repetiam por
    extenso; `.env.template`/`.env.sample`/`.env.dist` são a mesma classe (arquivo SEM
    segredo que o agente DEVE poder editar) e ficavam de fora — medido: `cp .env.example
    .env.template` passava a ser NEGADO.
(b) `_sob_prefixo` trocou substring por fronteira de caminho (ganho, fica: fecha travessia
    de diretório) mas mudou em silêncio a semântica de `permitido_em` apontando para um
    ARQUIVO — o próprio arquivo listado passa a bloquear. Sem cheque no auditor
    (`auditar_guardas`, fora deste arquivo — ver `precisa_de_outros`), este teste fixa o
    comportamento ATUAL para ele não regredir de novo em silêncio.
(c) Assimetria de mensagem: `cat .env > backup.txt` é liberado (correto, o alvo do
    redirecionamento é `backup.txt`) mas `cp .env backup.txt` bloqueava com `MOTIVO_ENV`
    ("edite `.env.example`"), remédio que não tem relação com quem está copiando.
"""

from __future__ import annotations

from harness_memoria.config import ConfigGuardas
from harness_memoria.hooks.guardar import avaliar

_G = ConfigGuardas()


# --------------------------------------------------------------------------- #
# (a) exceção de `.env` sem segredo consolidada — `.env.template` também livre
# --------------------------------------------------------------------------- #


def test_cp_env_example_para_env_template_e_liberado():
    """Regressão medida pelo revisor: a exceção só conhecia `.env.example` por extenso em
    dois lugares, e `.env.template` — grafia comum de arquivo sem segredo — era negado."""
    assert avaliar("Bash", {"command": "cp .env.example .env.template"}, _G) is None


def test_write_em_env_sample_e_liberado():
    assert avaliar("Write", {"file_path": "C:/proj/.env.sample"}, _G) is None


def test_write_em_env_dist_e_liberado():
    assert avaliar("Write", {"file_path": "C:/proj/.env.dist"}, _G) is None


def test_write_em_grafia_fora_da_lista_continua_bloqueado():
    """Controle: a lista de exceção não pode virar porta para qualquer `.env.*` — só as
    quatro grafias de arquivo SEM segredo saem do bloqueio."""
    assert avaliar("Write", {"file_path": "C:/proj/.env.staging"}, _G) is not None


# --------------------------------------------------------------------------- #
# (b) `permitido_em` apontando para um ARQUIVO — comportamento fixado, não corrigido aqui
# --------------------------------------------------------------------------- #


def test_permitido_em_apontando_para_arquivo_bloqueia_o_proprio_arquivo():
    """Comportamento ATUAL de `_sob_prefixo`, fixado em teste para não regredir em
    silêncio de novo: `permitido_em` que aponta para um ARQUIVO (não diretório) não libera
    esse arquivo, porque a fronteira exige algo depois do prefixo no caminho.

    A correção completa — o auditor reprovando `permitido_em` com extensão de arquivo na
    config — está fora deste arquivo (`src/harness_memoria/auditar/__init__.py`) e vai
    registrada em `precisa_de_outros`. Este teste, e o docstring de `_sob_prefixo`, são o
    aviso que existe até esse cheque existir.
    """
    g = ConfigGuardas(
        caminhos=(
            {
                "padrao": "*.xlsx",
                "permitido_em": ["tests/fixtures/exemplo.xlsx"],
                "motivo": "planilha com dado de aluno não entra no repositório",
            },
        )
    )
    assert avaliar("Write", {"file_path": "tests/fixtures/exemplo.xlsx"}, g) is not None


# --------------------------------------------------------------------------- #
# (c) `cp`/`mv` de `.env` para outro caminho: motivo próprio, não o de edição
# --------------------------------------------------------------------------- #


def test_cat_env_redirecionado_continua_liberado():
    """Controle: o lado que já estava certo (alvo do redirecionamento é o que vem depois
    do último `>`) não pode regredir com o conserto do lado `cp`/`mv`."""
    assert avaliar("Bash", {"command": "cat .env > backup.txt"}, _G) is None


def test_cp_env_para_backup_bloqueia_com_motivo_proprio_de_copia():
    """`cp .env backup.txt` faz o MESMO dano que `cat .env > backup.txt` (tira o segredo
    do caminho ignorado) e por isso continua bloqueado — mas quem roda isso não está
    editando nada, então `MOTIVO_ENV` ("edite `.env.example`") é remédio non-sequitur."""
    motivo = avaliar("Bash", {"command": "cp .env backup.txt"}, _G)
    assert motivo is not None
    assert ".env.example" not in motivo, motivo
    assert "cp" in motivo and "mv" in motivo, motivo


def test_mv_env_para_outro_lugar_bloqueia_com_motivo_de_copia():
    motivo = avaliar("Bash", {"command": "mv .env /tmp/backup"}, _G)
    assert motivo is not None
    assert "sair de um caminho ignorado" in motivo, motivo


def test_cp_para_dentro_de_env_continua_com_motivo_de_edicao():
    """Quando o `.env` é o DESTINO (`cp backup.txt .env`), o motivo continua sendo o de
    edição — é escrita real de segredo no arquivo rastreado, não cópia para fora dele."""
    motivo = avaliar("Bash", {"command": "cp backup.txt .env"}, _G)
    assert motivo is not None
    assert ".env.example" in motivo, motivo
