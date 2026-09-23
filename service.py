# -*- coding: utf-8 -*-
"""
service.sleeptimer 3.0.3 -- Kodi service entry point.

Drives SleepTimerMachine on a 1 s tick.  Playback state comes from
Player.GetActivePlayers with xbmc.Player as a cross-check; Kodi's global idle
timer is used only as an additional activity hint, never as the primary source.
"""

import time

import xbmc

from resources.lib import activity as act
from resources.lib import kodiio
from resources.lib import statemachine as sm

VERSION = "3.0.3"
TICK_SECONDS = 1.0


class Service(object):
    def __init__(self):
        self._settings = kodiio.Settings()
        self._log_early("initialising")
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
        self._last_state = None
        self._last_report = 0.0

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _log_early(msg):
        xbmc.log("[service.sleeptimer] %s" % msg, xbmc.LOGINFO)

    def _log(self, msg, force=False):
        try:
            self._io.log(msg, force=force)
        except Exception:
            self._log_early(msg)

    def _is_playing(self):
        """
        True while a relevant player is active, including while paused, because
        a paused movie is still a watching session.
        """
        want = self._settings.raw_string("video_types", "video")
        try:
            players = kodiio.jsonrpc("Player.GetActivePlayers").get("result") or []
        except Exception:
            players = []

        for p in players:
            if want == "any" or p.get("type") == "video":
                return True

        try:
            player = xbmc.Player()
            return bool(player.isPlaying() if want == "any"
                        else player.isPlayingVideo())
        except Exception:
            return False

    def _heartbeat(self, cfg):
        """
        Periodic progress line, so a log from a failed night immediately shows
        how far the timer got instead of only showing the resets.
        """
        if not self._settings.raw_bool("debug_log"):
            return
        now = time.time()
        interval = max(60, self._settings.raw_int("heartbeat_interval", 300))
        if (now - self._last_report) < interval:
            return
        self._last_report = now
        if self._machine.state == sm.IDLE:
            return
        remaining = cfg.movie_sleep_timer - self._machine.elapsed
        msg = "heartbeat: state=%s t=%.0fs remaining=%.0fs session=%.0fs" % (
            self._machine.state,
            self._machine.elapsed,
            remaining,
            self._machine.session_elapsed,
        )
        if cfg.session_max_timer > 0:
            msg += " cap_remaining=%.0fs" % (
                cfg.session_max_timer - self._machine.session_elapsed
            )
        self._log(msg, force=True)

    # --------------------------------------------------------------------- run

    def run(self):
        self._log("service.sleeptimer %s started" % VERSION, force=True)
        self._tracker.reset()

        while not self._monitor.abortRequested():
            try:
                cfg = self._settings.snapshot()
                playing = self._is_playing()
                user_activity, reason = self._tracker.consume()
                self._machine.tick(playing, user_activity, reason)
                self._heartbeat(cfg)
            except Exception as exc:
                self._log("tick failed: %r" % exc, force=True)

            if self._monitor.waitForAbort(TICK_SECONDS):
                break

        # Restore the user's volume and drop any pending TV-off sequence.
        try:
            if self._machine.state != sm.IDLE:
                self._machine._goto(sm.IDLE)
        except Exception:
            pass
        try:
            self._io.shutdown()
        except Exception:
            pass
        self._log("service.sleeptimer stopped", force=True)


if __name__ == "__main__":
    Service().run()
