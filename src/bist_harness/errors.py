"""Project-specific exceptions."""


class LLMUnavailableError(RuntimeError):
    """The configured LLM endpoint could not be reached or refused the request."""


class DataUnavailableError(RuntimeError):
    """A data source returned nothing usable for the requested series."""
