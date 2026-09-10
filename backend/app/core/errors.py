class AppError(Exception):
    def __init__(self, *, status_code: int, code: str, detail: str) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        super().__init__(detail)


class ResourceNotFoundError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=404, code="NOT_FOUND", detail=detail)


class PermissionDeniedError(AppError):
    def __init__(self, detail: str = "Not enough permissions") -> None:
        super().__init__(status_code=403, code="FORBIDDEN", detail=detail)


class ConflictError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, code="CONFLICT", detail=detail)


class InvalidTransitionError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, code="INVALID_TRANSITION", detail=detail)

