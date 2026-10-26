"""The CP-SAT model must be built the same way in every Python process (DEFECT_LOG #30).

Python randomises string hashing per process, so looping over a set of strings can change the
order constraints are added in, and with it the search: the same instance, seed and time limit
then gave different schedules in different runs. This test builds the model in fresh
interpreters with different hash seeds and requires byte-identical models (no solving needed).
"""

import os
import subprocess
import sys

CODE = """
import hashlib, os, sys
from ortools.sat.python import cp_model
from brimline_engine.scheduling.baselines import edd
from brimline_engine.scheduling.config import scheduler_config
from brimline_engine.scheduling.cpsat import solve
from brimline_engine.scheduling.generator import generate
from brimline_engine.shop_config import load_shop_config

def capture(self, model):
    print(hashlib.sha256(str(model.Proto()).encode()).hexdigest())
    sys.stdout.flush()
    os._exit(0)  # the model is all this test needs; skip the search

cp_model.CpSolver.solve = capture
cfg = scheduler_config()
inst = generate(1, 20, load_shop_config(), cfg)
solve(inst, cfg, hint=edd(inst, cfg.durations))
"""


def model_digest(hash_seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    out = subprocess.run(
        [sys.executable, "-c", CODE], capture_output=True, text=True, check=True, env=env
    )
    return out.stdout.strip()


def test_the_model_does_not_depend_on_the_hash_seed() -> None:
    digests = {model_digest(seed) for seed in ("1", "2", "3", "4")}
    assert len(digests) == 1, digests
