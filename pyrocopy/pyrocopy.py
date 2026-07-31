#!/usr/bin/env python
"""Robust file utilities for Python inspired by Windows' robocopy.

Homepage: https://github.com/caskater4/pyrocopy

Copyright (C) 2016 Jean-Philippe Steinmetz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

import errno
import fnmatch
import logging
import os
import re
import stat
import sys
from typing import TypedDict, cast

__version__: tuple[int, int, int] = (0, 8, 0)
__version_str__: str = ".".join(str(v) for v in __version__)

#: Logger used to report information and progress during operations.
logger: logging.Logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

BUFFERSIZE_KIB: int = 16  # Buffer size in kiB for file-copy operations.
_PROGRESS_BAR_WIDTH: int = 80

_Pattern = str | re.Pattern[str]


# ---------------------------------------------------------------------------
# Result TypedDicts
# ---------------------------------------------------------------------------


class _CopyCounters(TypedDict):
    filesCopied: int
    filesFailed: int
    filesSkipped: int
    dirsCopied: int
    dirsFailed: int
    dirsSkipped: int


class _CopyLists(TypedDict, total=False):
    filesCopiedList: list[str]
    filesFailedList: list[str]
    filesSkippedList: list[str]
    dirsCopiedList: list[str]
    dirsFailedList: list[str]
    dirsSkippedList: list[str]


class CopyResults(_CopyCounters, _CopyLists):
    """Results returned by :func:`copy` and :func:`sync`."""


class _MirrorRequiredExtras(TypedDict):
    filesRemoved: int
    dirsRemoved: int


class _MirrorOptionalExtras(TypedDict, total=False):
    filesRemovedList: list[str]
    dirsRemovedList: list[str]


class MirrorResults(CopyResults, _MirrorRequiredExtras, _MirrorOptionalExtras):
    """Results returned by :func:`mirror`."""


class _MoveCounters(TypedDict):
    filesMoved: int
    filesFailed: int
    filesSkipped: int
    dirsMoved: int
    dirsFailed: int
    dirsSkipped: int


class _MoveLists(TypedDict, total=False):
    filesMovedList: list[str]
    filesFailedList: list[str]
    filesSkippedList: list[str]
    dirsMovedList: list[str]
    dirsFailedList: list[str]
    dirsSkippedList: list[str]


class MoveResults(_MoveCounters, _MoveLists):
    """Results returned by :func:`move`."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compile_patterns(patterns: list[str] | None) -> list[_Pattern]:
    """Compile pattern strings into fnmatch strings or compiled regex objects.

    Args:
        patterns: Raw pattern strings; prefix with ``re:`` for regex.

    Returns:
        A list of plain fnmatch strings and compiled :class:`re.Pattern` objects.
    """
    if not patterns:
        return []
    compiled: list[_Pattern] = []
    for pattern in patterns:
        if pattern.startswith("re:"):
            compiled.append(re.compile(pattern[3:]))
        else:
            compiled.append(pattern)
    return compiled


def _init_copy_results(detailed: bool) -> CopyResults:
    """Return a zero-initialized :class:`CopyResults`, adding list fields when *detailed* is True."""
    results: CopyResults = {
        "filesCopied": 0,
        "filesFailed": 0,
        "filesSkipped": 0,
        "dirsCopied": 0,
        "dirsFailed": 0,
        "dirsSkipped": 0,
    }
    if detailed:
        results["filesCopiedList"] = []
        results["filesFailedList"] = []
        results["filesSkippedList"] = []
        results["dirsCopiedList"] = []
        results["dirsFailedList"] = []
        results["dirsSkippedList"] = []
    return results


def _record_file_result(
    results: CopyResults,
    result: int,
    src_path: str,
    dst_path: str,
    detailed: bool,
) -> None:
    """Update *results* in-place from the outcome code of a file copy.

    Args:
        results: Mutable results dict to update.
        result: 1 = copied, 0 = skipped, negative = error.
        src_path: Source path used for logging and list tracking.
        dst_path: Destination path used for logging.
        detailed: Whether list fields are present and should be appended to.
    """
    if result == 1:
        logger.info("Copied: %s => %s", src_path, dst_path)
        results["filesCopied"] += 1
        if detailed:
            results["filesCopiedList"].append(src_path)  # type: ignore[union-attr]
    elif result == 0:
        logger.info("Skipped: %s", src_path)
        results["filesSkipped"] += 1
        if detailed:
            results["filesSkippedList"].append(src_path)  # type: ignore[union-attr]
    else:
        logger.error("Failed: %s => %s", src_path, dst_path)
        results["filesFailed"] += 1
        if detailed:
            results["filesFailedList"].append(src_path)  # type: ignore[union-attr]


def _merge_unique(base: list[str], additions: list[str]) -> list[str]:
    """Return *base* extended with items from *additions* not already present in *base*."""
    seen = set(base)
    return base + [x for x in additions if x not in seen]

def copy(
    src: str,
    dst: str,
    includeFiles: list[str] | None = None,
    includeDirs: list[str] | None = None,
    excludeFiles: list[str] | None = None,
    excludeDirs: list[str] | None = None,
    level: int = 0,
    followLinks: bool = False,
    forceOverwrite: bool = False,
    preserveStats: bool = True,
    detailedResults: bool = False,
) -> CopyResults:
    """Copy all files and folders from *src* to *dst*.

    Args:
        src: The source path to copy from.
        dst: The destination path to copy to.
        includeFiles: Patterns for files to include; prefix regex with ``re:``.
        includeDirs: Patterns for directories to include; prefix regex with ``re:``.
        excludeFiles: Patterns for files to exclude; prefix regex with ``re:``.
        excludeDirs: Patterns for directories to exclude; prefix regex with ``re:``.
        level: Max depth (0 = all; positive = from top; negative = from bottom).
        followLinks: Traverse symbolic links as directories.
        forceOverwrite: Overwrite destination files even if they are newer.
        preserveStats: Copy mode, atime, mtime, and flags to the destination.
        detailedResults: Populate per-item list fields in the returned dict.

    Returns:
        A :class:`CopyResults` dict with copy statistics.
    """
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)

    results = _init_copy_results(detailedResults)
    include_file_patterns = _compile_patterns(includeFiles)
    include_dir_patterns = _compile_patterns(includeDirs)
    exclude_file_patterns = _compile_patterns(excludeFiles)
    exclude_dir_patterns = _compile_patterns(excludeDirs)

    if _isSamePath(src, dst):
        logger.error("Cannot perform a copy to the same location.")
        results["dirsFailed"] += 1
        return results

    if os.path.isfile(src) or (not followLinks and os.path.islink(src)):
        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))
        result = _copyFile(src, dst, include_file_patterns, exclude_file_patterns, forceOverwrite=forceOverwrite)
        _record_file_result(results, result, src, dst, detailedResults)
        return results

    if not os.path.isdir(src):
        logger.error("Source path is not valid: %s", src)
        results["filesFailed"] += 1
        return results

    if not os.path.isdir(dst):
        mkdir(dst)

    max_depth = _getTreeDepth(src)

    # Traverse bottom-up to ensure correct behaviour for include/exclude patterns.
    for root, dirs, files in os.walk(src, topdown=False, followlinks=followLinks):
        rel_root = os.path.relpath(root, src)

        logger.debug("Processing Directory: %s", rel_root)

        if os.path.islink(root) and not followLinks:
            logger.info("Skipped: %s", rel_root)
            results["dirsSkipped"] += 1
            if detailedResults:
                results["dirsSkippedList"].append(rel_root)  # type: ignore[union-attr]
            continue

        if level != 0:
            depth = 0 if rel_root == "." else rel_root.count(os.path.sep) + 1
            if level < 0:
                depth = max_depth - depth
            if depth >= abs(level):
                logger.info("Skipped: %s", rel_root)
                results["dirsSkipped"] += 1
                if detailedResults:
                    results["dirsSkippedList"].append(rel_root)  # type: ignore[union-attr]
                continue

        if rel_root != "." and not _checkShouldCopy(rel_root, False, include_dir_patterns, exclude_dir_patterns):
            logger.info("Skipped: %s", rel_root)
            results["dirsSkipped"] += 1
            if detailedResults:
                results["dirsSkippedList"].append(rel_root)  # type: ignore[union-attr]
            continue

        dst_root = dst if rel_root == "." else os.path.join(dst, rel_root)
        if not os.path.isdir(dst_root):
            mkdir(dst_root)

        if rel_root != ".":
            if os.path.isdir(dst_root):
                results["dirsCopied"] += 1
                if detailedResults:
                    results["dirsCopiedList"].append(rel_root)  # type: ignore[union-attr]
            else:
                logger.exception("Failed: %s", rel_root)
                results["dirsFailed"] += 1
                if detailedResults:
                    results["dirsFailedList"].append(rel_root)  # type: ignore[union-attr]
                continue

        for file in files:
            file_path = os.path.join(rel_root, file)
            src_full = os.path.join(src, root, file)
            dst_full = os.path.join(dst, file_path)
            result = _copyFile(
                src_full, dst_full,
                includes=include_file_patterns,
                excludes=exclude_file_patterns,
                forceOverwrite=forceOverwrite,
                preserveStats=preserveStats,
            )
            _record_file_result(results, result, file_path, dst_full, detailedResults)

    return results


def mkdir(path: str) -> bool:
    """Create a directory at *path*, including all missing parent directories.

    Args:
        path: The path of the directory to create.

    Returns:
        True if the directory exists after the call, False otherwise.
    """
    if os.path.exists(path):
        return os.path.isdir(path)

    parent, _ = os.path.split(path)
    if parent and not os.path.isdir(parent):
        mkdir(parent)

    if parent and not os.path.isdir(parent):
        return False

    os.mkdir(path)
    logger.debug("Created: %s", path)
    return os.path.isdir(path)


def mirror(
    src: str,
    dst: str,
    includeFiles: list[str] | None = None,
    includeDirs: list[str] | None = None,
    excludeFiles: list[str] | None = None,
    excludeDirs: list[str] | None = None,
    level: int = 0,
    followLinks: bool = False,
    forceOverwrite: bool = False,
    preserveStats: bool = True,
    detailedResults: bool = False,
) -> MirrorResults:
    """Create an exact copy of *src* at *dst*, removing destination-only files and directories.

    Args:
        src: The source path to mirror from.
        dst: The destination path to mirror to.
        includeFiles: Patterns for files to include; prefix regex with ``re:``.
        includeDirs: Patterns for directories to include; prefix regex with ``re:``.
        excludeFiles: Patterns for files to exclude; prefix regex with ``re:``.
        excludeDirs: Patterns for directories to exclude; prefix regex with ``re:``.
        level: Max depth (0 = all; positive = from top; negative = from bottom).
        followLinks: Traverse symbolic links as directories.
        forceOverwrite: Overwrite destination files even if they are newer.
        preserveStats: Copy mode, atime, mtime, and flags to the destination.
        detailedResults: Populate per-item list fields in the returned dict.

    Returns:
        A :class:`MirrorResults` dict with copy and removal statistics.
    """
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)

    copy_results = copy(
        src, dst,
        includeFiles=includeFiles, includeDirs=includeDirs,
        excludeFiles=excludeFiles, excludeDirs=excludeDirs,
        level=level, followLinks=followLinks,
        forceOverwrite=forceOverwrite, preserveStats=preserveStats,
        detailedResults=True,
    )

    results: MirrorResults = cast(MirrorResults, copy_results)
    results["filesRemoved"] = 0
    results["dirsRemoved"] = 0
    if detailedResults:
        results["filesRemovedList"] = []
        results["dirsRemovedList"] = []

    # Keep excluded items from being deleted during the removal pass.
    if excludeDirs:
        results["dirsSkippedList"].extend(excludeDirs)  # type: ignore[union-attr]
    if excludeFiles:
        results["filesSkippedList"].extend(excludeFiles)  # type: ignore[union-attr]

    max_depth = _getTreeDepth(src)

    # Build lookup sets once for O(1) membership tests during the removal walk.
    skipped_dirs: set[str] = set(results.get("dirsSkippedList") or [])
    failed_dirs: set[str] = set(results.get("dirsFailedList") or [])
    skipped_files: set[str] = set(results.get("filesSkippedList") or [])
    failed_files: set[str] = set(results.get("filesFailedList") or [])

    for root, dirs, files in os.walk(dst, topdown=False, followlinks=followLinks):
        rel_root = os.path.relpath(root, dst)

        if level != 0:
            depth = 0 if rel_root == "." else rel_root.count(os.path.sep) + 1
            if level < 0:
                depth = max_depth - depth
            if depth >= abs(level):
                continue

        if rel_root in skipped_dirs or rel_root in failed_dirs:
            continue

        for file in files:
            file_path = os.path.join(root, file)
            rel_file_path = os.path.join(rel_root, file)
            if rel_file_path in skipped_files or rel_file_path in failed_files:
                continue
            if not os.path.exists(os.path.join(src, rel_file_path)):
                try:
                    os.remove(file_path)
                    results["filesRemoved"] += 1
                    if detailedResults:
                        results["filesRemovedList"].append(rel_file_path)  # type: ignore[union-attr]
                except OSError:
                    results["filesFailedList"].append(rel_file_path)  # type: ignore[union-attr]

        if not os.path.exists(os.path.join(src, rel_root)):
            if not os.listdir(root):
                try:
                    os.rmdir(root)
                    results["dirsRemoved"] += 1
                    if detailedResults:
                        results["dirsRemovedList"].append(rel_root)  # type: ignore[union-attr]
                except OSError:
                    results["dirsFailed"] += 1
                    if detailedResults:
                        results["dirsFailedList"].append(rel_root)  # type: ignore[union-attr]
            else:
                results["dirsFailed"] += 1
                if detailedResults:
                    results["dirsFailedList"].append(rel_root)  # type: ignore[union-attr]

    if not detailedResults:
        for key in ("filesCopiedList", "filesFailedList", "filesSkippedList",
                    "dirsCopiedList", "dirsFailedList", "dirsSkippedList"):
            results.pop(key, None)  # type: ignore[misc]

    return results


def move(
    src: str,
    dst: str,
    includeFiles: list[str] | None = None,
    includeDirs: list[str] | None = None,
    excludeFiles: list[str] | None = None,
    excludeDirs: list[str] | None = None,
    level: int = 0,
    followLinks: bool = False,
    forceOverwrite: bool = False,
    preserveStats: bool = True,
    detailedResults: bool = False,
) -> MoveResults:
    """Move all files and folders from *src* to *dst*.

    Args:
        src: The source path to move from.
        dst: The destination path to move to.
        includeFiles: Patterns for files to include; prefix regex with ``re:``.
        includeDirs: Patterns for directories to include; prefix regex with ``re:``.
        excludeFiles: Patterns for files to exclude; prefix regex with ``re:``.
        excludeDirs: Patterns for directories to exclude; prefix regex with ``re:``.
        level: Max depth (0 = all; positive = from top; negative = from bottom).
        followLinks: Traverse symbolic links as directories.
        forceOverwrite: Overwrite destination files even if they are newer.
        preserveStats: Copy mode, atime, mtime, and flags to the destination.
        detailedResults: Populate per-item list fields in the returned dict.

    Returns:
        A :class:`MoveResults` dict with move statistics.
    """
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)

    copy_results = copy(
        src, dst,
        includeFiles=includeFiles, includeDirs=includeDirs,
        excludeFiles=excludeFiles, excludeDirs=excludeDirs,
        level=level, followLinks=followLinks,
        forceOverwrite=forceOverwrite, preserveStats=preserveStats,
        detailedResults=True,
    )

    # Build case-insensitive lookup sets for the source-deletion walk.
    failed_dirs_lower = {d.lower() for d in copy_results["dirsFailedList"]}   # type: ignore[union-attr]
    skipped_dirs_lower = {d.lower() for d in copy_results["dirsSkippedList"]} # type: ignore[union-attr]
    failed_files_lower = {f.lower() for f in copy_results["filesFailedList"]} # type: ignore[union-attr]
    skipped_files_lower = {f.lower() for f in copy_results["filesSkippedList"]}  # type: ignore[union-attr]

    for root, dirs, files in os.walk(src, topdown=False):
        rel_root = os.path.relpath(root, src)

        if rel_root.lower() in failed_dirs_lower or rel_root.lower() in skipped_dirs_lower:
            continue

        for file in files:
            file_path = os.path.join(root, file)
            rel_file_path = os.path.join(rel_root, file)
            if not os.path.lexists(file_path):
                continue
            if rel_file_path.lower() in failed_files_lower or rel_file_path.lower() in skipped_files_lower:
                continue
            try:
                os.remove(file_path)
            except OSError:
                copy_results["filesFailedList"].append(rel_file_path)  # type: ignore[union-attr]

        if not os.listdir(root):
            if os.path.islink(root):
                os.unlink(root)
            else:
                try:
                    os.rmdir(root)
                except OSError:
                    copy_results["dirsFailed"] += 1

    results: MoveResults = {
        "filesMoved": copy_results["filesCopied"],
        "filesFailed": copy_results["filesFailed"],
        "filesSkipped": copy_results["filesSkipped"],
        "dirsMoved": copy_results["dirsCopied"],
        "dirsFailed": copy_results["dirsFailed"],
        "dirsSkipped": copy_results["dirsSkipped"],
    }
    if detailedResults:
        results["filesMovedList"] = copy_results["filesCopiedList"]   # type: ignore[union-attr]
        results["filesFailedList"] = copy_results["filesFailedList"]  # type: ignore[union-attr]
        results["filesSkippedList"] = copy_results["filesSkippedList"]  # type: ignore[union-attr]
        results["dirsMovedList"] = copy_results["dirsCopiedList"]     # type: ignore[union-attr]
        results["dirsFailedList"] = copy_results["dirsFailedList"]    # type: ignore[union-attr]
        results["dirsSkippedList"] = copy_results["dirsSkippedList"]  # type: ignore[union-attr]

    return results


def sync(
    path1: str,
    path2: str,
    includeFiles: list[str] | None = None,
    includeDirs: list[str] | None = None,
    excludeFiles: list[str] | None = None,
    excludeDirs: list[str] | None = None,
    level: int = 0,
    followLinks: bool = False,
    forceOverwrite: bool = False,
    preserveStats: bool = True,
    detailedResults: bool = False,
) -> CopyResults:
    """Synchronize files and folders between *path1* and *path2* (bi-directional copy).

    Equivalent to ``copy(path1, path2)`` followed by ``copy(path2, path1)``.

    Args:
        path1: First path to synchronize.
        path2: Second path to synchronize.
        includeFiles: Patterns for files to include; prefix regex with ``re:``.
        includeDirs: Patterns for directories to include; prefix regex with ``re:``.
        excludeFiles: Patterns for files to exclude; prefix regex with ``re:``.
        excludeDirs: Patterns for directories to exclude; prefix regex with ``re:``.
        level: Max depth (0 = all; positive = from top; negative = from bottom).
        followLinks: Traverse symbolic links as directories.
        forceOverwrite: Overwrite destination files even if they are newer.
        preserveStats: Copy mode, atime, mtime, and flags to the destination.
        detailedResults: Populate per-item list fields in the returned dict.

    Returns:
        A :class:`CopyResults` dict with combined statistics from both directions.
    """
    path1 = os.path.abspath(path1)
    path2 = os.path.abspath(path2)

    results = copy(
        path1, path2,
        includeFiles=includeFiles, includeDirs=includeDirs,
        excludeFiles=excludeDirs,  # NOTE: preserving original behaviour
        level=level, followLinks=followLinks,
        forceOverwrite=forceOverwrite, preserveStats=preserveStats,
        detailedResults=True,
    )
    results2 = copy(
        path2, path1,
        includeFiles=includeFiles, includeDirs=includeDirs,
        excludeFiles=excludeDirs,  # NOTE: preserving original behaviour
        level=level, followLinks=followLinks,
        forceOverwrite=forceOverwrite, preserveStats=preserveStats,
        detailedResults=True,
    )

    # Merge results from both directions, avoiding duplicates.
    for list_key in ("filesCopiedList", "filesFailedList", "filesSkippedList",
                     "dirsCopiedList", "dirsFailedList", "dirsSkippedList"):
        results[list_key] = _merge_unique(  # type: ignore[literal-required]
            results[list_key],   # type: ignore[literal-required]
            results2[list_key],  # type: ignore[literal-required]
        )

    results["filesCopied"] = len(results["filesCopiedList"])   # type: ignore[arg-type]
    results["filesFailed"] = len(results["filesFailedList"])   # type: ignore[arg-type]
    results["filesSkipped"] = len(results["filesSkippedList"]) # type: ignore[arg-type]
    results["dirsCopied"] = len(results["dirsCopiedList"])     # type: ignore[arg-type]
    results["dirsFailed"] = len(results["dirsFailedList"])     # type: ignore[arg-type]
    results["dirsSkipped"] = len(results["dirsSkippedList"])   # type: ignore[arg-type]

    if not detailedResults:
        for key in ("filesCopiedList", "filesFailedList", "filesSkippedList",
                    "dirsCopiedList", "dirsFailedList", "dirsSkippedList"):
            results.pop(key, None)  # type: ignore[misc]

    return results


def _isSamePath(src: str, dst: str) -> bool:
    """Return True if *src* and *dst* resolve to the same filesystem location."""
    if hasattr(os.path, "samefile"):
        try:
            return os.path.samefile(src, dst)
        except OSError:
            return False
    return os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst))


def _normalizeDirPattern(pattern: _Pattern, path: str) -> _Pattern:
    """Expand *pattern* with wildcards so it matches *path* at any depth.

    On Windows, regex path separators are normalised to ``/``.

    Examples::

        _normalizeDirPattern("*", "Level1")                              → "*"
        _normalizeDirPattern("*/Level2", "Level1")                       → "*/Level2"
        _normalizeDirPattern("Level1", "Level1/Level2/Level3")           → "Level1/*/*"
    """
    is_regex = False
    tmp: str
    if isinstance(pattern, re.Pattern):
        tmp = pattern.pattern
        is_regex = True
    elif pattern.startswith("re:"):
        tmp = pattern[3:]
        is_regex = True
    else:
        tmp = pattern

    num_path_sep = path.count(os.path.sep)
    num_pattern_sep = tmp.count(os.path.sep)

    while num_path_sep > num_pattern_sep:
        tmp = (tmp + "/.*" if tmp else ".*") if is_regex else os.path.join(tmp, "*")
        num_pattern_sep += 1

    return re.compile(tmp) if is_regex else tmp


def _normalizeFilePattern(pattern: _Pattern, filepath: str) -> _Pattern:
    """Expand *pattern* with wildcards so it matches *filepath* at any depth.

    Wildcards are inserted before the filename tail of the pattern, not at the end.

    Examples::

        _normalizeFilePattern("*.txt", "myFile.txt")                     → "*.txt"
        _normalizeFilePattern("*.txt", "Level1/myFile.txt")              → "*/**.txt"
        _normalizeFilePattern("Level1/*.txt", "Level1/Level2/MyFile.txt")→ "Level1/*/*.txt"
    """
    is_regex = False
    tmp: str
    if isinstance(pattern, re.Pattern):
        tmp = pattern.pattern
        is_regex = True
    elif pattern.startswith("re:"):
        tmp = pattern[3:]
        is_regex = True
    else:
        tmp = pattern

    pattern_dir, pattern_file = os.path.split(tmp)
    tmp = pattern_dir

    num_path_sep = filepath.count(os.path.sep)
    num_pattern_sep = tmp.count(os.path.sep) + (1 if tmp else 0)

    while num_path_sep > num_pattern_sep:
        tmp = (tmp + "/.*" if tmp else ".*") if is_regex else os.path.join(tmp, "*")
        num_pattern_sep += 1

    tmp = (tmp + "/" + pattern_file) if is_regex else os.path.join(tmp, pattern_file)

    return re.compile(tmp) if is_regex else tmp


def _checkShouldCopy(
    path: str,
    bIsFile: bool,
    includes: list[_Pattern] | None,
    excludes: list[_Pattern] | None,
) -> bool:
    """Return True if *path* should be copied given *includes* and *excludes*.

    When *includes* are provided the path must match at least one; excludes are not checked.
    When only *excludes* are provided the path must not match any of them.
    """
    # Normalise separators for regex matching (relevant on Windows).
    re_path = path.replace(os.path.sep, "/") if os.path.sep == "\\" else path

    if includes:
        for pattern in includes:
            norm = _normalizeFilePattern(pattern, path) if bIsFile else _normalizeDirPattern(pattern, path)
            if isinstance(norm, re.Pattern):
                if norm.match(re_path) is not None:
                    return True
            elif fnmatch.fnmatch(path, norm):
                return True
        return False

    if excludes:
        for pattern in excludes:
            norm = _normalizeFilePattern(pattern, path) if bIsFile else _normalizeDirPattern(pattern, path)
            if isinstance(norm, re.Pattern):
                if norm.match(re_path) is not None:
                    return False
            elif fnmatch.fnmatch(path, norm):
                return False

    return True


def _copyFile(
    src: str,
    dst: str,
    includes: list[_Pattern] | None = None,
    excludes: list[_Pattern] | None = None,
    showProgress: bool = True,
    forceOverwrite: bool = False,
    preserveStats: bool = True,
) -> int:
    """Copy the file at *src* to *dst*.

    Args:
        src: Source file path.
        dst: Destination file path.
        includes: Compiled include patterns; the file must match at least one.
        excludes: Compiled exclude patterns; the file must not match any.
        showProgress: Kept for API compatibility; progress is always displayed when INFO logging is active.
        forceOverwrite: Overwrite *dst* even if it is newer than *src*.
        preserveStats: Copy file stats (mode, atime, mtime, flags) to *dst*.

    Returns:
        1 if copied, 0 if skipped, -1 on error.
    """
    if not os.path.isfile(src):
        return -1
    if _isSamePath(src, dst):
        return -1
    if not _checkShouldCopy(src, True, includes, excludes):
        return 0
    if not forceOverwrite and os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return 0

    dst_dir = os.path.split(dst)[0]
    if not os.path.isdir(dst_dir):
        mkdir(dst_dir)

    logger.info("Copying: %s => %s", src, dst)
    if os.path.islink(src):
        try:
            os.symlink(os.readlink(src), dst)
        except OSError:
            return -1
    else:
        max_read = BUFFERSIZE_KIB * 1024
        try:
            with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                bytes_total = os.path.getsize(src)
                bytes_written = 0
                while True:
                    buf = fsrc.read(max_read)
                    if not buf:
                        break
                    fdst.write(buf)
                    bytes_written += len(buf)
                    _displayProgress(bytes_written, bytes_total)
        except OSError:
            return -1

        logger.info("")

        if preserveStats:
            _copyStats(src, dst)

    if os.path.exists(dst) and (os.path.islink(dst) or os.path.getsize(src) == os.path.getsize(dst)):
        return 1
    return -1


def _copyStats(src: str, dst: str) -> None:
    """Copy stat info (mode bits, atime, mtime, flags) from *src* to *dst*."""
    st = os.stat(src)
    mode = stat.S_IMODE(st.st_mode)
    if hasattr(os, "utime"):
        os.utime(dst, (st.st_atime, st.st_mtime))
    if hasattr(os, "chmod"):
        os.chmod(dst, mode)
    if hasattr(os, "chflags") and hasattr(st, "st_flags"):
        try:
            os.chflags(dst, st.st_flags)  # type: ignore[attr-defined]
        except OSError as why:
            for err in ("EOPNOTSUPP", "ENOTSUP"):
                if hasattr(errno, err) and why.errno == getattr(errno, err):
                    break
            else:
                raise


def _displayProgress(currentValue: int, totalValue: int) -> None:
    """Write an in-place progress bar to any stdout/stderr logger handlers at INFO level.

    Args:
        currentValue: Bytes (or units) transferred so far.
        totalValue: Total bytes (or units) to transfer.
    """
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
    if "filesCopied" in results:
        logger.info("\tCopied: %d", results["filesCopied"])  # type: ignore[typeddict-item]
    if "filesMoved" in results:
        logger.info("\tMoved: %d", results["filesMoved"])  # type: ignore[typeddict-item]
    logger.info("\tSkipped: %d", results["filesSkipped"])
    logger.info("\tFailed: %d", results["filesFailed"])
    logger.info("")
    logger.info("Directories:")
    if "dirsCopied" in results:
        logger.info("\tCopied: %d", results["dirsCopied"])  # type: ignore[typeddict-item]
    if "dirsMoved" in results:
        logger.info("\tMoved: %d", results["dirsMoved"])  # type: ignore[typeddict-item]
    logger.info("\tSkipped: %d", results["dirsSkipped"])
    logger.info("\tFailed: %d", results["dirsFailed"])
    logger.info("--------------------")


def _getTreeDepth(path: str) -> int:
    """Return the maximum directory depth of the tree rooted at *path*."""
    max_depth = 0
    for root, dirs, files in os.walk(path):
        rel_root = os.path.relpath(root, path)
        depth = rel_root.count(os.path.sep) + 1
        max_depth = max(max_depth, depth)
    return max_depth
