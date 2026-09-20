from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def main() -> None:
    sys.path.insert(0, str(ROOT))

    from modules.api.app import create_app
    from modules.api.config import AppConfig

    app = create_app(
        AppConfig(
            base_dir=ROOT,
            bootstrap_token="openapi-generation",
        )
    )
    output = ROOT / "build" / "openapi.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["npm", "run", "api:generate"], cwd=FRONTEND, check=True)


if __name__ == "__main__":
    main()
