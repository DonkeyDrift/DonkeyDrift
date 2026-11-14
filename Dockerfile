# P0.3 安全重写（2026-10-12）：旧镜像 python:3.6（已 EOL）+ 引用不存在的
# setup.py/[tf] extra（照现状根本构建不过），且 Jupyter 空密码 + 空 token
# 直接绑 0.0.0.0（等于匿名 RCE）。新镜像：
#   - python:3.11-slim（setup.cfg 声明 >=3.10,<3.13）
#   - 按 setup.cfg 真实 extras 安装（[pc,dev]），先装依赖后拷代码吃层缓存
#   - Jupyter 必须持令牌启动：JUPYTER_TOKEN 环境变量注入，缺省构建机上
#     生成随机令牌打到日志；绝不空密码/空 token，绝不 --allow-root
#   - 非 root 用户 donkey 运行
FROM python:3.11-slim

WORKDIR /app

# av/opencv/pillow 等 manylinux wheel 的运行时共享库
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖再 COPY 全量代码：改代码不重装依赖层。editable 安装让
# /app/donkeycar 即导入源（与旧镜像一致：代码更新无需重跑 pip install）
COPY setup.cfg pyproject.toml README.md MANIFEST.in /app/
COPY donkeycar /app/donkeycar
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -e ".[pc,dev]" \
    && pip install --no-cache-dir notebook

COPY . /app

# 非 root 运行；home 供 jupyter 写配置/工作目录
RUN useradd --create-home --uid 1000 donkey \
    && chown -R donkey:donkey /app
USER donkey

# 容器内服务要靠端口映射暴露，后端显式对外监听（隔离边界是容器本身，
# 真正的门禁是 token 鉴权——对外访问仍必须 ?token=/Bearer）。
ENV DRIVE_WEB_HOST=0.0.0.0

# 8000: Web UI 后端；8888: Jupyter
EXPOSE 8000 8888

# 启动 Jupyter Notebook：令牌必须非空——JUPYTER_TOKEN 缺省时在启动
# 机上生成随机令牌并打到日志（docker logs 可取），绝不空密码/空 token。
CMD TOKEN="${JUPYTER_TOKEN:-$(python -c 'import secrets; print(secrets.token_urlsafe(24))')}"; \
    if [ -z "$TOKEN" ]; then echo 'JUPYTER_TOKEN 不能为空' >&2; exit 1; fi; \
    echo "Jupyter 启动，访问令牌: $TOKEN"; \
    exec jupyter notebook --no-browser --ip=0.0.0.0 --port=8888 \
        --ServerApp.root_dir=/app \
        --ServerApp.token="$TOKEN" \
        --ServerApp.password=''
