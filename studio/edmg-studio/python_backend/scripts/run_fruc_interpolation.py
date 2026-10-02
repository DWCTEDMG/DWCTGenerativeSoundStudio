"""Adapt the installed NVIDIA FRUC 2x sample to Studio's video contract."""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from run_rife_interpolation import _ffmpeg_path, _ffprobe_path, _probe_video


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:] or result.stdout[-3000:])
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--fps', required=True, type=int)
    args = parser.parse_args()
    source = args.input.resolve(strict=True)
    destination = args.output.resolve()
    if source == destination or not 1 <= args.fps <= 240:
        raise ValueError('Distinct input/output and target FPS between 1 and 240 required')
    exe = Path(os.environ['EDMG_FRUC_EXE']).resolve(strict=True)
    ffmpeg = _ffmpeg_path()
    ffprobe = _ffprobe_path(ffmpeg)
    info = _probe_video(ffprobe, source)
    stream = info['streams'][0]
    width, height = int(stream['width']), int(stream['height'])
    rate = Fraction(stream['avg_frame_rate'])
    duration = float(info['format']['duration'])
    if width % 2 or height % 2 or rate <= 0:
        raise ValueError('FRUC requires even dimensions and a positive source rate')
    passes = max(0, math.ceil(math.log2(args.fps / float(rate))))
    if passes > 6:
        raise ValueError('FRUC conversion exceeds the supported 64x expansion')
    frame_bytes = width * height * 3 // 2
    expected = round(duration * args.fps)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Keep only the current and next raw pass. Check peak scratch-space demand.
    required = int(duration * float(rate) * 2**passes * frame_bytes * 2.5)
    if shutil.disk_usage(destination.parent).free < required:
        raise RuntimeError(f'FRUC needs approximately {required // 1048576} MiB scratch space')
    device = os.getenv('EDMG_INTERPOLATION_CUDA_DEVICE', '0')
    env = os.environ.copy()
    env['CUDA_VISIBLE_DEVICES'] = device
    logs = []
    with tempfile.TemporaryDirectory(prefix='edmg-fruc-', dir=destination.parent) as temporary:
        root = Path(temporary)
        current = root / 'source.yuv'
        run([str(ffmpeg), '-v', 'error', '-y', '-i', str(source), '-an',
             '-pix_fmt', 'yuv420p', '-f', 'rawvideo', str(current)])
        count = current.stat().st_size // frame_bytes
        if count < 2 or current.stat().st_size % frame_bytes:
            raise RuntimeError('FRUC needs at least two complete decoded frames')
        for index in range(passes):
            folder = root / f'pass-{index}'
            logs.append(run([str(exe), f'--input={current}', f'--width={width}',
                             f'--height={height}', f'--output={folder}',
                             '--surfaceformat=0', '--allocationtype=0',
                             f'--endframe={count-1}'], cwd=exe.parent, env=env))
            output = folder / ('FRUC_' + current.name)
            if not output.is_file() or output.stat().st_size != count * 2 * frame_bytes:
                raise RuntimeError('FRUC did not produce all expected frames')
            # Sample emits a repeated first frame followed by the first source.
            # Removing that leading frame preserves pair timestamps at every pass.
            following = root / f'frames-{index}.yuv'
            with output.open('rb') as reader, following.open('wb') as writer:
                reader.seek(frame_bytes)
                shutil.copyfileobj(reader, writer, 8 * 1024 * 1024)
            output.unlink()
            current.unlink()
            current = following
            count = count * 2 - 1
            rate *= 2
        encoded = root / 'encoded.mp4'
        run([str(ffmpeg), '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p',
             '-s', f'{width}x{height}', '-r', str(rate), '-i', str(current),
             '-vf', f'tpad=stop_mode=clone:stop_duration={duration},fps={args.fps}',
             '-frames:v', str(expected), '-an', '-c:v', 'h264_nvenc', '-gpu', device,
             '-preset', 'p5', '-cq', '18', '-b:v', '0', '-movflags', '+faststart', str(encoded)])
        result = _probe_video(ffprobe, encoded)
        if (int(result['streams'][0].get('nb_frames', 0)) != expected
                or abs(float(result['format']['duration']) - duration) > 1/args.fps + .01):
            raise RuntimeError('FRUC output failed duration/frame-count validation')
        os.replace(encoded, destination)
        receipt = dict(ok=True, provider='nvidia_ofa_fruc', cuda_device=device,
                       encoder='h264_nvenc', passes=passes, sample_logs=logs, probe=result)
        destination.with_suffix('.fruc.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
