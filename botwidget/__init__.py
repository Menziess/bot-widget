"""Bot Widget: an animated desktop face for OpenBot and Grok Bot."""

try:
    from botwidget._version import __version__
except ImportError:  # a checkout that was never installed, so there is no baked-in version
    __version__ = "0.0.0+unknown"

from botwidget.system.a11y import link_system_gi

link_system_gi()
