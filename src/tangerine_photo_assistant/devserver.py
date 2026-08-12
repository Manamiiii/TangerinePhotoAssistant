from __future__ import annotations

import os
from pathlib import Path

from .webapp import create_app

config_path = Path(os.environ.get("TANGERINE_CONFIG", "config.mac-test.toml"))
app = create_app(config_path.resolve(), static_directory=None)
