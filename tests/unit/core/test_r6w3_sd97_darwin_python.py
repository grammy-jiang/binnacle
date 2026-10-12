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
