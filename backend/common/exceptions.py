class RefineryException(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

class FileTooLargeException(RefineryException):
    def __init__(self):
        super().__init__("ERR_FILE_TOO_LARGE", "File size exceeds limit")
