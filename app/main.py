from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import ffmpeg
import os
from typing import Optional, List
import uuid
import shutil
import asyncio
from datetime import datetime

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
        if output_path and os.path.exists(output_path):
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