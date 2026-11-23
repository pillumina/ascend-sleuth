"""命令行输入的共用解析：内联 JSON 对象与 JSON 文件。

CLI 与评测门禁都要把 ``--scores`` 这类内联 JSON 转成对象；解析规则只有一份，
错误类型由调用方传进来（CLI 用 ``CliError``，门禁用 ``GateError``）。
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional


def json_object(text: Optional[str], name: str, error) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise error(f"{name} is not valid JSON: {exc}") from exc
    if value is not None and not isinstance(value, dict):
        raise error(f"{name} must be a JSON object")
    return value


def read_json(path: Any) -> Any:
    """读一个 JSON 文件；调用方决定把读取错误映射成哪类错误。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))
