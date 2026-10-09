# Base dos scaffolds das evals — usar com `source`, nunca executar sozinho.
#
# Monta o consumidor sintético no workspace vazio da run, copia o pacote do harness para a
# raiz dele (o scaffold e a sessão não recebem `PYTHONPATH` — `env` das evals só aceita
# `EVAL_*` —, e `python -m harness_memoria.auditar` acha o pacote pelo cwd), e abre o git.
# O caso acrescenta o que é dele e termina com `commitar`.
#
# Medido no spike de 2026-10-09: `$0` do scaffold é o caminho absoluto do script dentro do
# repositório, `python`/`python3`/`uv` estão no PATH, e os hooks do plugin abrem o gate com
# o `.claude/harness.json` que este script escreve — o sandbox não carrega `.claude/` como
# configuração da plataforma, mas os hooks leem o arquivo do disco.
set -euo pipefail
RAIZ_DO_PLUGIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MES=$(date +%Y-%m)

bash "$RAIZ_DO_PLUGIN/evals/_comum/consumidor.sh" .
cp -r "$RAIZ_DO_PLUGIN/src/harness_memoria" ./harness_memoria
printf '__pycache__/\n.eval-diario.md\n' > .gitignore
# Caminho estável para os graders: o nome do arquivo do diário depende do mês da run.
ln -s "docs/diario/$MES.md" .eval-diario.md
git init -q

commitar() {
  git add -A && git -c user.name=eval -c user.email=eval@local commit -qm "base da eval"
}
