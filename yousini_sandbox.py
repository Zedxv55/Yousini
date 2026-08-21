#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sandbox สำหรับ Yousini ที่ใช้ OS isolation อย่างชัดเจน.

โหมดมาตรฐานใช้ Bubblewrap (`bwrap`) เพื่อแยก mount, process, IPC, UTS,
user และ network namespaces ออกจาก host. ระบบจะ **fail closed**: หากไม่มี
Bubblewrap จะไม่ fallback ไป execute คำสั่งบน host โดยอ้างว่าเป็น sandbox.

Workspace ถูก bind แบบ read-only เป็นค่าเริ่มต้น. ผู้เรียกต้องระบุ
``writable=True`` อย่างชัดเจนเมื่อต้องการให้คำสั่งแก้ไฟล์ใน workspace.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


class SandboxUnavailable(RuntimeError):
    """Raised when the requested isolation backend is not available."""


class Sandbox:
    """Run one shell command inside a Bubblewrap-isolated workspace.

    This class intentionally has no unsafe automatic fallback. `backend="auto"`
    selects Bubblewrap when installed; otherwise :meth:`run` returns a structured
    unavailable result instead of running the command on the host.
    """

    def __init__(
        self,
        workspace: str | os.PathLike[str] | None = None,
        *,
        root_dir: str | os.PathLike[str] | None = None,
        timeout: int = 30,
        memory_limit_mb: int = 512,
        cpu_limit_s: int = 30,
        process_limit: int = 64,
        writable: bool = False,
        network: bool = False,
        backend: str = "auto",
    ):
        # root_dir remains as a compatibility alias for the first experimental API.
        if workspace is not None and root_dir is not None:
            raise ValueError("ระบุ workspace หรือ root_dir ได้เพียงหนึ่งค่า")
        chosen = workspace if workspace is not None else root_dir
        self._temporary_workspace = chosen is None
        self.workspace = Path(chosen or tempfile.mkdtemp(prefix="yousini_sandbox_")).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = max(1, int(timeout))
        self.memory_limit = max(64, int(memory_limit_mb)) * 1024 * 1024
        self.cpu_limit_s = max(1, int(cpu_limit_s))
        self.process_limit = max(1, int(process_limit))
        self.writable = bool(writable)
        self.network = bool(network)
        self.backend = backend
        self.active_processes: dict[int, subprocess.Popen[str]] = {}

    @property
    def root_dir(self) -> Path:
        """Compatibility alias for callers of the initial sandbox prototype."""
        return self.workspace

    @staticmethod
    def available_backends() -> dict[str, bool]:
        """Return the isolation runtimes visible on PATH."""
        return {"bwrap": bool(shutil.which("bwrap"))}

    def status(self) -> dict[str, Any]:
        """Describe security-relevant runtime properties without running code."""
        bwrap = bool(shutil.which("bwrap"))
        selected = "bwrap" if self.backend == "auto" else self.backend
        return {
            "ok": selected == "bwrap" and bwrap,
            "backend": selected,
            "available": {"bwrap": bwrap},
            "isolated": selected == "bwrap" and bwrap,
            "network": self.network,
            "workspace_mode": "read-write" if self.writable else "read-only",
            "workspace": str(self.workspace),
        }

    def _runtime(self) -> str:
        backend = "bwrap" if self.backend == "auto" else self.backend
        if backend != "bwrap":
            raise SandboxUnavailable(f"ไม่รองรับ sandbox backend: {backend}")
        bwrap = shutil.which("bwrap")
        if not bwrap:
            raise SandboxUnavailable(
                "ไม่พบ Bubblewrap (bwrap); sandbox จะไม่รันคำสั่งบน host โดยอัตโนมัติ. "
                "บน Debian/Ubuntu ให้ติดตั้งด้วย: sudo apt install bubblewrap"
            )
        return bwrap

    def _resolve_cwd(self, cwd: str | os.PathLike[str] | None) -> tuple[Path, str]:
        """Resolve a working directory and reject paths escaping the workspace."""
        if cwd is None:
            target = self.workspace
        else:
            raw = Path(cwd)
            target = raw.resolve() if raw.is_absolute() else (self.workspace / raw).resolve()
        try:
            relative = target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("cwd ต้องอยู่ภายใน workspace ของ sandbox") from exc
        if not target.exists():
            if not self.writable:
                raise ValueError("สร้าง cwd ใหม่ไม่ได้เมื่อ workspace เป็น read-only")
            target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            raise ValueError("cwd ของ sandbox ต้องเป็น directory")
        # /tmp exists on a normal Unix root. Using an existing mount point avoids
        # creating a new path after the host root is mounted read-only by bwrap.
        inside = "/tmp" if str(relative) == "." else f"/tmp/{relative.as_posix()}"
        return target, inside

    @staticmethod
    def _start_process_group() -> None:
        """Put the Bubblewrap launcher in a dedicated group for reliable cancellation."""
        os.setsid()

    def _limited_shell(self) -> str:
        """Return a shell prelude applied after the namespace exists.

        Applying RLIMIT_NPROC before Bubblewrap starts can prevent the runtime from
        creating its namespaces on busy hosts. The limits are therefore applied by
        the first shell *inside* the isolated namespace.
        """
        memory_kb = max(1, self.memory_limit // 1024)
        return (
            f"ulimit -t {self.cpu_limit_s}; "
            f"ulimit -v {memory_kb}; "
            f"ulimit -u {self.process_limit}; "
            "ulimit -n 128; "
            'exec /bin/bash -lc "$1"'
        )

    def _command(self, command: str, inside_cwd: str) -> list[str]:
        bwrap = self._runtime()
        workspace_flag = "--bind" if self.writable else "--ro-bind"
        args = [
            bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--ro-bind", "/", "/",
            # /tmp exists before mounting and is replaced with the constrained
            # workspace, so bwrap does not need to create a directory on a read-only root.
            workspace_flag, str(self.workspace), "/tmp",
            "--tmpfs", "/var/tmp",
            "--tmpfs", "/home",
            "--proc", "/proc",
            "--dev", "/dev",
            "--clearenv",
            "--setenv", "HOME", "/home/sandbox",
            "--setenv", "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "--setenv", "LANG", "C.UTF-8",
            "--setenv", "TERM", os.environ.get("TERM", "xterm-256color"),
            "--chdir", inside_cwd,
        ]
        # bwrap unshares network as part of --unshare-all. This explicit flag is
        # opt-in and should only be used when the caller has separately approved it.
        if self.network:
            args.append("--share-net")
        # Pass the user command as a positional parameter rather than interpolating
        # it into the bootstrap script, so quotes and shell metacharacters survive.
        return args + ["--", "/bin/bash", "-lc", self._limited_shell(), "yousini-sandbox", command]

    @staticmethod
    def _result(
        *,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = -1,
        duration: float = 0.0,
        pid: int | None = None,
        backend: str = "bwrap",
        isolated: bool = False,
        timed_out: bool = False,
        unavailable: bool = False,
    ) -> dict[str, Any]:
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "duration": duration,
            "pid": pid,
            "backend": backend,
            "isolated": isolated,
            "timed_out": timed_out,
            "unavailable": unavailable,
        }

    def run(self, command: str, cwd: str | os.PathLike[str] | None = None) -> dict[str, Any]:
        """Run ``command`` in the isolated workspace and return a structured result."""
        start = time.monotonic()
        if not isinstance(command, str) or not command.strip():
            return self._result(stderr="Error: ต้องระบุคำสั่งสำหรับ sandbox", duration=0.0)
        try:
            _, inside_cwd = self._resolve_cwd(cwd)
            argv = self._command(command, inside_cwd)
        except SandboxUnavailable as exc:
            return self._result(
                stderr=f"Sandbox unavailable: {exc}",
                duration=time.monotonic() - start,
                unavailable=True,
            )
        except Exception as exc:
            return self._result(stderr=f"Sandbox error: {exc}", duration=time.monotonic() - start)

        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                preexec_fn=self._start_process_group,
            )
            self.active_processes[process.pid] = process
            stdout, stderr = process.communicate(timeout=self.timeout)
            return self._result(
                stdout=stdout,
                stderr=stderr,
                exit_code=process.returncode,
                duration=time.monotonic() - start,
                pid=process.pid,
                isolated=True,
            )
        except subprocess.TimeoutExpired:
            if process is not None:
                self.kill(process.pid)
                stdout, stderr = process.communicate()
            else:
                stdout, stderr = "", ""
            return self._result(
                stdout=stdout,
                stderr=(stderr + "\n" if stderr else "") + f"Sandbox timed out after {self.timeout}s",
                duration=time.monotonic() - start,
                pid=process.pid if process else None,
                isolated=True,
                timed_out=True,
            )
        except Exception as exc:
            return self._result(
                stderr=f"Sandbox error: {exc}",
                duration=time.monotonic() - start,
                pid=process.pid if process else None,
            )
        finally:
            if process is not None:
                self.active_processes.pop(process.pid, None)

    def kill(self, pid: int) -> None:
        """Kill a sandbox command and every process in its process group."""
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

    def cleanup(self) -> None:
        """Terminate active work and remove only a temporary workspace we created."""
        for pid in list(self.active_processes):
            self.kill(pid)
        self.active_processes.clear()
        if self._temporary_workspace and self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)


if __name__ == "__main__":
    sandbox = Sandbox()
    print(sandbox.status())
    print(sandbox.run("printf 'sandbox-ready\\n'"))
    sandbox.cleanup()
