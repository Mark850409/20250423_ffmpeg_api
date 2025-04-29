# 使用輕量級 Python 映像檔
FROM python:3.9-slim

# 安裝 ffmpeg 與字型支援（必要的字幕轉圖功能）
RUN apt-get update && \
    apt-get install -y ffmpeg fonts-noto-cjk fontconfig && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製並安裝 Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製主要應用程式
COPY main.py .

# 設定啟動 FastAPI 應用
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
