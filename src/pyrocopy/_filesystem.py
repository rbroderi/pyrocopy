from __future__ import annotations

import errno
import os
import stat

from ._display import _displayProgress
from ._patterns import _Pattern, _checkShouldCopy
from ._runtime import BUFFERSIZE_KIB, logger


def mkdir(path: str) -> bool:
    """Create a directory at *path*, including all missing parent directories."""
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


def _isSamePath(src: str, dst: str) -> bool:
    """Return True if *src* and *dst* resolve to the same filesystem location."""
    if hasattr(os.path, "samefile"):
        try:
            return os.path.samefile(src, dst)
        except OSError:
            return False
    return os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst))


def _copyFile(
    src: str,
    dst: str,
    includes: list[_Pattern] | None = None,
    excludes: list[_Pattern] | None = None,
    showProgress: bool = True,
    forceOverwrite: bool = False,
    preserveStats: bool = True,
) -> int:
    """Copy the file at *src* to *dst*."""
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
                    if showProgress:
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


def _getTreeDepth(path: str) -> int:
    """Return the maximum directory depth of the tree rooted at *path*."""
    max_depth = 0
    for root, dirs, files in os.walk(path):
        rel_root = os.path.relpath(root, path)
        depth = rel_root.count(os.path.sep) + 1
        max_depth = max(max_depth, depth)
    return max_depth
