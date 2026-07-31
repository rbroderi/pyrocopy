from __future__ import annotations

from dataclasses import dataclass

from ._runtime import logger


@dataclass(slots=True)
class _CopyState:
    """Mutable accumulator used internally by :func:`copy`."""

    filesCopied: int = 0
    filesFailed: int = 0
    filesSkipped: int = 0
    dirsCopied: int = 0
    dirsFailed: int = 0
    dirsSkipped: int = 0
    filesCopiedList: list[str] | None = None
    filesFailedList: list[str] | None = None
    filesSkippedList: list[str] | None = None
    dirsCopiedList: list[str] | None = None
    dirsFailedList: list[str] | None = None
    dirsSkippedList: list[str] | None = None


@dataclass(frozen=True, slots=True)
class CopyResults:
    """Results returned by :func:`copy` and :func:`sync`."""

    filesCopied: int
    filesFailed: int
    filesSkipped: int
    dirsCopied: int
    dirsFailed: int
    dirsSkipped: int
    filesCopiedList: list[str] | None = None
    filesFailedList: list[str] | None = None
    filesSkippedList: list[str] | None = None
    dirsCopiedList: list[str] | None = None
    dirsFailedList: list[str] | None = None
    dirsSkippedList: list[str] | None = None


@dataclass(slots=True)
class _MirrorState:
    """Mutable accumulator used internally by :func:`mirror`."""

    filesCopied: int = 0
    filesFailed: int = 0
    filesSkipped: int = 0
    dirsCopied: int = 0
    dirsFailed: int = 0
    dirsSkipped: int = 0
    filesRemoved: int = 0
    dirsRemoved: int = 0
    filesCopiedList: list[str] | None = None
    filesFailedList: list[str] | None = None
    filesSkippedList: list[str] | None = None
    dirsCopiedList: list[str] | None = None
    dirsFailedList: list[str] | None = None
    dirsSkippedList: list[str] | None = None
    filesRemovedList: list[str] | None = None
    dirsRemovedList: list[str] | None = None


@dataclass(frozen=True, slots=True)
class MirrorResults:
    """Results returned by :func:`mirror`."""

    filesCopied: int
    filesFailed: int
    filesSkipped: int
    dirsCopied: int
    dirsFailed: int
    dirsSkipped: int
    filesRemoved: int
    dirsRemoved: int
    filesCopiedList: list[str] | None = None
    filesFailedList: list[str] | None = None
    filesSkippedList: list[str] | None = None
    dirsCopiedList: list[str] | None = None
    dirsFailedList: list[str] | None = None
    dirsSkippedList: list[str] | None = None
    filesRemovedList: list[str] | None = None
    dirsRemovedList: list[str] | None = None


@dataclass(frozen=True, slots=True)
class MoveResults:
    """Results returned by :func:`move`."""

    filesMoved: int
    filesFailed: int
    filesSkipped: int
    dirsMoved: int
    dirsFailed: int
    dirsSkipped: int
    filesMovedList: list[str] | None = None
    filesFailedList: list[str] | None = None
    filesSkippedList: list[str] | None = None
    dirsMovedList: list[str] | None = None
    dirsFailedList: list[str] | None = None
    dirsSkippedList: list[str] | None = None


def _init_copy_state(detailed: bool) -> _CopyState:
    """Return a zero-initialized :class:`_CopyState`, populating list fields when *detailed* is True."""
    state = _CopyState()
    if detailed:
        state.filesCopiedList = []
        state.filesFailedList = []
        state.filesSkippedList = []
        state.dirsCopiedList = []
        state.dirsFailedList = []
        state.dirsSkippedList = []
    return state


def _record_file_result(
    state: _CopyState,
    result: int,
    src_path: str,
    dst_path: str,
    detailed: bool,
) -> None:
    """Update *state* in-place from the outcome code of a file copy."""
    if result == 1:
        logger.info("Copied: %s => %s", src_path, dst_path)
        state.filesCopied += 1
        if detailed:
            state.filesCopiedList.append(src_path)  # type: ignore[union-attr]
    elif result == 0:
        logger.info("Skipped: %s", src_path)
        state.filesSkipped += 1
        if detailed:
            state.filesSkippedList.append(src_path)  # type: ignore[union-attr]
    else:
        logger.error("Failed: %s => %s", src_path, dst_path)
        state.filesFailed += 1
        if detailed:
            state.filesFailedList.append(src_path)  # type: ignore[union-attr]


def _merge_unique(base: list[str], additions: list[str]) -> list[str]:
    """Return *base* extended with items from *additions* not already present in *base*."""
    seen = set(base)
    return base + [x for x in additions if x not in seen]
