from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    # Single source of truth: the version in pyproject.toml
    __version__ = version("dynamic-pi4b-fan")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0+unknown"
