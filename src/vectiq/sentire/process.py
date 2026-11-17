"""Supervise the Sentire process: start, keep its output, restart it if it stops, stop it cleanly."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import signal
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("vectiq.sentire")
NPUB = re.compile(r"\b(npub1[02-9ac-hj-np-z]{58})\b")


class Sidecar:
    def __init__(self, binary: Path, config: Path, env: dict[str, str], *, keep: int = 300,
                 on_line: Callable[[str], None] | None = None):
        self.binary, self.config, self.env = binary, config, env
        self.lines: deque[str] = deque(maxlen=keep)
        self.on_line = on_line
        self.proc: asyncio.subprocess.Process | None = None
        self.npub = ""
        self.started_at = 0.0
        self.restarts = 0
        self.last_exit: int | None = None
        self.last_error = ""
        self._task: asyncio.Task | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def uptime(self) -> float:
        return time.time() - self.started_at if self.running else 0.0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.get_running_loop().create_task(self._run(), name="sentire")

    async def _run(self) -> None:
        backoff = 5.0
        while not self._stopping:
            began = time.time()
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    str(self.binary), str(self.config), stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL,
                    env={**os.environ, **self.env}, cwd=str(self.config.parent), start_new_session=True)
            except OSError as exc:
                self.last_error = f"couldn't start {self.binary}: {exc}"
                log.error("sentire: %s", self.last_error)
                return
            self.started_at = began
            self._say(f"[vectiq] started Sentire (pid {self.proc.pid})")
            assert self.proc.stdout is not None
            async for raw in self.proc.stdout:
                self._say(raw.decode("utf-8", "replace").rstrip())
            self.last_exit = await self.proc.wait()
            if self._stopping:
                break
            self.restarts += 1
            if self.lines and ("refused" in self.lines[-1] or "unset" in self.lines[-1]):
                self.last_error = self.lines[-1]
            self._say(f"[vectiq] Sentire stopped (exit {self.last_exit}); starting again in {backoff:.0f}s")
            await asyncio.sleep(backoff)
            backoff = 5.0 if time.time() - began > 300 else min(backoff * 2, 300.0)

    def _say(self, line: str) -> None:
        if not line:
            return
        self.lines.append(f"{time.strftime('%H:%M:%S')} {line}")
        if (m := NPUB.search(line)) and "online as" in line:
            self.npub = m.group(1)
        if line.startswith("config refused") or " unset " in line:
            self.last_error = line
        log.info("sentire: %s", line)
        if self.on_line is not None:
            with contextlib.suppress(Exception):
                self.on_line(line)

    async def stop(self, timeout: float = 10.0) -> None:
        self._stopping = True
        proc = self.proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._say("[vectiq] stopped Sentire")

    async def restart(self) -> None:
        await self.stop()
        self.start()
