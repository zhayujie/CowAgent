import time

import pip
from pip._internal import main as pipmain

from common.log import _reset_logger, logger


def install(package):
    pipmain(["install", package])


def install_requirements(file):
    pipmain(["install", "-r", file, "--upgrade"])
    _reset_logger(logger)


def check_dulwich():
    needwait = False
    for i in range(2):
        if needwait:
            time.sleep(3)
            needwait = False
        try:
            import dulwich

            return
        except ImportError:
            try:
                install("dulwich")
            except Exception:
                needwait = True
    try:
        import dulwich
    except ImportError:
        raise ImportError("Unable to import dulwich")
