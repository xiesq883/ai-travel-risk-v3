"""Store an Amap Web Service key in the local app/.env without echo."""

from __future__ import annotations

from getpass import getpass
from pathlib import Path

from dotenv import set_key

APP = Path(__file__).resolve().parents[1]
ENV = APP / ".env"


def main() -> int:
    key = getpass("AMAP_WEB_SERVICE_KEY（输入不显示，留空取消）: ").strip()
    if not key:
        print("未修改。")
        return 1
    if any(char.isspace() for char in key):
        print("Key 不能包含空白字符，未修改。")
        return 1
    ENV.touch(exist_ok=True)
    set_key(str(ENV), "AMAP_WEB_SERVICE_KEY", key)
    print("已写入本机 app/.env；重启服务后生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
