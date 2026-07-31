from __future__ import annotations

import fnmatch
import os
import re

_Pattern = str | re.Pattern[str]


def _compile_patterns(patterns: list[str] | None) -> list[_Pattern]:
    """Compile pattern strings into fnmatch strings or compiled regex objects."""
    if not patterns:
        return []
    compiled: list[_Pattern] = []
    for pattern in patterns:
        if pattern.startswith("re:"):
            compiled.append(re.compile(pattern[3:]))
        else:
            compiled.append(pattern)
    return compiled


def _normalizeDirPattern(pattern: _Pattern, path: str) -> _Pattern:
    """Expand *pattern* with wildcards so it matches *path* at any depth."""
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
    """Expand *pattern* with wildcards so it matches *filepath* at any depth."""
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
    """Return True if *path* should be copied given *includes* and *excludes*."""
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
