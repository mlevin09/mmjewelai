"""POSIX decoder sandbox; invocation is internal, not an exposed command interface."""

import os
import resource
import sys

import imageio_ffmpeg

from .audio import FORMATS


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in FORMATS.values():
        raise SystemExit(2)
    binary = imageio_ffmpeg.get_ffmpeg_exe()
    # macOS does not implement a usable RLIMIT_AS here. Production is pinned Linux/amd64;
    # developer macOS codec tests verify decoding, not the Linux memory isolation gate.
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
    os.execv(
        binary,
        [
            binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "quiet",
            "-xerror",
            "-max_alloc",
            "67108864",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-protocol_whitelist",
            "pipe",
            "-f",
            sys.argv[1],
            "-i",
            "pipe:0",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-t",
            "61",
            "-threads",
            "1",
            "-f",
            "f32le",
            "pipe:1",
        ],
    )


if __name__ == "__main__":
    main()
