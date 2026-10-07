"""Opt-in Linux admission for independent automatic CUDA jobs.
Physical UUID locks cover each isolated worker's full lifetime. Explicit devices
and external/multi-device engines retain existing admission semantics.
"""
import contextlib
import os

if os.name == "posix":
    import fcntl
else:
    fcntl = None
from pathlib import Path
import subprocess
import threading
import time

_local = threading.local()
_TYPES = {'internal_still_scene', 'internal_video'}

def eligible(job):
    if os.getenv('EDMG_AUTO_GPU_SCHEDULING') != '1' or job.type not in _TYPES:
        return False
    p = job.payload
    if str(p.get('device_preference', p.get('device', 'auto'))).lower() not in ('auto', 'cuda'):
        return False
    if (p.get('runtime') or p.get('runtime_policy') or {}).get('device') is not None:
        return False
    if p.get('ltx_cuda_devices') or p.get('wsl_gpu_indices'):
        return False
    if 'hunyuan' in str(p.get('video_model_id') or '').lower():
        return False
    if p.get('interpolation_engine') == 'fruc':
        return False
    engine = str(p.get('video_model_engine') or p.get('engine') or '').lower()
    return engine not in ('hunyuan_video15', 'ltx_25', 'comfyui', 'tensorrt_standalone')

def inventory():
    result = subprocess.run(['nvidia-smi', '--query-gpu=index,uuid,memory.free',
                             '--format=csv,noheader,nounits'], check=True,
                            capture_output=True, text=True, timeout=10)
    return [(int(i.strip()), u.strip(), int(m.strip()))
            for i,u,m in (line.split(',') for line in result.stdout.splitlines() if line.strip())]

def worker_environment():
    env = os.environ.copy()
    gpu = getattr(_local, 'gpu', None)
    if gpu is not None:
        env['CUDA_VISIBLE_DEVICES'] = gpu[1]
        env['EDMG_ASSIGNED_PHYSICAL_GPU'] = str(gpu[0])
        env['EDMG_AUTO_GPU_SCHEDULING'] = '0'
    return env

@contextlib.contextmanager
def reserve(active, waiting):
    root = Path(os.getenv('EDMG_AUTO_GPU_LOCK_ROOT', '/home/user/.local/state/edmg/gpu-admission'))
    root.mkdir(parents=True, exist_ok=True)
    minimum = int(os.getenv('EDMG_AUTO_GPU_MIN_FREE_MIB', '8192'))
    held = None
    try:
        while active():
            # Favor available VRAM; rotating tie-break prevents idle GPUs starving.
            gpus = inventory()
            offset = int(time.monotonic()) % max(1, len(gpus))
            gpus = gpus[offset:] + gpus[:offset]
            gpus.sort(key=lambda g: g[2], reverse=True)
            for gpu in gpus:
                if gpu[2] < minimum:
                    continue
                handle = (root / (gpu[1] + '.lock')).open('a+')
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    continue
                held = handle
                _local.gpu = gpu
                yield gpu
                return
            waiting()
            time.sleep(0.5)
        from .services.model_load_coordinator import ModelLoadCanceled
        raise ModelLoadCanceled('Canceled while waiting for a free GPU')
    finally:
        _local.gpu = None
        if held is not None:
            fcntl.flock(held, fcntl.LOCK_UN)
            held.close()

@contextlib.contextmanager
def dispatch_guard(automatic, active):
    root = Path(os.getenv('EDMG_AUTO_GPU_LOCK_ROOT', '/home/user/.local/state/edmg/gpu-admission'))
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'fleet.lock').open('a+') as handle:
        # Automatic single-GPU workers coexist; explicit/multi-GPU jobs remain exclusive.
        mode = fcntl.LOCK_SH if automatic else fcntl.LOCK_EX
        while True:
            if not active():
                from .services.model_load_coordinator import ModelLoadCanceled
                raise ModelLoadCanceled('Canceled while waiting for fleet admission')
            try:
                fcntl.flock(handle, mode | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.5)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
