import logging
import os
import tempfile
import time
import ffmpeg
from firebase_functions import storage_fn
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app, storage as admin_storage
from dotenv import load_dotenv
import requests
import ffmpeg 
import static_ffmpeg
static_ffmpeg.add_paths() 


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

def run_ffmpeg(input_file, output_playlist, resolution, bitrate, segment_pattern):
    """
    Sử dụng thư viện ffmpeg-python để transcode.
    Code style: Fluent Interface (OOP).
    """
    if not os.path.exists(input_file):
        logger.error(f"[CRITICAL] Tệp đầu vào không tồn tại: {input_file}")
        return False
    
    try:
        # 1. Xử lý bitrate (chuyển "1500k" -> 1500000 -> bufsize "3000k")
        try:
            bitrate_val = int(bitrate.lower().replace('k', ''))
            bufsize = f"{bitrate_val * 2}k"
        except ValueError:
            bufsize = "2000k"

        # 2. Khởi tạo Input
        stream = ffmpeg.input(input_file)

        # 3. Cấu hình Output với các tham số HLS
        stream = ffmpeg.output(
            stream, 
            output_playlist,
            
            # Video/Audio Codec
            vcodec='libx264',
            acodec='aac',
            
            # Performance & Quality
            preset='fast',
            tune='zerolatency',
            crf=28,
            maxrate=bitrate,
            bufsize=bufsize,
            
            # Resolution & GOP
            s=resolution,
            g=48,
            keyint_min=48,
            sc_threshold=0,
            
            # HLS Specific Options
            format='hls',
            hls_time=6,
            hls_list_size=0,
            hls_segment_filename=segment_pattern,
            hls_flags='independent_segments',
            start_number=0,
            threads=2,
            y=None
        )

        logger.info(f"Đang xử lý {resolution} với ffmpeg-python...")
        ffmpeg.run(stream, capture_stdout=True, capture_stderr=True)
        
        return True

    except ffmpeg.Error as e:
        # Thư viện này ném ra lỗi ffmpeg.Error rất chi tiết
        logger.error(f"[FFMPEG ERROR] Lỗi khi transcode {resolution}")
        # Lấy log lỗi chi tiết từ FFmpeg (stderr)
        error_log = e.stderr.decode('utf8') if e.stderr else "No stderr details"
        logger.error(f"Chi tiết: {error_log}")
        return False
        
    except Exception as e:
        logger.error(f"[UNEXPECTED] Lỗi không mong đợi: {e}")
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
                ffmpeg_success = run_ffmpeg(
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