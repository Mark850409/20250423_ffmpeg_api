from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
import ffmpeg
import uvicorn
import os
from typing import Optional, List, Dict
import uuid
import shutil
import asyncio
from datetime import datetime
import zipfile
import json
from enum import Enum
import aiofiles
import tempfile
import subprocess

# 任務狀態枚舉
class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# 任務追蹤字典
tasks: Dict[str, Dict] = {}

# 任務結果儲存目錄
TASK_OUTPUT_DIR = "task_outputs"
if not os.path.exists(TASK_OUTPUT_DIR):
    os.makedirs(TASK_OUTPUT_DIR)

app = FastAPI(
    title="FFmpeg 影音處理 API 服務",
    description="提供影片轉檔、圖片合成影片等功能的 API 服務",
    version="1.0.0"
)

# 建立暫存目錄
UPLOAD_DIR = "temp"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

@app.post("/convert", 
    summary="影片格式轉換",
    description="將上傳的影片轉換為指定格式，支援調整解析度和編碼器"
)
async def convert_video(
    file: UploadFile = File(..., description="要轉換的影片檔案"),
    output_format: str = "mp4",
    video_codec: Optional[str] = None,
    audio_codec: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None
):
    """
    影片格式轉換 API
    
    參數說明：
    - file: 要轉換的影片檔案
    - output_format: 輸出格式（預設：mp4）
    - video_codec: 視訊編碼器（可選）
    - audio_codec: 音訊編碼器（可選）
    - width: 輸出影片寬度（可選）
    - height: 輸出影片高度（可選）
    """
    try:
        # 生成唯一的檔案名
        input_filename = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
        input_path = os.path.join(UPLOAD_DIR, input_filename)
        
        # 儲存上傳的檔案
        with open(input_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # 設定輸出檔案名
        output_filename = f"{uuid.uuid4()}.{output_format}"
        output_path = os.path.join(UPLOAD_DIR, output_filename)
        
        # 建立 FFmpeg 串流
        stream = ffmpeg.input(input_path)
        
        # 設定轉檔參數
        stream_params = {}
        if video_codec:
            stream_params['vcodec'] = video_codec
        if audio_codec:
            stream_params['acodec'] = audio_codec
        if width and height:
            stream = ffmpeg.filter(stream, 'scale', width, height)
            
        # 執行轉檔
        stream = ffmpeg.output(stream, output_path, **stream_params)
        ffmpeg.run(stream)
        
        # 回傳轉換後的檔案
        return FileResponse(
            output_path,
            media_type='application/octet-stream',
            filename=f"converted_{file.filename.split('.')[0]}.{output_format}"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # 清理暫存檔案
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)

@app.get("/health",
    summary="服務健康檢查",
    description="檢查 API 服務是否正常運作"
)
async def health_check():
    """
    健康檢查 API
    
    回傳：
    - status: 服務狀態
    """
    return {"status": "healthy"}

@app.post("/create_video",
    summary="圖片合成影片",
    description="將多張圖片和音樂合成為影片，支援多種轉場效果"
)
async def create_video_from_images(
    images: List[UploadFile] = File(..., description="要合成的圖片檔案列表"),
    audio: UploadFile = File(..., description="背景音樂檔案"),
    duration_per_image: float = 5.0,
    output_format: str = "mp4",
    width: Optional[int] = 1920,
    height: Optional[int] = 1080,
    fade_duration: float = 1.0,
    transition_type: str = "fade",
    transition_duration: float = 2.0
):
    """
    圖片合成影片 API
    
    參數說明：
    - images: 要合成的圖片檔案列表
    - audio: 背景音樂檔案
    - duration_per_image: 每張圖片顯示時間（秒）（預設：5秒）
    - output_format: 輸出影片格式（預設：mp4）
    - width: 輸出影片寬度（預設：1920）
    - height: 輸出影片高度（預設：1080）
    - fade_duration: 淡入淡出時間（秒）（預設：1秒）
    - transition_type: 轉場效果類型（預設：fade）
        - fade: 淡入淡出
        - dissolve: 溶解
    - transition_duration: 轉場持續時間（秒）（預設：2秒）
    
    回傳：
    - 合成後的影片檔案
    """
    temp_image_dir = os.path.join(UPLOAD_DIR, str(uuid.uuid4()))
    os.makedirs(temp_image_dir, exist_ok=True)
    output_path = None
    audio_path = None
    
    try:
        # 儲存音樂檔案
        audio_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{os.path.splitext(audio.filename)[1]}")
        with open(audio_path, "wb") as buffer:
            content = await audio.read()
            buffer.write(content)

        # 儲存圖片檔案
        image_files = []
        for i, image in enumerate(images):
            image_path = os.path.join(temp_image_dir, f"image_{i:04d}{os.path.splitext(image.filename)[1]}")
            with open(image_path, "wb") as buffer:
                content = await image.read()
                buffer.write(content)
            image_files.append(image_path)

        # 建立輸出檔案路徑
        output_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.{output_format}")

        # 建立 filter complex 字串
        filter_complex = []
        
        # 處理每張圖片的輸入和轉場效果
        for i, _ in enumerate(image_files):
            # 縮放和填充
            filter_complex.append(f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2[scaled{i}];")
            
            # 根據轉場類型添加不同效果
            if transition_type == "fade":
                if i == 0:
                    filter_complex.append(f"[scaled{i}]fade=t=out:st={duration_per_image-transition_duration}:d={transition_duration}[v{i}];")
                elif i == len(image_files) - 1:
                    filter_complex.append(f"[scaled{i}]fade=t=in:st=0:d={transition_duration}[v{i}];")
                else:
                    filter_complex.append(
                        f"[scaled{i}]fade=t=in:st=0:d={transition_duration},"
                        f"fade=t=out:st={duration_per_image-transition_duration}:d={transition_duration}[v{i}];")
            elif transition_type == "dissolve":
                # 溶解效果
                if i == 0:
                    filter_complex.append(f"[scaled{i}]format=rgba,fade=t=out:st={duration_per_image-transition_duration}:d={transition_duration}:alpha=1[v{i}];")
                elif i == len(image_files) - 1:
                    filter_complex.append(f"[scaled{i}]format=rgba,fade=t=in:st=0:d={transition_duration}:alpha=1[v{i}];")
                else:
                    filter_complex.append(
                        f"[scaled{i}]format=rgba,fade=t=in:st=0:d={transition_duration}:alpha=1,"
                        f"fade=t=out:st={duration_per_image-transition_duration}:d={transition_duration}:alpha=1[v{i}];")

        # 串連所有視頻片段
        video_inputs = ''.join(f'[v{i}]' for i in range(len(image_files)))
        filter_complex.append(f"{video_inputs}concat=n={len(image_files)}:v=1:a=0[outv]")

        # 組合所有 filter complex 命令
        filter_complex_str = ''.join(filter_complex)

        # 建立輸入檔案列表
        input_args = []
        for image_file in image_files:
            input_args.extend(['-loop', '1', '-t', str(duration_per_image), '-i', image_file])
        
        # 加入音訊輸入
        input_args.extend(['-i', audio_path])

        # 執行 FFmpeg 命令
        cmd = [
            'ffmpeg',
            *input_args,
            '-filter_complex', filter_complex_str,
            '-map', '[outv]',
            '-map', f'{len(image_files)}:a',
            '-shortest',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-profile:v', 'high',
            '-crf', '23',            # 控制視頻質量
            '-movflags', '+faststart',  # 支援網路播放
            '-c:a', 'aac',
            '-b:a', '192k',
            '-pix_fmt', 'yuv420p',   # 確保更好的相容性
            '-y',
            output_path
        ]

        # 執行命令
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg error: {stderr.decode()}")

        # 先清理暫存檔案（除了輸出檔案）
        if os.path.exists(temp_image_dir):
            shutil.rmtree(temp_image_dir)
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)

        # 確保輸出檔案存在
        if not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="Output file was not created")

        # 設定正確的 MIME type
        mime_type = {
            'mp4': 'video/mp4',
            'webm': 'video/webm',
            'mov': 'video/quicktime',
            'avi': 'video/x-msvideo'
        }.get(output_format.lower(), 'video/mp4')

        # 生成包含時間戳記的檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"created_video_{timestamp}.{output_format}"

        # 使用 FileResponse 回傳檔案
        response = FileResponse(
            path=output_path,
            media_type=mime_type,
            filename=output_filename,
            headers={
                'Content-Disposition': f'attachment; filename="{output_filename}"',
                'Access-Control-Expose-Headers': 'Content-Disposition'
            }
        )

        # 設定回應完成後才刪除輸出檔案
        response.background = BackgroundTask(lambda: os.remove(output_path) if os.path.exists(output_path) else None)

        return response

    except Exception as e:
        # 發生錯誤時清理所有檔案
        if os.path.exists(temp_image_dir):
            shutil.rmtree(temp_image_dir)
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/add_subtitle",
    summary="為影片加入字幕",
    description="將字幕檔案加入到影片中，支援 SRT 格式字幕檔，可自訂字幕樣式"
)
async def add_subtitle(
    video: UploadFile = File(..., description="要加入字幕的影片檔案"),
    subtitle: UploadFile = File(..., description="字幕檔案（支援 .srt 格式）"),
    output_format: str = "mp4",
    encoding: str = "utf-8",
    # 字型相關設定
    font_name: str = "Arial",
    font_size: int = 24,
    font_color: str = "white",
    font_alpha: float = 1.0,
    # 邊框相關設定
    border_style: int = 3,
    border_size: int = 1,
    border_color: str = "black",
    border_alpha: float = 1.0,
    # 陰影相關設定
    shadow_size: int = 2,
    shadow_color: str = "black",
    shadow_alpha: float = 0.5,
    # 背景相關設定
    background: bool = True,
    background_color: str = "black",
    background_alpha: float = 0.5,
    # 位置相關設定
    margin_vertical: int = 20,
    alignment: int = 2  # 1-9，2為底部置中
):
    """
    為影片加入字幕 API
    
    參數說明：
    - video: 要加入字幕的影片檔案
    - subtitle: 字幕檔案（支援 .srt 格式）
    - output_format: 輸出影片格式（預設：mp4）
    - encoding: 字幕檔案編碼格式（預設：utf-8）
    
    字型相關設定：
    - font_name: 字型名稱（預設：Arial）
    - font_size: 字型大小（預設：24）
    - font_color: 字型顏色（預設：white）
    - font_alpha: 字型透明度（0-1，預設：1.0）
    
    邊框相關設定：
    - border_style: 邊框樣式（1-3，預設：3）
    - border_size: 邊框大小（預設：1）
    - border_color: 邊框顏色（預設：black）
    - border_alpha: 邊框透明度（0-1，預設：1.0）
    
    陰影相關設定：
    - shadow_size: 陰影大小（預設：2）
    - shadow_color: 陰影顏色（預設：black）
    - shadow_alpha: 陰影透明度（0-1，預設：0.5）
    
    背景相關設定：
    - background: 是否顯示背景（預設：True）
    - background_color: 背景顏色（預設：black）
    - background_alpha: 背景透明度（0-1，預設：0.5）
    
    位置相關設定：
    - margin_vertical: 垂直邊距（預設：20）
    - alignment: 對齊方式（1-9，預設：2）
        1: 左下  2: 中下  3: 右下
        4: 左中  5: 中中  6: 右中
        7: 左上  8: 中上  9: 右上
    
    回傳：
    - 加入字幕後的影片檔案（檔名格式：subtitled_video_YYYYMMDD_HHMMSS.mp4）
    
    注意事項：
    1. 字幕檔案必須是 SRT 格式
    2. 字幕檔案的編碼建議使用 UTF-8
    3. 顏色可使用顏色名稱或十六進制碼（如：#FFFFFF）
    4. 透明度範圍為 0-1，0 為完全透明，1 為完全不透明
    """
    try:
        # 生成唯一的檔案名
        video_filename = f"{uuid.uuid4()}{os.path.splitext(video.filename)[1]}"
        video_path = os.path.join(UPLOAD_DIR, video_filename)
        
        subtitle_filename = f"{uuid.uuid4()}{os.path.splitext(subtitle.filename)[1]}"
        subtitle_path = os.path.join(UPLOAD_DIR, subtitle_filename)
        
        output_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.{output_format}")
        
        # 儲存上傳的檔案
        with open(video_path, "wb") as buffer:
            content = await video.read()
            buffer.write(content)
            
        with open(subtitle_path, "wb") as buffer:
            content = await subtitle.read()
            buffer.write(content)

        # 將路徑轉換為適合 FFmpeg 使用的格式
        safe_subtitle_path = subtitle_path.replace('\\', '/').replace(':', '\\:')

        # 設定字幕過濾器（修改後的版本）
        filter_complex = (
            f"subtitles={safe_subtitle_path}"
            f":force_style='"
            f"Fontname={font_name},"
            f"FontSize={font_size},"
            f"PrimaryColour=&H{font_color_to_ass_color(font_color, font_alpha)},"  # 修改顏色轉換
            f"OutlineColour=&H{font_color_to_ass_color(border_color, border_alpha)},"
            f"BackColour=&H{font_color_to_ass_color(background_color, background_alpha)},"
            f"BorderStyle={border_style},"
            f"Outline={border_size},"
            f"Shadow={shadow_size},"
            f"MarginV={margin_vertical},"
            f"Alignment={alignment},"
            f"Bold=1,"  # 加粗
            f"BackColour=&H{font_color_to_ass_color(background_color, background_alpha)}'"  # 背景顏色
        )

        # 執行 FFmpeg 命令
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', filter_complex,
            '-c:v', 'libx264',
            '-c:a', 'copy',
            '-y',
            output_path
        ]

        # 執行命令
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"FFmpeg error: {stderr.decode()}")  # 添加錯誤輸出以便調試
            raise Exception(f"FFmpeg error: {stderr.decode()}")

        # 生成包含時間戳記的檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"subtitled_video_{timestamp}.{output_format}"

        # 使用 FileResponse 回傳檔案
        response = FileResponse(
            path=output_path,
            media_type='video/mp4',
            filename=output_filename
        )

        # 設定回應完成後才刪除暫存檔案
        async def cleanup():
            if os.path.exists(video_path):
                os.remove(video_path)
            if os.path.exists(subtitle_path):
                os.remove(subtitle_path)
            if os.path.exists(output_path):
                os.remove(output_path)

        response.background = BackgroundTask(cleanup)
        
        return response

    except Exception as e:
        # 發生錯誤時清理所有檔案
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(subtitle_path):
            os.remove(subtitle_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        raise HTTPException(status_code=500, detail=str(e))

# 修改顏色轉換函數
def font_color_to_ass_color(color: str, alpha: float = 1.0) -> str:
    """將顏色轉換為 ASS 格式的顏色碼"""
    def rgb_to_bgr(color_hex: str) -> str:
        """將 RGB 顏色轉換為 BGR 格式"""
        if len(color_hex) == 6:
            r, g, b = color_hex[:2], color_hex[2:4], color_hex[4:]
            return f"{b}{g}{r}"
        return color_hex

    # 顏色對照表
    color_map = {
        'white': 'FFFFFF',
        'black': '000000',
        'red': 'FF0000',
        'green': '00FF00',
        'blue': '0000FF',
        'yellow': 'FFFF00',
    }

    # 處理顏色輸入
    if color.lower() in color_map:
        color_hex = color_map[color.lower()]
    elif color.startswith('#'):
        color_hex = color[1:]
    else:
        color_hex = 'FFFFFF'  # 預設白色

    # 轉換 alpha 值（0-1 轉換為 00-FF）
    alpha_hex = format(int(255 * (1 - alpha)), '02X')

    # 轉換為 ASS 格式：AABBGGRR
    return f"{alpha_hex}{rgb_to_bgr(color_hex)}" 

@app.post("/create_waveform",
    summary="產生音訊波形視覺化",
    description="將音訊檔案轉換為波形視覺化影片，支援自訂波形樣式和顏色"
)
async def create_waveform(
    audio: UploadFile = File(..., description="音訊檔案"),
    output_format: str = "mp4",
    width: int = 1920,
    height: int = 1080,
    wave_mode: str = "line",  # line, point, p2p, cline
    wave_color: str = "white",
    background_color: str = "black",
    fps: int = 30,
    duration: Optional[float] = None
):
    """
    產生音訊波形視覺化 API
    
    參數說明：
    - audio: 音訊檔案
    - output_format: 輸出格式（預設：mp4）
    - width: 輸出影片寬度（預設：1920）
    - height: 輸出影片高度（預設：1080）
    - wave_mode: 波形模式（預設：line）
        - line: 線條模式
        - point: 點狀模式
        - p2p: 峰對峰模式
        - cline: 中心線模式
    - wave_color: 波形顏色（預設：white）
    - background_color: 背景顏色（預設：black）
    - fps: 幀率（預設：30）
    - duration: 指定輸出影片長度（可選，預設使用音訊原始長度）
    """
    try:
        # 生成唯一的檔案名
        audio_filename = f"{uuid.uuid4()}{os.path.splitext(audio.filename)[1]}"
        audio_path = os.path.join(UPLOAD_DIR, audio_filename)
        output_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.{output_format}")
        
        # 儲存上傳的音訊檔案
        with open(audio_path, "wb") as buffer:
            content = await audio.read()
            buffer.write(content)

        # 正確的 filter_complex，先產生背景，再疊加波形
        filter_complex = (
            f"color=c={background_color}:s={width}x{height}:d=1[bg];"
            f"[0:a]showwaves=s={width}x{height}:mode={wave_mode}:colors={wave_color}:r={fps}[wave];"
            f"[bg][wave]overlay=format=auto[v]"
        )

        cmd = [
            'ffmpeg',
            '-i', audio_path,
            '-filter_complex', filter_complex,
            '-map', '[v]',
            '-map', '0:a',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-y'
        ]

        # 如果指定了時長，添加時長參數
        if duration:
            cmd.extend(['-t', str(duration)])

        cmd.append(output_path)

        # 執行命令
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg error: {stderr.decode()}")

        # 生成包含時間戳記的檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"waveform_{timestamp}.{output_format}"

        # 回傳檔案
        response = FileResponse(
            path=output_path,
            media_type='video/mp4',
            filename=output_filename
        )

        # 設定回應完成後才刪除暫存檔案
        async def cleanup():
            if os.path.exists(audio_path):
                os.remove(audio_path)
            if os.path.exists(output_path):
                os.remove(output_path)

        response.background = BackgroundTask(cleanup)
        return response

    except Exception as e:
        # 發生錯誤時清理所有檔案
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create_spectrogram",
    summary="產生音訊頻譜視覺化",
    description="將音訊檔案轉換為頻譜視覺化影片，支援自訂頻譜樣式和顏色"
)
async def create_spectrogram(
    audio: UploadFile = File(..., description="音訊檔案"),
    output_format: str = "mp4",
    width: int = 1920,
    height: int = 1080,
    mode: str = "combined",  # combined, separate
    color_mode: str = "intensity",  # intensity, channel
    scale: str = "log",  # lin, log, sqrt
    saturation: float = 1.0,
    win_func: str = "hanning",  # rectangular, hanning, hamming, blackman
    fps: int = 30,
    background_color: str = "black",
    duration: Optional[float] = None
):
    """
    產生音訊頻譜視覺化 API
    
    參數說明：
    - audio: 音訊檔案
    - output_format: 輸出格式（預設：mp4）
    - width: 輸出影片寬度（預設：1920）
    - height: 輸出影片高度（預設：1080）
    - mode: 頻譜模式（預設：combined）
        - combined: 合併通道
        - separate: 分離通道
    - color_mode: 顏色模式（預設：intensity）
        - intensity: 強度
        - channel: 通道
    - scale: 頻率刻度（預設：log）
        - lin: 線性
        - log: 對數
        - sqrt: 平方根
    - saturation: 顏色飽和度（預設：1.0）
    - win_func: 窗函數（預設：hanning）
        - rectangular: 矩形窗
        - hanning: 漢寧窗
        - hamming: 漢明窗
        - blackman: 布萊克曼窗
    - fps: 影片幀率（預設：30）
    - background_color: 背景顏色（預設：black）
    - duration: 指定輸出影片長度（可選，預設使用音訊原始長度）
    """
    try:
        # 生成唯一的檔案名
        audio_filename = f"{uuid.uuid4()}{os.path.splitext(audio.filename)[1]}"
        audio_path = os.path.join(UPLOAD_DIR, audio_filename)
        output_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.{output_format}")
        
        # 儲存上傳的音訊檔案
        with open(audio_path, "wb") as buffer:
            content = await audio.read()
            buffer.write(content)

        # 建立 FFmpeg 命令
        filter_complex = (
            f"[0:a]showspectrum=s={width}x{height}:"
            f"mode={mode}:"
            f"color={color_mode}:"
            f"scale={scale}:"
            f"saturation={saturation}:"
            f"win_func={win_func}:"
            f"fps={fps}[v]"
        )

        cmd = [
            'ffmpeg',
            '-i', audio_path,
            '-filter_complex', filter_complex,
            '-map', '[v]',
            '-map', '0:a',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-y'
        ]

        # 如果指定了時長，添加時長參數
        if duration:
            cmd.extend(['-t', str(duration)])

        cmd.append(output_path)

        # 執行命令
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg error: {stderr.decode()}")

        # 生成包含時間戳記的檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"spectrogram_{timestamp}.{output_format}"

        # 回傳檔案
        response = FileResponse(
            path=output_path,
            media_type='video/mp4',
            filename=output_filename
        )

        # 設定回應完成後才刪除暫存檔案
        async def cleanup():
            if os.path.exists(audio_path):
                os.remove(audio_path)
            if os.path.exists(output_path):
                os.remove(output_path)

        response.background = BackgroundTask(cleanup)
        return response

    except Exception as e:
        # 發生錯誤時清理所有檔案
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create_audio_visualization",
    summary="產生音訊視覺化與多圖背景合成",
    description="將音訊檔案與多張背景圖片合成為視覺化影片，支援波形或頻譜效果"
)
async def create_audio_visualization(
    audio: UploadFile = File(..., description="音訊檔案"),
    backgrounds: List[UploadFile] = File(..., description="多張背景圖片"),
    output_format: str = "mp4",
    width: int = 1920,
    height: int = 1080,
    image_duration: float = 5.0,
    visualization_type: str = "waveform",  # waveform, spectrum
    wave_mode: str = "line",
    wave_color: str = "white",
    spectrum_mode: str = "combined",
    spectrum_color: str = "intensity",
    spectrum_scale: str = "log",
    spectrum_saturation: float = 1.0,
    fps: int = 30,
    opacity: float = 0.8,
    duration: Optional[float] = None
):
    temp_image_dir = os.path.join(UPLOAD_DIR, str(uuid.uuid4()))
    os.makedirs(temp_image_dir, exist_ok=True)
    audio_path = None
    output_path = None
    bg_video_path = None
    try:
        # 儲存音訊檔案
        audio_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{os.path.splitext(audio.filename)[1]}")
        with open(audio_path, "wb") as buffer:
            content = await audio.read()
            buffer.write(content)

        # 儲存多張圖片
        image_files = []
        for i, img in enumerate(backgrounds):
            img_path = os.path.join(temp_image_dir, f"img_{i:04d}{os.path.splitext(img.filename)[1]}")
            with open(img_path, "wb") as buffer:
                content = await img.read()
                buffer.write(content)
            image_files.append(img_path)

        if not image_files:
            raise Exception("未上傳任何背景圖片")

        # 生成背景影片
        bg_video_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.mp4")
        
        # 建立 filter_complex
        filter_parts = []
        
        # 處理每張圖片的縮放
        for i in range(len(image_files)):
            filter_parts.append(f"[{i}:v]scale={width}:{height},setsar=1[scaled{i}]")
        
        # 建立串接指令
        concat_inputs = "".join(f"[scaled{i}]" for i in range(len(image_files)))
        filter_parts.append(f"{concat_inputs}concat=n={len(image_files)}:v=1:a=0[outv]")
        
        # 組合完整的 filter_complex
        filter_complex = ";".join(filter_parts)
        
        # 建立輸入檔案列表
        input_files = []
        for img_path in image_files:
            input_files.extend(["-loop", "1", "-t", str(image_duration), "-i", img_path])
        
        # 執行 FFmpeg 命令生成背景影片
        cmd = [
            "ffmpeg", "-y",
            *input_files,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-shortest",
            bg_video_path
        ]
        
        print("Debug - FFmpeg command:", " ".join(cmd))  # 除錯用
        print("Debug - Filter complex:", filter_complex)  # 除錯用
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode()
            print(f"FFmpeg stderr: {error_msg}")
            raise Exception(f"背景影片生成失敗: {error_msg}")

        if not os.path.exists(bg_video_path):
            raise Exception("背景影片檔案未生成")

        # 生成音訊視覺化
        output_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.{output_format}")
        cmd = create_visualization_command(
            audio_path=audio_path,
            background_path=bg_video_path,
            output_path=output_path,
            width=width,
            height=height,
            visualization_type=visualization_type,
            wave_mode=wave_mode,
            wave_color=wave_color,
            spectrum_mode=spectrum_mode,
            spectrum_color=spectrum_color,
            spectrum_scale=spectrum_scale,
            spectrum_saturation=spectrum_saturation,
            fps=fps,
            opacity=opacity,
            duration=duration
        )

        # 執行命令
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"FFmpeg error: {stderr.decode()}")
            raise Exception(f"FFmpeg error: {stderr.decode()}")

        # 檢查輸出檔案
        if not os.path.exists(output_path):
            raise Exception("輸出檔案未生成")

        # 產生下載檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"audio_visualization_{timestamp}.{output_format}"

        response = FileResponse(
            path=output_path,
            media_type='video/mp4',
            filename=output_filename
        )

        # 回應完成後自動刪除檔案
        async def cleanup():
            if os.path.exists(output_path):
                os.remove(output_path)
        response.background = BackgroundTask(cleanup)
        return response

    except Exception as e:
        # 發生錯誤時清理所有臨時檔案
        cleanup_files = [
            audio_path,
            bg_video_path,
            *([output_path] if 'output_path' in locals() else [])
        ]
        
        for file_path in cleanup_files:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as cleanup_error:
                print(f"清理檔案 {file_path} 時發生錯誤: {str(cleanup_error)}")
        
        if 'temp_image_dir' in locals() and os.path.exists(temp_image_dir):
            try:
                shutil.rmtree(temp_image_dir)
            except Exception as cleanup_error:
                print(f"清理目錄 {temp_image_dir} 時發生錯誤: {str(cleanup_error)}")
        
        raise Exception(f"生成音訊視覺化影片時發生錯誤: {str(e)}")

@app.post("/create_audio_visualization_with_subtitle",
    summary="產生音訊視覺化、多圖背景與字幕合成（非同步）",
    description="將音訊檔案、多張背景圖片與 SRT 字幕合成視覺化影片，支援字幕樣式自訂。此 API 為非同步處理，會立即回傳任務 ID。"
)
async def create_audio_visualization_with_subtitle(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(..., description="音訊檔案"),
    backgrounds: List[UploadFile] = File([], description="多張背景圖片"),
    subtitle: UploadFile = File(..., description="字幕檔案（SRT）"),
    output_format: str = "mp4",
    width: int = 1920,
    height: int = 1080,
    image_duration: float = 5.0,
    visualization_type: str = "waveform",  # waveform, spectrum
    wave_mode: str = "line",
    wave_color: str = "white",
    spectrum_mode: str = "combined",
    spectrum_color: str = "intensity",
    spectrum_scale: str = "log",
    spectrum_saturation: float = 1.0,
    fps: int = 30,
    opacity: float = 0.8,
    # 字幕樣式
    font_name: str = "Arial",
    font_size: int = 24,
    font_color: str = "white",
    font_alpha: float = 1.0,
    border_style: int = 3,
    border_size: int = 1,
    border_color: str = "black",
    border_alpha: float = 1.0,
    shadow_size: int = 2,
    shadow_color: str = "black",
    shadow_alpha: float = 0.5,
    background: bool = True,
    background_color: str = "black",
    background_alpha: float = 0.5,
    margin_vertical: int = 20,
    alignment: int = 2,
    duration: Optional[float] = None
):
    # 驗證輸入參數
    if not backgrounds:
        raise HTTPException(status_code=400, detail="請至少上傳一張背景圖片")

    # 生成任務 ID
    task_id = str(uuid.uuid4())
    
    # 建立任務工作目錄
    task_dir = os.path.join(TASK_OUTPUT_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    
    # 儲存上傳的檔案
    audio_path = os.path.join(task_dir, f"audio{os.path.splitext(audio.filename)[1]}")
    subtitle_path = os.path.join(task_dir, f"subtitle{os.path.splitext(subtitle.filename)[1]}")
    
    # 儲存檔案
    async with aiofiles.open(audio_path, 'wb') as f:
        await f.write(await audio.read())
    async with aiofiles.open(subtitle_path, 'wb') as f:
        await f.write(await subtitle.read())
    
    # 儲存背景圖片
    background_paths = []
    for i, bg in enumerate(backgrounds):
        bg_path = os.path.join(task_dir, f"bg_{i}{os.path.splitext(bg.filename)[1]}")
        async with aiofiles.open(bg_path, 'wb') as f:
            await f.write(await bg.read())
        background_paths.append(bg_path)
    
    # 儲存任務參數
    task_params = {
        "audio_path": audio_path,
        "subtitle_path": subtitle_path,
        "background_paths": background_paths,
        "output_format": output_format,
        "width": width,
        "height": height,
        "image_duration": image_duration,
        "visualization_type": visualization_type,
        "wave_mode": wave_mode,
        "wave_color": wave_color,
        "spectrum_mode": spectrum_mode,
        "spectrum_color": spectrum_color,
        "spectrum_scale": spectrum_scale,
        "spectrum_saturation": spectrum_saturation,
        "fps": fps,
        "opacity": opacity,
        "font_name": font_name,
        "font_size": font_size,
        "font_color": font_color,
        "font_alpha": font_alpha,
        "border_style": border_style,
        "border_size": border_size,
        "border_color": border_color,
        "border_alpha": border_alpha,
        "shadow_size": shadow_size,
        "shadow_color": shadow_color,
        "shadow_alpha": shadow_alpha,
        "background": background,
        "background_color": background_color,
        "background_alpha": background_alpha,
        "margin_vertical": margin_vertical,
        "alignment": alignment,
        "duration": duration,
        "task_dir": task_dir
    }
    
    # 初始化任務狀態
    tasks[task_id] = {
        "status": TaskStatus.PENDING,
        "params": task_params,
        "output_path": None,
        "error": None,
        "progress": 0,
        "created_at": datetime.now().isoformat(),
        "completed_at": None
    }
    
    # 在背景執行任務
    background_tasks.add_task(process_visualization_task, task_id)
    
    return JSONResponse({
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "message": "任務已提交，請使用任務 ID 查詢進度"
    })

@app.get("/task/{task_id}",
    summary="查詢任務狀態",
    description="使用任務 ID 查詢處理進度，當任務完成時會回傳下載連結"
)
async def get_task_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="找不到指定的任務")
    
    task = tasks[task_id]
    response = {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "created_at": task["created_at"]
    }
    
    if task["status"] == TaskStatus.COMPLETED:
        # 產生下載用的檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"audio_visualization_subtitle_{timestamp}.{task['params']['output_format']}"
        
        # 設定下載連結和檔名
        response["download_url"] = f"/download/{task_id}/{output_filename}"
        response["filename"] = output_filename
        response["completed_at"] = task["completed_at"]
    elif task["status"] == TaskStatus.FAILED:
        response["error"] = task["error"]
    
    return JSONResponse(response)

@app.get("/download/{task_id}/{filename}",
    summary="下載已完成的任務結果",
    description="下載已完成任務的視覺化影片檔案"
)
async def download_task_result(task_id: str, filename: str):
    if task_id not in tasks or tasks[task_id]["status"] != TaskStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="找不到可下載的檔案")
    
    output_path = tasks[task_id]["output_path"]
    if not output_path or not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="檔案不存在")
    
    return FileResponse(
        path=output_path,
        media_type='video/mp4',
        filename=filename,
        background=BackgroundTask(lambda: None)  # 不刪除檔案，由清理任務處理
    )

async def process_visualization_task(task_id: str):
    """處理視覺化任務的背景工作函數"""
    task = tasks[task_id]
    params = task["params"]
    
    try:
        # 更新狀態為處理中
        tasks[task_id]["status"] = TaskStatus.PROCESSING
        
        # 建立輸出路徑
        output_path = os.path.join(params["task_dir"], f"output.{params['output_format']}")
        temp_image_dir = os.path.join(params["task_dir"], "temp_images")
        os.makedirs(temp_image_dir, exist_ok=True)
        
        # 處理背景影片
        tasks[task_id]["progress"] = 10
        bg_video_path = os.path.join(params["task_dir"], "background.mp4")
        
        # 建立 filter_complex
        filter_parts = []
        for i, _ in enumerate(params["background_paths"]):
            filter_parts.append(f"[{i}:v]scale={params['width']}:{params['height']},setsar=1[scaled{i}]")
        
        concat_inputs = "".join(f"[scaled{i}]" for i in range(len(params["background_paths"])))
        filter_parts.append(f"{concat_inputs}concat=n={len(params['background_paths'])}:v=1:a=0[outv]")
        
        filter_complex = ";".join(filter_parts)
        
        # 建立輸入檔案列表
        input_files = []
        for img_path in params["background_paths"]:
            input_files.extend(["-loop", "1", "-t", str(params["image_duration"]), "-i", img_path])
        
        # 執行 FFmpeg 命令生成背景影片
        cmd = [
            "ffmpeg", "-y",
            *input_files,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-shortest",
            bg_video_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if process.returncode != 0:
            raise Exception("背景影片生成失敗")
        
        # 生成音訊視覺化影片
        tasks[task_id]["progress"] = 40
        temp_video_path = os.path.join(params["task_dir"], "temp_video.mp4")
        
        cmd = create_visualization_command(
            audio_path=params["audio_path"],
            background_path=bg_video_path,
            output_path=temp_video_path,
            width=params["width"],
            height=params["height"],
            visualization_type=params["visualization_type"],
            wave_mode=params["wave_mode"],
            wave_color=params["wave_color"],
            spectrum_mode=params["spectrum_mode"],
            spectrum_color=params["spectrum_color"],
            spectrum_scale=params["spectrum_scale"],
            spectrum_saturation=params["spectrum_saturation"],
            fps=params["fps"],
            opacity=params["opacity"],
            duration=params["duration"]
        )
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if process.returncode != 0:
            raise Exception("音訊視覺化影片生成失敗")
        
        # 加入字幕
        tasks[task_id]["progress"] = 70
        safe_subtitle_path = params["subtitle_path"].replace('\\', '/').replace(':', '\\:')
        
        filter_complex = (
            f"subtitles={safe_subtitle_path}"
            f":force_style='"
            f"Fontname={params['font_name']},"
            f"FontSize={params['font_size']},"
            f"PrimaryColour=&H{font_color_to_ass_color(params['font_color'], params['font_alpha'])},"
            f"OutlineColour=&H{font_color_to_ass_color(params['border_color'], params['border_alpha'])},"
            f"BackColour=&H{font_color_to_ass_color(params['background_color'], params['background_alpha'])},"
            f"BorderStyle={params['border_style']},"
            f"Outline={params['border_size']},"
            f"Shadow={params['shadow_size']},"
            f"MarginV={params['margin_vertical']},"
            f"Alignment={params['alignment']},"
            f"Bold=1,"
            f"BackColour=&H{font_color_to_ass_color(params['background_color'], params['background_alpha'])}'"
        )
        
        cmd = [
            'ffmpeg',
            '-i', temp_video_path,
            '-vf', filter_complex,
            '-c:v', 'libx264',
            '-c:a', 'copy',
            '-y',
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if process.returncode != 0:
            raise Exception("字幕加入失敗")
        
        # 更新任務狀態為完成
        tasks[task_id].update({
            "status": TaskStatus.COMPLETED,
            "output_path": output_path,
            "progress": 100,
            "completed_at": datetime.now().isoformat()
        })
        
        # 清理中間檔案
        if os.path.exists(bg_video_path):
            os.remove(bg_video_path)
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
        
    except Exception as e:
        # 更新任務狀態為失敗
        tasks[task_id].update({
            "status": TaskStatus.FAILED,
            "error": str(e),
            "completed_at": datetime.now().isoformat()
        })
        
        # 清理所有檔案
        try:
            shutil.rmtree(params["task_dir"])
        except Exception:
            pass

# 定期清理已完成的任務
async def cleanup_tasks():
    while True:
        try:
            current_time = datetime.now()
            tasks_to_remove = []
            
            for task_id, task in tasks.items():
                if task["status"] in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                    completed_at = datetime.fromisoformat(task["completed_at"])
                    # 清理超過 1 小時的任務
                    if (current_time - completed_at).total_seconds() > 3600:
                        if task["status"] == TaskStatus.COMPLETED and task["output_path"]:
                            try:
                                if os.path.exists(task["params"]["task_dir"]):
                                    shutil.rmtree(task["params"]["task_dir"])
                            except Exception:
                                pass
                        tasks_to_remove.append(task_id)
            
            # 移除已清理的任務
            for task_id in tasks_to_remove:
                del tasks[task_id]
                
        except Exception as e:
            print(f"清理任務時發生錯誤: {str(e)}")
        
        # 每 15 分鐘執行一次清理
        await asyncio.sleep(900)

# 在應用程式啟動時開始清理任務
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_tasks())

def create_visualization_command(
    audio_path: str,
    background_path: str,
    output_path: str,
    width: int,
    height: int,
    visualization_type: str,
    wave_mode: str,
    wave_color: str,
    spectrum_mode: str,
    spectrum_color: str,
    spectrum_scale: str,
    spectrum_saturation: float,
    fps: int,
    opacity: float,
    duration: float = None
):
    """
    根據參數產生 ffmpeg 指令（list），合成音訊視覺化影片。
    """
    filter_complex = []
    filter_complex.append(f"[0:v]scale={width}:{height}[bg];")
    if visualization_type == "waveform":
        filter_complex.append(
            f"[1:a]showwaves=s={width}x{height}:mode={wave_mode}:colors={wave_color}:r={fps}[waves];"
        )
        filter_complex.append(f"[waves]format=rgba,colorchannelmixer=aa={opacity}[overlay];")
    else:
        filter_complex.append(
            f"[1:a]showspectrum=s={width}x{height}:mode={spectrum_mode}:color={spectrum_color}:scale={spectrum_scale}:saturation={spectrum_saturation}:slide=replace:r={fps}[spectrum];"
        )
        filter_complex.append(f"[spectrum]format=rgba,colorchannelmixer=aa={opacity}[overlay];")
    filter_complex.append("[bg][overlay]overlay=0:0:format=auto,format=yuv420p[v]")
    cmd = [
        'ffmpeg',
        '-i', background_path,
        '-i', audio_path,
        '-filter_complex', ''.join(filter_complex),
        '-map', '[v]',
        '-map', '1:a',
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-shortest',
        '-y'
    ]
    if duration:
        cmd.extend(['-t', str(duration)])
    cmd.append(output_path)
    return cmd

@app.post("/separate_vocals",
    summary="音訊人聲分離",
    description="使用 FFmpeg 濾鏡進行人聲分離處理"
)
async def separate_vocals(
    audio: UploadFile = File(..., description="要進行人聲分離的音訊檔案"),
    output_format: str = "mp3",
    vocal_type: str = "vocals",  # vocals 或 instrumental
    high_freq: int = 4000,      # 高通濾波器頻率
    low_freq: int = 300,        # 低通濾波器頻率
    center_boost: float = 2.0,  # 中央聲道增強
    side_reduction: float = 0.7 # 側聲道降低
):
    """
    音訊人聲分離 API
    
    參數說明：
    - audio: 要進行人聲分離的音訊檔案
    - output_format: 輸出格式（預設：mp3）
    - vocal_type: 選擇輸出人聲或伴奏（預設：vocals）
        - vocals: 輸出人聲部分
        - instrumental: 輸出伴奏部分
    - high_freq: 高通濾波器頻率（預設：4000Hz）
    - low_freq: 低通濾波器頻率（預設：300Hz）
    - center_boost: 中央聲道增強係數（預設：2.0）
    - side_reduction: 側聲道降低係數（預設：0.7）
    
    回傳：
    - 分離後的音訊檔案（人聲或伴奏）
    """
    try:
        # 建立暫存目錄
        temp_dir = os.path.join(UPLOAD_DIR, str(uuid.uuid4()))
        os.makedirs(temp_dir, exist_ok=True)
        
        # 儲存上傳的音訊檔案
        input_filename = f"{uuid.uuid4()}{os.path.splitext(audio.filename)[1]}"
        input_path = os.path.join(temp_dir, input_filename)
        output_path = os.path.join(temp_dir, f"output.{output_format}")
        
        with open(input_path, "wb") as buffer:
            content = await audio.read()
            buffer.write(content)

        # 建立進階的濾鏡鏈
        if vocal_type == "vocals":
            # 提取人聲的濾鏡組合
            filter_complex = (
                f"channelsplit=channel_layout=stereo[left][right];"
                f"[left]highpass=f={low_freq},lowpass=f={high_freq}[l_filtered];"
                f"[right]highpass=f={low_freq},lowpass=f={high_freq}[r_filtered];"
                f"[l_filtered][r_filtered]join=inputs=2:channel_layout=stereo,"
                f"stereotools=mlev={center_boost}:slev={side_reduction}:mode=1[out]"
            )
        else:
            # 提取伴奏的濾鏡組合
            filter_complex = (
                f"channelsplit=channel_layout=stereo[left][right];"
                f"[left]highpass=f={high_freq},lowpass=f={low_freq}[l_filtered];"
                f"[right]highpass=f={high_freq},lowpass=f={low_freq}[r_filtered];"
                f"[l_filtered][r_filtered]join=inputs=2:channel_layout=stereo,"
                f"stereotools=mlev={1-center_boost}:slev={1+side_reduction}:mode=1[out]"
            )

        # 執行 FFmpeg 命令
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-filter_complex', filter_complex,
            '-map', '[out]',
            '-c:a', 'libmp3lame',
            '-q:a', '0',  # 最高品質
            '-b:a', '320k',  # 最高位元率
            output_path
        ]

        # 執行命令
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"FFmpeg error: {stderr.decode()}")  # 輸出錯誤訊息以便除錯
            raise Exception(f"音訊處理失敗: {stderr.decode()}")

        # 檢查輸出檔案
        if not os.path.exists(output_path):
            raise Exception("輸出檔案未生成")

        # 生成下載檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"{vocal_type}_{timestamp}.{output_format}"

        # 回傳檔案
        response = FileResponse(
            path=output_path,
            media_type='audio/mpeg',
            filename=output_filename
        )

        # 設定清理任務
        async def cleanup():
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"清理檔案時發生錯誤: {str(e)}")

        response.background = BackgroundTask(cleanup)
        return response

    except Exception as e:
        # 發生錯誤時清理所有檔案
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create_video_with_subtitle_async",
    summary="非同步：多圖合成影片並加字幕",
    description="將多張圖片與音樂合成影片後再加上字幕，支援非同步任務查詢與下載。"
)
async def create_video_with_subtitle_async(
    background_tasks: BackgroundTasks,
    images: List[UploadFile] = File(..., description="要合成的圖片檔案列表"),
    audio: UploadFile = File(..., description="背景音樂檔案"),
    subtitle: UploadFile = File(..., description="字幕檔案（SRT）"),
    duration_per_image: float = 5.0,
    output_format: str = "mp4",
    width: int = 1920,
    height: int = 1080,
    fade_duration: float = 1.0,
    transition_type: str = "fade",
    transition_duration: float = 2.0,
    # 字幕樣式
    font_name: str = "Arial",
    font_size: int = 24,
    font_color: str = "white",
    font_alpha: float = 1.0,
    border_style: int = 3,
    border_size: int = 1,
    border_color: str = "black",
    border_alpha: float = 1.0,
    shadow_size: int = 2,
    shadow_color: str = "black",
    shadow_alpha: float = 0.5,
    background: bool = True,
    background_color: str = "black",
    background_alpha: float = 0.5,
    margin_vertical: int = 20,
    alignment: int = 2
):
    """
    非同步多圖合成影片並加字幕 API
    """
    import aiofiles
    # 產生任務 ID 與目錄
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(TASK_OUTPUT_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    # 儲存圖片
    image_paths = []
    for i, img in enumerate(images):
        img_path = os.path.join(task_dir, f"img_{i}{os.path.splitext(img.filename)[1]}")
        async with aiofiles.open(img_path, 'wb') as f:
            await f.write(await img.read())
        image_paths.append(img_path)
    # 儲存音樂
    audio_path = os.path.join(task_dir, f"audio{os.path.splitext(audio.filename)[1]}")
    async with aiofiles.open(audio_path, 'wb') as f:
        await f.write(await audio.read())
    # 儲存字幕
    subtitle_path = os.path.join(task_dir, f"subtitle{os.path.splitext(subtitle.filename)[1]}")
    async with aiofiles.open(subtitle_path, 'wb') as f:
        await f.write(await subtitle.read())
    # 任務參數
    task_params = {
        "image_paths": image_paths,
        "audio_path": audio_path,
        "subtitle_path": subtitle_path,
        "output_format": output_format,
        "width": width,
        "height": height,
        "duration_per_image": duration_per_image,
        "fade_duration": fade_duration,
        "transition_type": transition_type,
        "transition_duration": transition_duration,
        "font_name": font_name,
        "font_size": font_size,
        "font_color": font_color,
        "font_alpha": font_alpha,
        "border_style": border_style,
        "border_size": border_size,
        "border_color": border_color,
        "border_alpha": border_alpha,
        "shadow_size": shadow_size,
        "shadow_color": shadow_color,
        "shadow_alpha": shadow_alpha,
        "background": background,
        "background_color": background_color,
        "background_alpha": background_alpha,
        "margin_vertical": margin_vertical,
        "alignment": alignment,
        "task_dir": task_dir
    }
    # 初始化任務狀態
    tasks[task_id] = {
        "status": TaskStatus.PENDING,
        "params": task_params,
        "output_path": None,
        "error": None,
        "progress": 0,
        "created_at": datetime.now().isoformat(),
        "completed_at": None
    }
    # 啟動背景任務
    background_tasks.add_task(process_video_with_subtitle_task, task_id)
    return JSONResponse({
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "message": "任務已提交，請使用任務 ID 查詢進度"
    })

async def process_video_with_subtitle_task(task_id: str):
    task = tasks[task_id]
    params = task["params"]
    try:
        # 狀態：合成影片
        tasks[task_id]["status"] = TaskStatus.PROCESSING
        tasks[task_id]["progress"] = 10
        video_path = os.path.join(params["task_dir"], f"video.{params['output_format']}")
        # 1. 圖片+音樂合成影片
        # 建立 filter_complex 字串
        filter_complex = []
        for i, _ in enumerate(params["image_paths"]):
            filter_complex.append(f"[{i}:v]scale={params['width']}:{params['height']}:force_original_aspect_ratio=decrease,pad={params['width']}:{params['height']}:(ow-iw)/2:(oh-ih)/2[scaled{i}];")
            if params["transition_type"] == "fade":
                if i == 0:
                    filter_complex.append(f"[scaled{i}]fade=t=out:st={params['duration_per_image']-params['transition_duration']}:d={params['transition_duration']}[v{i}];")
                elif i == len(params["image_paths"]) - 1:
                    filter_complex.append(f"[scaled{i}]fade=t=in:st=0:d={params['transition_duration']}[v{i}];")
                else:
                    filter_complex.append(f"[scaled{i}]fade=t=in:st=0:d={params['transition_duration']},fade=t=out:st={params['duration_per_image']-params['transition_duration']}:d={params['transition_duration']}[v{i}];")
            elif params["transition_type"] == "dissolve":
                if i == 0:
                    filter_complex.append(f"[scaled{i}]format=rgba,fade=t=out:st={params['duration_per_image']-params['transition_duration']}:d={params['transition_duration']}:alpha=1[v{i}];")
                elif i == len(params["image_paths"]) - 1:
                    filter_complex.append(f"[scaled{i}]format=rgba,fade=t=in:st=0:d={params['transition_duration']}:alpha=1[v{i}];")
                else:
                    filter_complex.append(f"[scaled{i}]format=rgba,fade=t=in:st=0:d={params['transition_duration']}:alpha=1,fade=t=out:st={params['duration_per_image']-params['transition_duration']}:d={params['transition_duration']}:alpha=1[v{i}];")
        video_inputs = ''.join(f'[v{i}]' for i in range(len(params["image_paths"])))
        filter_complex.append(f"{video_inputs}concat=n={len(params['image_paths'])}:v=1:a=0[outv]")
        filter_complex_str = ''.join(filter_complex)
        input_args = []
        for img_path in params["image_paths"]:
            input_args.extend(['-loop', '1', '-t', str(params["duration_per_image"]), '-i', img_path])
        input_args.extend(['-i', params["audio_path"]])
        cmd = [
            'ffmpeg',
            *input_args,
            '-filter_complex', filter_complex_str,
            '-map', '[outv]',
            '-map', f'{len(params["image_paths"])}:a',
            '-shortest',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-profile:v', 'high',
            '-crf', '23',
            '-movflags', '+faststart',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-y',
            video_path
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        if process.returncode != 0 or not os.path.exists(video_path):
            raise Exception("合成影片失敗")
        tasks[task_id]["progress"] = 60
        # 2. 加字幕
        output_path = os.path.join(params["task_dir"], f"output.{params['output_format']}")
        safe_subtitle_path = params["subtitle_path"].replace('\\', '/').replace(':', '\\:')
        filter_complex_sub = (
            f"subtitles={safe_subtitle_path}"
            f":force_style='"
            f"Fontname={params['font_name']},"
            f"FontSize={params['font_size']},"
            f"PrimaryColour=&H{font_color_to_ass_color(params['font_color'], params['font_alpha'])},"
            f"OutlineColour=&H{font_color_to_ass_color(params['border_color'], params['border_alpha'])},"
            f"BackColour=&H{font_color_to_ass_color(params['background_color'], params['background_alpha'])},"
            f"BorderStyle={params['border_style']},"
            f"Outline={params['border_size']},"
            f"Shadow={params['shadow_size']},"
            f"MarginV={params['margin_vertical']},"
            f"Alignment={params['alignment']},"
            f"Bold=1,"
            f"BackColour=&H{font_color_to_ass_color(params['background_color'], params['background_alpha'])}'"
        )
        cmd2 = [
            'ffmpeg',
            '-i', video_path,
            '-vf', filter_complex_sub,
            '-c:v', 'libx264',
            '-c:a', 'copy',
            '-y',
            output_path
        ]
        process2 = await asyncio.create_subprocess_exec(
            *cmd2,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process2.communicate()
        if process2.returncode != 0 or not os.path.exists(output_path):
            raise Exception("加字幕失敗")
        tasks[task_id].update({
            "status": TaskStatus.COMPLETED,
            "output_path": output_path,
            "progress": 100,
            "completed_at": datetime.now().isoformat()
        })
        # 清理中間檔案
        if os.path.exists(video_path):
            os.remove(video_path)
    except Exception as e:
        tasks[task_id].update({
            "status": TaskStatus.FAILED,
            "error": str(e),
            "completed_at": datetime.now().isoformat()
        })
        try:
            shutil.rmtree(params["task_dir"])
        except Exception:
            pass

@app.post("/get_audio_duration",
    summary="取得音檔秒數",
    description="上傳mp3音檔，回傳音檔的總秒數"
)
async def get_audio_duration(
    audio: UploadFile = File(..., description="音訊檔案（mp3）")
):
    """
    取得音檔秒數 API
    - 上傳 mp3 音檔，回傳音檔長度（秒，float）
    """
    import tempfile
    import subprocess
    import json
    import os
    # 儲存暫存檔
    suffix = os.path.splitext(audio.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name
    try:
        # 使用 ffprobe 取得音檔資訊
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'json',
            tmp_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise Exception(f"ffprobe error: {result.stderr}")
        info = json.loads(result.stdout)
        duration = float(info['format']['duration']) if 'format' in info and 'duration' in info['format'] else None
        if duration is None:
            raise Exception("無法取得音檔長度")
        return {"duration": duration}
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

if __name__ == "__main__":
    # 從環境變數獲取端口，如果沒有則使用預設值
    port = int(os.environ.get("PORT", 8000))
    
    # 在生產環境中使用 0.0.0.0 作為 host
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=True,  # 啟用代理標頭支援
        forwarded_allow_ips="*"  # 允許所有轉發的 IP
    )