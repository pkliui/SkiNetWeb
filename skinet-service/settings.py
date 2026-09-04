"""
Service configuration, loaded from environment variables and the training
config used to train the model.

CONFIG_PATH/MODEL_PATH/MAX_UPLOAD_BYTES/INFER_SLOW_WARN_SECONDS/
MAX_CASE_REPORT_CONCURRENCY have no default in code: the single source of truth for
these is the repo's .env, consumed by backend and service containers via docker-compose*.yml.
`Settings` raises one error listing every missing/invalid field at once,
rather than failing on the first one encountered.

INPUT_SIZE/NORM_MEAN/NORM_STD/SEGMENTATION_THRESHOLD are read from the YAML
file at CONFIG_PATH (the same config used to train the model), not from env
vars and are bound to values in the config used for training, hence kept away from .env.

env vars are injected by docker-compose's `environment:` block
(itself substituted from the repo's .env) into the container.
"""

import numpy as np
import yaml
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Configuration file and the trained model
    config_path: str
    model_path: str
    # Maximum file size to upload. Shared with the Node proxy's MAX_UPLOAD_BYTES
    # (skinetweb-server/src/config.ts) so both layers enforce the same real limit
    # rather than nginx's looser outer bound.
    max_upload_bytes: int = Field(gt=0)
    # How often to log that an /infer request is still running, for user info purposes
    infer_slow_warn_seconds: float
    # Case-report concurrency ceiling. Shared with the Node proxy's
    # MAX_CASE_REPORT_CONCURRENCY (skinetweb-server/src/config.ts), which enforces
    # it as Express's concurrency limit on /case-report; the LLM httpx client's
    # connection pool in main.py is sized off this same value.
    max_case_report_concurrency: int = Field(gt=0)
    ort_intra_op_num_threads: int = 1


try:
    _settings = Settings()  # pyright: ignore[reportCallIssue]
except ValidationError as exc:
    raise RuntimeError(f"Invalid service configuration:\n{exc}") from exc

CONFIG_PATH = _settings.config_path
MODEL_PATH = _settings.model_path
MAX_UPLOAD_BYTES = _settings.max_upload_bytes
INFER_SLOW_WARN_SECONDS = _settings.infer_slow_warn_seconds
MAX_CASE_REPORT_CONCURRENCY = _settings.max_case_report_concurrency

# ONNX parallelism note
#
# Set ORT_INTRA_OP_NUM_THREADS=1, meaning use only 1 core per inference call,
# leaving all other cores available for other possible users, each of whom
# may be wishing to make an inference call.
#
# By default, ORT_INTRA_OP_NUM_THREADS is 0 (session.run() uses all the
# computer's cores). Because each _run_inference request already runs on its
# own thread via run_in_threadpool, leaving it at 0 would make every one of
# those threads use all cores too, causing cross-request contention.
#
# Hence we instead deliberately cap each session.run to a single core and let
# any possible N-way concurrency come from the OS scheduling N request threads
# (if there are N requests for inference).
#
# (ORT_INTER_OP_NUM_THREADS is not set: it only applies when execution_mode
# is ORT_PARALLEL, and this session uses the default ORT_SEQUENTIAL mode, so
# it would be a no-op.)
ORT_INTRA_OP_NUM_THREADS = _settings.ort_intra_op_num_threads

# Read other variables from config file
with open(CONFIG_PATH) as _f:
    _config = yaml.safe_load(_f)

# Transformation config used for training
_transform_config = _config["TRANSFORM_CONFIG"]
# Image size the training was done at
INPUT_SIZE = _transform_config["crop"]["size"][0]
# Actual per-channel pixel statistics of the training split,
# as computed in SkiNet/ML/transformations/compute_dataset_stats.py
NORM_MEAN = np.array(_transform_config["normalization_mean"], dtype=np.float32)
NORM_STD = np.array(_transform_config["normalization_std"], dtype=np.float32)
# Segmentation threshold as found out in SkiNet/analysis_results/E3-isic2017-threshold-sweep-and-test-evaluation.ipynb
SEGMENTATION_THRESHOLD = float(_config["TRAIN_CONFIG"]["optimal_threshold"])
