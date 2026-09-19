# -*- coding: utf-8 -*-

"""Key-press trigger for the Sleep Timer service addon.

This script is invoked by Kodi's keymap system (e.g. when PageUp is
pressed).  It writes a signal file that the running Sleep Timer service
picks up on its next check cycle to:

  1. Reset the idle timer (Alternative mode).
  2. Run the configured custom command immediately.

Usage in a keymap XML::

    <pageup>RunScript(special://home/addons/service.sleeptimer/trigger_key.py)</pageup>
"""

import os
import sys

# Allow importing from the addon directory itself
_addon_dir = os.path.dirname(os.path.abspath(__file__))
if _addon_dir not in sys.path:
    sys.path.insert(0, _addon_dir)

from service import write_signal, _log  # noqa: E402

_log("trigger_key.py invoked — writing signal file")
write_signal()
