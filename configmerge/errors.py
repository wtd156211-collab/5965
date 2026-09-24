"""错误类型与错误码。"""

# 错误码（顺序即检查顺序的优先级）
BAD_PATH = "BAD_PATH"
UNKNOWN_PATH = "UNKNOWN_PATH"
BAD_REF = "BAD_REF"
UNKNOWN_REF = "UNKNOWN_REF"
CYCLE = "CYCLE"


class ConfigError(Exception):
    """所有配置库错误的基类。

    code: 错误码；detail: 不含逗号的说明文本。
    """

    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")

    def line(self):
        """输出为 ``error,<code>,<detail>`` 一行。"""
        return f"error,{self.code},{self.detail}"
