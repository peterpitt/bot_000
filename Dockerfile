# 星際智囊團工作台：純 Python 標準函式庫，無需安裝套件
# Docker Hub 被限流時可改用鏡像：--build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.12-slim
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8066

WORKDIR /app
RUN useradd --create-home --uid 10001 app

COPY consultancy ./consultancy
COPY prompts ./prompts
COPY web ./web

USER app
EXPOSE 8066

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8066'), timeout=2)"

CMD ["python", "-m", "consultancy", "serve"]
