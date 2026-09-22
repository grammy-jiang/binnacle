"""Failure boundaries for the private job-manager client protocol."""

from io import BytesIO

import pytest

from binnacle import job_client


class _FakeSocket:
    def __init__(self, response: bytes):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def settimeout(self, timeout):
        pass

    def connect(self, path):
        pass

    def sendall(self, wire):
        pass

    def makefile(self, mode):
        return BytesIO(self.response)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (b"", "closed the connection"),
        (b"{not-json}\n", "malformed JSON"),
        (b"[]\n", "non-object response"),
        (b'{"ok":false,"error":"rejected"}\n', "rejected"),
    ],
)
def test_request_rejects_invalid_manager_responses(
    tmp_path, monkeypatch, response, message
):
    monkeypatch.setattr(
        job_client.socket,
        "socket",
        lambda *args, **kwargs: _FakeSocket(response),
    )

    with pytest.raises(job_client.JobManagerError, match=message):
        job_client.ping(tmp_path / "jobs.sock")
