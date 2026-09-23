# -*- coding: utf-8 -*-
"""Kodi bindings: settings snapshots and actuators."""

import json
import time

import xbmc
import xbmcaddon
import xbmcgui

from . import statemachine as sm
from . import tvpower

ADDON_ID = "service.sleeptimer"


def jsonrpc(method, **params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        return json.loads(xbmc.executeJSONRPC(json.dumps(payload)))
    except Exception:
        return {}


class Settings(object):
    """
    Reads the addon settings.  Every accessor re-opens the Addon object so that
    changes made in the settings dialog are picked up without a restart, and
    every accessor is exception-safe: Kodi raises 'Unknown addon id' while the
    addon is being reloaded, which must never kill the service thread.
    """

    def __init__(self):
        self._cache = None
        self._cached_at = 0.0

    # ----------------------------------------------------------- raw accessors

    @staticmethod
    def _addon():
        return xbmcaddon.Addon(ADDON_ID)

    def raw_int(self, key, default=0):
        try:
            return int(self._addon().getSettingInt(key))
        except Exception:
            return default

    def raw_string(self, key, default=""):
        try:
            return self._addon().getSettingString(key) or default
        except Exception:
            return default

    def raw_bool(self, key, default=False):
        try:
            return bool(self._addon().getSettingBool(key))
        except Exception:
            return default

    def localize(self, sid):
        try:
            return self._addon().getLocalizedString(sid)
        except Exception:
            return ""

    def info(self, key, default=""):
        try:
            return self._addon().getAddonInfo(key) or default
        except Exception:
            return default

    # -------------------------------------------------------------- snapshot

    def _build(self):
        return sm.Config(
            enabled=self.raw_bool("enabled", True),
            movie_sleep_timer=self.raw_int("movie_sleep_timer", 45) * 60,
            tv_off_timer=self.raw_int("tv_off_timer", 0) * 60,
            session_max_timer=self.raw_int("session_max_timer", 0) * 60,
            volume_reduction_percent=self.raw_int("volume_reduction_percent", 7),
            volume_reduction_interval=self.raw_int("volume_reduction_interval", 5),
            notify_on_ramp=self.raw_bool("notify_on_ramp", True),
            tv_off_command=self.raw_string("tv_off_command").strip(),
            tv_on_command=self.raw_string("tv_on_command").strip(),
            stop_grace_period=self.raw_int("stop_grace_period", 60),
            volume_restore_delay=self.raw_int("volume_restore_delay", 5),
        )

    def snapshot(self):
        now = time.time()
        if self._cache is None or (now - self._cached_at) > 2.0:
            self._cache = self._build()
            self._cached_at = now
        return self._cache

    def invalidate(self):
        self._cache = None


class KodiIO(object):
    """
    Actuator implementation for SleepTimerMachine.

    Volume writes are announced to the activity tracker so the ramp is not
    mistaken for the user turning the volume down.
    """

    def __init__(self, settings, monitor, activity):
        self._s = settings
        self._monitor = monitor
        self._activity = activity
        self._tv_off = tvpower.TvPowerOff(settings, self.log)
        self._icon = settings.info("icon")
        self._name = settings.info("name", "Sleep Timer")

    # ---------------------------------------------------------------- logging

    def log(self, msg, force=False):
        level = xbmc.LOGINFO if (force or self._s.raw_bool("debug_log")) \
            else xbmc.LOGDEBUG
        xbmc.log("[%s] %s" % (ADDON_ID, msg), level)

    # ----------------------------------------------------------------- volume

    def get_volume(self):
        res = jsonrpc("Application.GetProperties", properties=["volume"])
        try:
            return int(res["result"]["volume"])
        except Exception:
            return None

    def set_volume(self, pct):
        pct = max(0, min(100, int(pct)))
        self._activity.expect_volume_change(pct)
        jsonrpc("Application.SetVolume", volume=pct)

    # --------------------------------------------------------------------- TV

    def tv_off(self):
        """Start the cancellable off sequence (see tvpower.TvPowerOff)."""
        self._tv_off.send()

    def tv_on(self):
        # Cancel first: a pending retry must never fight the on-command.
        self._tv_off.cancel()
        cmd = self._s.raw_string("tv_on_command").strip()
        mode = self._s.raw_string("tv_command_mode", "shell")
        timeout = max(5, self._s.raw_int("tv_command_timeout", 15))
        if cmd:
            tvpower.run_detached(cmd, mode, self.log, timeout=timeout)
        else:
            xbmc.executebuiltin("CECActivateSource")

    def tv_on_cancel_only(self):
        """Used on entry to Idle: drop any pending off sequence, send nothing."""
        self._tv_off.cancel()

    # --------------------------------------------------------------- playback

    def stop_playback(self):
        res = jsonrpc("Player.GetActivePlayers")
        for p in (res.get("result") or []):
            pid = p.get("playerid")
            if pid is not None:
                jsonrpc("Player.Stop", playerid=pid)
        xbmc.executebuiltin("PlayerControl(Stop)")

    def activate_screensaver(self):
        xbmc.executebuiltin("ActivateScreensaver")

    # ------------------------------------------------------------------- misc

    def notify_ramp(self, seconds):
        tpl = self._s.localize(32100) or \
            "Sleeping in %d s - press any key to cancel"
        try:
            message = tpl % seconds
        except (TypeError, ValueError):
            message = "%s (%ds)" % (tpl, seconds)
        try:
            xbmcgui.Dialog().notification(
                self._name, message, self._icon,
                int(max(3, min(seconds, 15)) * 1000), False,
            )
        except Exception as exc:
            self.log("notification failed: %s" % exc)

    def sleep(self, seconds):
        try:
            return not self._monitor.waitForAbort(seconds)
        except Exception:
            return True

    def shutdown(self):
        self._tv_off.cancel()
