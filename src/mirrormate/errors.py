class MirrorMateError(Exception):
    """A user-facing MirrorMate error."""

    exit_code = 4


class UsageError(MirrorMateError):
    exit_code = 2


class UnavailableError(MirrorMateError):
    exit_code = 3


class PermissionDeniedError(MirrorMateError):
    exit_code = 77


class CatalogError(MirrorMateError):
    exit_code = 2
