class ProtectionState:
    def __init__(self, restore_delay=1.0):
        self.restore_delay = restore_delay
        self.safe_since = None
        self.protecting = True

    def update(self, now, risk):
        if risk:
            self.safe_since = None
            self.protecting = True
        else:
            if self.safe_since is None:
                self.safe_since = now
            if now - self.safe_since >= self.restore_delay:
                self.protecting = False
        return self.protecting
