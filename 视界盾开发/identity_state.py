"""模板永久保留，当前身份连续验证；轨迹变化或漏检不继承确认。"""
class IdentityGate:
    def __init__(self, required=5):
        self.required = required
        self.candidate = None
        self.count = 0

    def update(self, candidate):
        if candidate is None:
            self.candidate, self.count = None, 0
            return False
        if candidate != self.candidate:
            self.candidate, self.count = candidate, 1
        else:
            self.count += 1
        return self.count >= self.required
