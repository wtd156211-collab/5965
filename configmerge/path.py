"""嵌套路径的语法解析与默认值树校验。

路径用点号分段，数组元素用方括号下标：

    server.port
    pools[1].size
    matrix[0][1]

解析结果是段元组：字符串为对象键、整数为数组下标。
语法不合法报 BAD_PATH；对照默认值树走不通报 UNKNOWN_PATH。
"""

from .errors import BAD_PATH, UNKNOWN_PATH, ConfigError

_STOPPERS = ".["


def parse(text, display=None):
    """只解析语法，返回段元组。display 用于报错时展示完整路径。"""
    shown = text if display is None else display
    if not isinstance(text, str) or text == "":
        raise ConfigError(BAD_PATH, f"path={shown}")

    segments = []
    i = 0
    n = len(text)
    need_key = True

    while i < n:
        ch = text[i]
        if ch == ".":
            if i == 0 or need_key:
                raise ConfigError(BAD_PATH, f"path={shown}")
            need_key = True
            i += 1
        elif ch == "[":
            if i == 0 or need_key:
                raise ConfigError(BAD_PATH, f"path={shown}")
            end = text.find("]", i + 1)
            if end == -1:
                raise ConfigError(BAD_PATH, f"path={shown}")
            digits = text[i + 1:end]
            if digits == "" or not digits.isdigit():
                raise ConfigError(BAD_PATH, f"path={shown}")
            segments.append(int(digits))
            i = end + 1
            need_key = False
        elif ch == "]":
            raise ConfigError(BAD_PATH, f"path={shown}")
        else:
            end = i
            while end < n and text[end] not in _STOPPERS:
                if text[end] == "]":
                    raise ConfigError(BAD_PATH, f"path={shown}")
                end += 1
            segments.append(text[i:end])
            i = end
            need_key = False

    if need_key:
        raise ConfigError(BAD_PATH, f"path={shown}")
    return tuple(segments)


def resolve(text, root, cache=None, display=None):
    """解析路径并从 root 走一遍，返回 (段元组, 终点节点)。

    cache 可选：以路径文本为键缓存段元组，避免重复解析同一文本。
    """
    shown = text if display is None else display
    segments = cache.get(text) if cache is not None else None
    if segments is None:
        segments = parse(text, display)
        if cache is not None:
            cache[text] = segments

    node = root
    for segment in segments:
        if isinstance(segment, int):
            if not isinstance(node, list) or segment >= len(node):
                raise ConfigError(UNKNOWN_PATH, f"path={shown}")
            node = node[segment]
        else:
            if not isinstance(node, dict) or segment not in node:
                raise ConfigError(UNKNOWN_PATH, f"path={shown}")
            node = node[segment]
    return segments, node


def walk(text, root):
    """按路径走默认值树，返回终点节点。"""
    return resolve(text, root)[1]


def to_text(segments):
    """段元组还原成路径文本（规范形式）。"""
    parts = []
    for segment in segments:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            if parts:
                parts.append(".")
            parts.append(segment)
    return "".join(parts)
