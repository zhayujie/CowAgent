"""Video duration probing shared by the channels.

DingTalk's sampleVideo message and Feishu's video upload both need the clip's
duration in milliseconds. ffprobe answers that; when it is missing or fails we
report 0 and the caller keeps its own fallback.
"""

import subprocess

from common.log import logger


def get_video_duration_ms(file_path: str, timeout: int = 10) -> int:
    """Duration of the video at *file_path* in milliseconds, 0 on any failure."""
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return int(float(result.stdout.strip()) * 1000)
        logger.warning(f"[MediaDuration] ffprobe failed for {file_path}: {result.stderr}")
        return 0
    except FileNotFoundError:
        logger.warning("[MediaDuration] ffprobe not found; install ffmpeg to probe durations.")
        return 0
    except Exception as e:
        logger.warning(f"[MediaDuration] Failed to get video duration for {file_path}: {e}")
        return 0
