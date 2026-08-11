"""python -m donkeycar.launcher 入口。

用法:
    python -m donkeycar.launcher [--port 8090] [--host 0.0.0.0]
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
        "--host", default="0.0.0.0",
        help="监听地址 (默认: 0.0.0.0)"
    )
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
