## 2024-05-18 - [Optimizing import time with lazy version string resolution]
**Learning:** `importlib.metadata.version` takes around 60ms to resolve and dominates the load time of `bambu_cli.constants`. Every command execution paid this penalty since `constants` is imported almost everywhere.
**Action:** Use Python's module-level `__getattr__` in `constants.py` to lazily evaluate `VERSION` so it's only computed when actually needed (like when `--version` is called).
