import logging.config
import os
import yaml


def setup_logging(default_path='logging.yaml',
                  default_level=logging.INFO,
                  env_key='PYLOG_CFG'):
    """Setup logging configuration

    """
    path = default_path
    value = os.getenv(env_key, None)
    if value:
        path = value
    if os.path.exists(path):
        with open(path, 'rt') as f:
            config = yaml.safe_load(f.read())
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)


def open_yaml(config_file):
    """
    Open as yaml file and returns it loaded
    """
    if os.path.isfile(config_file):
        with open(config_file) as file:
            config = yaml.load(file)
    else:
        raise FileNotFoundError
    return config


if __name__ == "__main__":
    pass
