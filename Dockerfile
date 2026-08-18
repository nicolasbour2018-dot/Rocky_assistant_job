FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ROCKY_STORAGE_DIR=/data \
    DATABASE_URL=sqlite:////data/rocky.db

RUN useradd --create-home --uid 1000 rocky

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

COPY --chown=rocky:rocky . /app
RUN mkdir -p /data && chown -R rocky:rocky /data

USER rocky
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=5)"

CMD ["python", "-m", "streamlit", "run", "dashboard/dashboard_v2.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
