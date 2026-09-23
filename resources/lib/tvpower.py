# -*- coding: utf-8 -*-
"""
Cancellable TV power-off worker.

Why this exists
---------------
The IR power button is a TOGGLE: one code both switches the TV on and off.  You
cannot read the TV's state from the IR side, so a naive "send and hope" can
fail, and a naive retry loop is catastrophic -- it toggles the TV off, on, off,
on forever.

The user's original workaround was a shell loop:

    while ! cec-ctl -S | grep -q "Standby"; do
        ir-ctl -S nec:0x408 -d /dev/lirc0
        sleep 30
    done

That has three fatal problems:
  1. It runs outside the addon's control and cannot be cancelled on wake-up.
  2. It re-sends the toggle forever if the verify command never reports
     Standby, which is exactly what happens when CEC goes unresponsive after
     the TV powers down.
  3. Launched with stdout/stderr=PIPE and no reader, it deadlocks as soon as
     cec-ctl fills the 64 KB pipe buffer.

So the retry logic lives here instead: a daemon thread that sends the toggle,
waits, verifies, and gives up after a bounded number of attempts -- and that
can be cancelled instantly when the user wakes up.
"""

import subprocess
import threading


def run_detached(command, mode, log, timeout=None):
    """Fire a command and wait for it.  Output is discarded, never piped."""
    if not command:
        return None
    try:
        if mode == "shell":
            proc = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,   # never PIPE: no reader -> deadlock
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            if timeout is None:
                return proc
            try:
                return proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log("command timed out, killing: %s" % command, force=True)
                _kill(proc, log)
                return None
        else:
            import xbmc
            xbmc.executebuiltin(command)
            return 0
    except Exception as exc:
        log("command failed (%s): %s" % (command, exc), force=True)
        return None


def _kill(proc, log):
    try:
        import os
        import signal
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class TvPowerOff(object):
    """
    Sends the IR toggle, then optionally verifies and retries.

    Verification is a shell command whose exit code 0 means "the TV is off"
    (e.g. `cec-ctl -S | grep -q Standby`).  Without a verify command exactly
    one toggle is sent and that is the end of it -- the safe default for a
    toggle-only button.
    """

    def __init__(self, settings, log):
        self._s = settings
        self._log = log
        self._thread = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public

    def send(self):
        """Start the off sequence.  Cancels any previous one first."""
        self.cancel()
        with self._lock:
            self._cancel = threading.Event()
            self._thread = threading.Thread(
                target=self._worker, args=(self._cancel,), daemon=True
            )
            self._thread.start()

    def cancel(self):
        """
        Stop any in-flight off sequence immediately.  Called on wake-up, so
        that a pending retry can never fight the TV-on command.
        """
        with self._lock:
            thread, cancel = self._thread, self._cancel
            self._thread = None
        if thread is not None and thread.is_alive():
            self._log("cancelling pending TV-off sequence", force=True)
            cancel.set()

    @property
    def busy(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ worker

    def _worker(self, cancel):
        mode = self._s.raw_string("tv_command_mode", "shell")
        off_cmd = self._s.raw_string("tv_off_command").strip()
        verify = self._s.raw_string("tv_off_verify_command").strip()
        retries = max(0, self._s.raw_int("tv_off_max_retries", 3))
        interval = max(5, self._s.raw_int("tv_off_retry_interval", 30))
        cmd_timeout = max(5, self._s.raw_int("tv_command_timeout", 15))

        if not off_cmd:
            self._log("no TV-off command configured", force=True)
            return

        attempts = 1 + (retries if verify else 0)

        for attempt in range(1, attempts + 1):
            if cancel.is_set():
                self._log("TV-off cancelled before attempt %d" % attempt,
                          force=True)
                return

            self._log("sending TV-off toggle (attempt %d/%d)"
                      % (attempt, attempts), force=True)
            run_detached(off_cmd, mode, self._log, timeout=cmd_timeout)

            if not verify:
                # Toggle-only button with no way to check: send exactly once.
                return

            # Wait before verifying, in cancellable slices.
            waited = 0.0
            while waited < interval:
                if cancel.wait(1.0):
                    self._log("TV-off cancelled while waiting", force=True)
                    return
                waited += 1.0

            if cancel.is_set():
                return

            rc = run_detached(verify, "shell", self._log, timeout=cmd_timeout)
            if rc == 0:
                self._log("TV confirmed off", force=True)
                return
            self._log("TV still not off (verify rc=%s)" % rc, force=True)

        self._log(
            "giving up after %d attempt(s); NOT re-sending the toggle, because "
            "another send could switch the TV back on" % attempts,
            force=True,
        )
