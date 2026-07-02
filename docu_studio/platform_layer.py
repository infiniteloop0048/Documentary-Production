"""Single location for all OS-conditional branches.

No other module in this codebase may call platform.system() or os.startfile().
All OS-specific logic lives here only (Constitution Principle VI).
"""
import os
import platform
import subprocess
from pathlib import Path

import platformdirs


def config_dir() -> Path:
    """Return the OS-appropriate user config directory for docu_studio."""
    return Path(platformdirs.user_config_dir("docu_studio", appauthor=False))


def ffmpeg_exe() -> str:
    """Return the path to the bundled FFmpeg binary via imageio-ffmpeg."""
    import imageio_ffmpeg  # type: ignore[import-untyped]
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffprobe_exe() -> str:
    """Return the path to ffprobe.

    Prefers a bundled binary sitting next to the imageio-ffmpeg ffmpeg binary.
    Falls back to the system ffprobe found via PATH when no bundled copy exists.
    """
    import shutil

    import imageio_ffmpeg  # type: ignore[import-untyped]

    ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    bundled = ffmpeg_path.parent / ("ffprobe.exe" if platform.system() == "Windows" else "ffprobe")
    if bundled.exists():
        return str(bundled)
    system_probe = shutil.which("ffprobe")
    if system_probe:
        return system_probe
    raise FileNotFoundError(
        "ffprobe not found: install ffmpeg system-wide (e.g. 'sudo apt install ffmpeg') "
        "or place a ffprobe binary next to the imageio-ffmpeg bundle."
    )


def open_folder(path: Path) -> None:
    """Open *path* in the OS native file explorer."""
    system = platform.system()
    if system == "Windows":
        os.startfile(str(path))  # noqa: S606
    elif system == "Darwin":
        subprocess.call(["open", str(path)])
    else:
        subprocess.call(["xdg-open", str(path)])
