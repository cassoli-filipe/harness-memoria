#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../_comum/base.sh"
# O projeto tem um comando de fechamento próprio: a skill do plugin tem de ceder a vez.
python3 - <<'PY'
import json
from pathlib import Path
p = Path(".claude/harness.json")
d = json.loads(p.read_text(encoding="utf-8"))
d["diario"] = {"skill_de_encerramento": "/handoff"}
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
PY
commitar
