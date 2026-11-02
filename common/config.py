import yaml
from pathlib import Path


def load_config(env: str, config_path: str = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).parents[1] / 'config.yml'

    with open(config_path, 'r', encoding='utf-8') as f:
        full = yaml.safe_load(f)

    cfg = {
        'batch_size': full.get('batch_size', 5000),
        'concurrency': full.get('concurrency', 50),
        'env': env,
    }
    env_cfg = full.get(env)
    if env_cfg is None:
        raise ValueError(f"환경 '{env}' 이 config.yml에 없습니다. (dev/stg/law/prod)")
    cfg.update(env_cfg)
    return cfg
