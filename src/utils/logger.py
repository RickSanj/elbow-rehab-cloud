"""_summary_

Returns:
    _type_: _description_
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stdout
)

logger = logging.getLogger(__name__)


def get_logger():
    return logger
