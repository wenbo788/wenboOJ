# 使用官方 Python 镜像作为基础镜像
#FROM python:3.13-slim
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.13-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
# fonts-wqy-microhei：图床水印要用中文字体（纯文字水印，无需 logo 素材）
RUN apt-get update && apt-get install -y \
    curl \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv (更快的 Python 包管理器)
RUN pip install --no-cache-dir uv

# 复制项目文件
COPY pyproject.toml uv.lock ./

# 使用 uv 安装依赖
RUN uv sync --frozen --no-dev

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p logs static/uploads

# 暴露端口
EXPOSE 8000

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 启动命令：先执行数据库迁移，再启动服务
#
# uvicorn 参数为什么这么配（对着「被打时别把连接堆死」来的）：
#   --limit-concurrency 256  超过并发直接快速 503，而不是无限排队；
#                            应用层 app/core/guard.py 在 64 就先行削峰，这里是兜底
#   --backlog 2048           内核 accept 队列长度，显式写出来便于运维调参
#   --timeout-keep-alive 15  空闲 keepalive 连接尽快回收，防连接堆积吃满 FD
#   --no-server-header       不回显 uvicorn 版本（少给扫描器信息）
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --limit-concurrency 256 --backlog 2048 --timeout-keep-alive 15 --no-server-header"]
