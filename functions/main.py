import logging
import os
import tempfile
import time
import subprocess
from firebase_functions import storage_fn
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app, storage as admin_storage
from dotenv import load_dotenv
import requests

set_global_options(max_instances=10)
initialize_app()
load_dotenv()
isDev = os.environ.get("ENVIROMENT") != "PRODUCTION"
if(not isDev):
    BACKEND_API_URL = os.environ.get("BACKEND_API_URL_PRODUCTION")
else:  
    BACKEND_API_URL = os.environ.get("BACKEND_API_URL_DEVELOPMENT")

ALLOW_VIDEO_TYPES = ['mp4', 'mov', 'avi', 'wmv', 'webm']
VIDEO_PREFIX = 'Revoland/PropertyVideos'
VARIANTS = {
    "720p": {"resolution": "1280x720", "bitrate": "1500k"},
    "1080p": {"resolution": "1920x1080", "bitrate": "2500k"}
}

logger = logging.getLogger(__name__)

def run_ffmpeg_command_direct(input_file, output_playlist, resolution, bitrate, segment_pattern):
    """
    Chạy lệnh ffmpeg trực tiếp sử dụng subprocess với cài đặt hiệu suất nâng cao
    """
    cmd = [
        'ffmpeg',
        '-hide_banner',     
        '-loglevel', 'error',
        '-i', input_file,
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-preset', 'fast',
        '-tune', 'zerolatency',
        '-crf', '28',
        '-maxrate', bitrate, 
        '-bufsize', f"{int(bitrate.rstrip('k')) * 2}k",
        '-s', resolution,
        '-g', '48', 
        '-keyint_min', '48',
        '-sc_threshold', '0',
        '-f', 'hls',
        '-hls_time', '6',
        '-hls_list_size', '0',
        '-hls_segment_filename', segment_pattern,
        '-hls_flags', 'independent_segments', 
        '-start_number', '0',
        '-threads', '2',
        '-y',
        output_playlist
    ]
    
    if not os.path.exists(input_file):
        logger.error(f"[CRITICAL] Tệp đầu vào không tồn tại: {input_file}")
        return False
    
    file_size = os.path.getsize(input_file)
    timeout_seconds = max(300, min(1800, file_size // (1024 * 1024) * 6))

    try:
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=timeout_seconds,
            env=dict(os.environ, **{'FFREPORT': 'file=/dev/null:level=8'})
        )
        
        if result.returncode == 0:
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"[UNEXPECTED] Lỗi FFmpeg không mong đợi ({type(e).__name__}): {e}")
        return False
    
@storage_fn.on_object_finalized()
def transcoding_to_hsl_video_on_object_finalized(event: storage_fn.CloudEvent[storage_fn.StorageObjectData]):
    """
    Tạo video HLS từ video gốc được tải lên Cloud Storage.
    1. Kích hoạt khi một tệp video mới được tải lên vào thư mục 'videos/'.
    2. Kiểm tra định dạng tệp và bỏ qua nếu không phải là MP4.
    3. Sử dụng ffmpeg để chuyển mã video sang định dạng HLS với các biến thể độ phân giải khác nhau.
    4. Tải lên các tệp HLS đã chuyển mã trở lại Cloud Storage vào thư mục 'videos/hls/{video_id}/'.
    5. Cập nhật điểm cuối backend với URL danh sách phát Master HLS.
    """
    
    file = event.data
    if not file or not getattr(file, "name", None):
        return  
    
    file_path = file.name  
    if not file_path.startswith(VIDEO_PREFIX) or not any(file_path.endswith(f'.{ext}') for ext in ALLOW_VIDEO_TYPES) or '_hls' in file_path:
        return 
 
    bucket = admin_storage.bucket(file.bucket)
    blob = bucket.blob(file_path)
    video_id = file_path.split('/')[-1].split('.')[0]

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            local_file = os.path.join(temp_dir, os.path.basename(file_path))
            blob.download_to_filename(local_file)
        except Exception as e:
            return

        hls_dir = os.path.join(temp_dir, "hls")
        os.makedirs(hls_dir, exist_ok=True)

        playlist_info = []
        successful_variants = {}
        
        for name, opts in VARIANTS.items():
            variant_dir = os.path.join(hls_dir, name)
            os.makedirs(variant_dir, exist_ok=True)
            hls_playlist = os.path.join(variant_dir, 'playlist.m3u8')
            
            try:
                segment_pattern = os.path.join(variant_dir, 'segment_%03d.ts')
                ffmpeg_success = run_ffmpeg_command_direct(
                    local_file, 
                    hls_playlist, 
                    opts["resolution"], 
                    opts["bitrate"], 
                    segment_pattern
                )
                
                if not ffmpeg_success or not os.path.exists(variant_dir):
                    continue  
                    
                ts_files = [f for f in os.listdir(variant_dir) if f.endswith('.ts')]
                if len(ts_files) == 0:
                    continue
            
                with open(hls_playlist, 'r') as f:
                    playlist_content = f.read()
                    if not playlist_content.strip() or '#EXTM3U' not in playlist_content:
                        continue
                
                uploaded_files = 0
                for filename in os.listdir(variant_dir):
                    local_variant_file = os.path.join(variant_dir, filename)
                    if not os.path.isfile(local_variant_file):
                        continue
                    
                    try:
                        remote_variant_blob = bucket.blob(f"{VIDEO_PREFIX}/Hls/{video_id}/{name}/{filename}")
                        remote_variant_blob.upload_from_filename(local_variant_file)
                        uploaded_files += 1
                    except Exception as upload_error:
                        logger.error(f"[UPLOAD FAILED] {filename} cho {name}: {upload_error}")
                        continue
                
                if uploaded_files > 0:
                    successful_variants[name] = opts
                    playlist_info.append(name)

            except Exception as e:
                continue

        if not successful_variants:
            return
            
        master_playlist = os.path.join(hls_dir, 'master_playlist.m3u8')
        
        try:
            with open(master_playlist, 'w', encoding='utf-8') as m3u8_file:
                m3u8_file.write('#EXTM3U\n')
                m3u8_file.write('#EXT-X-VERSION:3\n')
                for name, opts in successful_variants.items():
                    resolution = opts["resolution"]
                    bitrate = opts["bitrate"].replace("k", "000")
                    m3u8_file.write(f'#EXT-X-STREAM-INF:BANDWIDTH={bitrate},RESOLUTION={resolution},CODECS="avc1.42e00a,mp4a.40.2"\n')
                    m3u8_file.write(f'{name}/playlist.m3u8\n')
                    
            with open(master_playlist, 'r') as f:
                master_content = f.read()
                if not master_content.strip() or '#EXTM3U' not in master_content:
                    raise ValueError("Master playlist không hợp lệ")
                    
        except Exception as e:
            logger.error(f"[MASTER PLAYLIST FAILED] Lỗi tạo master playlist: {e}")
            return
            
        try:
            master_playlist_blob = bucket.blob(f"{VIDEO_PREFIX}/Hls/{video_id}/master_playlist.m3u8")
            master_playlist_blob.upload_from_filename(master_playlist)
        except Exception as e:
            logger.error(f"[UPLOAD FAILED] Master playlist upload lỗi: {e}")
            return
        
        try:
            original_video_id = video_id.split('_')[0]
            update_video_hls_endpoint = f"{BACKEND_API_URL}/api/videos/original/{original_video_id}/hls"
            hls_variants_payload = []       
            if playlist_info:
                master_url = master_playlist_blob.public_url
                hls_variants_payload.append({
                    "resolution": "MASTER",
                    "url": master_url
                })
                for name in playlist_info:
                    variant_blob = bucket.blob(f'{VIDEO_PREFIX}/Hls/{video_id}/{name}/playlist.m3u8')
                    variant_url = variant_blob.public_url
                    hls_variants_payload.append({
                        "resolution": name,
                        "url": variant_url
                    })
            
                payload = {"hlsVariants": hls_variants_payload}

                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        logger.info(f"Retry {attempt + 1} of {max_retries} to update backend")
                        if isDev:
                            res = requests.put(
                                update_video_hls_endpoint,
                                json=payload,
                                timeout=30,
                                headers={'Content-Type': 'application/json'},
                                verify=False
                            )
                        else:
                            res = requests.put(
                                update_video_hls_endpoint,
                                json=payload,
                                timeout=30,
                                headers={'Content-Type': 'application/json'}
                            )
                        res.raise_for_status()
                        logger.info(f"Successfully send to Backend with URL ID {video_id} (sent {len(hls_variants_payload)} variants)")
                        break
                    except requests.exceptions.Timeout:
                        logger.warning(f"Retry {attempt + 1} was due to timeout.")
                        if attempt == max_retries - 1:
                            raise
                    except requests.exceptions.RequestException as e:
                        logger.error(f"Retry {max_retries} in: {e}")
                        if attempt == max_retries - 1:
                            raise
                    time.sleep(2 ** attempt)  # Exponential backoff
                
        except Exception as e:
            logger.error(f"Retry {max_retries} in: {e}")
    return