"""Safe authentication and authorization errors."""


class AuthenticationError(RuntimeError):
    pass


class AuthenticationUnavailableError(RuntimeError):
    pass


class AuthorizationDeniedError(RuntimeError):
    pass


class MembershipNotFoundError(RuntimeError):
    pass


class MembershipConflictError(RuntimeError):
    pass


class LastOwnerError(RuntimeError):
    pass
