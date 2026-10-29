"""Fail-closed bubblewrap execution of *untrusted* generated verifier scripts.

Never falls back to running generated code on the host. Requires Linux bwrap,
user namespaces and a trusted Python interpreter. Separate per-check resource limits.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

@dataclass(frozen=True)
class SandboxResult:
    outcome: str
    detail: str
    stdout: str = ""
    stderr: str = ""
    code: int | None = None

def available() -> bool:
    return sys.platform.startswith("linux") and bool(shutil.which("bwrap"))

def _limits():
    limits = [(resource.RLIMIT_CPU, 20), (resource.RLIMIT_NOFILE, 64),
              (resource.RLIMIT_FSIZE, 8 * 1024 * 1024),
              (resource.RLIMIT_AS, 768 * 1024 * 1024)]
    for name, value in limits:
        resource.setrlimit(name, (value, value))

def run_python(code: str, *, timeout: float = 10.0) -> SandboxResult:
    if not isinstance(code, str) or len(code.encode("utf-8")) > 131072:
        return SandboxResult("error", "checker_too_large")
    if not available():
        return SandboxResult("error", "bubblewrap_unavailable; generated code NOT executed")
    if not 0 < timeout <= 60:
        return SandboxResult("error", "invalid_timeout")
    with tempfile.TemporaryDirectory(prefix="council-verifier-") as work:
        path = Path(work) / "check.py"
        path.write_text(code, encoding="utf-8")
        cmd = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
               "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
               "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        # A merged-usr distribution uses /lib -> /usr/lib; reproduce the
        # symlink rather than binding through a symlink destination.
        cmd += ["--ro-bind", "/usr", "/usr"]
        for mount in ("/lib", "/lib64"):
            if Path(mount).is_symlink():
                target=os.readlink(mount)
                if target in ("usr/lib", "/usr/lib"):
                    cmd += ["--symlink", "usr/lib", mount]
                else:
                    return SandboxResult("error", "unexpected_system_library_symlink")
            elif Path(mount).exists():
                cmd += ["--ro-bind", mount, mount]
        # Read-only interpreter/venv only, not the caller's working directory.
        prefix = str(Path(sys.prefix).resolve())
        if not (prefix == "/usr" or prefix.startswith("/usr/")):
            cmd += ["--ro-bind", prefix, prefix]
        # Only this throwaway scratch directory is writable in the sandbox.
        cmd += ["--bind", work, "/work", "--chdir", "/work",
                "--", sys.executable, "-I", "-B", "/work/check.py"]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                  text=True, timeout=timeout, preexec_fn=_limits,
                                  check=False, start_new_session=True)
        except subprocess.TimeoutExpired:
            return SandboxResult("timeout", "sandbox timeout")
        except OSError:
            return SandboxResult("error", "sandbox creation failed")
        if proc.returncode:
            return SandboxResult("error", "sandbox process failed", proc.stdout[-1600:],
                                 proc.stderr[-1600:], proc.returncode)
        try:
            answer = json.loads(proc.stdout.strip().splitlines()[-1])
            if not isinstance(answer, dict) or type(answer.get("pass")) is not bool:
                raise ValueError()
        except (ValueError, IndexError):
            return SandboxResult("error", "checker did not emit final JSON pass boolean",
                                 proc.stdout[-1600:], proc.stderr[-1600:], proc.returncode)
        return SandboxResult("pass" if answer["pass"] else "fail",
                             "sandbox completed", proc.stdout[-1600:],
                             proc.stderr[-1600:], proc.returncode)
