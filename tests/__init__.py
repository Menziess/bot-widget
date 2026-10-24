# Ensure tests always run in offscreen mode regardless of desktop environment
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
