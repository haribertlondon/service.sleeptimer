# -*- coding: utf-8 -*-
"""Kodi bindings for the sleep timer: settings, actuators and activity input."""

import json
import subprocess
import time

import xbmc
import xbmcaddon
import xbmcgui

from . import statemachine as sm

ADDON_ID = "service.sleeptimer"


def _jsonrpc(method, **params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        return json.loads(raw)
    except Exception:
        return {}


class Settings(object):
    """Reads the addon settings and converts them into a Config snapshot."""

    def __init__(self):
        self._addon = xbmcaddon.Addon(ADDON_ID)
        self._cache = None
        self._cached_at = 0.0

    def _get(self):
        a = xbmcaddon.Addon(ADDON_ID)          # re-read: picks up live changes
        
        # Read TV command settings with fallback for dependency issues
        try:
            tv_off_cmd = a.getSettingString("tv_off_command").strip()
        except Exception:
            tv_off_cmd = ""
        
        try:
            tv_on_cmd = a.getSettingString("tv_on_command").strip()
        except Exception:
            tv_on_cmd = ""
        
        return sm.Config(
            enabled=a.getSettingBool("enabled"),
            movie_sleep_timer=a.getSettingInt("movie_sleep_timer") * 60,
            tv_off_timer=a.getSettingInt("tv_off_timer") * 60,
            volume_reduction_percent=a.getSettingInt("volume_reduction_percent"),
            volume_reduction_interval=a.getSettingInt("volume_reduction_interval"),
            notify_on_ramp=a.getSettingBool("notify_on_ramp"),
            tv_off_command=tv_off_cmd,
            tv_on_command=tv_on_cmd,
            stop_grace_period=a.getSettingInt("stop_grace_period"),
            volume_restore_delay=a.getSettingInt("volume_restore_delay"),
        )

    def snapshot(self):
        """Cached for 2s so one tick sees a consistent set of values."""
        now = time.time()
        if self._cache is None or (now - self._cached_at) > 2.0:
            self._cache = self._get()
            self._cached_at = now
        return self._cache

    def invalidate(self):
        self._cache = None

    # raw access for things the machine does not need
    def raw_int(self, key, default=0):
        try:
            return xbmcaddon.Addon(ADDON_ID).getSettingInt(key)
        except Exception:
            return default

    def raw_string(self, key, default=""):
        try:
            return xbmcaddon.Addon(ADDON_ID).getSettingString(key)
        except Exception:
            return default

    def raw_bool(self, key, default=False):
        try:
            return xbmcaddon.Addon(ADDON_ID).getSettingBool(key)
        except Exception:
            return default

    def localize(self, sid):
        return xbmcaddon.Addon(ADDON_ID).getLocalizedString(sid)


class KodiIO(object):
    """
    Implements the actuator protocol expected by SleepTimerMachine.

    Volume changes issued here are marked so that the activity monitor can
    distinguish them from the user turning the knob.  Without that filter the
    ramp would look like user activity and the timer would reset forever.
    """

    def __init__(self, settings, monitor, activity):
        self._s = settings
        self._monitor = monitor
        self._activity = activity
        self._icon = xbmcaddon.Addon(ADDON_ID).getAddonInfo("icon")
        self._name = xbmcaddon.Addon(ADDON_ID).getAddonInfo("name")

    # ---------------------------------------------------------------- logging

    def log(self, msg, force=False):
        if force or self._s.raw_bool("debug_log"):
            xbmc.log("[%s] %s" % (ADDON_ID, msg), xbmc.LOGINFO)
        else:
            xbmc.log("[%s] %s" % (ADDON_ID, msg), xbmc.LOGDEBUG)

    # ----------------------------------------------------------------- volume

    def get_volume(self):
        res = _jsonrpc(
            "Application.GetProperties", properties=["volume", "muted"]
        )
        try:
            return int(res["result"]["volume"])
        except Exception:
            return None

    def set_volume(self, pct):
        pct = max(0, min(100, int(pct)))
        self._activity.expect_volume_change(pct)
        _jsonrpc("Application.SetVolume", volume=pct)

    # --------------------------------------------------------------------- TV

    def _run_command(self, command):
        if not command:
            return
        mode = self._s.raw_string("tv_command_mode", "builtin")
        try:
            if mode == "shell":
                try:
                    # Use explicit file descriptors for better compatibility
                    subprocess.Popen(
                        command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        close_fds=True,
                    )
                except AttributeError:
                    # Fallback if DEVNULL/PIPE not available
                    subprocess.Popen(command, shell=True)
            else:
                xbmc.executebuiltin(command)
        except Exception as exc:
            self.log("command failed (%s): %s" % (command, exc), force=True)

    def tv_off(self):
        # IR blaster: this is a TOGGLE button.  Must be sent exactly once per
        # off-transition; the machine guarantees that via tv_is_off.
        self._run_command(self._s.raw_string("tv_off_command"))

    def tv_on(self):
        cmd = self._s.raw_string("tv_on_command")
        if cmd:
            self._run_command(cmd)
        else:
            # Fallback: deactivating the screensaver triggers CEC wake-up.
            _jsonrpc("GUI.ActivateWindow", window="home")
            xbmc.executebuiltin("CECActivateSource")

    # --------------------------------------------------------------- playback

    def stop_playback(self):
        _jsonrpc("Player.Stop", playerid=1)
        _jsonrpc("Player.Stop", playerid=0)
        xbmc.executebuiltin("PlayerControl(Stop)")

    def activate_screensaver(self):
        xbmc.executebuiltin("ActivateScreensaver")

    # ------------------------------------------------------------------- misc

    def notify(self, message, seconds=8):
        xbmcgui.Dialog().notification(
            self._name, message, self._icon, int(seconds * 1000), False
        )

    def notify_ramp(self, seconds):
        tpl = self._s.localize(32100) or "Sleeping in %d s - press any key to cancel"
        try:
            message = tpl % seconds
        except TypeError:
            message = "%s (%ds)" % (tpl, seconds)
        self.notify(message, min(seconds, 10))

    def sleep(self, seconds):
        return not self._monitor.waitForAbort(seconds)
