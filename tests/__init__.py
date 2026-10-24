# Ensure tests always run in offscreen mode, even when the desktop session
# already exports QT_QPA_PLATFORM (setdefault would then be a no-op)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
