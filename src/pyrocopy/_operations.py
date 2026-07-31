from __future__ import annotations

import os
from dataclasses import asdict

from ._filesystem import _copyFile, _getTreeDepth, _isSamePath, mkdir
from ._patterns import _checkShouldCopy, _compile_patterns
from ._results import (
    CopyResults,
    MirrorResults,
    MoveResults,
    _init_copy_state,
    _merge_unique,
    _MirrorState,
    _record_file_result,
)
from ._runtime import logger


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
    """Copy all files and folders from *src* to *dst*."""
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)

    state = _init_copy_state(detailedResults)
    include_file_patterns = _compile_patterns(includeFiles)
    include_dir_patterns = _compile_patterns(includeDirs)
    exclude_file_patterns = _compile_patterns(excludeFiles)
    exclude_dir_patterns = _compile_patterns(excludeDirs)

    if _isSamePath(src, dst):
        logger.error("Cannot perform a copy to the same location.")
        state.dirsFailed += 1
        return CopyResults(**asdict(state))

    if os.path.isfile(src) or (not followLinks and os.path.islink(src)):
        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))
        result = _copyFile(src, dst, include_file_patterns, exclude_file_patterns, forceOverwrite=forceOverwrite)
        _record_file_result(state, result, src, dst, detailedResults)
        return CopyResults(**asdict(state))

    if not os.path.isdir(src):
        logger.error("Source path is not valid: %s", src)
        state.filesFailed += 1
        return CopyResults(**asdict(state))

    if not os.path.isdir(dst):
        mkdir(dst)

    max_depth = _getTreeDepth(src)

    for root, dirs, files in os.walk(src, topdown=False, followlinks=followLinks):
        rel_root = os.path.relpath(root, src)

        logger.debug("Processing Directory: %s", rel_root)

        if os.path.islink(root) and not followLinks:
            logger.info("Skipped: %s", rel_root)
            state.dirsSkipped += 1
            if detailedResults:
                state.dirsSkippedList.append(rel_root)  # type: ignore[union-attr]
            continue

        if level != 0:
            depth = 0 if rel_root == "." else rel_root.count(os.path.sep) + 1
            if level < 0:
                depth = max_depth - depth
            if depth >= abs(level):
                logger.info("Skipped: %s", rel_root)
                state.dirsSkipped += 1
                if detailedResults:
                    state.dirsSkippedList.append(rel_root)  # type: ignore[union-attr]
                continue

        if rel_root != "." and not _checkShouldCopy(rel_root, False, include_dir_patterns, exclude_dir_patterns):
            logger.info("Skipped: %s", rel_root)
            state.dirsSkipped += 1
            if detailedResults:
                state.dirsSkippedList.append(rel_root)  # type: ignore[union-attr]
            continue

        dst_root = dst if rel_root == "." else os.path.join(dst, rel_root)
        if not os.path.isdir(dst_root):
            mkdir(dst_root)

        if rel_root != ".":
            if os.path.isdir(dst_root):
                state.dirsCopied += 1
                if detailedResults:
                    state.dirsCopiedList.append(rel_root)  # type: ignore[union-attr]
            else:
                logger.exception("Failed: %s", rel_root)
                state.dirsFailed += 1
                if detailedResults:
                    state.dirsFailedList.append(rel_root)  # type: ignore[union-attr]
                continue

        for file in files:
            file_path = os.path.join(rel_root, file)
            src_full = os.path.join(src, root, file)
            dst_full = os.path.join(dst, file_path)
            result = _copyFile(
                src_full,
                dst_full,
                includes=include_file_patterns,
                excludes=exclude_file_patterns,
                forceOverwrite=forceOverwrite,
                preserveStats=preserveStats,
            )
            _record_file_result(state, result, file_path, dst_full, detailedResults)

    return CopyResults(**asdict(state))


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
    """Create an exact copy of *src* at *dst*, removing destination-only files and directories."""
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)

    copy_results = copy(
        src,
        dst,
        includeFiles=includeFiles,
        includeDirs=includeDirs,
        excludeFiles=excludeFiles,
        excludeDirs=excludeDirs,
        level=level,
        followLinks=followLinks,
        forceOverwrite=forceOverwrite,
        preserveStats=preserveStats,
        detailedResults=True,
    )

    state = _MirrorState(
        filesCopied=copy_results.filesCopied,
        filesFailed=copy_results.filesFailed,
        filesSkipped=copy_results.filesSkipped,
        dirsCopied=copy_results.dirsCopied,
        dirsFailed=copy_results.dirsFailed,
        dirsSkipped=copy_results.dirsSkipped,
        filesRemoved=0,
        dirsRemoved=0,
        filesCopiedList=list(copy_results.filesCopiedList or []),
        filesFailedList=list(copy_results.filesFailedList or []),
        filesSkippedList=list(copy_results.filesSkippedList or []),
        dirsCopiedList=list(copy_results.dirsCopiedList or []),
        dirsFailedList=list(copy_results.dirsFailedList or []),
        dirsSkippedList=list(copy_results.dirsSkippedList or []),
        filesRemovedList=[] if detailedResults else None,
        dirsRemovedList=[] if detailedResults else None,
    )

    max_depth = _getTreeDepth(src)

    failed_dirs: set[str] = set(state.dirsFailedList or [])
    failed_files: set[str] = set(state.filesFailedList or [])
    include_file_patterns = _compile_patterns(includeFiles)
    include_dir_patterns = _compile_patterns(includeDirs)
    exclude_file_patterns = _compile_patterns(excludeFiles)
    exclude_dir_patterns = _compile_patterns(excludeDirs)

    for root, dirs, files in os.walk(dst, topdown=False, followlinks=followLinks):
        rel_root = os.path.relpath(root, dst)
        normalized_rel_root = "" if rel_root == "." else rel_root

        if level != 0:
            depth = 0 if rel_root == "." else rel_root.count(os.path.sep) + 1
            if level < 0:
                depth = max_depth - depth
            if depth >= abs(level):
                continue

        if rel_root in failed_dirs:
            continue

        for file in files:
            file_path = os.path.join(root, file)
            rel_file_path = file if not normalized_rel_root else os.path.join(normalized_rel_root, file)
            src_file_path = os.path.join(src, rel_file_path)
            if rel_file_path in failed_files:
                continue
            if os.path.exists(src_file_path):
                continue
            if not _checkShouldCopy(
                rel_file_path,
                True,
                include_file_patterns,
                exclude_file_patterns,
            ):
                continue
            if not os.path.lexists(file_path):
                continue
            try:
                os.remove(file_path)
                state.filesRemoved += 1
                if detailedResults:
                    state.filesRemovedList.append(rel_file_path)  # type: ignore[union-attr]
            except OSError:
                state.filesFailedList.append(rel_file_path)  # type: ignore[union-attr]

        src_dir_path = src if not normalized_rel_root else os.path.join(src, normalized_rel_root)
        dir_selected = rel_root == "." or _checkShouldCopy(
            normalized_rel_root,
            False,
            include_dir_patterns,
            exclude_dir_patterns,
        )
        if not os.path.exists(src_dir_path) or not dir_selected:
            if not os.listdir(root):
                try:
                    os.rmdir(root)
                    state.dirsRemoved += 1
                    if detailedResults:
                        state.dirsRemovedList.append(rel_root)  # type: ignore[union-attr]
                except OSError:
                    state.dirsFailed += 1
                    if detailedResults:
                        state.dirsFailedList.append(rel_root)  # type: ignore[union-attr]
            else:
                state.dirsFailed += 1
                if detailedResults:
                    state.dirsFailedList.append(rel_root)  # type: ignore[union-attr]

    return MirrorResults(
        filesCopied=state.filesCopied,
        filesFailed=state.filesFailed,
        filesSkipped=state.filesSkipped,
        dirsCopied=state.dirsCopied,
        dirsFailed=state.dirsFailed,
        dirsSkipped=state.dirsSkipped,
        filesRemoved=state.filesRemoved,
        dirsRemoved=state.dirsRemoved,
        filesCopiedList=state.filesCopiedList if detailedResults else None,
        filesFailedList=state.filesFailedList if detailedResults else None,
        filesSkippedList=state.filesSkippedList if detailedResults else None,
        dirsCopiedList=state.dirsCopiedList if detailedResults else None,
        dirsFailedList=state.dirsFailedList if detailedResults else None,
        dirsSkippedList=state.dirsSkippedList if detailedResults else None,
        filesRemovedList=state.filesRemovedList if detailedResults else None,
        dirsRemovedList=state.dirsRemovedList if detailedResults else None,
    )


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
    """Move all files and folders from *src* to *dst*."""
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)

    copy_results = copy(
        src,
        dst,
        includeFiles=includeFiles,
        includeDirs=includeDirs,
        excludeFiles=excludeFiles,
        excludeDirs=excludeDirs,
        level=level,
        followLinks=followLinks,
        forceOverwrite=forceOverwrite,
        preserveStats=preserveStats,
        detailedResults=True,
    )

    failed_dirs_lower = {d.lower() for d in (copy_results.dirsFailedList or [])}
    skipped_dirs_lower = {d.lower() for d in (copy_results.dirsSkippedList or [])}
    failed_files_lower = {f.lower() for f in (copy_results.filesFailedList or [])}
    skipped_files_lower = {f.lower() for f in (copy_results.filesSkippedList or [])}

    extra_failed_files: list[str] = []
    extra_dirs_failed: int = 0

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
                extra_failed_files.append(rel_file_path)

        if not os.listdir(root):
            if os.path.islink(root):
                os.unlink(root)
            else:
                try:
                    os.rmdir(root)
                except OSError:
                    extra_dirs_failed += 1

    all_failed_files = list(copy_results.filesFailedList or []) + extra_failed_files

    return MoveResults(
        filesMoved=copy_results.filesCopied,
        filesFailed=copy_results.filesFailed + len(extra_failed_files),
        filesSkipped=copy_results.filesSkipped,
        dirsMoved=copy_results.dirsCopied,
        dirsFailed=copy_results.dirsFailed + extra_dirs_failed,
        dirsSkipped=copy_results.dirsSkipped,
        filesMovedList=copy_results.filesCopiedList if detailedResults else None,
        filesFailedList=all_failed_files if detailedResults else None,
        filesSkippedList=copy_results.filesSkippedList if detailedResults else None,
        dirsMovedList=copy_results.dirsCopiedList if detailedResults else None,
        dirsFailedList=copy_results.dirsFailedList if detailedResults else None,
        dirsSkippedList=copy_results.dirsSkippedList if detailedResults else None,
    )


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
    """Synchronize files and folders between *path1* and *path2* (bi-directional copy)."""
    path1 = os.path.abspath(path1)
    path2 = os.path.abspath(path2)

    results1 = copy(
        path1,
        path2,
        includeFiles=includeFiles,
        includeDirs=includeDirs,
        excludeFiles=excludeFiles,
        excludeDirs=excludeDirs,
        level=level,
        followLinks=followLinks,
        forceOverwrite=forceOverwrite,
        preserveStats=preserveStats,
        detailedResults=True,
    )
    results2 = copy(
        path2,
        path1,
        includeFiles=includeFiles,
        includeDirs=includeDirs,
        excludeFiles=excludeFiles,
        excludeDirs=excludeDirs,
        level=level,
        followLinks=followLinks,
        forceOverwrite=forceOverwrite,
        preserveStats=preserveStats,
        detailedResults=True,
    )

    merged_files_copied = _merge_unique(list(results1.filesCopiedList or []), list(results2.filesCopiedList or []))
    merged_files_failed = _merge_unique(list(results1.filesFailedList or []), list(results2.filesFailedList or []))
    merged_files_skipped = _merge_unique(list(results1.filesSkippedList or []), list(results2.filesSkippedList or []))
    merged_dirs_copied = _merge_unique(list(results1.dirsCopiedList or []), list(results2.dirsCopiedList or []))
    merged_dirs_failed = _merge_unique(list(results1.dirsFailedList or []), list(results2.dirsFailedList or []))
    merged_dirs_skipped = _merge_unique(list(results1.dirsSkippedList or []), list(results2.dirsSkippedList or []))

    return CopyResults(
        filesCopied=len(merged_files_copied),
        filesFailed=len(merged_files_failed),
        filesSkipped=len(merged_files_skipped),
        dirsCopied=len(merged_dirs_copied),
        dirsFailed=len(merged_dirs_failed),
        dirsSkipped=len(merged_dirs_skipped),
        filesCopiedList=merged_files_copied if detailedResults else None,
        filesFailedList=merged_files_failed if detailedResults else None,
        filesSkippedList=merged_files_skipped if detailedResults else None,
        dirsCopiedList=merged_dirs_copied if detailedResults else None,
        dirsFailedList=merged_dirs_failed if detailedResults else None,
        dirsSkippedList=merged_dirs_skipped if detailedResults else None,
    )
