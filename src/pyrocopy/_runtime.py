from __future__ import annotations

import logging

#: Logger used to report information and progress during operations.
logger: logging.Logger = logging.getLogger("pyrocopy")
logger.addHandler(logging.NullHandler())

BUFFERSIZE_KIB: int = 16  # Buffer size in kiB for file-copy operations.
_PROGRESS_BAR_WIDTH: int = 80
