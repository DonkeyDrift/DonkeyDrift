"""python -m donkeycar.launcher 入口。

用法:
    python -m donkeycar.launcher [--port 8090] [--host 127.0.0.1]

默认只监听 127.0.0.1（P0 安全补强）；对外监听需显式 ``--host 0.0.0.0``
或设 ``DONKEY_LAUNCHER_HOST``，非本机访问还需携带访问令牌（见
launcher/auth.py）。
"""

import argparse

from .server import run_server


def main():
    parser = argparse.ArgumentParser(
        description="DonkeyDrifter Web Launcher 服务"
    )
    parser.add_argument(
        "--port", type=int, default=8090,
        help="监听端口 (默认: 8090)"
    )
    parser.add_argument(
        "--host", default=None,
        help="监听地址 (默认: 127.0.0.1，仅本机；对外监听请显式传 0.0.0.0 "
             "或设 DONKEY_LAUNCHER_HOST)"
    )
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
