"""Shared encoding settings for videos that may be uploaded to Douyin."""

VIDEO_BITRATE = "2500k"
VIDEO_MIN_BITRATE = "1000k"
VIDEO_MAX_BITRATE = "4000k"
VIDEO_BUFFER_SIZE = "8000k"


def h264_video_args() -> list[str]:
    """Return H.264 arguments with a bitrate floor instead of CRF-only sizing."""

    return [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        VIDEO_BITRATE,
        "-minrate",
        VIDEO_MIN_BITRATE,
        "-maxrate",
        VIDEO_MAX_BITRATE,
        "-bufsize",
        VIDEO_BUFFER_SIZE,
        "-x264-params",
        "nal-hrd=cbr",
        "-pix_fmt",
        "yuv420p",
    ]
