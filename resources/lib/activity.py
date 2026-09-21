# -*- coding: utf-8 -*-
"""
Activity detection.

Kodi's global idle timer (xbmc.getGlobalIdleTime()) is not reliable on its own:
it is reset by things that are not user interaction, and on some platforms it
does not react to remote key presses that go straight into the player at all.
We therefore combine three independent sources and latch any of them:

  1. xbmc.Player callbacks  -- onPlayBackPaused / Resumed / SeekChapter /
     onPlayBackSeek / onAVChange / onPlayBackStarted.  This is the primary
     source and covers KodiPlayer.SeekForward, KodiPlayer.Pause etc.
  2. xbmc.Monitor callbacks -- onScreensaverDeactivated, onDPMSDeactivated,
     onNotification for Input.* and Player.* events.
  3. The global idle time, as a fallback: a *drop* in idle time means someone
     pressed something.  Only a drop is meaningful; the absolute value is not.

Volume changes caused by our own ramp are filtered out by comparing against a
short list of expected values.  Without this the ramp would be mistaken for the
user turning the volume down and would reset the timer indefinitely.
"""

import threading
import time

import xbmc


class ActivityTracker(object):
    def __init__(self, log):
        self._log = log
        self._lock = threading.Lock()
        self._flag = False
        self._last_reason = ""
        self._expected_volumes = []
        self._last_idle = 0

    # ------------------------------------------------------------------ latch

    def report(self, reason):
        with self._lock:
            self._flag = True
            self._last_reason = reason
        self._log("activity: %s" % reason)

    def consume(self):
        """Returns True if activity happened since the last call, and clears."""
        self._poll_idle_time()
        with self._lock:
            flag, self._flag = self._flag, False
            return flag

    @property
    def last_reason(self):
        with self._lock:
            return self._last_reason

    def reset(self):
        with self._lock:
            self._flag = False
        self._last_idle = xbmc.getGlobalIdleTime()

    # --------------------------------------------------------- volume filter

    def expect_volume_change(self, value):
        with self._lock:
            self._expected_volumes.append((int(value), time.time()))
            self._expected_volumes = self._expected_volumes[-8:]

    def is_expected_volume(self, value):
        now = time.time()
        with self._lock:
            keep = []
            matched = False
            for val, ts in self._expected_volumes:
                if now - ts > 10.0:
                    continue
                if not matched and val == int(value):
                    matched = True
                    continue
                keep.append((val, ts))
            self._expected_volumes = keep
        return matched

    # ------------------------------------------------------- idle-time source

    def _poll_idle_time(self):
        try:
            idle = xbmc.getGlobalIdleTime()
        except Exception:
            return
        # A decrease means the idle counter was reset -> something was pressed.
        if idle < self._last_idle:
            with self._lock:
                self._flag = True
                self._last_reason = "globalIdleTime reset"
        self._last_idle = idle


class SleepPlayer(xbmc.Player):
    """Player callbacks are the primary, reliable activity source."""

    ACTIVITY_EVENTS = (
        "onPlayBackPaused",
        "onPlayBackResumed",
        "onPlayBackSeek",
        "onPlayBackSeekChapter",
        "onPlayBackSpeedChanged",
    )

    def __init__(self, tracker, log):
        super(SleepPlayer, self).__init__()
        self._tracker = tracker
        self._log = log
        self._playing_video = False

    # ------------------------------------------------------------- lifecycle

    def onAVStarted(self):
        self._playing_video = self.isPlayingVideo()
        self._tracker.report("onAVStarted")

    def onPlayBackStarted(self):
        self._tracker.report("onPlayBackStarted")

    def onPlayBackStopped(self):
        self._playing_video = False

    def onPlayBackEnded(self):
        self._playing_video = False

    def onPlayBackError(self):
        self._playing_video = False

    # -------------------------------------------------------------- activity

    def onPlayBackPaused(self):
        # A pause is an explicit user interaction and therefore resets the
        # timer (per spec), it does not merely suspend it.
        self._tracker.report("onPlayBackPaused")

    def onPlayBackResumed(self):
        self._tracker.report("onPlayBackResumed")

    def onPlayBackSeek(self, time_ms, seek_offset):
        self._tracker.report("onPlayBackSeek(%s)" % seek_offset)

    def onPlayBackSeekChapter(self, chapter):
        self._tracker.report("onPlayBackSeekChapter(%s)" % chapter)

    def onPlayBackSpeedChanged(self, speed):
        self._tracker.report("onPlayBackSpeedChanged(%s)" % speed)


class SleepMonitor(xbmc.Monitor):
    def __init__(self, tracker, log, on_settings_changed):
        super(SleepMonitor, self).__init__()
        self._tracker = tracker
        self._log = log
        self._on_settings_changed = on_settings_changed

    def onSettingsChanged(self):
        self._log("settings changed")
        self._on_settings_changed()

    def onScreensaverDeactivated(self):
        # The user woke Kodi up; this also switches the TV on via CEC.
        self._tracker.report("onScreensaverDeactivated")

    def onDPMSDeactivated(self):
        self._tracker.report("onDPMSDeactivated")

    def onNotification(self, sender, method, data):
        if method in ("Player.OnSeek", "Player.OnPause", "Player.OnResume",
                      "Player.OnSpeedChanged", "Player.OnPlay"):
            self._tracker.report("notification %s" % method)
        elif method == "Application.OnVolumeChanged":
            # Only count it when it was not our own ramp step.
            volume = None
            try:
                import json
                volume = json.loads(data).get("volume")
            except Exception:
                pass
            if volume is None or not self._tracker.is_expected_volume(volume):
                self._tracker.report("user volume change (%s)" % volume)
            else:
                self._log("ignored own volume change (%s)" % volume)
