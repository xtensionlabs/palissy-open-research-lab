import pytest

from palissy.sandbox import LocalExecutor
from palissy.stages.hypothesis import _extract_json, format_literature


def test_extract_json_from_wrapped_text():
    assert _extract_json('Sure:\n{"hypothesis": "h", "cited": [1]}\n') == {
        "hypothesis": "h", "cited": [1]}


def test_extract_json_raises_without_object():
    with pytest.raises(ValueError):
        _extract_json("no json here")


def test_format_literature_numbers_sources():
    out = format_literature([{"title": "T", "url": "http://x", "content": "abc"}])
    assert out.startswith("[1] T (http://x)")


async def test_local_executor_runs_and_captures_output():
    r = await LocalExecutor().run("print('hi')")
    assert r.ok and r.stdout.strip() == "hi" and r.backend == "local-fallback"


async def test_local_executor_reports_failure_and_timeout():
    assert (await LocalExecutor().run("raise SystemExit(3)")).exit_code == 3
    assert (await LocalExecutor().run("import time; time.sleep(5)", timeout=1)).exit_code == 124
