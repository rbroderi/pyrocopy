from __future__ import annotations

import logging
import sys

from ._results import CopyResults, MirrorResults, MoveResults
from ._runtime import _PROGRESS_BAR_WIDTH, logger


def _displayProgress(currentValue: int, totalValue: int) -> None:
    """Write an in-place progress bar to any stdout/stderr logger handlers at INFO level."""
    if logger.getEffectiveLevel() > logging.INFO:
        return

    streams = [
        h.stream
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler) and h.stream in (sys.stderr, sys.stdout)
    ]
    if not streams:
        return

    filled = int(_PROGRESS_BAR_WIDTH * currentValue / totalValue)
    if filled >= _PROGRESS_BAR_WIDTH:
        bar = "=" * _PROGRESS_BAR_WIDTH
    else:
        bar = "=" * filled + ">" + " " * (_PROGRESS_BAR_WIDTH - filled - 1)
    line = f"{currentValue} / {totalValue} [{bar}]\r"

    for stream in streams:
        stream.write(line)
        stream.flush()


def _displayCopyResults(results: CopyResults | MirrorResults | MoveResults) -> None:
    """Log a summary table of the copy/move/mirror *results* at INFO level."""
    if logger.getEffectiveLevel() > logging.ERROR:
        return

    logger.info("--------------------")
    logger.info("Files:")
    if hasattr(results, "filesCopied"):
        logger.info("\tCopied: %d", results.filesCopied)  # type: ignore[union-attr]
    if hasattr(results, "filesMoved"):
        logger.info("\tMoved: %d", results.filesMoved)  # type: ignore[union-attr]
    logger.info("\tSkipped: %d", results.filesSkipped)
    logger.info("\tFailed: %d", results.filesFailed)
    logger.info("")
    logger.info("Directories:")
    if hasattr(results, "dirsCopied"):
        logger.info("\tCopied: %d", results.dirsCopied)  # type: ignore[union-attr]
    if hasattr(results, "dirsMoved"):
        logger.info("\tMoved: %d", results.dirsMoved)  # type: ignore[union-attr]
    logger.info("\tSkipped: %d", results.dirsSkipped)
    logger.info("\tFailed: %d", results.dirsFailed)
    logger.info("--------------------")
