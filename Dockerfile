FROM python:3.9-slim

# 安裝 FFmpeg 和必要的字型包
RUN apt-get update && \
    apt-get install -y ffmpeg \
                       fonts-liberation \
                       fonts-noto-cjk \
                       fonts-dejavu \
                       fontconfig && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製需要的檔案
COPY requirements.txt .
COPY app/ ./app/

# 安裝 Python 套件
RUN pip install --no-cache-dir -r requirements.txt

# 建立暫存目錄
RUN mkdir temp

# 更新字型快取
RUN fc-cache -fv

# 設定環境變數
ENV PYTHONPATH=/app
ENV FONTCONFIG_PATH=/etc/fonts
ENV PYTHONIOENCODING=utf8

# 啟動服務
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]