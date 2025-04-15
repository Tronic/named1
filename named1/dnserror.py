class WontResolve(LookupError):
    def __init__(self, message, exceptions=None):
        super().__init__(message)
        self.exceptions = exceptions

    def __str__(self):
        return super().__str__() + "".join(f"\n  {e!r}" for e in self.exceptions or [])
