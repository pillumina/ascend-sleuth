"""evolve 领域错误的共同基类。

各模块的错误仍继承 ``ValueError``（输入不合法）或 ``RuntimeError``（运行期不可用），
调用方照旧按父类区分这两类；加这一层是为了让 CLI 在派发处只兜一次，
新模块的错误不会因为漏进某个 ``except`` 元组而变成 traceback。
"""


class EvolveError(Exception):
    """所有 evolve 领域错误的基类；CLI 在派发处兜底成一条 error 行。"""
