import json
import logging
import sys
import time
from typing import Any


def event(message: str, **fields: Any) -> None:
    logging.getLogger('tryon').info(json.dumps({'time': time.time(), 'event': message, **fields}, ensure_ascii=False))


def configure() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stdout)
