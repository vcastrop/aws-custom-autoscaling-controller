import json
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "config.json"


def load_config(config_path=None):

    path = Path(
        config_path
        or os.environ.get("CONTROLLER_CONFIG")
        or DEFAULT_CONFIG_PATH
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Controller configuration file not found: {path}"
        )

    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    validate_config(config)

    return config


def validate_config(config):
    required_sections = [
        "aws",
        "capacity",
        "thresholds",
        "timing",
        "tags",
    ]

    for section in required_sections:
        if section not in config:
            raise ValueError(
                f"Missing required configuration section: {section}"
            )

    min_capacity = config["capacity"]["min_instances"]
    max_capacity = config["capacity"]["max_instances"]

    if min_capacity < 1:
        raise ValueError("min_instances must be at least 1")

    if max_capacity < min_capacity:
        raise ValueError(
            "max_instances must be greater than or equal to min_instances"
        )

    scale_in_cpu = config["thresholds"]["cpu_scale_in"]
    scale_out_cpu = config["thresholds"]["cpu_scale_out"]

    if scale_in_cpu >= scale_out_cpu:
        raise ValueError(
            "cpu_scale_in must be lower than cpu_scale_out"
        )