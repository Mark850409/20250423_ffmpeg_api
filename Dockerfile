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
COPY . .

# 建立暫存目錄
RUN mkdir -p /app/temp && chmod 777 /app/temp

# 暴露端口（配合環境變數）
EXPOSE 8000

# 設定環境變數
ENV PORT=8000

# 設定啟動 FastAPI 應用
CMD ["python", "main.py"]
