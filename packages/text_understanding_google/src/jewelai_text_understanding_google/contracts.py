"""Safe typed failures for the untrusted understanding boundary."""


class TextUnderstandingError(RuntimeError):
    """Base failure without provider payload or secret detail."""


class TextUnderstandingTimeoutError(TextUnderstandingError):
    pass


class TextUnderstandingUnavailableError(TextUnderstandingError):
    pass


class TextUnderstandingRejectedError(TextUnderstandingError):
    pass


class TextUnderstandingInvalidResponseError(TextUnderstandingError):
    pass
