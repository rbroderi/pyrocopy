#!/usr/bin/env python
"""Robust file utilities for Python inspired by Windows' robocopy.

Homepage: https://github.com/caskater4/pyrocopy
"""
from __future__ import annotations

from ._display import _displayCopyResults, _displayProgress
from ._filesystem import _copyFile, _copyStats, _getTreeDepth, _isSamePath, mkdir
from ._operations import copy, mirror, move, sync
from ._patterns import _Pattern, _checkShouldCopy, _compile_patterns, _normalizeDirPattern, _normalizeFilePattern
from ._results import CopyResults, MirrorResults, MoveResults, _CopyState, _MirrorState
from ._runtime import BUFFERSIZE_KIB, logger

__version__: tuple[int, int, int] = (0, 8, 0)
__version_str__: str = ".".join(str(v) for v in __version__)

__all__ = [
    "BUFFERSIZE_KIB",
    "logger",
    "__version__",
    "__version_str__",
    "copy",
    "mirror",
    "move",
    "sync",
    "mkdir",
    "CopyResults",
    "MirrorResults",
    "MoveResults",
    "_CopyState",
    "_MirrorState",
    "_Pattern",
    "_compile_patterns",
    "_checkShouldCopy",
    "_normalizeDirPattern",
    "_normalizeFilePattern",
    "_copyFile",
    "_copyStats",
    "_displayProgress",
    "_displayCopyResults",
    "_isSamePath",
    "_getTreeDepth",
]
