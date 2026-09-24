"""错误类型与错误码。"""


class ConfigError(Exception):
    """加载 / 合并 / 解析引用阶段的错误。

    code   错误码（BAD_PATH / UNKNOWN_PATH / BAD_REF / UNKNOWN_REF / CYCLE）
    detail 不含逗号的明细，直接拼进 ``error,<code>,<detail>`` 输出
    """

    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def render(self):
        return f"error,{self.code},{self.detail}"
