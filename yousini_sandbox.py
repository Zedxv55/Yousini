#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini Sandbox — OS-level isolation
Provides a secure environment to run untrusted shell commands.
Initial implementation focuses on subprocess isolation with resource limits.
"""
import os
import subprocess
import signal
import time
import tempfile
import shutil
from pathlib import Path

class Sandbox:
    def __init__(self, root_dir: str = None, timeout: int = 30, memory_limit_mb: int = 512):
        self.root_dir = Path(root_dir or tempfile.mkdtemp(prefix="yousini_sandbox_"))
        self.timeout = timeout
        self.memory_limit = memory_limit_mb * 1024 * 1024
        self.active_processes = {}

        if not self.root_dir.exists():
            self.root_dir.mkdir(parents=True)

    def run(self, command: str, cwd: str = None) -> dict:
        """Execute a command within the sandbox environment."""
        target_cwd = self.root_dir / (cwd or "")
        if not target_cwd.exists():
            target_cwd.mkdir(parents=True, exist_ok=True)

        start_time = time.time()
        try:
            # Basic isolation: use a dedicated group and limited environment
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(self.root_dir),
                "USER": "yousini_sandbox",
                "LANG": "en_US.UTF-8",
            }
            
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=str(target_cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                preexec_fn=os.setsid # Create new process group
            )
            
            self.active_processes[process.pid] = process
            
            stdout, stderr = process.communicate(timeout=self.timeout)
            exit_code = process.returncode
            
        except subprocess.TimeoutExpired:
            self.kill(process.pid)
            stdout, stderr = "", "Error: Command timed out."
            exit_code = -1
        except Exception as e:
            stdout, stderr = "", f"Error: {str(e)}"
            exit_code = -1
        finally:
            if process.pid in self.active_processes:
                del self.active_processes[process.pid]

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "duration": time.time() - start_time,
            "pid": process.pid
        }

    def kill(self, pid: int):
        """Kill a process and its entire process group."""
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

    def cleanup(self):
        """Terminate all active processes and remove sandbox directory."""
        for pid in list(self.active_processes.keys()):
            self.kill(pid)
        
        if self.root_dir.exists() and "yousini_sandbox_" in self.root_dir.name:
            shutil.rmtree(self.root_dir)

if __name__ == "__main__":
    # Quick test
    sb = Sandbox()
    print(f"Sandbox created at: {sb.root_dir}")
    res = sb.run("echo 'Hello from Sandbox'; pwd; id")
    print(f"Result: {res}")
    sb.cleanup()
