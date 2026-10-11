"""TYPE-01: run with uv run --locked --group lint python <this file>.

No pytest dependency or ambient executable search. Every negative must produce
exactly its pinned error location/code/message; crashes and missing mypy fail.
Temporary filenames are fixed; each invocation gets a private temporary root.
Q1 alone owns hook enrollment. This driver does not install or change anything.
"""

import json
import os
import re
import subprocess
import sys
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
IMPORTS = """from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision, JobRef, OutputSnapshot, ReceiptQueryResult, Scope,
    VerifiedRunGrant, Success, Failure, BoundaryError, ErrorCode,
)
from binnacle.features.commands.job_awareness.ports import HandleAuthorityPort, ReceiptQueryPort
"""
GOOD = (
    IMPORTS
    + """from tests.contracts.job_awareness.fakes import FakeHandleAuthority, FakeReceiptQuery

def consume(authority: HandleAuthorityPort, query: ReceiptQueryPort,
            grant: VerifiedRunGrant, job: JobRef, snapshot: OutputSnapshot) -> str:
    decision: AuthorityDecision = authority.check(grant, job, frozenset({Scope.OBSERVE}))
    result: ReceiptQueryResult = query.query(grant, snapshot)
    if isinstance(result, Success):
        return result.value.state.value
    return result.error.code.value + decision.value

authority: HandleAuthorityPort = FakeHandleAuthority()
query: ReceiptQueryPort = FakeReceiptQuery(authority)
"""
)
BAD_RETURNS = {
    "bad_dict.py": ("ReceiptQueryResult", "{}", "dict[Never, Never]"),
    "bad_none.py": ("ReceiptQueryResult", "None", "None"),
    "bad_authority.py": ("AuthorityDecision", '"authorized"', "str"),
}


def run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )


def check_diagnostic(
    result: subprocess.CompletedProcess[str],
    name: str,
    line: int,
    code: str,
    message: str,
) -> bool:
    """Reject unrelated errors, missing diagnostics, crashes and checker absence."""
    errors = result.stdout.splitlines()
    expected = f"{name}:{line}: error: {message}  [{code}]"
    return (
        result.returncode == 1
        and result.stderr == ""
        and len(errors) == 1
        and errors[0].endswith(expected)
    )


def main() -> int:
    try:
        mypy_version = version("mypy")
    except PackageNotFoundError:
        print("TYPE-01 FAIL: mypy is missing from this interpreter", file=sys.stderr)
        return 1
    lock = (ROOT / "uv.lock").read_bytes()
    match = re.search(rb'\[\[package\]\]\nname = "mypy"\nversion = "([^"]+)"', lock)
    if match is None or match[1].decode() != mypy_version:
        print("TYPE-01 FAIL: mypy does not match uv.lock", file=sys.stderr)
        return 1
    env = dict(
        os.environ,
        MYPYPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT))),
        PYTHONDONTWRITEBYTECODE="1",
    )
    print(
        json.dumps(
            {
                "gate": "TYPE-01",
                "python": sys.version,
                "mypy": mypy_version,
                "uv_lock_sha256": sha256(lock).hexdigest(),
                "root": str(ROOT),
            }
        )
    )
    with TemporaryDirectory(prefix="binnacle-ja-types-") as directory:
        temp = Path(directory)
        command = [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--no-incremental",
            "--cache-dir",
            str(temp / "cache"),
            "--show-error-codes",
            "--no-error-summary",
            "--no-pretty",
            "--python-version",
            "3.10",
            "--follow-imports",
            "normal",
        ]
        cases: list[tuple[str, str, int, str, str]] = [("good.py", GOOD, 0, "", "")]
        for name, (result_type, expression, actual) in BAD_RETURNS.items():
            source = (
                IMPORTS + f"def wrong() -> {result_type}:\n    return {expression}\n"
            )
            expected_type = (
                "Success[ConsumerReceipt] | Failure"
                if result_type == "ReceiptQueryResult"
                else "AuthorityDecision"
            )
            message = f'Incompatible return value type (got "{actual}", expected "{expected_type}")'
            cases.append(
                (name, source, len(source.splitlines()), "return-value", message)
            )
        source = IMPORTS + 'grant: VerifiedRunGrant = {"chat_id": "untrusted"}\n'
        cases.append(
            (
                "bad_claims.py",
                source,
                len(source.splitlines()),
                "assignment",
                'Incompatible types in assignment (expression has type "dict[str, str]", variable has type "VerifiedRunGrant")',
            )
        )
        source = (
            IMPORTS
            + "from binnacle.features.commands.job_awareness.models import RunGrantClaims\ndef bad(claims: RunGrantClaims) -> VerifiedRunGrant:\n    return claims\n"
        )
        cases.append(
            (
                "bad_parsed_claims.py",
                source,
                len(source.splitlines()),
                "return-value",
                'Incompatible return value type (got "RunGrantClaims", expected "VerifiedRunGrant")',
            )
        )
        for name, source, line, code, message in cases:
            path = temp / name
            path.write_text(source)
            targets = [str(path)]
            if name == "good.py":
                targets += [
                    str(ROOT / "src/binnacle/features/commands/job_awareness"),
                    str(ROOT / "tests/contracts/job_awareness/fakes.py"),
                ]
            result = run(command + targets, env)
            ok = (
                result.returncode == 0 and not result.stdout and not result.stderr
                if name == "good.py"
                else check_diagnostic(result, name, line, code, message)
            )
            print(
                json.dumps(
                    {
                        "case": name,
                        "exit_code": result.returncode,
                        "pass": ok,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
            )
            if not ok:
                return 1
        # A checker-unavailable process is an error, never a successful negative.
        missing = run([sys.executable, "-S", "-m", "mypy", "--version"], env)
        if (
            missing.returncode == 0
            or "No module named mypy" not in missing.stderr
            or check_diagnostic(missing, "bad.py", 1, "return-value", "")
        ):
            print("TYPE-01 FAIL: missing-checker control was not rejected")
            return 1
        print("TYPE-01 PASS: positive, five exact negatives, missing-checker control")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"TYPE-01 FAIL: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
