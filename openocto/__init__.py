"""OpenOcto — open-source personal AI assistant constructor with voice control."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("openocto-dev")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"
