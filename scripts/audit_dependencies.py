"""Audit the locked dependencies for known vulnerabilities with pip-audit.

Runs the same way on every operating system, which a shell pipeline would not.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    """Export the locked requirements to a temporary file and audit them."""
    uv = shutil.which("uv")
    uvx = shutil.which("uvx")
    if uv is None or uvx is None:
        print("uv and uvx must be on PATH", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="vidbrief-audit-") as tmp:
        requirements = Path(tmp) / "requirements.txt"
        export = [
            uv, "export",
            "--format", "requirements-txt",
            "--no-emit-project",
            "--quiet",
            "--output-file", str(requirements),
        ]  # fmt: skip
        subprocess.run(export, check=True)  # noqa: S603 - argument list, no shell, trusted binary
        audit = [uvx, "pip-audit", "--disable-pip", "--requirement", str(requirements)]
        return subprocess.run(audit, check=False).returncode  # noqa: S603 - same as above


if __name__ == "__main__":
    raise SystemExit(main())
