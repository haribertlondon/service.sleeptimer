# -*- coding: utf-8 -*-
"""
service.sleeptimer 2.0.0 -- Kodi service entry point.

Drives the SleepTimerMachine on a 1s tick.  Playback detection uses
Player.GetActivePlayers / xbmc.Player rather than Kodi's global idle timer,
which is not dependable; the idle timer is only used as an additional
activity hint.
"""

import time

import xbmc

from resources.lib import activity as act
from resources.lib import kodiio
from resources.lib import statemachine as sm

TICK_SECONDS = 1.0


class Service(object):
    def __init__(self):
        self._settings = kodiio.Settings()
        self._tracker = act.ActivityTracker(self._log)
        self._monitor = act.SleepMonitor(
            self._tracker, self._log, self._settings.invalidate
        )
        self._io = kodiio.KodiIO(self._settings, self._monitor, self._tracker)
        self._player = act.SleepPlayer(self._tracker, self._log)
        self._machine = sm.SleepTimerMachine(
            io=self._io,
            config_provider=self._settings.snapshot,
            clock=time.time,
        )

    # ------------------------------------------------------------------ helpers

    def _log(self, msg, force=False):
        self._io_log(msg, force)

    def _io_log(self, msg, force=False):
        try:
            self._io.log(msg, force=force)
        except AttributeError:
            xbmc.log("[service.sleeptimer] %s" % msg, xbmc.LOGINFO)

    def _is_playing(self):
        """
        True while a relevant player is active -- including while paused, since
        a paused movie is still a watching session.

        Player.GetActivePlayers is the authoritative source; xbmc.Player is
        used as a cheap cross-check because the JSON-RPC call can briefly
        return an empty list during stream changes.
        """
        want = self._settings.raw_string("video_types", "video")
        try:
            res = kodiio._jsonrpc("Player.GetActivePlayers")
            players = res.get("result") or []
        except Exception:
            players = []

        for p in players:
            ptype = p.get("type")
            if want == "any" or ptype == "video":
                return True

        if want == "any":
            return bool(xbmc.Player().isPlaying())
        return bool(xbmc.Player().isPlayingVideo())

    # --------------------------------------------------------------------- run

    def run(self):
        self._io.log("service.sleeptimer 2.0.0 started", force=True)
        self._tracker.reset()

        while not self._monitor.abortRequested():
            try:
                playing = self._is_playing()
                user_activity = self._tracker.consume()
                self._machine.tick(playing, user_activity)
            except Exception as exc:
                self._io.log("tick failed: %r" % exc, force=True)

            if self._monitor.waitForAbort(TICK_SECONDS):
                break

        # Leaving the machine in Idle restores the user's volume on shutdown.
        try:
            if self._machine.state != sm.IDLE:
                self._machine._goto(sm.IDLE)
        except Exception:
            pass
        self._io.log("service.sleeptimer stopped", force=True)


if __name__ == "__main__":
    Service().run()
