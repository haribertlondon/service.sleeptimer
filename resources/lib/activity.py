# -*- coding: utf-8 -*-
"""
Activity detection.

The central distinction, and the bug that kept the timer alive all night in
2.0.0/3.0.x: *the player doing something* is not *the user doing something*.

Kodi auto-advances playlists.  Every new item fires onPlayBackStarted,
onAVStarted and Player.OnPlay.  Treating those as user activity means that with
20-minute files a 45-minute timer can never expire -- it gets reset every 20
minutes forever.  Playback start therefore only STARTS a session (from Idle);
inside a running session it is ignored.

Genuine user activity (resets the timer):
    seek, seek-chapter, pause, resume, speed change,
    user volume change, screensaver/DPMS deactivation,
    keymap-driven actions, a *drop* in the global idle time

Not user activity:
    onPlayBackStarted / onAVStarted / Player.OnPlay  (playlist advance)
    volume writes performed by the ramp itself
"""

import json
import threading
import time

import xbmc

# Player events that merely indicate the player moved on by itself.
PLAYBACK_LIFECYCLE = ("onPlayBackStarted", "onAVStarted", "Player.OnPlay")


class ActivityTracker(object):
    def __init__(self, log):
        self._log = log
        self._lock = threading.Lock()
        self._flag = False
        self._reason = ""
        self._expected_volumes = []
        self._last_idle = 0

    # ------------------------------------------------------------------ latch

    def report(self, reason):
        """Report GENUINE user activity."""
        with self._lock:
            self._flag = True
            self._reason = reason
        self._log("activity: %s" % reason)

    def note(self, reason):
        """Log something that is explicitly NOT user activity."""
        self._log("ignored (not user activity): %s" % reason)

    def consume(self):
        """Returns (flag, reason) for activity since the last call, and clears."""
        self._poll_idle_time()
        with self._lock:
            flag, self._flag = self._flag, False
            reason, self._reason = self._reason, ""
            return flag, reason

    def reset(self):
        with self._lock:
            self._flag = False
            self._reason = ""
        try:
            self._last_idle = xbmc.getGlobalIdleTime()
        except Exception:
            self._last_idle = 0

    # --------------------------------------------------------- volume filter

    def expect_volume_change(self, value):
        with self._lock:
            self._expected_volumes.append((int(value), time.time()))
            self._expected_volumes = self._expected_volumes[-16:]

    def is_expected_volume(self, value):
        now = time.time()
        with self._lock:
            keep = []
            matched = False
            for val, ts in self._expected_volumes:
                if now - ts > 15.0:
                    continue
                if not matched and val == int(value):
                    matched = True
                    continue
                keep.append((val, ts))
            self._expected_volumes = keep
        return matched

    # ------------------------------------------------------- idle-time source

    def _poll_idle_time(self):
        """
        Kodi's global idle timer is not dependable on its own, so only a
        *decrease* is used as a hint.  The absolute value is ignored.
        """
        try:
            idle = xbmc.getGlobalIdleTime()
        except Exception:
            return
        if idle < self._last_idle:
            with self._lock:
                self._flag = True
                self._reason = "globalIdleTime reset"
        self._last_idle = idle


class SleepPlayer(xbmc.Player):
    def __init__(self, tracker, log):
        super(SleepPlayer, self).__init__()
        self._tracker = tracker
        self._log = log

    # --- lifecycle: NOT user activity ------------------------------------

    def onPlayBackStarted(self):
        self._tracker.note("onPlayBackStarted (playlist advance)")

    def onAVStarted(self):
        self._tracker.note("onAVStarted")

    def onPlayBackEnded(self):
        self._tracker.note("onPlayBackEnded")

    def onPlayBackStopped(self):
        self._tracker.note("onPlayBackStopped")

    def onPlayBackError(self):
        self._tracker.note("onPlayBackError")

    # --- genuine interaction ---------------------------------------------

    def onPlayBackPaused(self):
        # Per spec a pause is an explicit interaction and resets the timer.
        self._tracker.report("pause")

    def onPlayBackResumed(self):
        self._tracker.report("resume")

    def onPlayBackSeek(self, time_ms, seek_offset):
        self._tracker.report("seek(%s)" % seek_offset)

    def onPlayBackSeekChapter(self, chapter):
        self._tracker.report("seekChapter(%s)" % chapter)

    def onPlayBackSpeedChanged(self, speed):
        self._tracker.report("speedChanged(%s)" % speed)


class SleepMonitor(xbmc.Monitor):
    ACTIVITY_NOTIFICATIONS = (
        "Player.OnSeek",
        "Player.OnPause",
        "Player.OnResume",
        "Player.OnSpeedChanged",
    )

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
        self._tracker.report("screensaverDeactivated")

    def onDPMSDeactivated(self):
        self._tracker.report("dpmsDeactivated")

    def onNotification(self, sender, method, data):
        if method in self.ACTIVITY_NOTIFICATIONS:
            self._tracker.report(method)
            return

        if method == "Player.OnPlay":
            self._tracker.note("Player.OnPlay (playlist advance)")
            return

        if method == "Application.OnVolumeChanged":
            volume = None
            try:
                volume = json.loads(data).get("volume")
            except Exception:
                pass
            if volume is None or not self._tracker.is_expected_volume(volume):
                self._tracker.report("volumeChange(%s)" % volume)
            else:
                self._log("ignored own volume change (%s)" % volume)
            return

        # The addon's own keymap sends this when any remote key is pressed.
        if method == "Other.sleeptimer_activity":
            self._tracker.report("keypress")
