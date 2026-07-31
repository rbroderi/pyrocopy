"""Tests for pyrocopy — migrated to pytest."""

import logging
import os
import random
import re
import shutil

import pytest

from pyrocopy import pyrocopy

logger = logging.getLogger(__name__)
MAX_FILE_SIZE = 16 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def gen_random_contents(path: str, max_file_size: int) -> None:
    """Write random binary-safe contents to the file at *path*."""
    with open(path, "w") as fh:
        total_chars = random.randint(0, max_file_size)
        cur_char = 0
        while cur_char < total_chars:
            fh.write(chr(random.randint(1, 255)))
            cur_char += 1
            if max_file_size >= 100 and cur_char % (max_file_size // 100) == 0:
                pyrocopy._displayProgress(cur_char, total_chars)
        fh.flush()


def gen_random_file(path: str, max_file_size: int) -> str:
    """Create a new file with random contents inside *path*; return the filename."""
    filename = "f" + str(random.randint(0, 2**31 - 1))
    filepath = os.path.join(path, filename)
    gen_random_contents(filepath, max_file_size)
    return filename


def gen_random_tree(path: str, maxlevels: int, total_files: int, max_file_size: int) -> str:
    """Generate a random directory tree rooted under *path*; return the root path."""
    root = os.path.join(path, "d" + str(random.randint(0, max(total_files * total_files, 1))))
    os.mkdir(root)

    num_files = 0
    while num_files < total_files:
        depth = random.randint(0, maxlevels)
        cur_dir = root
        for _ in range(depth):
            tmp = os.path.join(cur_dir, "d" + str(random.randint(0, max(total_files * total_files, 1))))
            if not os.path.exists(tmp):
                os.mkdir(tmp)
            cur_dir = tmp

        max_to_create = total_files - num_files
        num_to_create = random.randint(0, max_to_create)
        for _ in range(num_to_create):
            gen_random_file(cur_dir, max_file_size)
        num_files += num_to_create

    return root


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_src_tree(tmp_path: pytest.TempPathFactory) -> dict[str, str]:
    """
    Minimal source tree used exclusively by depth-level copy tests.

    Structure (15 files total, no dummydir or extra named files):
        <src>/    5 random f* files
        <lvl1>/   3 random f* files
        <lvl2>/   7 random f* files
    """
    src = gen_random_tree(str(tmp_path), 0, 5, MAX_FILE_SIZE)
    lvl1 = gen_random_tree(src, 0, 3, MAX_FILE_SIZE)
    lvl2 = gen_random_tree(lvl1, 0, 7, MAX_FILE_SIZE)
    return {"src": src, "lvl1": lvl1, "lvl2": lvl2}


@pytest.fixture
def src_tree(tmp_path: pytest.TempPathFactory) -> dict[str, str]:
    """
    Complex source tree used by copy / move tests.

    Structure (24 files total):
        <src>/           5 random f* files + file1
        <src>/dummydir/  dummy1, dummy2
        <src>/dummydir/moredir/  more0 … more4
        <lvl1>/          3 random f* files + test
        <lvl2>/          7 random f* files
    """
    src = gen_random_tree(str(tmp_path), 0, 5, MAX_FILE_SIZE)
    lvl1 = gen_random_tree(src, 0, 3, MAX_FILE_SIZE)
    lvl2 = gen_random_tree(lvl1, 0, 7, MAX_FILE_SIZE)
    gen_random_contents(os.path.join(src, "file1"), MAX_FILE_SIZE)
    gen_random_contents(os.path.join(lvl1, "test"), MAX_FILE_SIZE)
    os.mkdir(os.path.join(src, "dummydir"))
    gen_random_contents(os.path.join(src, "dummydir", "dummy1"), MAX_FILE_SIZE)
    gen_random_contents(os.path.join(src, "dummydir", "dummy2"), MAX_FILE_SIZE)
    os.mkdir(os.path.join(src, "dummydir", "moredir"))
    for i in range(5):
        gen_random_contents(os.path.join(src, "dummydir", "moredir", f"more{i}"), MAX_FILE_SIZE)
    return {"src": src, "lvl1": lvl1, "lvl2": lvl2}


@pytest.fixture
def mirror_data(tmp_path: pytest.TempPathFactory) -> dict:
    """
    Fixed pathA / pathB directory structures used by mirror and sync tests.

        pathA/            fileA1
        pathA/subA1/      fileSubA1, fileSubA1-2
        pathA/subA2/      fileSubA2
        pathA/subA2/subSubA1/  fileSubA21

        pathB/            fileB1
        pathB/subB1/      fileSubB1
        pathB/subB1/subSubB1/  fileSubB11
    """
    path_a = str(tmp_path / "pathA")
    sub_a1 = os.path.join(path_a, "subA1")
    sub_a2 = os.path.join(path_a, "subA2")
    sub_a21 = os.path.join(sub_a2, "subSubA1")
    pyrocopy.mkdir(sub_a1)
    pyrocopy.mkdir(sub_a21)
    gen_random_contents(os.path.join(path_a, "fileA1"), MAX_FILE_SIZE)
    gen_random_contents(os.path.join(sub_a1, "fileSubA1"), MAX_FILE_SIZE)
    gen_random_contents(os.path.join(sub_a1, "fileSubA1-2"), MAX_FILE_SIZE)
    gen_random_contents(os.path.join(sub_a2, "fileSubA2"), MAX_FILE_SIZE)
    gen_random_contents(os.path.join(sub_a21, "fileSubA21"), MAX_FILE_SIZE)

    path_b = str(tmp_path / "pathB")
    sub_b1 = os.path.join(path_b, "subB1")
    sub_b11 = os.path.join(sub_b1, "subSubB1")
    pyrocopy.mkdir(sub_b11)
    gen_random_contents(os.path.join(path_b, "fileB1"), MAX_FILE_SIZE)
    gen_random_contents(os.path.join(sub_b1, "fileSubB1"), MAX_FILE_SIZE)
    gen_random_contents(os.path.join(sub_b11, "fileSubB11"), MAX_FILE_SIZE)

    return {
        "tmp_path": tmp_path,
        "pathA": path_a, "pathB": path_b,
        "subPathA1": sub_a1, "subPathA2": sub_a2, "subPathA21": sub_a21,
        "subPathB1": sub_b1, "subPathB11": sub_b11,
    }


# ---------------------------------------------------------------------------
# Pattern normalisation tests
# ---------------------------------------------------------------------------

def test_normalize_dir_pattern() -> None:
    assert pyrocopy._normalizeDirPattern("*", "Level1") == "*"
    assert (
        pyrocopy._normalizeDirPattern(os.path.join("*", "Level2"), "Level1")
        == os.path.join("*", "Level2")
    )
    assert (
        pyrocopy._normalizeDirPattern("Level1", os.path.join("Level1", "Level2", "Level3"))
        == os.path.join("Level1", "*", "*")
    )


def test_normalize_file_pattern() -> None:
    assert pyrocopy._normalizeFilePattern("*.txt", "myFile.txt") == "*.txt"
    assert (
        pyrocopy._normalizeFilePattern("*.txt", os.path.join("Level1", "myFile.txt"))
        == os.path.join("*", "*.txt")
    )
    assert (
        pyrocopy._normalizeFilePattern(os.path.join("*", "*.txt"), "myFile.txt")
        == os.path.join("*", "*.txt")
    )
    assert (
        pyrocopy._normalizeFilePattern(
            os.path.join("Level1", "*.txt"),
            os.path.join("Level1", "Level2", "MyFile.txt"),
        )
        == os.path.join("Level1", "*", "*.txt")
    )


# ---------------------------------------------------------------------------
# _checkShouldCopy — directory matching
# ---------------------------------------------------------------------------

def test_check_should_copy_dirs() -> None:
    assert pyrocopy._checkShouldCopy("Level1", False, ["Level1"], None)
    assert pyrocopy._checkShouldCopy("Level1", False, ["re:Level1"], None)
    assert not pyrocopy._checkShouldCopy("Level1", False, None, ["Level1"])
    assert not pyrocopy._checkShouldCopy("Level1", False, None, ["re:Level1"])
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2"), False, [os.path.join("*", "Level2")], None
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2"), False,
        ["re:" + os.path.join(".*", "Level2")], None,
    )
    # multi-level — pattern without wildcards must NOT match deeper paths
    assert not pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False, ["Level2"], None
    )
    assert not pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False, ["re:Level2"], None
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False,
        [os.path.join("*", "Level2")], None,
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False,
        ["re:" + os.path.join(".*", "Level2")], None,
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False, None, None
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False, ["Level*"], None
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False, ["re:Level.*"], None
    )
    assert not pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False, None, ["Level*"]
    )
    assert not pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False, None, ["re:Level.*"]
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "Level2", "Level3"), False, ["re:Level[0-9]+"], None
    )


# ---------------------------------------------------------------------------
# _checkShouldCopy — file matching
# ---------------------------------------------------------------------------

def test_check_should_copy_files() -> None:
    assert pyrocopy._checkShouldCopy("myFile.txt", True, None, None)
    assert pyrocopy._checkShouldCopy("myFile.txt", True, ["*.txt"], None)
    assert not pyrocopy._checkShouldCopy("myFile.log", True, ["*.txt"], None)
    assert not pyrocopy._checkShouldCopy("myFile.txt2", True, ["*.txt"], None)
    assert not pyrocopy._checkShouldCopy("myFile.txt", True, None, ["*.txt"])
    assert pyrocopy._checkShouldCopy("myFile.txt", True, None, ["*.txt2"])
    assert pyrocopy._checkShouldCopy("myFile.log", True, None, ["*.txt"])
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "myFile.txt"), True, ["*.txt"], None
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "SubPath1", "SubPath2", "myFile.txt"), True, ["*.txt"], None
    )
    assert not pyrocopy._checkShouldCopy(
        os.path.join("Level1", "SubPath1", "SubPath2", "myFile.txt"), True, None, ["*.txt"]
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "SubPath1", "SubPath2", "myFile.txt"),
        True, None, [os.path.join("pathA", "*.txt")],
    )
    assert pyrocopy._checkShouldCopy(
        os.path.join("Level1", "SubPath1", "SubPath2", "f2342080"),
        True, ["re:f[0-9]+"], None,
    )


# ---------------------------------------------------------------------------
# mkdir
# ---------------------------------------------------------------------------

def test_mkdir(tmp_path: pytest.TempPathFactory) -> None:
    new_folder = str(tmp_path / "New Folder")
    assert not os.path.isdir(new_folder)
    assert pyrocopy.mkdir(new_folder), "Failed to create new_folder"
    assert os.path.isdir(new_folder)
    # Calling mkdir on an existing dir must return True
    assert pyrocopy.mkdir(new_folder), "mkdir on existing dir should return True"

    nested = str(tmp_path / "Level1" / "Level2" / "Level3" / "Level4")
    assert not os.path.isdir(nested)
    assert pyrocopy.mkdir(nested), "Failed to create nested path"
    assert os.path.isdir(nested)
    assert pyrocopy.mkdir(nested), "mkdir on existing nested dir should return True"


# ---------------------------------------------------------------------------
# _isSamePath
# ---------------------------------------------------------------------------

def test_is_same_path(tmp_path: pytest.TempPathFactory) -> None:
    dir1 = str(tmp_path / "dir1")
    dir2 = str(tmp_path / "dir2")
    os.makedirs(dir1)
    os.makedirs(dir2)
    assert not pyrocopy._isSamePath(dir1, dir2)
    assert pyrocopy._isSamePath(dir1, dir1)


# ---------------------------------------------------------------------------
# _getTreeDepth
# ---------------------------------------------------------------------------

def test_get_tree_depth(tmp_path: pytest.TempPathFactory) -> None:
    (tmp_path / "Level1" / "Level2" / "Level3" / "Level4").mkdir(parents=True)
    assert pyrocopy._getTreeDepth(str(tmp_path / "Level1")) == 3


# ---------------------------------------------------------------------------
# copy — basic
# ---------------------------------------------------------------------------

def test_copy_basic(tmp_path: pytest.TempPathFactory) -> None:
    num_files = 30
    src = gen_random_tree(str(tmp_path), 4, num_files, MAX_FILE_SIZE)
    dst = src + "Copy"

    results = pyrocopy.copy(src, dst, preserveStats=True)
    assert results.filesCopied == num_files, "initial copy: wrong filesCopied"
    assert results.filesFailed == 0 and results.dirsFailed == 0

    # Second copy — all files should be skipped (same mtime)
    results = pyrocopy.copy(src, dst, preserveStats=True)
    assert results.filesSkipped == num_files, "second copy: files should be skipped"
    assert results.filesFailed == 0 and results.dirsFailed == 0

    # Force overwrite
    results = pyrocopy.copy(src, dst, forceOverwrite=True, preserveStats=True)
    assert results.filesCopied == num_files, "force overwrite: wrong filesCopied"
    assert results.filesFailed == 0 and results.dirsFailed == 0


# ---------------------------------------------------------------------------
# copy — depth levels
# ---------------------------------------------------------------------------

def test_copy_depth_levels(base_src_tree: dict) -> None:
    src = base_src_tree["src"]
    dst = src + "Copy"

    results = pyrocopy.copy(src, dst, level=1)
    assert results.filesCopied == 5, "level=1"
    shutil.rmtree(dst)

    results = pyrocopy.copy(src, dst, level=-1)
    assert results.filesCopied == 7, "level=-1"
    shutil.rmtree(dst)

    results = pyrocopy.copy(src, dst, level=2)
    assert results.filesCopied == 8, "level=2"
    shutil.rmtree(dst)

    results = pyrocopy.copy(src, dst, level=-2)
    assert results.filesCopied == 10, "level=-2"
    shutil.rmtree(dst)


# ---------------------------------------------------------------------------
# copy — include / exclude
# ---------------------------------------------------------------------------

def test_copy_file_includes(src_tree: dict) -> None:
    src = src_tree["src"]
    dst = src + "Copy"
    results = pyrocopy.copy(src, dst, includeFiles=["re:f[0-9]+"])
    assert results.filesCopied == 15, "includeFiles f[0-9]+"
    for root, _dirs, files in os.walk(dst):
        for file in files:
            assert re.match(r"f[0-9]+", file), f"unexpected file not matching pattern: {file}"


def test_copy_file_excludes(src_tree: dict) -> None:
    src = src_tree["src"]
    dst = src + "Copy"
    results = pyrocopy.copy(src, dst, excludeFiles=["re:f[0-9]+"])
    assert results.filesCopied == 9, "excludeFiles f[0-9]+"
    for root, _dirs, files in os.walk(dst):
        for file in files:
            assert not re.match(r"f[0-9]+", file), f"excluded file found: {file}"


def test_copy_dir_includes(src_tree: dict) -> None:
    src = src_tree["src"]
    dst = src + "Copy"
    results = pyrocopy.copy(src, dst, includeDirs=["re:d[0-9]+"])
    assert results.filesCopied == 17, "includeDirs d[0-9]+"
    for _root, dirs, _files in os.walk(dst):
        for d in dirs:
            assert d not in ("moredir", "dummydir"), f"unexpected directory: {d}"


def test_copy_dir_excludes(src_tree: dict) -> None:
    src = src_tree["src"]
    dst = src + "Copy"
    results = pyrocopy.copy(src, dst, excludeDirs=[os.path.join("*", "moredir")])
    assert results.filesCopied == 19, "excludeDirs moredir"
    for _root, dirs, _files in os.walk(dst):
        assert "moredir" not in dirs, "excluded directory 'moredir' found in output"


# ---------------------------------------------------------------------------
# move — basic
# ---------------------------------------------------------------------------

def test_move_basic(src_tree: dict) -> None:
    src = src_tree["src"]
    dst = src + "Moved"

    results = pyrocopy.move(src, dst)
    assert results.filesMoved == 24, "move all: filesMoved"
    assert not os.path.exists(src) or not os.listdir(src), "src not cleaned up after move"


# ---------------------------------------------------------------------------
# move — depth levels
# ---------------------------------------------------------------------------

def test_move_depth_levels(src_tree: dict) -> None:
    src = src_tree["src"]
    dst = src + "Moved"

    # Move everything to dst first
    pyrocopy.move(src, dst)

    results = pyrocopy.move(dst, src, level=1)
    assert results.filesMoved == 6, "level=1"
    assert os.path.exists(dst), "level=1 deleted whole dst tree"

    results = pyrocopy.move(dst, src, level=-1)
    assert results.filesMoved == 12, "level=-1"
    assert os.path.exists(dst), "level=-1 deleted whole dst tree"

    results = pyrocopy.move(dst, src)
    assert results.filesMoved == 6, "move remainder"
    assert not os.path.exists(dst), "dst not cleaned up after final move"


# ---------------------------------------------------------------------------
# move — dir includes / excludes
# ---------------------------------------------------------------------------

def test_move_dir_includes_excludes(src_tree: dict) -> None:
    src = src_tree["src"]
    lvl2 = src_tree["lvl2"]
    dst = src + "Moved"

    # Include only dummydir — root files + dummydir subtree = 6+7 = 13 files
    results = pyrocopy.move(src, dst, includeDirs=["dummydir"], detailedResults=True)
    assert results.filesMoved == 13, "move includeDirs=dummydir"
    assert os.path.exists(src), "move with includeDirs deleted whole src tree"

    # src still has lvl1 (4 files) and lvl2 (7 files)
    exclude_lvl2 = [os.path.join("*", os.path.basename(lvl2))]
    results = pyrocopy.move(src, dst, excludeDirs=exclude_lvl2, detailedResults=True)
    assert results.filesMoved == 4, "move excludeDirs=lvl2: filesMoved"
    assert results.dirsSkipped == 1, "move excludeDirs=lvl2: dirsSkipped"
    assert os.path.exists(dst), "move with excludeDirs deleted whole dst tree"

    # Move the remaining 7 files in lvl2
    results = pyrocopy.move(src, dst)
    assert results.filesMoved == 7, "move remainder after dir excludes"
    assert not os.path.exists(src), "src not cleaned up after final move"


# ---------------------------------------------------------------------------
# move — file includes / excludes
# ---------------------------------------------------------------------------

def test_move_file_includes_excludes(src_tree: dict) -> None:
    src = src_tree["src"]
    dst = src + "Moved"

    # Move all 24 files to dst first
    pyrocopy.move(src, dst)

    # Move only f[0-9]+ files back (15 files, 9 skipped)
    results = pyrocopy.move(dst, src, includeFiles=["re:f[0-9]+"])
    assert results.filesMoved == 15, "move includeFiles f[0-9]+: filesMoved"
    assert results.filesSkipped == 9, "move includeFiles f[0-9]+: filesSkipped"
    assert os.path.exists(dst), "move with includeFiles deleted whole dst tree"

    # Move all except 'test' (8 files, 1 skipped)
    results = pyrocopy.move(dst, src, excludeFiles=["test"])
    assert results.filesMoved == 8, "move excludeFiles=test: filesMoved"
    assert results.filesSkipped == 1, "move excludeFiles=test: filesSkipped"


# ---------------------------------------------------------------------------
# mirror — basic
# ---------------------------------------------------------------------------

def test_mirror_basic(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_b, mir_b)

    results = pyrocopy.mirror(mir_a, mir_b)
    assert results.filesCopied == 5 and results.dirsCopied == 3
    assert results.filesRemoved == 3 and results.dirsRemoved == 2


# ---------------------------------------------------------------------------
# mirror — depth levels
# ---------------------------------------------------------------------------

def test_mirror_depth_level_1(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_b, mir_b)

    results = pyrocopy.mirror(mir_a, mir_b, level=1)
    assert results.filesCopied == 1 and results.filesRemoved == 1
    assert os.path.exists(os.path.join(mir_b, "fileA1"))
    assert not os.path.exists(os.path.join(mir_b, "fileB1"))


def test_mirror_depth_level_neg1(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sub_a21, sub_b11 = mirror_data["subPathA21"], mirror_data["subPathB11"]
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_b, mir_b)

    results = pyrocopy.mirror(mir_a, mir_b, level=-1)
    assert results.filesCopied == 1 and results.filesRemoved == 1
    assert results.dirsCopied == 1 and results.dirsRemoved == 1
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a21, path_a), "fileSubA21"))
    assert not os.path.exists(os.path.join(mir_b, os.path.relpath(sub_b11, path_b), "fileSubB11"))


def test_mirror_depth_level_2(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sub_a1, sub_a2 = mirror_data["subPathA1"], mirror_data["subPathA2"]
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_b, mir_b)

    results = pyrocopy.mirror(mir_a, mir_b, level=2, detailedResults=True)
    assert results.filesCopied == 4 and results.filesRemoved == 2
    assert results.dirsCopied == 2 and results.dirsRemoved == 0
    assert os.path.exists(os.path.join(mir_b, "fileA1"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1-2"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a2, path_a), "fileSubA2"))
    assert not os.path.exists(os.path.join(mir_b, "fileB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "fileSubB1"))


def test_mirror_depth_level_neg2(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sub_a1, sub_a2, sub_a21 = (
        mirror_data["subPathA1"], mirror_data["subPathA2"], mirror_data["subPathA21"]
    )
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_b, mir_b)

    results = pyrocopy.mirror(mir_a, mir_b, level=-2, detailedResults=True)
    assert results.filesCopied == 4 and results.filesRemoved == 2
    assert results.dirsCopied == 3 and results.dirsRemoved == 2
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1-2"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a2, path_a), "fileSubA2"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a21, path_a), "fileSubA21"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "fileSubB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "subSubB1", "fileSubB11"))


# ---------------------------------------------------------------------------
# mirror — file includes / excludes
# ---------------------------------------------------------------------------

def test_mirror_file_includes(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sub_a1 = mirror_data["subPathA1"]
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_b, mir_b)

    results = pyrocopy.mirror(mir_a, mir_b, includeFiles=["*A1*"], detailedResults=True)
    assert results.filesCopied == 3 and results.filesSkipped == 2
    assert results.filesRemoved == 3 and results.dirsRemoved == 2
    assert os.path.exists(os.path.join(mir_b, "fileA1"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1-2"))
    assert not os.path.exists(os.path.join(mir_b, "fileB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "fileSubB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "subSubB1", "fileSubB11"))


def test_mirror_file_includes_remove_matching_destination_only_files(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a = mirror_data["pathA"]
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_a, mir_b)
    gen_random_contents(os.path.join(mir_b, "orphanA1"), MAX_FILE_SIZE)
    os.mkdir(os.path.join(mir_b, "orphanDir"))
    gen_random_contents(os.path.join(mir_b, "orphanDir", "nestedA1"), MAX_FILE_SIZE)
    gen_random_contents(os.path.join(mir_b, "orphanB1"), MAX_FILE_SIZE)

    results = pyrocopy.mirror(mir_a, mir_b, includeFiles=["*A1*"], detailedResults=True)
    assert results.filesRemoved == 5 and results.dirsRemoved == 1
    assert not os.path.exists(os.path.join(mir_b, os.path.relpath(mirror_data["subPathA2"], path_a), "fileSubA2"))
    assert not os.path.exists(os.path.join(mir_b, os.path.relpath(mirror_data["subPathA21"], path_a), "fileSubA21"))
    assert not os.path.exists(os.path.join(mir_b, "orphanA1"))
    assert not os.path.exists(os.path.join(mir_b, "orphanDir", "nestedA1"))
    assert not os.path.exists(os.path.join(mir_b, "orphanDir"))
    assert not os.path.exists(os.path.join(mir_b, "orphanB1"))


def test_mirror_file_excludes(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sub_a2, sub_a21 = mirror_data["subPathA2"], mirror_data["subPathA21"]
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_b, mir_b)

    results = pyrocopy.mirror(mir_a, mir_b, excludeFiles=["fileA1*", "fileSubA1*"], detailedResults=True)
    assert results.filesCopied == 2 and results.filesSkipped == 3
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a2, path_a), "fileSubA2"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a21, path_a), "fileSubA21"))
    assert not os.path.exists(os.path.join(mir_b, "fileB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "fileSubB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "subSubB1", "fileSubB11"))


# ---------------------------------------------------------------------------
# mirror — dir includes / excludes
# ---------------------------------------------------------------------------

def test_mirror_dir_includes(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sub_a1 = mirror_data["subPathA1"]
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_b, mir_b)

    results = pyrocopy.mirror(mir_a, mir_b, includeDirs=["subA1"], detailedResults=True)
    assert results.filesCopied == 3 and results.dirsSkipped == 2
    assert results.filesRemoved == 3 and results.dirsRemoved == 2
    assert os.path.exists(os.path.join(mir_b, "fileA1"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1-2"))
    assert not os.path.exists(os.path.join(mir_b, "fileB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "fileSubB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "subSubB1", "fileSubB11"))


def test_mirror_dir_excludes(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sub_a1, sub_a2, sub_a21 = (
        mirror_data["subPathA1"], mirror_data["subPathA2"], mirror_data["subPathA21"]
    )
    mir_a, mir_b = str(tmp_path / "mirrorA"), str(tmp_path / "mirrorB")
    pyrocopy.copy(path_a, mir_a)
    pyrocopy.copy(path_b, mir_b)

    results = pyrocopy.mirror(
        mir_a, mir_b, excludeDirs=[os.path.join("*", "subSubA1")], detailedResults=True
    )
    assert results.filesCopied == 4 and results.dirsSkipped == 1
    assert results.filesRemoved == 3 and results.dirsRemoved == 2
    assert os.path.exists(os.path.join(mir_b, "fileA1"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a1, path_a), "fileSubA1-2"))
    assert os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a2, path_a), "fileSubA2"))
    assert not os.path.exists(os.path.join(mir_b, os.path.relpath(sub_a21, path_a), "fileSubA21"))
    assert not os.path.exists(os.path.join(mir_b, "fileB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "fileSubB1"))
    assert not os.path.exists(os.path.join(mir_b, "subB1", "subSubB1", "fileSubB11"))


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

def test_sync_basic(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sync_a, sync_b = str(tmp_path / "syncA"), str(tmp_path / "syncB")
    pyrocopy.copy(path_a, sync_a)
    pyrocopy.copy(path_b, sync_b)

    results = pyrocopy.sync(sync_a, sync_b, preserveStats=True)
    assert results.filesCopied == 8 and results.dirsCopied == 5
    # The second copy direction (syncB→syncA) encounters the 5 pathA files already in
    # syncA with identical mtimes and skips them; these are counted in the merged result.
    assert results.filesSkipped == 5 and results.dirsSkipped == 0
    assert results.filesFailed == 0 and results.dirsFailed == 0


def test_sync_with_pre_existing_files(mirror_data: dict) -> None:
    """Files already present in both trees with same mtime are skipped."""
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sync_a, sync_b = str(tmp_path / "syncA"), str(tmp_path / "syncB")
    pyrocopy.copy(path_a, sync_a)
    pyrocopy.copy(path_b, sync_b)
    # Pre-seed one file in each direction so they are skipped during sync
    pyrocopy.copy(os.path.join(sync_a, "fileA1"), os.path.join(sync_b, "fileA1"))
    pyrocopy.copy(os.path.join(sync_b, "fileB1"), os.path.join(sync_a, "fileB1"))

    results = pyrocopy.sync(sync_a, sync_b, preserveStats=True, detailedResults=True)
    assert results.filesFailed == 0 and results.dirsFailed == 0
    assert results.filesCopied == 6 and results.dirsCopied == 5
    # The two pre-seeded files plus all 4 pathA files are skipped in the B→A direction.
    assert results.filesSkipped == 6 and results.dirsSkipped == 0


def test_sync_with_one_pre_existing_file(mirror_data: dict) -> None:
    """A file copied from B→A before the sync is skipped during the sync."""
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sub_b11 = mirror_data["subPathB11"]
    sync_a, sync_b = str(tmp_path / "syncA"), str(tmp_path / "syncB")
    pyrocopy.copy(path_a, sync_a)
    pyrocopy.copy(path_b, sync_b)
    # Copy one file from B into A so it should be skipped during sync
    pyrocopy.copy(
        os.path.join(sync_b, os.path.relpath(sub_b11, path_b), "fileSubB11"),
        os.path.join(sync_a, os.path.relpath(sub_b11, path_b), "fileSubB11"),
    )

    results = pyrocopy.sync(sync_a, sync_b, preserveStats=True, detailedResults=True)
    assert results.filesFailed == 0 and results.dirsFailed == 0
    assert results.filesCopied == 7 and results.dirsCopied == 5
    # fileSubB11 plus the 5 pathA files are skipped in the B→A direction.
    assert results.filesSkipped == 6 and results.dirsSkipped == 0


def test_sync_respects_file_excludes(mirror_data: dict) -> None:
    tmp_path = mirror_data["tmp_path"]
    path_a, path_b = mirror_data["pathA"], mirror_data["pathB"]
    sync_a, sync_b = str(tmp_path / "syncA"), str(tmp_path / "syncB")
    pyrocopy.copy(path_a, sync_a)
    pyrocopy.copy(path_b, sync_b)

    results = pyrocopy.sync(sync_a, sync_b, excludeFiles=["*fileB1"], detailedResults=True)
    assert results.filesFailed == 0 and results.dirsFailed == 0
    assert not os.path.exists(os.path.join(sync_a, "fileB1"))
    assert os.path.exists(os.path.join(sync_b, "fileB1"))
