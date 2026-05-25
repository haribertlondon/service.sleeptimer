# -*- coding: utf-8 -*-

""" Service Sleep Timer  (c)  2015 enen92, Solo0815

# This program is free software; you can redistribute it and/or modify it under the terms
# of the GNU General Public License as published by the Free Software Foundation;
# either version 2 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program;
# if not, see <http://www.gnu.org/licenses/>.


"""

import datetime
import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import json
import os

addon_id = 'service.sleeptimer'
selfAddon = xbmcaddon.Addon(addon_id)
datapath = xbmcvfs.translatePath(selfAddon.getAddonInfo('profile'))
addonfolder = xbmcvfs.translatePath(selfAddon.getAddonInfo('path'))

__version__ = selfAddon.getAddonInfo('version')

# Functions:
def translate(text):
    return selfAddon.getLocalizedString(text)

def _log( message ):
    xbmc.log(addon_id + ": " + str(message), level=xbmc.LOGDEBUG)
    
def _debug( message, debug ):
    if debug == 'true':
        _log ( "DEBUG: " + str(message) )

# print the actual playing file in DEBUG-mode
def print_act_playing_file(debug):
    if debug == 'true':
        actPlayingFile = xbmc.Player().getPlayingFile()
        _log (str(actPlayingFile))

# wait for abort - xbmc.sleep or time.sleep doesn't work
# and prevents Kodi from exiting
def do_next_check( monitor, iTimeToWait, debug ):
    if debug == 'true':
        _log ( "DEBUG: next check in " + str(iTimeToWait) + " min" )
    if monitor.waitForAbort(int(iTimeToWait)*60):
        return True
    return False

def get_kodi_time():
    am_pm = xbmc.getInfoLabel('System.Time(xx)').lower()
    system_time = xbmc.getInfoLabel('System.Time(hh:mm)')
    hour = int(system_time.split(':')[0])
    minute = system_time.split(':')[1]
    if am_pm == 'pm':
        if hour != 12:
            hour = hour + 12
    elif am_pm == 'am':
        if hour == 12:
            hour = 0
    # Zero-pad hour to always produce a 4-digit number (e.g. "0030", "1305")
    time_string = str(hour).zfill(2) + str(minute)
    return int(time_string)

def should_i_supervise(kodi_time, supervise_start_time, supervise_end_time, debug):
    if selfAddon.getSetting('supervision_mode') == '0' or debug == 'true':
        return True
    else:
        if supervise_start_time == 0 and supervise_end_time == 0:
            return True
        elif kodi_time > supervise_start_time:
            if supervise_end_time > supervise_start_time:
                if kodi_time < supervise_end_time:
                    return True
                else:
                    return False
            else:
                supervise_end_time += 2400
                if kodi_time < supervise_end_time:
                    return True
                else:
                    return False
        else:
            if kodi_time < supervise_end_time:
                return True
            else:
                return False


class AlternativeDetectionMode( xbmc.Player ):    

    def __init__( self, *args ):  
        _log ( "Init Alternative mode" )      
        self.resetTime()
        self.lastEnded = None
        
    def getSecondsFromNow(self, x):
        return (datetime.datetime.now()-x).total_seconds()

    def resetTime(self):
        self.lastUserInteractionTime = datetime.datetime.now()
      
    def onPlayBackSeekChapter(self, chapter):
        _log( "onPlayBackSeekChapter" )
        self.resetTime()  
        
    def onPlayBackSeek(self, time, seekOffset):
        _log( "onPlayBackSeek" )
        self.resetTime()

    def onPlayBackResumed( self ):
        # Will be called when xbmc starts playing a file
        _log( "onPlayBackResumed" )
        self.resetTime()

    def onPlayBackPaused( self ):
        # Will be called when xbmc stops playing a file
        _log( "onPlayBackPaused" )
        self.resetTime()

    def onPlayBackStopped( self ):
        # Will be called when user stops xbmc playing a file
        _log( "onPlayBackStopped" )
        self.resetTime()
        
    def onPlayBackStarted( self ):
        # Will be called when user stops xbmc playing a file        
        if self.lastEnded is None:
            _log("onPlayBackStarted: No ended movie detected before => user interaction")
            self.resetTime()
            return
        
        delayFromLastEnded = self.getSecondsFromNow(self.lastEnded)            
        _log( "onPlayBackStarted: Last Ended was detected within " + str(delayFromLastEnded) + "seconds" )
        
        if delayFromLastEnded is not None and delayFromLastEnded < 60:
            _log("onPlayBackStarted: Last movie endend => No user interaction")
            #do nothing
        else:
            _log("onPlayBackStarted: Last movie did not end during 60s => User interaction")
            self.resetTime()
            
        
    def onPlayBackEnded( self ):
        _log( "onPlayBackEnded" )
        _log("Storing last Ended time")
        self.lastEnded = datetime.datetime.now()
        #self.resetTime()
        
    def getGlobalIdleTime(self, debug):
        result = int(self.getSecondsFromNow(self.lastUserInteractionTime))
        
        _debug ( "XBMC        Idle Time " + repr(xbmc.getGlobalIdleTime()), debug)
        _debug ( "Alternative Idle Time " + repr(result), debug )
        return result
        


def getIdleTimeInSeconds(alternativeMode, useAlternativeMode, debug):
    if useAlternativeMode == 'true':
        idle_time = alternativeMode.getGlobalIdleTime(debug)
    else:
        idle_time = xbmc.getGlobalIdleTime()
    return idle_time


def reload_settings():
    """Re-read all settings from the addon. Called on every loop iteration
    to pick up user changes without requiring a Kodi restart."""
    selfAddon = xbmcaddon.Addon(addon_id)
    settings = {
        'debug': selfAddon.getSetting('debug_mode'),
        'check_time': int(selfAddon.getSetting('check_time')),
        'check_time_next': int(selfAddon.getSetting('check_time_next')),
        'time_to_wait': int(selfAddon.getSetting('waiting_time_dialog')),
        'audiochange': selfAddon.getSetting('audio_change'),
        'muteVol': int(selfAddon.getSetting('mute_volume')),
        'audiointervallength': int(selfAddon.getSetting('audio_interval_length')),
        'audio_enable': selfAddon.getSetting('audio_enable'),
        'video_enable': selfAddon.getSetting('video_enable'),
        'max_time_audio': int(selfAddon.getSetting('max_time_audio')),
        'max_time_video': int(selfAddon.getSetting('max_time_video')),
        'enable_screensaver': selfAddon.getSetting('enable_screensaver'),
        'custom_cmd': selfAddon.getSetting('custom_cmd'),
        'cmd': selfAddon.getSetting('cmd'),
        'useAlternativeMode': selfAddon.getSetting('alternativemode'),
    }
    return settings


class service:
    def __init__(self):
        FirstCycle = True
        next_check = False
        monitor = xbmc.Monitor()
        alternativeMode = AlternativeDetectionMode()
        diff_between_idle_and_check_time = None
        curVol = None

        while not monitor.abortRequested():
            # Re-read settings on every iteration so changes take effect immediately
            s = reload_settings()
            debug = s['debug']
            check_time = s['check_time']
            check_time_next = s['check_time_next']
            time_to_wait = s['time_to_wait']
            audiochange = s['audiochange']
            muteVol = s['muteVol']
            audiointervallength = s['audiointervallength']
            enable_audio = s['audio_enable']
            enable_video = s['video_enable']
            maxaudio_time_in_minutes = s['max_time_audio']
            maxvideo_time_in_minutes = s['max_time_video']
            enable_screensaver = s['enable_screensaver']
            custom_cmd = s['custom_cmd']
            cmd = s['cmd']
            useAlternativeMode = s['useAlternativeMode']

            kodi_time = get_kodi_time()
            try:
                supervise_start_time = int(selfAddon.getSetting('hour_start_sup').split(':')[0]+selfAddon.getSetting('hour_start_sup').split(':')[1])
            except ValueError:
                supervise_start_time = 0
            try:
                supervise_end_time = int(selfAddon.getSetting('hour_end_sup').split(':')[0]+selfAddon.getSetting('hour_end_sup').split(':')[1])
            except ValueError:
                supervise_end_time = 0
            proceed = should_i_supervise(kodi_time, supervise_start_time, supervise_end_time, debug)

            # Set iCheckTime from settings (may be overridden below if dialog is cancelled)
            iCheckTime = check_time

            if proceed:
                if FirstCycle:
                    _log ( "started ... (" + str(__version__) + ")" )
                    if debug == 'true':
                        _log ( "DEBUG: ################################################################" )
                        _log ( "DEBUG: Settings in Kodi:" )
                        _log ( 'DEBUG: enable_audio: ' + enable_audio )
                        _log ( "DEBUG: maxaudio_time_in_minutes: " + str(maxaudio_time_in_minutes) )
                        _log ( "DEBUG: enable_video: " + str(enable_video) )
                        _log ( "DEBUG: maxvideo_time_in_minutes: " + str(maxvideo_time_in_minutes) )
                        _log ( "DEBUG: check_time: " + str(iCheckTime) )
                        _log ( "DEBUG: Supervision mode: Always")
                        _log ( "DEBUG: ################################################################" )
                        # Set this low values for easier debugging!
                        _log ( "DEBUG: debug is enabled! Override Settings:" )
                        #enable_audio = 'true'
                        _log ( "DEBUG: -> enable_audio: " + str(enable_audio) )
                        #maxaudio_time_in_minutes = 1
                        _log ( "DEBUG: -> maxaudio_time_in_minutes: " + str(maxaudio_time_in_minutes) )
                        #enable_video = 'true'
                        _log ( "DEBUG: -> enable_video: " + str(enable_video) )
                        #maxvideo_time_in_minutes = 1
                        _log ( "DEBUG: -> maxvideo_time_in_minutes: " + str(maxvideo_time_in_minutes) )
                        #iCheckTime = 1
                        _log ( "DEBUG: -> check_time: " + str(iCheckTime) )
                        _log ( "DEBUG: ----------------------------------------------------------------" )

                    # wait 15s before start to let Kodi finish the intro-movie
                    if monitor.waitForAbort(15):
                        break

                    max_time_in_minutes = -1
                    FirstCycle = False
                
                idle_time = getIdleTimeInSeconds(alternativeMode, useAlternativeMode, debug)
                idle_time_in_minutes = idle_time / 60.0

                if xbmc.Player().isPlaying():

                    if debug == 'true' and max_time_in_minutes == -1:
                        _log ( "DEBUG: max_time_in_minutes before calculation: " + str(max_time_in_minutes) )

                    if next_check:
                        # add "diff_between_idle_and_check_time" to "idle_time_in_minutes"
                        idle_time_in_minutes += int(diff_between_idle_and_check_time)

                    if debug == 'true' and max_time_in_minutes == -1:
                        _log ( "DEBUG: max_time_in_minutes after calculation: " + str(max_time_in_minutes) )

                    if xbmc.Player().isPlayingAudio():
                        if enable_audio == 'true':
                            if debug == 'true':
                                _log ( "DEBUG: enable_audio is true" )
                                print_act_playing_file(debug)
                            what_is_playing = "audio"
                            max_time_in_minutes = maxaudio_time_in_minutes
                        else:
                            _debug ( "Player is playing Audio, but check is disabled", debug )
                            if do_next_check(monitor, iCheckTime, debug):
                                break
                            continue

                    elif xbmc.Player().isPlayingVideo():
                        if enable_video == 'true':
                            if debug == 'true':
                                _log ( "DEBUG: enable_video is true" )
                                print_act_playing_file(debug)
                            what_is_playing = "video"
                            max_time_in_minutes = maxvideo_time_in_minutes
                        else:
                            _debug ( "Player is playing Video, but check is disabled", debug )
                            if do_next_check(monitor, iCheckTime, debug):
                                break
                            continue

                    ### ToDo:
                    # expand it with RetroPlayer for playing Games!!!

                    else:
                        if debug == 'true':
                            _log ( "DEBUG: Player is playing, but no Audio or Video" )
                            print_act_playing_file(debug)
                        what_is_playing = "other"
                        if do_next_check(monitor, iCheckTime, debug):
                            break
                        continue

                    _debug ( "what_is_playing: " + str(what_is_playing), debug )
                    _debug ( "idle_time: '" + str(idle_time) + "s'; idle_time_in_minutes: '" + str(idle_time_in_minutes) + "'", debug )
                    _debug ( "max_time_in_minutes: " + str(max_time_in_minutes), debug )

                    # only display the Progressdialog, if audio or video is enabled AND idle limit is reached

                    # Check if what_is_playing is not "other" and idle time exceeds limit
                    if ( what_is_playing != "other" and idle_time_in_minutes >= max_time_in_minutes ):

                        _debug ( "idle_time exceeds max allowed. Display Progressdialog", debug )

                        msgdialogprogress = xbmcgui.DialogProgress()
                        ret = msgdialogprogress.create(translate(30000),translate(30001))
                        secs=0
                        percent=0
                        # use the multiplier 100 to get better %/calculation
                        increment = 100*100 / time_to_wait
                        cancelled = False
                        while secs < time_to_wait:
                            secs = secs + 1
                            # divide with 100, to get the right value
                            percent = increment*secs/100
                            secs_left = str((time_to_wait - secs))
                            remaining_display = str(secs_left) + " seconds left."
                            msgdialogprogress.update(int(percent), remaining_display)
                            xbmc.sleep(1000)
                            if (msgdialogprogress.iscanceled()):
                                cancelled = True
                                alternativeMode.resetTime()
                                _debug ( "Progressdialog cancelled", debug )
                                break
                        if cancelled == True:
                            iCheckTime = check_time_next
                            _log ( "Progressdialog cancelled, next check in " + str(iCheckTime) + " min" )
                            # set next_check, so that it opens the dialog after "iCheckTime"
                            next_check = True
                            msgdialogprogress.close()
                        else:
                            _log ( "Progressdialog not cancelled: stopping Player" )
                            msgdialogprogress.close()

                            # softmute audio before stop playing
                            # get actual volume
                            curVol = None
                            dct = {}
                            if audiochange == 'true':
                                resp = xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Application.GetProperties", "params": { "properties": [ "volume"] }, "id": 1}')
                                dct = json.loads(resp)

                                if ("result" in dct) and ("volume" in dct["result"]):
                                    curVol = dct["result"]["volume"]
                                    
                                    _debug ( "Original volume value is " + str(curVol), debug )

                                    for i in range(curVol - 1, muteVol - 1, -1):
                                        _debug ( "Reducing volume to " + str(i), debug)
                                        xbmc.executebuiltin('SetVolume(%d,showVolumeBar)' % (i))
                                        # move down slowly ((total mins / steps) * ms in a min)
                                        # (curVol-muteVol) runs the full timer where a user might control their volume via kodi instead of cutting it short when assuming a set volume of 100%
                                        xbmc.sleep(round(audiointervallength / (curVol - muteVol) * 60000))
                                        
                                        #check if user pressed something while audio volume is going down and abort sleep process
                                        idle_time_in_minutes = getIdleTimeInSeconds(alternativeMode, useAlternativeMode, debug) / 60.0
                                        if idle_time_in_minutes < max_time_in_minutes:
                                            _debug ( "User pressed a key while volume is going down. Aborting sleep process", debug )
                                            #set volume back
                                            _debug ( "Setting back original volume " + str(dct["result"]["volume"]), debug)
                                            xbmc.executebuiltin('SetVolume(%d,showVolumeBar)' % (dct["result"]["volume"]))
                                            iCheckTime = check_time_next
                                            _log ( "Progressdialog cancelled, next check in " + str(iCheckTime) + " min" )
                                            # set next_check, so that it opens the dialog after "iCheckTime"
                                            next_check = True
                                            cancelled = True
                                            break
                                    if cancelled:
                                        continue    

                            # stop player anyway
                            if curVol is not None:
                                _debug ( "Waiting before stop, volume=" + str(curVol), debug )
                            else:
                                _debug ( "Waiting before stop (no volume change)", debug )
                            monitor.waitForAbort(5) # wait 5s before stopping

                            if audiochange == 'true':
                                if ("result" in dct) and ("volume" in dct["result"]):                                    
                                    curVol = dct["result"]["volume"]
                                    _debug ( "Reset volume to original value " + str(curVol), debug )
                                    # we can move upwards fast, because there is nothing playing
                                    xbmc.executebuiltin('SetVolume(%d,showVolumeBar)' % (curVol))
                                else:
                                    _debug ( "DID NOT Reset volume to original value (no result in JSON-RPC response)", debug )
                                                            
                            _debug ( "Stopping player...", debug )
                            xbmc.executebuiltin('PlayerControl(Stop)')

                            if enable_screensaver == 'true':
                                _debug ( "Activating screensaver", debug )
                                xbmc.executebuiltin('ActivateScreensaver')

                            # Run a custom cmd after playback is stopped
                            if custom_cmd == 'true':
                                _debug ( "Running custom script", debug )
                                os.system(cmd)
                    else:
                        _debug ( "Playing the stream, time does not exceed max limit", debug )
                else:
                    _debug ( "Not playing any media file", debug )
                    # reset max_time_in_minutes
                    max_time_in_minutes = -1

                diff_between_idle_and_check_time = idle_time_in_minutes - iCheckTime

                if debug == 'true' and next_check:
                    _log ( "DEBUG: diff_between_idle_and_check_time: " + str(diff_between_idle_and_check_time) )

                if do_next_check(monitor, iCheckTime, debug):
                    break
            else:
                if do_next_check(monitor, check_time, debug):
                    break

service()
