class ArbitrageError(Exception):
    """Base class for errors shown to the user without a traceback."""


class ConfigError(ArbitrageError):
    """Missing credentials, bad config file or bad input file."""


class SourceError(ArbitrageError):
    """A marketplace or supplier API call failed."""
