import os
from pathlib import Path

# settings.py reads CONFIG_PATH at import time (module-level `yaml.safe_load`), and
# main.py imports from settings, so this must be set before any test module does
# `import main`. Point it at the real training config shipped in the repo so
# INPUT_SIZE/NORM_MEAN/NORM_STD/SEGMENTATION_THRESHOLD match production rather than being faked
# in tests.
os.environ.setdefault(
    "CONFIG_PATH",
    str(Path(__file__).resolve().parents[2] / "models" / "main_config.yaml"),
)

# settings.py also requires MAX_UPLOAD_BYTES, MODEL_PATH, INFER_SLOW_WARN_SECONDS, and
# MAX_CASE_REPORT_CONCURRENCY at import time now (no literal fallback, to keep them
# from drifting out of sync with docker-compose*.yml's copies — see settings.py).
# Tests aren't run through docker-compose, so read the same repo .env it uses
# instead of hardcoding these a third time.
_REQUIRED_FROM_ENV_FILE = (
    "MAX_UPLOAD_BYTES",
    "MODEL_PATH",
    "INFER_SLOW_WARN_SECONDS",
    "MAX_CASE_REPORT_CONCURRENCY",
)
if any(_name not in os.environ for _name in _REQUIRED_FROM_ENV_FILE):
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        for _name in _REQUIRED_FROM_ENV_FILE:
            if _line.startswith(f"{_name}=") and _name not in os.environ:
                os.environ[_name] = _line.split("=", 1)[1].strip()
