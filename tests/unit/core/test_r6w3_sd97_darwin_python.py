"""SD-97: macOS manager interpreter floor, without weakening Linux support."""

from binnacle.diagnostics.doctor import check_darwin_job_python


def test_linux_has_no_darwin_python_check():
    assert check_darwin_job_python("linux", (3, 10), False) == []


def test_darwin_310_to_312_refuse_manager_even_if_waitid_was_injected():
    for minor in (10, 11, 12):
        (check,) = check_darwin_job_python("darwin", (3, minor), True)
        assert check.status == "fail"
        assert "Python >= 3.13" in check.detail
        assert "idle" in check.hint


def test_darwin_313_without_waitid_refuses_manager():
    (check,) = check_darwin_job_python("darwin", (3, 13), False)
    assert check.status == "fail" and "os.waitid" in check.detail


def test_darwin_313_with_waitid_and_314_are_supported():
    for minor in (13, 14):
        (check,) = check_darwin_job_python("darwin", (3, minor), True)
        assert check.status == "ok"
        assert "supported" in check.detail


def test_doctor_does_not_apply_manager_python_floor_to_frontend():
    """A healthy 3.13 manager may serve a 3.12 frontend (R6W3-02)."""
    import ast
    from pathlib import Path

    from binnacle.diagnostics import doctor

    module = ast.parse(Path(doctor.__file__).read_text(encoding="utf-8"))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_all"
    )
    calls = [
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "check_darwin_job_python" not in calls
    assert "check_job_manager" in calls
