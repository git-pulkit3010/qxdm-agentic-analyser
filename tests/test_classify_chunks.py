"""
Regression tests for the watcher's file grouping logic.

The watcher must recognise every piece of a single test run, no matter how the
pieces are labelled, and group them under ONE test_id.

Run: .venv/bin/python tests/test_classify_chunks.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.watcher import classify_chunks


def _group(names: list[str]) -> dict[str, list[str]]:
    """Classify the given filenames and return {test_id: [chunk names in order]}."""
    groups = classify_chunks([Path(n) for n in names])
    return {test_id: [p.name for _, p in chunks] for test_id, chunks in groups.items()}


def test_letter_parts_are_one_run():
    """TEST_RUN_001_A / _B are two parts of the SAME run, not two runs."""
    assert _group(["TEST_RUN_001_A.txt", "TEST_RUN_001_B.txt"]) == {
        "TEST_RUN_001": ["TEST_RUN_001_A.txt", "TEST_RUN_001_B.txt"]
    }


def test_letter_parts_are_ordered():
    """Parts sort A, B, C ... regardless of the order they arrive in."""
    groups = _group(["TEST_RUN_001_C.txt", "TEST_RUN_001_A.txt", "TEST_RUN_001_B.txt"])
    assert list(groups) == ["TEST_RUN_001"]
    assert groups["TEST_RUN_001"] == [
        "TEST_RUN_001_A.txt", "TEST_RUN_001_B.txt", "TEST_RUN_001_C.txt"
    ]


def test_double_letter_parts():
    """Parts beyond Z keep their natural order (AA after Z)."""
    groups = _group(["RUN_AA.txt", "RUN_Z.txt", "RUN_A.txt"])
    assert groups["RUN"] == ["RUN_A.txt", "RUN_Z.txt", "RUN_AA.txt"]


def test_numeric_parts_are_one_run():
    """The original convention still groups numbered chunks under one run."""
    assert _group(["TEST_RUN_001.txt", "TEST_RUN_002.txt"]) == {
        "TEST_RUN": ["TEST_RUN_001.txt", "TEST_RUN_002.txt"]
    }


def test_keyword_parts_are_one_run():
    """Keyword markers (chunk/part/segment/seq) still group under one run."""
    assert _group(["RUN123_chunk_001.txt", "RUN123_chunk_002.txt"]) == {
        "RUN123": ["RUN123_chunk_001.txt", "RUN123_chunk_002.txt"]
    }
    assert _group(["log_chunk_3.txt"]) == {"log": ["log_chunk_3.txt"]}
    assert _group(["test_session_02.txt"]) == {"test": ["test_session_02.txt"]}


def test_unmarked_files_stay_standalone():
    """Files with no part marker remain their own test run, untouched."""
    assert _group(["sample.txt"]) == {"sample": ["sample.txt"]}
    assert _group(["UE23_TCP_UDP_UL_75_01-11.06-36-49-875.txt"]) == {
        "UE23_TCP_UDP_UL_75_01-11.06-36-49": ["UE23_TCP_UDP_UL_75_01-11.06-36-49-875.txt"]
    }


def test_mixed_part_styles_group_together():
    """A run may mix marker styles (e.g. _A / _2) and still group as one run."""
    groups = _group(["TEST_RUN_001_A.txt", "TEST_RUN_001_2.txt"])
    assert list(groups) == ["TEST_RUN_001"]
    assert sorted(groups["TEST_RUN_001"]) == ["TEST_RUN_001_2.txt", "TEST_RUN_001_A.txt"]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
    print("\nAll tests passed." if not failures else f"\n{failures} test(s) failed.")
    sys.exit(1 if failures else 0)
