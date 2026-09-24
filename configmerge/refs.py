"""引用解析：在最终合并结果上把 ``${路径}`` 替换成目标当前的值。

解析顺序：按默认值树的键顺序（深度优先）逐个解析引用；每个引用沿
「引用 -> 引用」链走，链上记录的是**目标**路径，第一个重复出现的
目标即环的起点（所以 ``a->b->c->a`` 报成 ``b->c->a->b``）。
解析结果按路径记忆化，每个节点只解析一次。
"""

from .errors import ConfigError
from .paths import MISSING, canonical, lookup, parse_path


def classify(value):
    """字符串分类：('ref', 内层路径) / ('bad', None) / ('plain', None)。

    只有整串形如 ``${路径}`` 才算引用；以 ``${`` 开头但不完整的是
    BAD_REF；``${`` 出现在字符串中间按普通字符串处理。
    """
    if not isinstance(value, str) or not value.startswith("${"):
        return ("plain", None)
    if len(value) > 3 and value.endswith("}") and value.find("}") == len(value) - 1:
        return ("ref", value[2:-1])
    return ("bad", None)


def collect_refs(tree, refs, path=()):
    """按树序收集所有引用节点；遇到 BAD_REF 立即抛错。"""
    if isinstance(tree, dict):
        for key, value in tree.items():
            collect_refs(value, refs, path + (key,))
    elif isinstance(tree, list):
        for index, value in enumerate(tree):
            collect_refs(value, refs, path + (index,))
    else:
        kind, inner = classify(tree)
        if kind == "bad":
            raise ConfigError("BAD_REF", f"value={tree}")
        if kind == "ref":
            refs[path] = inner


class RefResolver:
    def __init__(self, tree, refs):
        self.tree = tree
        self.refs = refs                # 路径元组 -> 引用内层字符串
        self.memo = {}                  # 路径元组 -> 解析后的值
        self.resolving = set()          # 正在解析的路径（挡穿过容器的环）
        self._target_cache = {}         # 引用内层字符串 -> 段元组（解析结果缓存）

    def resolve_all(self):
        for path in list(self.refs):
            if path not in self.memo:
                self._final_value(path)

    def _parse_target(self, inner):
        cached = self._target_cache.get(inner)
        if cached is not None:
            return cached
        try:
            segments = parse_path(inner)
        except ConfigError:
            segments = None
        self._target_cache[inner] = segments
        return segments

    def _final_value(self, path):
        if path in self.memo:
            return self.memo[path]
        node = lookup(self.tree, path)
        if path in self.refs:
            return self._resolve_ref(path)
        if isinstance(node, dict):
            self.resolving.add(path)
            try:
                value = {key: self._final_value(path + (key,)) for key in node}
            finally:
                self.resolving.discard(path)
        elif isinstance(node, list):
            self.resolving.add(path)
            try:
                value = [self._final_value(path + (i,)) for i in range(len(node))]
            finally:
                self.resolving.discard(path)
        else:
            value = node
        self.memo[path] = value
        return value

    def _resolve_ref(self, start):
        """沿引用链走。chain 记录经过的引用节点，targets 记录链上的
        目标路径；目标第一次重复时，从它第一次出现的位置到链尾再
        接上它，就是环。"""
        chain = [start]
        self.resolving.add(start)
        seen = {}
        targets = []
        current = start
        while True:
            inner = self.refs[current]
            segments = self._parse_target(inner)
            if segments is None:
                raise ConfigError("UNKNOWN_REF", f"ref={inner}")
            if lookup(self.tree, segments, MISSING) is MISSING:
                raise ConfigError("UNKNOWN_REF", f"ref={inner}")
            if segments in self.memo:
                value = self.memo[segments]
                break
            if segments in seen:
                cycle = targets[seen[segments]:] + [segments]
                detail = "->".join(canonical(p) for p in cycle)
                raise ConfigError("CYCLE", detail)
            if segments in self.refs:
                seen[segments] = len(targets)
                targets.append(segments)
                chain.append(segments)
                current = segments
                continue
            if segments in self.resolving:
                # 穿过对象/数组绕回来的环
                cycle = targets + [segments]
                cycle.append(cycle[0])
                detail = "->".join(canonical(p) for p in cycle)
                raise ConfigError("CYCLE", detail)
            value = self._final_value(segments)
            break
        for path in chain:
            self.resolving.discard(path)
            self.memo[path] = value
        return value


def substitute(node, refs, memo, path=()):
    """把树里的引用节点替换成解析后的值，其余结构原样保留。"""
    if isinstance(node, dict):
        return {key: substitute(value, refs, memo, path + (key,)) for key, value in node.items()}
    if isinstance(node, list):
        return [substitute(value, refs, memo, path + (i,)) for i, value in enumerate(node)]
    if path in refs:
        return memo[path]
    return node
