import os
# --- 🚨 OPENMP SILENT CRASH PROTECTOR 🚨 ---
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import logging
logging.getLogger("transformers").setLevel(logging.ERROR)

import sys
import shutil
import subprocess
from datetime import datetime
import time
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import gc
import re
import platform
import multiprocessing
import traceback
import json
import tempfile

# --- THE BLACK HOLE (Prevents PyInstaller sys.stdout crashes) ---
class NullWriter:
    def write(self, text): pass
    def flush(self): pass

if sys.stdout is None: sys.stdout = NullWriter()
if sys.stderr is None: sys.stderr = NullWriter()

# --- UNIVERSAL APP PATH (PyInstaller 6.0+ Safe) ---
if getattr(sys, 'frozen', False):
    APP_ROOT = os.path.dirname(sys.executable)
    DATA_ROOT = sys._MEIPASS # Automatically points inside the hidden _internal folder
else:
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))
    DATA_ROOT = APP_ROOT

# --- 🚨 THE DLL RESCUE MISSION (CROSS-PLATFORM SAFE) 🚨 ---
if platform.system() == "Windows" and getattr(sys, 'frozen', False):
    try:
        os.add_dll_directory(DATA_ROOT)
        os.add_dll_directory(os.path.join(DATA_ROOT, "torch", "lib"))
    except AttributeError:
        pass

# --- 🚨 AI IMPORTS 🚨 ---
try:
    import torch
    from torchvision import transforms
    from ultralytics import YOLO
    from transformers import AutoModelForImageSegmentation, MaskFormerImageProcessor, MaskFormerForInstanceSegmentation
    AI_LIBRARIES_LOADED = True
except Exception as e:
    print(f"CRITICAL AI IMPORT ERROR: {e}")
    AI_LIBRARIES_LOADED = False

# --- STANDARD LIBRARIES ---
import cv2
import numpy as np
import rawpy
import exifread
from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORT_AVAILABLE = True
except Exception:
    HEIC_SUPPORT_AVAILABLE = False

try:
    import imageio_ffmpeg
    IMAGEIO_FFMPEG_AVAILABLE = True
except Exception:
    imageio_ffmpeg = None
    IMAGEIO_FFMPEG_AVAILABLE = False

# --- SCENE DETECT IMPORT ---
try:
    from scenedetect import SceneManager, ContentDetector, open_video
    SCENE_DETECT_AVAILABLE = True
except ImportError:
    SCENE_DETECT_AVAILABLE = False
    print("scenedetect library not found. Auto-Scene splitting disabled.")

# --- ENGINE CONSTANTS ---
JPG_FORMATS = ('.jpg', '.jpeg')
PNG_FORMATS = ('.png',)
TIFF_FORMATS = ('.tif', '.tiff')
HEIC_FORMATS = ('.heic', '.heif')
RAW_FORMATS = ('.dng', '.cr2', '.nef', '.arw', '.orf', '.rw2')
VIDEO_FORMATS = ('.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv')
SUPPORTED_FORMATS = JPG_FORMATS + PNG_FORMATS + TIFF_FORMATS + HEIC_FORMATS + RAW_FORMATS
IMAGE_TYPE_FORMATS = {
    "jpg": JPG_FORMATS,
    "png": PNG_FORMATS,
    "tiff": TIFF_FORMATS,
    "heic": HEIC_FORMATS,
    "raw": RAW_FORMATS,
}
DEFAULT_IMAGE_TYPES = ("jpg", "png", "tiff", "heic", "raw")

# --- GLOBAL THREADING VARIABLES ---
cancel_flag = False
msg_queue = queue.Queue()
ai_lock = threading.Lock() 
active_video_process = None
AI_RUNTIME_DEVICE = "cpu"


# =========================================================================================
# ======================== PART 1: CORE BACKEND FUNCTIONS =================================
# =========================================================================================

def initialize_ai_libraries():
    global AI_LIBRARIES_LOADED
    return AI_LIBRARIES_LOADED

def compact_error(exc):
    return str(exc).replace("\n", " ").strip()

def terminate_child_process(proc, timeout=3.0):
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=timeout)
    except Exception:
        pass

def request_cancel(reason="Cancel requested."):
    global cancel_flag, active_video_process
    cancel_flag = True
    terminate_child_process(active_video_process)

def start_stdin_cancel_watcher():
    try:
        if sys.stdin is None or sys.stdin.closed:
            return None
    except Exception:
        return None

    def watch_for_cancel():
        while not cancel_flag:
            try:
                line = sys.stdin.readline()
            except Exception:
                break
            if not line:
                break
            if line.strip().lower() in {"cancel", "stop", "quit"}:
                request_cancel("Cancel requested from UI.")
                break

    watcher = threading.Thread(target=watch_for_cancel, name="scanprep-cancel-watch", daemon=True)
    watcher.start()
    return watcher

def is_accelerator_error(exc):
    msg = compact_error(exc).lower()
    cuda_fragments = [
        "no kernel image is available",
        "not compatible with the current pytorch installation",
        "cuda error",
        "cuda out of memory",
        "cudnn",
        "cublas",
        "nvrtc",
        "illegal memory access",
        "device-side assert",
    ]
    mps_fragments = [
        "mps",
        "metal",
    ]
    return any(fragment in msg for fragment in cuda_fragments + mps_fragments)

def get_cuda_arch_report(device_idx):
    try:
        name = torch.cuda.get_device_name(device_idx)
        major, minor = torch.cuda.get_device_capability(device_idx)
        sm_tag = f"sm_{major}{minor}"
        arch_list = torch.cuda.get_arch_list() if hasattr(torch.cuda, "get_arch_list") else []
        return name, sm_tag, arch_list
    except Exception as e:
        return f"CUDA device {device_idx}", "unknown", []

def parse_cuda_arch_tag(tag):
    for prefix in ("sm_", "compute_"):
        if isinstance(tag, str) and tag.startswith(prefix):
            raw = tag[len(prefix):]
            if raw.isdigit() and len(raw) >= 2:
                return int(raw[:-1]), int(raw[-1])
    return None

def cuda_arch_is_covered(sm_tag, arch_list):
    if not arch_list or sm_tag == "unknown":
        return True, ""

    compute_tag = sm_tag.replace("sm_", "compute_")
    if sm_tag in arch_list or compute_tag in arch_list:
        return True, f"direct {sm_tag}"

    requested = parse_cuda_arch_tag(sm_tag)
    if requested is None:
        return False, ""

    req_major, req_minor = requested
    same_major = []
    for arch in arch_list:
        parsed = parse_cuda_arch_tag(arch)
        if parsed is None:
            continue
        arch_major, arch_minor = parsed
        if arch_major == req_major and arch_minor <= req_minor:
            same_major.append((arch_minor, arch))

    if same_major:
        _, compatible_arch = max(same_major)
        return True, f"compatible via {compatible_arch}"

    return False, ""

def smoke_test_torch_device(device):
    try:
        with torch.no_grad():
            x = torch.ones((16, 16), device=device, dtype=torch.float32)
            y = x @ x
            _ = float(y[0, 0].detach().cpu())
        if str(device).startswith("cuda"):
            torch.cuda.synchronize(device)
        return True, ""
    except Exception as e:
        return False, compact_error(e)

def select_ai_device():
    if not AI_LIBRARIES_LOADED:
        return "cpu"

    try:
        if torch.cuda.is_available():
            for device_idx in range(torch.cuda.device_count()):
                device = f"cuda:{device_idx}"
                name, sm_tag, arch_list = get_cuda_arch_report(device_idx)
                arch_ok, arch_note = cuda_arch_is_covered(sm_tag, arch_list)
                if not arch_ok:
                    msg_queue.put(('status', f"Skipping {name}: PyTorch build does not include {sm_tag}; using fallback if needed."))
                    continue
                ok, reason = smoke_test_torch_device(device)
                if ok:
                    if arch_note and arch_note != f"direct {sm_tag}":
                        msg_queue.put(('status', f"Using CUDA acceleration: {name} ({sm_tag}, {arch_note})"))
                    else:
                        msg_queue.put(('status', f"Using CUDA acceleration: {name} ({sm_tag})"))
                    return device
                msg_queue.put(('status', f"CUDA test failed on {name}; trying fallback. {reason[:180]}"))
            try: torch.cuda.empty_cache()
            except Exception: pass

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            ok, reason = smoke_test_torch_device("mps")
            if ok:
                msg_queue.put(('status', "Using Apple Metal acceleration."))
                return "mps"
            msg_queue.put(('status', f"Apple Metal test failed; using CPU. {reason[:180]}"))
    except Exception as e:
        msg_queue.put(('status', f"Accelerator detection failed; using CPU. {compact_error(e)[:180]}"))

    msg_queue.put(('status', "Using CPU for AI masks."))
    return "cpu"

def retry_on_cpu(loader, feature_name, original_error):
    if not is_accelerator_error(original_error):
        raise original_error
    msg_queue.put(('status', f"{feature_name} failed on the selected accelerator; retrying on CPU."))
    try:
        torch.cuda.empty_cache()
    except Exception:
        pass
    return loader("cpu"), "cpu"

def sync_accelerator(device):
    try:
        if str(device).startswith("cuda"):
            torch.cuda.synchronize(device)
    except Exception:
        pass

def get_ai_runtime_log_lines(device="cpu"):
    lines = [
        f"AI libraries loaded: {AI_LIBRARIES_LOADED}",
        f"AI selected device: {device}",
        f"App root: {APP_ROOT}",
        f"Data root: {DATA_ROOT}",
    ]
    if not AI_LIBRARIES_LOADED:
        return lines

    try:
        lines.append(f"Torch: {torch.__version__}")
        lines.append(f"Torch CUDA build: {torch.version.cuda}")
        lines.append(f"CUDA available: {torch.cuda.is_available()}")
        if hasattr(torch.cuda, "get_arch_list"):
            lines.append(f"Torch compiled arch list: {torch.cuda.get_arch_list()}")
        if torch.cuda.is_available():
            lines.append(f"CUDA device count: {torch.cuda.device_count()}")
            for idx in range(torch.cuda.device_count()):
                name = torch.cuda.get_device_name(idx)
                cap = torch.cuda.get_device_capability(idx)
                lines.append(f"CUDA device {idx}: {name} (sm_{cap[0]}{cap[1]})")
    except Exception as e:
        lines.append(f"AI runtime report failed: {compact_error(e)}")
    return lines

def get_effective_worker_count(configured_threads, ai_active, device):
    max_threads = max(1, int(configured_threads))
    if ai_active:
        if str(device).startswith("cuda") or str(device).startswith("mps"):
            return min(max_threads, 4)
        return min(max_threads, max(1, (os.cpu_count() or 2) // 2))
    return max_threads

def safe_int(val_str, default_val):
    try: return int(val_str) if str(val_str).strip() else default_val
    except: return default_val

def safe_float(val_str, default_val):
    try: return float(val_str) if str(val_str).strip() else default_val
    except: return default_val

def is_raw_file(filepath):
    return filepath.lower().endswith(RAW_FORMATS)

def is_heic_file(filepath):
    return filepath.lower().endswith(HEIC_FORMATS)

def build_allowed_formats(image_type_flags=None):
    if not image_type_flags:
        return SUPPORTED_FORMATS
    allowed = []
    for type_key in DEFAULT_IMAGE_TYPES:
        if image_type_flags.get(type_key, False):
            allowed.extend(IMAGE_TYPE_FORMATS[type_key])
    return tuple(allowed)

def parse_folder_search_depth(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or "unlimited" in text or "all" in text:
        return None
    match = re.search(r'-?\d+', text)
    if not match:
        return None
    return max(0, int(match.group(0)))

def folder_depth_from_root(root, start_dir):
    rel = os.path.relpath(root, start_dir)
    if rel == ".":
        return 0
    return len([part for part in re.split(r'[\\/]+', rel) if part and part != "."])

def get_valid_videos(start_dir, recursive=False, max_depth=None):
    videos = []
    if not start_dir or not os.path.isdir(start_dir):
        return videos
    max_depth = parse_folder_search_depth(max_depth)
    if recursive:
        for root, dirs, files in os.walk(start_dir):
            if '.scanprep_ignore' in files and root != start_dir:
                dirs.clear()
                continue
            if max_depth is not None and folder_depth_from_root(root, start_dir) >= max_depth:
                dirs.clear()
            for name in files:
                if name.lower().endswith(VIDEO_FORMATS):
                    videos.append(os.path.join(root, name))
    else:
        for name in os.listdir(start_dir):
            full_path = os.path.join(start_dir, name)
            if os.path.isfile(full_path) and name.lower().endswith(VIDEO_FORMATS):
                videos.append(full_path)
    return sorted(videos, key=lambda p: os.path.basename(p).lower())

def default_output_dir_for_input(input_path):
    if not input_path:
        return ""
    if os.path.isdir(input_path):
        return os.path.join(input_path, "_ScanPrep_Output")
    return os.path.join(os.path.dirname(input_path), "_ScanPrep_Output")

def load_pillow_image_array(filepath, flags=cv2.IMREAD_COLOR):
    if is_heic_file(filepath) and not HEIC_SUPPORT_AVAILABLE:
        return None
    with Image.open(filepath) as img:
        img = ImageOps.exif_transpose(img)
        if flags == cv2.IMREAD_GRAYSCALE:
            return np.array(img.convert("L"))
        if flags == cv2.IMREAD_UNCHANGED and img.mode == "RGBA":
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGBA2BGRA)
        return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)

def cv2_imread(filepath, flags=cv2.IMREAD_COLOR):
    try:
        if is_heic_file(filepath) or filepath.lower().endswith(JPG_FORMATS):
            return load_pillow_image_array(filepath, flags)
        return cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), flags)
    except Exception: return None

def cv2_imwrite(filepath, img, params=None):
    try:
        ext = os.path.splitext(filepath)[1]
        result, n = cv2.imencode(ext, img, params or [])
        if result:
            with open(filepath, mode='wb') as f: n.tofile(f)
            return True
        return False
    except Exception: return False

def get_output_path_for_mode(path, output_exists_mode="Overwrite"):
    mode = str(output_exists_mode or "Overwrite").strip().lower()
    if mode.startswith("skip") and os.path.exists(path):
        return None
    if mode.startswith("auto") and os.path.exists(path):
        return get_available_output_path(path)
    return path

def cv2_imwrite_with_mode(filepath, img, params=None, output_exists_mode="Overwrite"):
    out_path = get_output_path_for_mode(filepath, output_exists_mode)
    if out_path is None:
        return None
    if cv2_imwrite(out_path, img, params):
        return out_path
    return None

def is_transparent_mask_output(mask_output_type):
    label = str(mask_output_type or "").lower()
    return "rgba" in label or "transparent" in label

def resize_for_preview(img, max_edge=2200):
    h, w = img.shape[:2]
    edge = max(h, w)
    if edge <= max_edge:
        return img
    scale = max_edge / float(edge)
    return cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)

PREVIEW_CACHE_DIRNAME = "_ScanPrep_Preview_Cache"
PREVIEW_ROOT_PREFIXES = ("_Sharpness_Preview_", "_Contrast_Preview_", "_Mask_Preview_")
PREVIEW_CACHE_PREFIXES = ("source_preview_",)

def is_same_or_child_path(path, parent):
    try:
        path_abs = os.path.normcase(os.path.abspath(path))
        parent_abs = os.path.normcase(os.path.abspath(parent))
        return os.path.commonpath([path_abs, parent_abs]) == parent_abs
    except Exception:
        return False

def cleanup_preview_artifacts(output_dir, keep_paths=None, remove_display_files=False, timing_log=None):
    if not output_dir or not os.path.isdir(output_dir):
        return 0

    output_abs = os.path.abspath(output_dir)
    keep_abs = [os.path.abspath(path) for path in (keep_paths or []) if path]
    removed = 0

    def should_keep(candidate):
        candidate_abs = os.path.abspath(candidate)
        return any(is_same_or_child_path(keep, candidate_abs) for keep in keep_abs)

    def remove_dir(candidate):
        nonlocal removed
        if not is_same_or_child_path(candidate, output_abs) or should_keep(candidate) or os.path.islink(candidate):
            return
        def make_writable_and_retry(func, path, _exc_info):
            try:
                os.chmod(path, 0o700)
                func(path)
            except Exception:
                pass
        try:
            shutil.rmtree(candidate, ignore_errors=False, onerror=make_writable_and_retry)
            if not os.path.exists(candidate):
                removed += 1
            elif timing_log is not None:
                timing_log.append(f"[CACHE] Could not remove preview folder {os.path.basename(candidate)}.")
        except Exception as e:
            if timing_log is not None:
                timing_log.append(f"[CACHE] Could not remove preview folder {os.path.basename(candidate)}: {compact_error(e)}")

    def remove_file(candidate):
        nonlocal removed
        if not is_same_or_child_path(candidate, output_abs) or should_keep(candidate):
            return
        try:
            os.remove(candidate)
            if not os.path.exists(candidate):
                removed += 1
        except Exception as e:
            if timing_log is not None:
                timing_log.append(f"[CACHE] Could not remove preview file {os.path.basename(candidate)}: {compact_error(e)}")

    try:
        for name in os.listdir(output_dir):
            candidate = os.path.join(output_dir, name)
            if os.path.isdir(candidate) and name.startswith(PREVIEW_ROOT_PREFIXES):
                remove_dir(candidate)
    except Exception as e:
        if timing_log is not None:
            timing_log.append(f"[CACHE] Could not scan preview folders: {compact_error(e)}")

    cache_dir = os.path.join(output_dir, PREVIEW_CACHE_DIRNAME)
    if os.path.isdir(cache_dir):
        try:
            for name in os.listdir(cache_dir):
                candidate = os.path.join(cache_dir, name)
                if os.path.isdir(candidate) and name.startswith(PREVIEW_CACHE_PREFIXES):
                    remove_dir(candidate)
                elif remove_display_files and os.path.isfile(candidate):
                    remove_file(candidate)
        except Exception as e:
            if timing_log is not None:
                timing_log.append(f"[CACHE] Could not scan preview cache: {compact_error(e)}")

    return removed

def get_preview_cache_dir(output_dir=""):
    if output_dir:
        cache_dir = os.path.join(output_dir, PREVIEW_CACHE_DIRNAME)
    else:
        cache_dir = os.path.join(tempfile.gettempdir(), "ScanPrep", PREVIEW_CACHE_DIRNAME)
    os.makedirs(cache_dir, exist_ok=True)
    create_ignore_marker(cache_dir)
    return cache_dir

def make_display_preview_image(filepath, output_dir="", max_edge=2200, quality=92):
    browser_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    ext = os.path.splitext(filepath)[1].lower()
    if ext in browser_exts and os.path.exists(filepath):
        return filepath

    cache_dir = get_preview_cache_dir(output_dir)
    base = re.sub(r'[^A-Za-z0-9_.-]+', "_", os.path.splitext(os.path.basename(filepath))[0]).strip("._") or "preview"
    try:
        stamp = f"{int(os.path.getmtime(filepath))}_{os.path.getsize(filepath)}"
    except Exception:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(cache_dir, f"{base}_{stamp}.jpg")
    if os.path.exists(out_path):
        return out_path

    if is_raw_file(filepath):
        with rawpy.imread(filepath) as raw:
            img_rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8, no_auto_bright=False)
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    else:
        img_bgr = cv2_imread(filepath, cv2.IMREAD_UNCHANGED)
        if img_bgr is None:
            raise ValueError(f"Cannot read preview image: {filepath}")
        if len(img_bgr.shape) == 2:
            img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
        elif len(img_bgr.shape) == 3 and img_bgr.shape[2] == 4:
            img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2BGR)
        if img_bgr.dtype == np.uint16:
            img_bgr = (img_bgr / 257.0).astype(np.uint8)
    img_bgr = resize_for_preview(img_bgr, max_edge=max_edge)
    if not cv2_imwrite(out_path, img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]):
        raise ValueError(f"Could not write preview image: {out_path}")
    return out_path

def get_time(filepath):
    try:
        with open(filepath, 'rb') as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
            if 'EXIF DateTimeOriginal' in tags:
                return datetime.strptime(str(tags['EXIF DateTimeOriginal']), '%Y:%m:%d %H:%M:%S')
    except Exception: pass
    return datetime.fromtimestamp(os.path.getmtime(filepath))

def get_next_session_number(output_dir):
    if not os.path.exists(output_dir): return 1
    max_idx = 0
    for folder_name in os.listdir(output_dir):
        match = re.search(r'(?:Scan_Session|Scene)_(\d+)', folder_name)
        if match: max_idx = max(max_idx, int(match.group(1)))
    return max_idx + 1

def create_ignore_marker(dir_path):
    marker = os.path.join(dir_path, '.scanprep_ignore')
    if not os.path.exists(marker):
        try: open(marker, 'w').close()
        except: pass

def get_valid_images(start_dir, allowed_formats=None, subfolder_mode="recursive", max_depth=None):
    allowed_formats = tuple(ext.lower() for ext in (allowed_formats or SUPPORTED_FORMATS))
    valid_imgs = []
    if subfolder_mode == "top":
        try:
            for f in os.listdir(start_dir):
                full_path = os.path.join(start_dir, f)
                if os.path.isfile(full_path) and f.lower().endswith(allowed_formats):
                    valid_imgs.append(full_path)
        except Exception:
            pass
        return valid_imgs
    max_depth = parse_folder_search_depth(max_depth)
    for root, dirs, files in os.walk(start_dir):
        if '.scanprep_ignore' in files and root != start_dir:
            dirs.clear() 
            continue
        if max_depth is not None and folder_depth_from_root(root, start_dir) >= max_depth:
            dirs.clear()
        for f in files:
            if f.lower().endswith(allowed_formats):
                valid_imgs.append(os.path.join(root, f))
    return valid_imgs

def check_paths_for_unicode(in_p, out_p):
    try:
        if in_p != "": in_p.encode('ascii')
        if out_p != "": out_p.encode('ascii')
        return False
    except UnicodeEncodeError: return True

def build_360_view_list(view_mode="Standard 14 views", include_bottom_views=True):
    label = str(view_mode or "").lower()
    if "26" in label or "dense" in label:
        horizon = [(yaw, 0) for yaw in range(0, 360, 30)]
        upper = [(yaw, 45) for yaw in (0, 51, 103, 154, 206, 257, 309)]
        lower = [(yaw, -45) for yaw in (26, 77, 129, 180, 231, 283, 334)]
    elif "18" in label or "balanced" in label:
        horizon = [(yaw, 0) for yaw in range(0, 360, 45)]
        upper = [(yaw, 45) for yaw in (0, 72, 144, 216, 288)]
        lower = [(yaw, -45) for yaw in (36, 108, 180, 252, 324)]
    elif "8" in label or "side" in label:
        horizon = [(yaw, 0) for yaw in range(0, 360, 45)]
        upper, lower = [], []
    else:
        horizon = [(yaw, 0) for yaw in range(0, 360, 45)]
        upper = [(0, 45), (120, 45), (240, 45)]
        lower = [(60, -45), (180, -45), (300, -45)]

    views = horizon + upper
    if include_bottom_views:
        views += lower
    return views

def format_360_view_name(base, idx, yaw, pitch, ext):
    return f"{base}_v{idx:02d}_y{int(yaw):03d}_p{int(pitch):+03d}{ext}"

def parse_360_view_angles(filepath):
    match = re.search(r"_y(\d{3})_p([+-]\d{2,3})", os.path.basename(filepath))
    if not match:
        return None
    try:
        return int(match.group(1)), int(match.group(2))
    except Exception:
        return None

def make_360_bottom_mask(h, w, filepath="", bottom_start_degrees=65):
    mask = np.ones((h, w), dtype=np.uint8) * 255
    angles = parse_360_view_angles(filepath)
    if angles is None:
        cutoff = int(h * 0.72)
        mask[cutoff:, :] = 0
        return mask

    yaw, pitch = angles
    f = (0.5 * w) / np.tan(np.deg2rad(90) / 2)
    cx, cy = w / 2, h / 2
    x, y = np.meshgrid(np.arange(w), np.arange(h))
    x_c, y_c = x - cx, y - cy
    z_c = np.ones_like(x_c) * f
    yaw_rad, pitch_rad = np.deg2rad(yaw), np.deg2rad(pitch)
    r_x = np.array([[1, 0, 0], [0, np.cos(pitch_rad), -np.sin(pitch_rad)], [0, np.sin(pitch_rad), np.cos(pitch_rad)]])
    r_y = np.array([[np.cos(yaw_rad), 0, np.sin(yaw_rad)], [0, 1, 0], [-np.sin(yaw_rad), 0, np.cos(yaw_rad)]])
    coords = np.stack((x_c, y_c, z_c), axis=-1) @ (r_y @ r_x).T
    lat = np.rad2deg(np.arcsin(coords[..., 1] / np.sqrt(np.sum(coords**2, axis=-1))))
    mask[lat >= bottom_start_degrees] = 0
    return mask

def extract_360_views(image_path, out_dir, out_fmt, jpg_quality=100, view_mode="Standard 14 views", include_bottom_views=True):
    global cancel_flag
    img = cv2_imread(image_path)
    if img is None: return
    eh, ew = img.shape[:2]
    out_w, out_h = ew // 4, ew // 4
    f = (0.5 * out_w) / np.tan(np.deg2rad(90) / 2)
    cx, cy = out_w / 2, out_h / 2
    x, y = np.meshgrid(np.arange(out_w), np.arange(out_h))
    x_c, y_c = x - cx, y - cy
    z_c = np.ones_like(x_c) * f
    views = build_360_view_list(view_mode, include_bottom_views)
    base = os.path.splitext(os.path.basename(image_path))[0]
    ext = ".png" if out_fmt=="PNG" else ".tif" if out_fmt=="TIFF" else ".jpg"
    write_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(jpg_quality)] if ext == ".jpg" else []
    for idx, (yaw, pitch) in enumerate(views):
        if cancel_flag: break
        time.sleep(0.001)
        yaw_rad, pitch_rad = np.deg2rad(yaw), np.deg2rad(pitch)
        R_x = np.array([[1, 0, 0], [0, np.cos(pitch_rad), -np.sin(pitch_rad)], [0, np.sin(pitch_rad), np.cos(pitch_rad)]])
        R_y = np.array([[np.cos(yaw_rad), 0, np.sin(yaw_rad)], [0, 1, 0], [-np.sin(yaw_rad), 0, np.cos(yaw_rad)]])
        R = R_y @ R_x
        coords = np.stack((x_c, y_c, z_c), axis=-1) @ R.T
        x_sph, y_sph, z_sph = coords[..., 0], coords[..., 1], coords[..., 2]
        lon, lat = np.arctan2(x_sph, z_sph), np.arcsin(y_sph / np.sqrt(x_sph**2 + y_sph**2 + z_sph**2))
        u, v = (lon / (2 * np.pi) + 0.5), (lat / np.pi + 0.5)
        map_x, map_y = (u * ew).astype(np.float32), (v * eh).astype(np.float32)
        proj_img = cv2.remap(img, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)
        cv2_imwrite(os.path.join(out_dir, format_360_view_name(base, idx + 1, yaw, pitch, ext)), proj_img, write_params)

def get_ffmpeg_executable():
    candidates = [
        os.path.join(APP_ROOT, "ffmpeg.exe"),
        os.path.join(APP_ROOT, "Tools", "ffmpeg", "ffmpeg.exe"),
        os.path.join(DATA_ROOT, "ffmpeg.exe"),
        os.path.join(DATA_ROOT, "Tools", "ffmpeg", "ffmpeg.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        if not IMAGEIO_FFMPEG_AVAILABLE or imageio_ffmpeg is None:
            return ""
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return ""

def get_video_target_width(res_mode):
    if res_mode == "4K (3840x2160)": return 3840
    if res_mode == "1440p (2560x1440)": return 2560
    if res_mode == "1080p (1920x1080)": return 1920
    return None

def get_video_output_extension(out_fmt):
    return ".png" if out_fmt == "PNG" else ".tif" if out_fmt == "TIFF" else ".jpg"

def get_video_write_params(out_fmt, jpg_quality):
    if out_fmt == "PNG":
        return [int(cv2.IMWRITE_PNG_COMPRESSION), 1]
    if out_fmt == "TIFF":
        return [int(cv2.IMWRITE_TIFF_COMPRESSION), 1]
    return [int(cv2.IMWRITE_JPEG_QUALITY), int(jpg_quality)]

def ffmpeg_jpeg_quality(jpg_quality):
    quality = int(np.clip(safe_int(jpg_quality, 92), 70, 100))
    return str(int(round(np.interp(quality, [70, 100], [8, 2]))))

def get_scene_detector_options(cfg):
    sensitivity = str(cfg.get("scene_sensitivity", "Normal")).strip().lower()
    threshold_map = {
        "low": 35.0,
        "normal": 27.0,
        "high": 18.0,
    }
    threshold = threshold_map.get(sensitivity, threshold_map["normal"])
    min_scene_seconds = float(np.clip(safe_float(cfg.get("scene_min_seconds", 4.0), 4.0), 0.5, 600.0))
    return {"threshold": threshold, "min_scene_seconds": min_scene_seconds}

def get_video_extraction_method(cfg, extract_mode):
    method = str((cfg or {}).get("vid_extract_method", "Fast extraction")).strip().lower()
    if method.startswith("accurate"):
        return "Accurate extraction"
    if extract_mode != "Target Amount of Frames":
        input_type = str((cfg or {}).get("input_type", "")).strip().lower()
        step = max(1, safe_int((cfg or {}).get("vid_ext_val", 10), 10))
        if input_type == "folder_360" or step >= 30:
            return "Fast extraction"
        return "Accurate extraction"
    return "Fast extraction"

def allocate_scene_frame_counts(scene_list, extract_mode, extract_val):
    scene_count = len(scene_list)
    if scene_count <= 0:
        return []
    if extract_mode != "Target Amount of Frames":
        return []

    target = max(1, safe_int(extract_val, 300))
    if target <= scene_count:
        return [1] * scene_count

    durations = [max(0.1, end_sec - start_sec) for start_sec, end_sec in scene_list]
    total_duration = sum(durations) or 1.0
    raw_counts = [target * (duration / total_duration) for duration in durations]
    counts = [max(1, int(np.floor(count))) for count in raw_counts]

    remainder = target - sum(counts)
    if remainder > 0:
        order = sorted(range(scene_count), key=lambda idx: (raw_counts[idx] - np.floor(raw_counts[idx]), durations[idx]), reverse=True)
        for idx in order[:remainder]:
            counts[idx] += 1
    elif remainder < 0:
        order = sorted(range(scene_count), key=lambda idx: (raw_counts[idx] - np.floor(raw_counts[idx]), durations[idx]))
        for idx in order:
            if remainder == 0:
                break
            reducible = min(counts[idx] - 1, -remainder)
            if reducible > 0:
                counts[idx] -= reducible
                remainder += reducible
    return counts

def get_video_metadata(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0, 1, 1.0, 0, 0
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    duration_sec = total_frames / fps if fps and fps > 0 else 1.0
    return fps, total_frames, duration_sec, width, height

def extract_video_preview_frame(video_path, out_dir, res_mode="Native", out_fmt="JPG", jpg_quality=92, seek_ratio=0.5, timing_log=None):
    global active_video_process
    os.makedirs(out_dir, exist_ok=True)
    safe_vid_name = re.sub(r'[\\/*?:"<>|]', "", os.path.splitext(os.path.basename(video_path))[0]).replace(" ", "_")
    ext = get_video_output_extension(out_fmt)
    out_path = os.path.join(out_dir, f"{safe_vid_name}_preview{ext}")
    fps, total_frames, duration_sec, _, _ = get_video_metadata(video_path)
    seek_sec = float(np.clip(duration_sec * float(seek_ratio), 0.0, max(0.0, duration_sec - 0.05)))
    target_w = get_video_target_width(res_mode)

    ffmpeg = get_ffmpeg_executable()
    if ffmpeg and not cancel_flag:
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-ss", f"{seek_sec:.3f}",
            "-i", video_path,
            "-frames:v", "1",
        ]
        if target_w:
            cmd.extend(["-vf", f"scale={target_w}:-2:flags=lanczos"])
        if out_fmt == "JPG":
            cmd.extend(["-q:v", ffmpeg_jpeg_quality(jpg_quality)])
        elif out_fmt == "PNG":
            cmd.extend(["-compression_level", "1"])
        cmd.append(out_path)
        proc = None
        try:
            proc = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0)
            active_video_process = proc
            deadline = time.time() + 45.0
            while proc.poll() is None:
                if cancel_flag:
                    terminate_child_process(proc)
                    return ""
                if time.time() > deadline:
                    terminate_child_process(proc)
                    raise subprocess.TimeoutExpired(cmd, 45)
                time.sleep(0.05)
            stdout, stderr = proc.communicate()
            if proc.returncode == 0 and os.path.exists(out_path):
                if timing_log is not None:
                    timing_log.append(f"[VIDEO] ffmpeg preview frame grabbed at {seek_sec:.2f}s.")
                return out_path
            if timing_log is not None:
                timing_log.append(f"[VIDEO] ffmpeg preview frame failed; using OpenCV fallback: {(stderr or '').strip()[-240:]}")
        except Exception as e:
            if timing_log is not None:
                timing_log.append(f"[VIDEO] ffmpeg preview frame failed; using OpenCV fallback: {compact_error(e)}")
        finally:
            if proc is not None and active_video_process is proc:
                active_video_process = None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return ""
    if fps and fps > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(np.clip(seek_sec * fps, 0, total_frames - 1)))
    else:
        cap.set(cv2.CAP_PROP_POS_MSEC, seek_sec * 1000.0)
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return ""
    if target_w and frame.shape[1] != target_w:
        scale = target_w / float(frame.shape[1])
        new_h = int(frame.shape[0] * scale)
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
        frame = cv2.resize(frame, (target_w, new_h), interpolation=interpolation)
    cv2_imwrite(out_path, frame, get_video_write_params(out_fmt, jpg_quality))
    if timing_log is not None:
        timing_log.append(f"[VIDEO] OpenCV preview frame grabbed at {seek_sec:.2f}s.")
    return out_path

def run_ffmpeg_video_extraction(video_path, scene_out_dir, safe_vid_name, extract_mode, extract_val, res_mode, out_fmt, fps, total_frames, duration_sec, jpg_quality, timing_log, start_sec=0.0, end_sec=None, status_label="Using video extractor..."):
    global cancel_flag, active_video_process
    if cancel_flag:
        return False
    ffmpeg = get_ffmpeg_executable()
    if not ffmpeg:
        return False
    if out_fmt not in ("JPG", "PNG", "TIFF"):
        return False

    start_sec = max(0.0, safe_float(start_sec, 0.0))
    segment_duration = max(0.1, safe_float(duration_sec, duration_sec))
    if end_sec is not None:
        segment_duration = max(0.1, safe_float(end_sec, start_sec + segment_duration) - start_sec)

    target_w = get_video_target_width(res_mode)
    if extract_mode == "Target Amount of Frames":
        target_count = max(1, safe_int(extract_val, 300))
        video_filter = f"fps={max(0.001, target_count / max(0.1, segment_duration)):.8f}"
        expected_total = target_count
    else:
        step = max(1, safe_int(extract_val, 10))
        video_filter = f"select=not(mod(n\\,{step}))"
        expected_total = max(1, int(np.ceil(total_frames / float(step))))

    if target_w:
        video_filter += f",scale={target_w}:-2:flags=lanczos"

    ext = get_video_output_extension(out_fmt)
    output_pattern = os.path.join(scene_out_dir, f"{safe_vid_name}_frame_%05d{ext}")
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-stats_period", "0.5",
        "-y",
    ]
    if start_sec > 0:
        cmd.extend(["-ss", f"{start_sec:.3f}"])
    cmd.extend(["-i", video_path])
    if end_sec is not None:
        cmd.extend(["-t", f"{segment_duration:.3f}"])
    cmd.extend(["-vf", video_filter])
    if extract_mode != "Target Amount of Frames":
        cmd.extend(["-vsync", "vfr"])
    if out_fmt == "JPG":
        cmd.extend(["-q:v", ffmpeg_jpeg_quality(jpg_quality)])
    elif out_fmt == "PNG":
        cmd.extend(["-compression_level", "1"])
    cmd.extend(["-progress", "pipe:1", "-nostats", output_pattern])

    timing_log.append(f"[VIDEO] Using ffmpeg extraction: {os.path.basename(ffmpeg)}")
    msg_queue.put(('status', status_label))
    msg_queue.put(('progress', 0, expected_total, "Extracting video frames..."))
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0)
        active_video_process = process
    except Exception as e:
        timing_log.append(f"[VIDEO] ffmpeg extraction could not start; using OpenCV fallback: {compact_error(e)}")
        return False

    try:
        progress_lines = queue.Queue()
        stderr_tail, stderr_lock = [], threading.Lock()

        def read_progress_stream():
            try:
                for line in iter(process.stdout.readline, ""):
                    progress_lines.put(line)
            except Exception:
                pass

        def read_error_stream():
            try:
                for line in iter(process.stderr.readline, ""):
                    clean = line.strip()
                    if clean:
                        with stderr_lock:
                            stderr_tail.append(clean)
                            del stderr_tail[:-8]
            except Exception:
                pass

        stdout_thread = threading.Thread(target=read_progress_stream, daemon=True)
        stderr_thread = threading.Thread(target=read_error_stream, daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        last_emit = time.time()
        last_frame = 0
        last_out_seconds = 0.0
        last_reported = 0
        while True:
            if cancel_flag and process.poll() is None:
                terminate_child_process(process)

            try:
                line = progress_lines.get(timeout=0.2)
            except queue.Empty:
                line = ""

            if line:
                stripped = line.strip()
                if stripped.startswith("frame="):
                    last_frame = max(0, safe_int(stripped.split("=", 1)[1], last_frame))
                elif stripped.startswith("out_time_ms=") or stripped.startswith("out_time_us="):
                    raw_time = stripped.split("=", 1)[1]
                    if raw_time != "N/A":
                        last_out_seconds = max(last_out_seconds, safe_float(raw_time, 0.0) / 1000000.0)
                elif stripped.startswith("out_time="):
                    raw_time = stripped.split("=", 1)[1]
                    if raw_time != "N/A":
                        try:
                            hh, mm, ss = raw_time.split(":")
                            last_out_seconds = max(last_out_seconds, (float(hh) * 3600.0) + (float(mm) * 60.0) + float(ss))
                        except Exception:
                            pass

            time_based = 0
            if last_out_seconds > 0:
                time_based = int(expected_total * min(1.0, last_out_seconds / max(0.1, segment_duration)))
            current = min(expected_total, max(last_frame, time_based, last_reported))
            now = time.time()
            if current > last_reported or now - last_emit > 3.0:
                progress_label = "Extracting video frames..."
                if current <= last_reported and current < expected_total:
                    progress_label = "Extracting video frames... decoding source video"
                msg_queue.put(('progress', current, expected_total, progress_label))
                last_reported = current
                last_emit = now

            if process.poll() is not None and progress_lines.empty():
                break

        return_code = process.wait()
        stdout_thread.join(timeout=0.5)
        stderr_thread.join(timeout=0.5)
        with stderr_lock:
            stderr_tail = list(stderr_tail)
    finally:
        if active_video_process is process:
            active_video_process = None
    if cancel_flag:
        return True
    if return_code != 0:
        timing_log.append(f"[VIDEO] ffmpeg extraction failed with code {return_code}; using OpenCV fallback.")
        for line in stderr_tail:
            timing_log.append(f"[VIDEO][ffmpeg] {line}")
        return False

    written = len([name for name in os.listdir(scene_out_dir) if name.lower().endswith(ext)])
    msg_queue.put(('progress', max(1, written), max(1, written), "Video extraction complete."))
    timing_log.append(f"[VIDEO] ffmpeg extracted {written} frame(s).")
    return True

def run_ffmpeg_seek_video_extraction(video_path, frames_to_extract, fps, res_mode, out_fmt, jpg_quality, timing_log, status_label="Using Fast extraction..."):
    global cancel_flag, active_video_process
    if cancel_flag or not frames_to_extract:
        return True
    ffmpeg = get_ffmpeg_executable()
    if not ffmpeg:
        return False
    if out_fmt not in ("JPG", "PNG", "TIFF"):
        return False

    target_w = get_video_target_width(res_mode)
    total = len(frames_to_extract)
    timing_log.append(f"[VIDEO] Using ffmpeg fast seek extraction: {os.path.basename(ffmpeg)}")
    msg_queue.put(('status', status_label))
    msg_queue.put(('progress', 0, total, "Extracting video frames..."))

    for idx, (frame_index, out_path) in enumerate(frames_to_extract, start=1):
        if cancel_flag:
            return True
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        seek_sec = max(0.0, float(frame_index) / max(0.001, float(fps or 0.0)))
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-y",
            "-ss", f"{seek_sec:.3f}",
            "-i", video_path,
            "-frames:v", "1",
        ]
        if target_w:
            cmd.extend(["-vf", f"scale={target_w}:-2:flags=lanczos"])
        if out_fmt == "JPG":
            cmd.extend(["-q:v", ffmpeg_jpeg_quality(jpg_quality)])
        elif out_fmt == "PNG":
            cmd.extend(["-compression_level", "1"])
        cmd.append(out_path)

        process = None
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0)
            active_video_process = process
            _, stderr = process.communicate()
        except Exception as e:
            timing_log.append(f"[VIDEO] Fast extraction could not continue; using Accurate extraction fallback: {compact_error(e)}")
            return False
        finally:
            if process is not None and active_video_process is process:
                active_video_process = None

        if cancel_flag:
            return True
        if process.returncode != 0 or not os.path.exists(out_path):
            err = compact_error((stderr or "").strip()[-300:])
            timing_log.append(f"[VIDEO] Fast extraction failed at frame {idx}/{total}; using Accurate extraction fallback. {err}")
            return False
        msg_queue.put(('progress', idx, total, "Extracting video frames..."))

    msg_queue.put(('progress', total, total, "Video extraction complete."))
    timing_log.append(f"[VIDEO] Fast extraction wrote {total} frame(s).")
    return True

def extract_video_frames_opencv(video_path, frames_to_extract, res_mode, out_fmt, jpg_quality, timing_log, total_frames):
    global cancel_flag
    if not frames_to_extract or cancel_flag:
        return
    cap = cv2.VideoCapture(video_path)
    target_w = get_video_target_width(res_mode)
    write_params = get_video_write_params(out_fmt, jpg_quality)
    frames_sorted = sorted(frames_to_extract, key=lambda item: item[0])
    total_extract = len(frames_sorted)
    extracted_count = 0
    current_frame = 0
    last_emit = 0.0
    msg_queue.put(('status', "Using OpenCV video extractor..."))

    for f_idx, out_path in frames_sorted:
        if cancel_flag: break
        f_idx = max(0, int(f_idx))
        while current_frame < f_idx and not cancel_flag:
            ok = cap.grab()
            if not ok:
                break
            current_frame += 1
            now = time.time()
            if now - last_emit > 0.75:
                msg_queue.put(('progress', extracted_count, total_extract, f"Extracting video frames... scanning source frame {min(current_frame, total_frames)}/{total_frames}"))
                last_emit = now
        if cancel_flag: break
        ret, frame = cap.read()
        current_frame += 1
        if ret and frame is not None:
            if target_w and frame.shape[1] != target_w:
                scale = target_w / float(frame.shape[1])
                new_h = int(frame.shape[0] * scale)
                interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
                frame = cv2.resize(frame, (target_w, new_h), interpolation=interpolation)
            cv2_imwrite(out_path, frame, write_params)
        extracted_count += 1
        now = time.time()
        if now - last_emit > 0.4 or extracted_count == total_extract:
            msg_queue.put(('progress', extracted_count, total_extract, "Extracting video frames..."))
            last_emit = now
    cap.release()
    timing_log.append(f"[VIDEO] OpenCV sequential extraction wrote {extracted_count} requested frame slot(s).")

def extract_video_frames(video_path, cache_dir, extract_mode, extract_val, do_scenes, res_mode, out_fmt, timing_log, jpg_quality=100, scene_cfg=None):
    global cancel_flag
    t_start = time.time()
    scene_cfg = scene_cfg or {}
    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    safe_vid_name = re.sub(r'[\\/*?:"<>|]', "", video_basename).replace(" ", "_")
    fps, total_frames, duration_sec, _, _ = get_video_metadata(video_path)
    if not fps and total_frames <= 1:
        return
    scene_list = []
    if do_scenes and SCENE_DETECT_AVAILABLE:
        try:
            scene_options = get_scene_detector_options(scene_cfg)
            min_scene_len = max(1, int(round(scene_options["min_scene_seconds"] * max(fps, 1))))
            msg_queue.put(('status', f"Scanning for scene changes ({scene_cfg.get('scene_sensitivity', 'Normal')} sensitivity)..."))
            video = open_video(video_path)
            orig_read = video.read
            frame_counter = [0]
            def cancellable_read(*args, **kwargs):
                if cancel_flag: return False  
                ret = orig_read(*args, **kwargs)
                frame_counter[0] += 1
                if frame_counter[0] % max(1, int(fps)) == 0:
                    msg_queue.put(('progress', frame_counter[0], total_frames, "Scanning video for scenes..."))
                return ret
            video.read = cancellable_read
            sm = SceneManager()
            sm.add_detector(ContentDetector(threshold=scene_options["threshold"], min_scene_len=min_scene_len))
            sm.detect_scenes(video)
            s_list = sm.get_scene_list()
            scene_list = [(s[0].get_seconds(), s[1].get_seconds()) for s in s_list]
            try: video.close()
            except: pass
            if scene_list:
                msg_queue.put(('status', f"Detected {len(scene_list)} scene session(s)."))
        except Exception as e:
            if not cancel_flag:
                msg_queue.put(('status', f"Scene detection failed; using one video session: {compact_error(e)}"))
            scene_list = [(0.0, duration_sec)]
    elif do_scenes and not SCENE_DETECT_AVAILABLE:
        msg_queue.put(('status', "Scene detection is not available; using one video session."))
        scene_list = [(0.0, duration_sec)]
    else: scene_list = [(0.0, duration_sec)]
    if cancel_flag: return
    if not scene_list: scene_list = [(0.0, duration_sec)]
    scene_target_counts = allocate_scene_frame_counts(scene_list, extract_mode, extract_val)
    frames_to_extract = [] 
    ffmpeg_scene_jobs = []
    extraction_method = get_video_extraction_method(scene_cfg, extract_mode)
    for i, (start_sec, end_sec) in enumerate(scene_list):
        scene_duration = max(0.1, end_sec - start_sec)
        start_f = int(start_sec * fps)
        end_f = min(total_frames, int(end_sec * fps))
        scene_len = max(1, end_f - start_f)
        folder_name = f"{safe_vid_name}_Scene_{i+1:03d}" if do_scenes else f"{safe_vid_name}_Frames"
        scene_out_dir = os.path.join(cache_dir, folder_name)
        os.makedirs(scene_out_dir, exist_ok=True)
        if extract_mode == "Target Amount of Frames":
            tgt = scene_target_counts[i] if i < len(scene_target_counts) else 1
            tgt = max(1, min(tgt, scene_len))
            indices = np.linspace(start_f, end_f - 1, tgt, dtype=int)
            ffmpeg_extract_val = str(tgt)
        else: 
            step = max(1, safe_int(extract_val, 10))
            indices = range(start_f, end_f, step)
            ffmpeg_extract_val = str(step)
        ext = ".png" if out_fmt == "PNG" else ".tif" if out_fmt == "TIFF" else ".jpg"
        for idx_count, f_idx in enumerate(indices):
            out_path = os.path.join(scene_out_dir, f"{safe_vid_name}_frame_{idx_count+1:05d}{ext}")
            frames_to_extract.append((f_idx, out_path))
        ffmpeg_scene_jobs.append((scene_out_dir, safe_vid_name, scene_duration, scene_len, start_sec, end_sec, ffmpeg_extract_val, i + 1))
    total_extract = len(frames_to_extract)
    if total_extract > 0 and not cancel_flag:
        used_fast_extractor = False
        timing_log.append(f"[VIDEO] Selected {extraction_method} for {extract_mode} ({total_extract} frame slot(s)).")
        if extraction_method == "Fast extraction":
            used_fast_extractor = run_ffmpeg_seek_video_extraction(
                video_path,
                frames_to_extract,
                fps,
                res_mode,
                out_fmt,
                jpg_quality,
                timing_log,
                status_label="Using Fast extraction...",
            )
        if not used_fast_extractor and not do_scenes:
            scene_out_dir, _, _, _, _, _, _, _ = ffmpeg_scene_jobs[0]
            used_fast_extractor = run_ffmpeg_video_extraction(
                video_path,
                scene_out_dir,
                safe_vid_name,
                extract_mode,
                extract_val,
                res_mode,
                out_fmt,
                fps,
                total_frames,
                duration_sec,
                jpg_quality,
                timing_log,
                status_label="Using Accurate extraction...",
            )
        elif not used_fast_extractor:
            used_fast_extractor = True
            for scene_out_dir, _, scene_duration, scene_len, start_sec, end_sec, ffmpeg_extract_val, scene_number in ffmpeg_scene_jobs:
                if cancel_flag:
                    break
                ok = run_ffmpeg_video_extraction(
                    video_path,
                    scene_out_dir,
                    safe_vid_name,
                    extract_mode,
                    ffmpeg_extract_val,
                    res_mode,
                    out_fmt,
                    fps,
                    scene_len,
                    scene_duration,
                    jpg_quality,
                    timing_log,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    status_label=f"Accurate extraction: scene {scene_number} of {len(ffmpeg_scene_jobs)}...",
                )
                used_fast_extractor = used_fast_extractor and ok
        if not used_fast_extractor and not cancel_flag:
            extract_video_frames_opencv(video_path, frames_to_extract, res_mode, out_fmt, jpg_quality, timing_log, total_frames)
    timing_log.append(f"Pre-Pass 0: Video Extraction Time: {time.time() - t_start:.2f}s")

sift = cv2.SIFT_create(nfeatures=1000)
bf = cv2.BFMatcher(cv2.NORM_L2)
def get_sift_features(filepath):
    try:
        if is_raw_file(filepath):
            with rawpy.imread(filepath) as raw: gray = cv2.cvtColor(raw.postprocess(half_size=True, use_camera_wb=True), cv2.COLOR_RGB2GRAY)
        else:
            img = cv2_imread(filepath)
            if img is None: return None, None
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        scale = min(1.0, 1024 / max(1, max(gray.shape)))
        if scale < 1.0: gray = cv2.resize(gray, (int(gray.shape[1] * scale), int(gray.shape[0] * scale)))
        return sift.detectAndCompute(gray, None)
    except: return None, None

def check_image_bridge(kp1, des1, kp2, des2, min_matches):
    if des1 is None or des2 is None or kp1 is None or kp2 is None or len(des1) < 2 or len(des2) < 2: return False
    try:
        matches = bf.knnMatch(des1, des2, k=2)
        good_matches = [m[0] for m in matches if len(m) == 2 and m[0].distance < 0.70 * m[1].distance]
        if len(good_matches) < min_matches: return False
        src_pts = np.float32([ kp1[m.queryIdx].pt for m in good_matches ]).reshape(-1, 1, 2)
        dst_pts = np.float32([ kp2[m.trainIdx].pt for m in good_matches ]).reshape(-1, 1, 2)
        _, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        return mask is not None and np.sum(mask) >= min_matches
    except: return False

def get_sharpness_isolation_map(files, session_scores, cfg):
    isolation_map = {f: False for f in files}
    valid_scores = [s for s in session_scores.values() if s != 999999]
    if not valid_scores:
        return isolation_map

    blur_mode = cfg.get("blur_mode", "Isolate Blurry Images")
    if "Threshold" in blur_mode or "Move Blurry" in blur_mode or "Blurry" in blur_mode:
        threshold = int(max(1, np.percentile(valid_scores, 95)) * (cfg.get("blur_rel", 35) / 100.0))
        for f, score in session_scores.items():
            isolation_map[f] = (score != 999999 and score < threshold)
    elif "Blurriest" in blur_mode or "Weakest" in blur_mode or "Cluster" in blur_mode:
        sz = max(1, int(cfg.get("cluster_sz", 5)))
        for i in range(0, len(files), sz):
            chunk = files[i:i+sz]
            if len(chunk) == sz:
                worst = min(chunk, key=lambda f: session_scores.get(f, 999999))
                for f in chunk:
                    isolation_map[f] = (f == worst)
    elif "Best X" in blur_mode or "Sharpest" in blur_mode:
        tgt = min(max(1, int(cfg.get("target_frames", 300))), len(files))
        if tgt < len(files):
            chunk_sz, kept = len(files) / float(tgt), set()
            for i in range(tgt):
                chunk = files[int(i * chunk_sz):int((i + 1) * chunk_sz)]
                if chunk:
                    kept.add(max(chunk, key=lambda f: session_scores.get(f, -1)))
            for f in files:
                isolation_map[f] = (f not in kept)
    return isolation_map

def normalize_gray_for_focus(img_gray):
    if img_gray is None:
        return None
    if img_gray.dtype == np.uint16:
        return (img_gray / 257.0).astype(np.uint8)
    if img_gray.dtype != np.uint8:
        return np.clip(img_gray, 0, 255).astype(np.uint8)
    return img_gray

def score_focus_tile(tile):
    if tile.size < 64:
        return 0.0
    tile_f = tile.astype(np.float32)
    if float(np.std(tile_f)) < 3.0:
        return 0.0
    gx = cv2.Sobel(tile_f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(tile_f, cv2.CV_32F, 0, 1, ksize=3)
    tenengrad = float(np.percentile(gx * gx + gy * gy, 90))
    lap_var = float(cv2.Laplacian(tile_f, cv2.CV_32F, ksize=3).var())
    return (0.66 * np.log1p(tenengrad)) + (0.34 * np.log1p(lap_var))

def get_multitile_focus_score(img_gray):
    h, w = img_gray.shape[:2]
    scale = min(1.0, 1600 / float(max(1, max(h, w))))
    if scale < 1.0:
        img_gray = cv2.resize(img_gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        h, w = img_gray.shape[:2]

    tile_scores = []
    for row in range(3):
        y0 = int(row * h / 3)
        y1 = int((row + 1) * h / 3)
        for col in range(3):
            x0 = int(col * w / 3)
            x1 = int((col + 1) * w / 3)
            tile = img_gray[y0:y1, x0:x1]
            if tile.shape[0] < 24 or tile.shape[1] < 24:
                continue
            tile_scores.append(score_focus_tile(tile))

    if not tile_scores:
        return 0
    tile_scores = np.array(tile_scores, dtype=np.float32)
    nonzero = tile_scores[tile_scores > 0]
    if nonzero.size == 0:
        return 0
    robust_score = (0.55 * np.percentile(nonzero, 75)) + (0.30 * np.median(nonzero)) + (0.15 * np.percentile(nonzero, 95))
    return int(max(1, robust_score * 1000.0))

def get_fast_blur_and_lighting(filepath):
    try:
        if is_raw_file(filepath):
            with rawpy.imread(filepath) as raw: img_gray = cv2.cvtColor(raw.postprocess(half_size=True, use_camera_wb=True), cv2.COLOR_RGB2GRAY)
        else: img_gray = cv2_imread(filepath, cv2.IMREAD_GRAYSCALE)
        if img_gray is None: return 999999, 0.0 
        img_gray = normalize_gray_for_focus(img_gray)
        if img_gray is None: return 999999, 0.0
        dark_pixel_ratio = np.sum(img_gray < 75) / float(max(1, img_gray.size))
        return get_multitile_focus_score(img_gray), dark_pixel_ratio
    except: return 999999, 0.0 

def get_yolo_mask(img, model, mask_people, mask_acc, mask_vehicles, device=None):
    h, w = img.shape[:2]
    mask = np.ones((h, w), dtype=np.uint8) * 255 
    target_classes = []
    if mask_people: target_classes.append(0) 
    if mask_acc: target_classes.extend([24, 25, 26, 28, 67]) 
    if mask_vehicles: target_classes.extend([1, 2, 3, 4, 5, 6, 7, 8]) 
    if not target_classes: return mask 
    predict_kwargs = {"verbose": False}
    if device is not None:
        predict_kwargs["device"] = device
    with ai_lock:
        results = model(img, **predict_kwargs)
        sync_accelerator(device)
    for result in results:
        if result.masks is not None:
            masks_data = result.masks.data.cpu().numpy()
            classes = result.boxes.cls.cpu().numpy()
            for i, cls in enumerate(classes):
                if int(cls) in target_classes:
                    m = masks_data[i]
                    mask[cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST) > 0.5] = 0 
    return cv2.erode(mask, np.ones((3,3), np.uint8), iterations=1) 

def get_birefnet_mask(img_rgb, model, device):
    orig_h, orig_w = img_rgb.shape[:2]
    transform = transforms.Compose([transforms.Resize((1024, 1024)), transforms.ToTensor(), transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    input_tensor = transform(Image.fromarray(img_rgb)).unsqueeze(0).to(device)
    with ai_lock:
        with torch.no_grad(): preds = model(input_tensor)[-1].sigmoid().cpu()
    mask = (preds[0].squeeze().numpy() > 0.5).astype(np.uint8) * 255
    return cv2.resize(mask, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)

def get_maskformer_sky_mask(img_rgb, processor, model, device):
    orig_h, orig_w = img_rgb.shape[:2]
    with ai_lock:
        with torch.no_grad():
            inputs = processor(images=Image.fromarray(img_rgb), return_tensors="pt").to(device)
            outputs = model(**inputs)
            predicted_map = processor.post_process_semantic_segmentation(outputs, target_sizes=[(orig_h, orig_w)])[0]
    pred_map_np = predicted_map.cpu().numpy()
    mask = np.ones((orig_h, orig_w), dtype=np.uint8) * 255
    sky_indices = [int(idx) for idx, lbl in model.config.id2label.items() if "sky" in lbl.lower() or "cloud" in lbl.lower()]
    if not sky_indices: sky_indices = [105, 106, 119] 
    mask[np.isin(pred_map_np, sky_indices)] = 0
    _, mask = cv2.threshold(cv2.GaussianBlur(mask, (3, 3), 0), 127, 255, cv2.THRESH_BINARY)
    return mask

def apply_denoise(img_rgb, method):
    if "None" in method: return img_rgb
    is_16bit = img_rgb.dtype == np.uint16
    max_val = 65535.0 if is_16bit else 255.0
    img_lab = cv2.cvtColor(img_rgb.astype(np.float32) / max_val, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(img_lab)
    merged = cv2.merge((l, cv2.bilateralFilter(a, 9, 10.0, 15.0), cv2.bilateralFilter(b, 9, 10.0, 15.0)))
    return np.clip(cv2.cvtColor(merged, cv2.COLOR_LAB2RGB) * max_val, 0, max_val).astype(np.uint16 if is_16bit else np.uint8)

def apply_tone_mapping(img_rgb, method, clahe_clip, clahe_grid, clahe_sat_boost=False):
    if "None" in method: return img_rgb
    method_text = str(method)
    is_16bit = img_rgb.dtype == np.uint16
    max_val = 65535.0 if is_16bit else 255.0

    if "CLAHE" in method_text or "Local Contrast Boost" in method_text:
        clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(clahe_grid, clahe_grid))
        l, a, b = cv2.split(cv2.cvtColor(img_rgb.astype(np.float32) / max_val, cv2.COLOR_RGB2LAB))
        l_clahe_16 = clahe.apply(np.clip(l * (65535.0 / 100.0), 0, 65535).astype(np.uint16))
        l_norm = l / 100.0
        blend = np.clip((l_norm - 0.5) / 0.3, 0.0, 1.0)
        l_final_norm = (l_clahe_16.astype(np.float32) / 65535.0) * (1.0 - blend) + l_norm * blend
        res_rgb = np.clip(cv2.cvtColor(cv2.merge((np.clip(l_final_norm * 100.0, 0, 100), a, b)), cv2.COLOR_LAB2RGB) * max_val, 0, max_val).astype(np.uint16 if is_16bit else np.uint8)
        if clahe_sat_boost:
            hsv = cv2.cvtColor(res_rgb.astype(np.float32) / max_val, cv2.COLOR_RGB2HSV)
            hue, sat, val = cv2.split(hsv)
            sat = np.clip(sat * 1.20, 0, 1.0) 
            res_rgb = np.clip(cv2.cvtColor(cv2.merge((hue, sat, val)), cv2.COLOR_HSV2RGB) * max_val, 0, max_val).astype(np.uint16 if is_16bit else np.uint8)
        return res_rgb
    elif "Exposure Fusion Look" in method_text:
        img_float = img_rgb.astype(np.float32) / max_val
        img_under_8 = (np.clip(np.power(img_float, 2.0), 0, 1) * 255.0).astype(np.uint8)
        img_base_8 = (img_float * 255.0).astype(np.uint8)
        img_over_8 = (np.clip(np.power(img_float, 0.5), 0, 1) * 255.0).astype(np.uint8)
        res = cv2.createMergeMertens().process([img_under_8, img_base_8, img_over_8])
        return np.clip(res * max_val, 0, max_val).astype(np.uint16 if is_16bit else np.uint8)
    elif "ACR Parametric" in method_text:
        l, a, b = cv2.split(cv2.cvtColor(img_rgb.astype(np.float32) / max_val, cv2.COLOR_RGB2LAB))
        l_norm = l / 100.0; l_new = np.copy(l_norm)
        shadow_mask, high_mask = l_norm < 0.4, l_norm > 0.7
        blend_shadow = (0.4 - l_norm[shadow_mask]) / 0.4
        l_new[shadow_mask] = l_norm[shadow_mask] * (1.0 - blend_shadow) + (l_norm[shadow_mask] ** 0.75) * blend_shadow
        blend_high = (l_norm[high_mask] - 0.7) / 0.3
        l_new[high_mask] = l_norm[high_mask] * (1.0 - blend_high) + (l_norm[high_mask] ** 1.25) * blend_high
        boost = np.clip(1.0 + ((l_new - l_norm) * 0.5), 1.0, 1.2)
        res = cv2.cvtColor(cv2.merge((np.clip(l_new * 100.0, 0, 100), a * boost, b * boost)), cv2.COLOR_LAB2RGB)
        return np.clip(res * max_val, 0, max_val).astype(np.uint16 if is_16bit else np.uint8)
    return img_rgb

def apply_scan_contrast_controls(img_rgb, controls):
    if not controls or not controls.get("enabled", False):
        return img_rgb
    is_16bit = img_rgb.dtype == np.uint16
    max_val = 65535.0 if is_16bit else 255.0
    strength = np.clip(float(controls.get("strength", 50)) / 100.0, 0.0, 1.0)
    shadows = np.clip(float(controls.get("shadows", 0)) / 100.0, -1.0, 1.0) * strength
    highlights = np.clip(float(controls.get("highlights", 0)) / 100.0, -1.0, 1.0) * strength
    midtones = np.clip(float(controls.get("midtones", 0)) / 100.0, -1.0, 1.0) * strength
    protect_highlights = bool(controls.get("protect_highlights", True))

    lab = cv2.cvtColor(img_rgb.astype(np.float32) / max_val, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    l_norm = np.clip(l / 100.0, 0.0, 1.0)
    original_l = l_norm.copy()

    shadow_weight = np.clip((0.58 - l_norm) / 0.58, 0.0, 1.0) ** 1.35
    highlight_weight = np.clip((l_norm - 0.42) / 0.58, 0.0, 1.0) ** 1.35
    midtone_weight = np.clip(1.0 - np.abs(l_norm - 0.5) / 0.5, 0.0, 1.0) ** 0.85

    l_norm = l_norm + (shadow_weight * shadows * 0.34)
    l_norm = l_norm + (highlight_weight * highlights * 0.28)
    l_norm = l_norm + (midtone_weight * midtones * 0.25)

    if protect_highlights:
        bright = original_l > 0.88
        l_norm[bright] = np.minimum(l_norm[bright], original_l[bright] + 0.035)

    res = cv2.cvtColor(cv2.merge((np.clip(l_norm * 100.0, 0, 100), a, b)), cv2.COLOR_LAB2RGB)
    return np.clip(res * max_val, 0, max_val).astype(np.uint16 if is_16bit else np.uint8)

def apply_feature_sharpening(img_rgb, controls=None):
    controls = controls or {}
    amount = np.clip(safe_float(controls.get("amount", 60), 60), 0, 250) / 100.0
    radius = np.clip(safe_float(controls.get("radius", 0.9), 0.9), 0.2, 5.0)
    threshold = np.clip(safe_float(controls.get("threshold", 4), 4), 0, 80)
    if amount <= 0:
        return img_rgb

    is_16bit = img_rgb.dtype == np.uint16
    max_val = 65535.0 if is_16bit else 255.0
    l, a, b = cv2.split(cv2.cvtColor(img_rgb.astype(np.float32) / max_val, cv2.COLOR_RGB2LAB))

    blurred_l = cv2.GaussianBlur(l, (0, 0), sigmaX=radius, sigmaY=radius)
    detail = l - blurred_l
    if threshold > 0:
        threshold_l = threshold * (100.0 / 255.0)
        abs_detail = np.abs(detail)
        soft_mask = np.clip((abs_detail - threshold_l) / max(threshold_l, 1e-5), 0.0, 1.0)
        detail = detail * soft_mask

    l_sharp = np.clip(l + (detail * amount), 0, 100)
    res = cv2.cvtColor(cv2.merge((l_sharp, a, b)), cv2.COLOR_LAB2RGB)
    return np.clip(res * max_val, 0, max_val).astype(np.uint16 if is_16bit else np.uint8)

def apply_acr_sharpening(img_rgb):
    return apply_feature_sharpening(img_rgb)

def get_available_output_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    idx = 1
    while True:
        candidate = f"{base}_{idx:03d}{ext}"
        if not os.path.exists(candidate):
            return candidate
        idx += 1

def clean_relative_output_part(path_part):
    part = os.path.normpath(str(path_part or "")).replace("\\", os.sep).replace("/", os.sep)
    if part in ("", ".", os.curdir):
        return ""
    if os.path.isabs(part):
        part = os.path.basename(part)
    safe_parts = [piece for piece in part.split(os.sep) if piece not in ("", ".", "..")]
    return os.path.join(*safe_parts) if safe_parts else ""

def resolve_session_output_base(output_dir, session_name, cfg):
    rel_session = clean_relative_output_part(session_name)
    if not rel_session:
        return output_dir

    input_type = cfg.get("input_type", "image_folder")
    subfolder_mode = cfg.get("subfolder_mode", "recursive")
    keep_structure = bool(cfg.get("keep_folder_structure", False))
    do_sort = bool(cfg.get("do_sort", False))

    should_use_session_folder = (
        input_type != "image_folder"
        or do_sort
        or subfolder_mode == "sessions"
        or keep_structure
    )
    return os.path.join(output_dir, rel_session) if should_use_session_folder else output_dir

def build_completion_message(source_items_handled, masks_created, processed_images_created, originals_routed):
    return (
        f"Complete! {source_items_handled} source items handled.\n"
        f"Masks created: {masks_created}\n"
        f"Processed images created: {processed_images_created}\n"
        f"Originals moved/copied: {originals_routed}"
    )

def route_original_file(filepath, final_dest, preserve_originals=False, timing_log=None):
    os.makedirs(final_dest, exist_ok=True)
    desired_path = os.path.join(final_dest, os.path.basename(filepath))
    if os.path.normcase(os.path.abspath(filepath)) == os.path.normcase(os.path.abspath(desired_path)):
        return desired_path

    out_path = get_available_output_path(desired_path)
    if preserve_originals:
        shutil.copy2(filepath, out_path)
        return out_path

    last_error = None
    for attempt in range(5):
        try:
            os.rename(filepath, out_path)
            return out_path
        except Exception as e:
            last_error = e
            if os.path.exists(out_path):
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception as remove_error:
                        if timing_log is not None:
                            timing_log.append(f"[ROUTE] Move copied {os.path.basename(filepath)}, but Windows kept the source locked: {compact_error(remove_error)}")
                return out_path
            time.sleep(0.15 * (attempt + 1))

    try:
        shutil.copy2(filepath, out_path)
        try:
            os.remove(filepath)
        except Exception as remove_error:
            if timing_log is not None:
                timing_log.append(f"[ROUTE] Move fallback copied {os.path.basename(filepath)} but could not remove the source: {compact_error(remove_error)}")
        return out_path
    except Exception as copy_error:
        if timing_log is not None:
            timing_log.append(f"[ROUTE] Could not route {os.path.basename(filepath)}: {compact_error(copy_error)}")
            if last_error is not None:
                timing_log.append(f"[ROUTE] Last move error: {compact_error(last_error)}")
        raise

def process_single_image(filepath, base_dest, is_video_input, do_yolo, do_subj, do_sky, ev_boost, tone_method, denoise_method, clahe_clip, clahe_grid, clahe_sat_boost, do_sharp, yolo_people, yolo_acc, yolo_vehicles, mask_output_type, out_fmt, yolo_model, subj_model, sky_processor, sky_model, device, folder_dict, is_blurry=False, return_path_only=False, jpg_quality=100, output_exists_mode="Overwrite", invert_masks=False, contrast_controls=None, preview_layers=False, mask_360_bottom=False, is_360_view=False, sharpen_controls=None):
    global cancel_flag
    if cancel_flag: return 0, 0, None, "Cancelled"
    t_start = time.time()
    filename = os.path.basename(filepath)
    orig_h, orig_w = 0, 0
    img_rgb_full = None
    linear_ev_multiplier = 2.0 ** ev_boost
    current_step = "starting"
    active_ai = do_yolo or do_subj or do_sky
    
    try:
        current_step = "reading image dimensions"
        if is_raw_file(filepath):
            with rawpy.imread(filepath) as raw:
                active_h, active_w = raw.sizes.height, raw.sizes.width
                orig_h, orig_w = (active_w, active_h) if raw.sizes.flip >= 4 else (active_h, active_w)
        else:
            temp_img = cv2_imread(filepath, cv2.IMREAD_UNCHANGED)
            if temp_img is None: return 0, 0, None, f"Error: Cannot read {filename}"
            if len(temp_img.shape) == 2: temp_img = cv2.cvtColor(temp_img, cv2.COLOR_GRAY2BGR)
            elif len(temp_img.shape) == 3 and temp_img.shape[2] == 4: temp_img = cv2.cvtColor(temp_img, cv2.COLOR_BGRA2BGR)
            orig_h, orig_w = temp_img.shape[:2]

        mask_dict = {}
        needs_mask_image = do_yolo or do_subj or do_sky or (mask_360_bottom and is_360_view)
        if needs_mask_image:
            current_step = "loading mask preview image"
            if is_raw_file(filepath):
                with rawpy.imread(filepath) as raw: ai_img_bgr = cv2.cvtColor(raw.postprocess(half_size=True, use_camera_wb=True), cv2.COLOR_RGB2BGR)
            else: ai_img_bgr = cv2_imread(filepath)
            if ai_img_bgr is None:
                return 0, 0, None, f"Error: Cannot read {filename}"
            if do_yolo:
                current_step = f"YOLO mask on {device}"
                if cancel_flag: return 0, 0, None, "Cancelled"
                mask_dict["YOLO"] = get_yolo_mask(ai_img_bgr, yolo_model, yolo_people, yolo_acc, yolo_vehicles, device)
            if do_sky:
                current_step = f"MaskFormer sky mask on {device}"
                if cancel_flag: return 0, 0, None, "Cancelled"
                mask_dict["Sky"] = get_maskformer_sky_mask(cv2.cvtColor(ai_img_bgr, cv2.COLOR_BGR2RGB), sky_processor, sky_model, device)
            if do_subj:
                current_step = f"BiRefNet subject mask on {device}"
                if cancel_flag: return 0, 0, None, "Cancelled"
                mask_dict["Subject"] = get_birefnet_mask(cv2.cvtColor(ai_img_bgr, cv2.COLOR_BGR2RGB), subj_model, device)
            if mask_360_bottom and is_360_view:
                current_step = "360 bottom mask"
                bottom_mask = make_360_bottom_mask(ai_img_bgr.shape[0], ai_img_bgr.shape[1], filepath)
                if np.any(bottom_mask == 0):
                    mask_dict["360Bottom"] = bottom_mask

        if cancel_flag: return 0, 0, None, "Cancelled"
        current_step = "processing output image"
        contrast_enabled = bool(contrast_controls and contrast_controls.get("enabled", False))
        transparent_mask_output = is_transparent_mask_output(mask_output_type)
        needs_processing = ("None" not in tone_method) or ("None" not in denoise_method) or transparent_mask_output or do_sharp or (ev_boost > 0.0) or contrast_enabled
        
        if needs_processing: 
            out_bps = 16 if out_fmt == "TIFF" else 8
            if is_raw_file(filepath):
                with rawpy.imread(filepath) as raw: img_rgb_full = raw.postprocess(use_camera_wb=True, output_bps=out_bps, exp_shift=linear_ev_multiplier)
            else:
                temp_img2 = cv2.cvtColor(cv2_imread(filepath), cv2.COLOR_BGR2RGB)
                if ev_boost > 0.0:
                    is_16bit = temp_img2.dtype == np.uint16
                    max_val = 65535.0 if is_16bit else 255.0
                    img_lin = np.clip(np.power(temp_img2.astype(np.float32) / max_val, 2.2) * linear_ev_multiplier, 0, 1)
                    img_rgb_full = np.clip(np.power(img_lin, 1/2.2) * max_val, 0, max_val).astype(np.uint16 if is_16bit else np.uint8)
                else: img_rgb_full = temp_img2
            if cancel_flag: return 0, 0, None, "Cancelled"
            processed_img = img_rgb_full.copy()
            processed_img = apply_denoise(processed_img, denoise_method)
            processed_img = apply_tone_mapping(processed_img, tone_method, clahe_clip, clahe_grid, clahe_sat_boost)
            processed_img = apply_scan_contrast_controls(processed_img, contrast_controls)
            if do_sharp: processed_img = apply_feature_sharpening(processed_img, sharpen_controls) 
            if out_fmt != "TIFF" and processed_img.dtype == np.uint16: processed_img = (processed_img / 257.0).astype(np.uint8)
                
        if cancel_flag: return 0, 0, None, "Cancelled"
        current_step = "writing outputs"
        write_params = [int(cv2.IMWRITE_PNG_COMPRESSION), 1] if out_fmt == "PNG" else [int(cv2.IMWRITE_TIFF_COMPRESSION), 1] if out_fmt == "TIFF" else [int(cv2.IMWRITE_JPEG_QUALITY), int(jpg_quality)]
        base, _ = os.path.splitext(filename)
        masks_created_this_img, process_created = 0, 0
        primary_out_path = ""
        metadata_result = None
        
        f_mask, f_proc, f_blur, f_subj = folder_dict["mask"], folder_dict["proc"], folder_dict["blur"], folder_dict["subj"]
        f_proc_blur = folder_dict.get("proc_blur", f"{f_proc}_Blurry")
        f_trans_env, f_trans_subj = folder_dict["trans_env"], folder_dict["trans_subj"]
        env_alpha_mask, subj_alpha_mask = None, None
        
        if "YOLO" in mask_dict or "Sky" in mask_dict or "360Bottom" in mask_dict:
            env_alpha_mask = np.ones((orig_h, orig_w), dtype=np.uint8) * 255
            if "YOLO" in mask_dict: env_alpha_mask = cv2.bitwise_and(env_alpha_mask, cv2.resize(mask_dict["YOLO"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST))
            if "Sky" in mask_dict: env_alpha_mask = cv2.bitwise_and(env_alpha_mask, cv2.resize(mask_dict["Sky"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST))
            if "360Bottom" in mask_dict: env_alpha_mask = cv2.bitwise_and(env_alpha_mask, cv2.resize(mask_dict["360Bottom"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST))
        if "Subject" in mask_dict:
            subj_alpha_mask = cv2.resize(mask_dict["Subject"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)

        if needs_processing and not transparent_mask_output:
            dest = os.path.join(base_dest, f_proc_blur if is_blurry else f_proc)
            os.makedirs(dest, exist_ok=True)
            create_ignore_marker(dest)
            ext = ".tif" if out_fmt == "TIFF" else (".png" if out_fmt == "PNG" else ".jpg")
            out_path = os.path.join(dest, f"{base}{ext}")
            written_path = cv2_imwrite_with_mode(out_path, cv2.cvtColor(processed_img, cv2.COLOR_RGB2BGR), write_params, output_exists_mode)
            if written_path:
                process_created += 1; primary_out_path = written_path

        if transparent_mask_output:
            rgb_base = processed_img if needs_processing else img_rgb_full
            if env_alpha_mask is not None:
                rgba_env = cv2.cvtColor(rgb_base, cv2.COLOR_RGB2RGBA)
                rgba_env[:, :, 3] = (env_alpha_mask.astype(np.uint16) * 257) if rgba_env.dtype == np.uint16 else env_alpha_mask 
                dest_env = os.path.join(base_dest, f"{f_blur}_{f_trans_env}" if is_blurry else f_trans_env)
                os.makedirs(dest_env, exist_ok=True)
                create_ignore_marker(dest_env)
                out_path_env = os.path.join(dest_env, f"{base}.png")
                written_path = cv2_imwrite_with_mode(out_path_env, cv2.cvtColor(rgba_env, cv2.COLOR_RGBA2BGRA), [int(cv2.IMWRITE_PNG_COMPRESSION), 1], output_exists_mode)
                if written_path:
                    masks_created_this_img += 1; primary_out_path = written_path
            if subj_alpha_mask is not None:
                rgba_subj = cv2.cvtColor(rgb_base, cv2.COLOR_RGB2RGBA)
                rgba_subj[:, :, 3] = (subj_alpha_mask.astype(np.uint16) * 257) if rgba_subj.dtype == np.uint16 else subj_alpha_mask 
                dest_subj = os.path.join(base_dest, f"{f_blur}_{f_trans_subj}" if is_blurry else f_trans_subj)
                os.makedirs(dest_subj, exist_ok=True)
                create_ignore_marker(dest_subj)
                out_path_subj = os.path.join(dest_subj, f"{base}.png")
                written_path = cv2_imwrite_with_mode(out_path_subj, cv2.cvtColor(rgba_subj, cv2.COLOR_RGBA2BGRA), [int(cv2.IMWRITE_PNG_COMPRESSION), 1], output_exists_mode)
                if written_path:
                    masks_created_this_img += 1; primary_out_path = written_path
            
        elif "Unified" in mask_output_type:
            if env_alpha_mask is not None:
                dest = os.path.join(base_dest, f"{f_blur}_{f_mask}" if is_blurry else f_mask)
                os.makedirs(dest, exist_ok=True)
                create_ignore_marker(dest)
                mask_to_write = 255 - env_alpha_mask if invert_masks else env_alpha_mask
                written_path = cv2_imwrite_with_mode(os.path.join(dest, f"{base}.jpg"), mask_to_write, [int(cv2.IMWRITE_JPEG_QUALITY), 95], output_exists_mode)
                if written_path:
                    masks_created_this_img += 1
            if subj_alpha_mask is not None:
                dest = os.path.join(base_dest, f"{f_blur}_{f_subj}" if is_blurry else f_subj)
                os.makedirs(dest, exist_ok=True)
                create_ignore_marker(dest)
                mask_to_write = 255 - subj_alpha_mask if invert_masks else subj_alpha_mask
                written_path = cv2_imwrite_with_mode(os.path.join(dest, f"{base}.jpg"), mask_to_write, [int(cv2.IMWRITE_JPEG_QUALITY), 95], output_exists_mode)
                if written_path:
                    masks_created_this_img += 1
        
        elif "Separate" in mask_output_type:
            if "YOLO" in mask_dict:
                dest = os.path.join(base_dest, f"{f_blur}_{f_mask}_YOLO" if is_blurry else f"{f_mask}_YOLO")
                os.makedirs(dest, exist_ok=True)
                create_ignore_marker(dest)
                mask_to_write = cv2.resize(mask_dict["YOLO"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)
                if invert_masks: mask_to_write = 255 - mask_to_write
                written_path = cv2_imwrite_with_mode(os.path.join(dest, f"{base}.jpg"), mask_to_write, [int(cv2.IMWRITE_JPEG_QUALITY), 95], output_exists_mode)
                if written_path:
                    masks_created_this_img += 1
            if "Sky" in mask_dict:
                dest = os.path.join(base_dest, f"{f_blur}_{f_mask}_Sky" if is_blurry else f"{f_mask}_Sky")
                os.makedirs(dest, exist_ok=True)
                create_ignore_marker(dest)
                mask_to_write = cv2.resize(mask_dict["Sky"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)
                if invert_masks: mask_to_write = 255 - mask_to_write
                written_path = cv2_imwrite_with_mode(os.path.join(dest, f"{base}.jpg"), mask_to_write, [int(cv2.IMWRITE_JPEG_QUALITY), 95], output_exists_mode)
                if written_path:
                    masks_created_this_img += 1
            if "360Bottom" in mask_dict:
                dest = os.path.join(base_dest, f"{f_blur}_{f_mask}_360Bottom" if is_blurry else f"{f_mask}_360Bottom")
                os.makedirs(dest, exist_ok=True)
                create_ignore_marker(dest)
                mask_to_write = cv2.resize(mask_dict["360Bottom"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)
                if invert_masks: mask_to_write = 255 - mask_to_write
                written_path = cv2_imwrite_with_mode(os.path.join(dest, f"{base}.jpg"), mask_to_write, [int(cv2.IMWRITE_JPEG_QUALITY), 95], output_exists_mode)
                if written_path:
                    masks_created_this_img += 1
            if subj_alpha_mask is not None:
                dest = os.path.join(base_dest, f"{f_blur}_{f_subj}" if is_blurry else f_subj)
                os.makedirs(dest, exist_ok=True)
                create_ignore_marker(dest)
                mask_to_write = 255 - subj_alpha_mask if invert_masks else subj_alpha_mask
                written_path = cv2_imwrite_with_mode(os.path.join(dest, f"{base}.jpg"), mask_to_write, [int(cv2.IMWRITE_JPEG_QUALITY), 95], output_exists_mode)
                if written_path:
                    masks_created_this_img += 1

        if preview_layers:
            def write_preview_layer(folder_name, mask):
                nonlocal masks_created_this_img
                dest = os.path.join(base_dest, folder_name)
                os.makedirs(dest, exist_ok=True)
                create_ignore_marker(dest)
                layer_to_write = 255 - mask if invert_masks else mask
                written_path = cv2_imwrite_with_mode(os.path.join(dest, f"{base}.jpg"), layer_to_write, [int(cv2.IMWRITE_JPEG_QUALITY), 95], "Skip existing")
                if written_path:
                    masks_created_this_img += 1

            if env_alpha_mask is not None and "Unified" not in mask_output_type:
                write_preview_layer(f_mask, env_alpha_mask)
            if "YOLO" in mask_dict and "Separate" not in mask_output_type:
                write_preview_layer(f"{f_mask}_YOLO", cv2.resize(mask_dict["YOLO"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST))
            if "Sky" in mask_dict and "Separate" not in mask_output_type:
                write_preview_layer(f"{f_mask}_Sky", cv2.resize(mask_dict["Sky"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST))
            if "360Bottom" in mask_dict and "Separate" not in mask_output_type:
                write_preview_layer(f"{f_mask}_360Bottom", cv2.resize(mask_dict["360Bottom"], (orig_w, orig_h), interpolation=cv2.INTER_NEAREST))
            if subj_alpha_mask is not None and "Separate" not in mask_output_type and "Unified" not in mask_output_type:
                write_preview_layer(f_subj, subj_alpha_mask)
                
        ai_label = device if active_ai else "none"
        timing_str = f"[{filename}] Processed in {time.time() - t_start:.2f}s (AI device: {ai_label})"
        if return_path_only: return primary_out_path
        return masks_created_this_img, process_created, metadata_result, timing_str

    except Exception as e:
        error_msg = f"[{filename}] FAILED during {current_step}: {compact_error(e)}"
        if active_ai:
            error_msg += f"\nAI device: {device}"
        if is_accelerator_error(e):
            try:
                sync_accelerator(device)
            except Exception:
                pass
        error_msg += "\n" + traceback.format_exc(limit=8)
        print(error_msg)
        return 0, 0, None, error_msg

def build_ai_pipeline(cfg):
    global AI_RUNTIME_DEVICE
    do_people, do_acc, do_vehicle = cfg["yolo_people"], cfg["yolo_acc"], cfg["yolo_vehicle"]
    do_yolo = do_people or do_acc or do_vehicle
    do_sky = cfg["do_sky"]
    do_subj = cfg["do_subj"]
    yolo_model, subj_model, sky_processor, sky_model, device = None, None, None, None, "cpu"
    
    if (do_yolo or do_subj or do_sky) and not AI_LIBRARIES_LOADED:
        msg_queue.put(('status', "AI libraries failed to load. Mask generation is disabled for this run."))
        do_yolo, do_sky, do_subj = False, False, False

    if (do_yolo or do_subj or do_sky) and AI_LIBRARIES_LOADED:
        msg_queue.put(('status', "Selecting AI runtime..."))
        device = select_ai_device()
        msg_queue.put(('status', f"Loading AI Models on {device.upper()}..."))

        def move_loaded_models_to_cpu():
            for model in (yolo_model, sky_model, subj_model):
                if model is not None:
                    try: model.to("cpu")
                    except Exception: pass
            try: torch.cuda.empty_cache()
            except Exception: pass

        def warmup_loaded_models():
            warmup_bgr = np.zeros((256, 256, 3), dtype=np.uint8)
            warmup_rgb = cv2.cvtColor(warmup_bgr, cv2.COLOR_BGR2RGB)
            if do_yolo and yolo_model is not None:
                get_yolo_mask(warmup_bgr, yolo_model, do_people, do_acc, do_vehicle, device)
                sync_accelerator(device)
            if do_sky and sky_processor is not None and sky_model is not None:
                get_maskformer_sky_mask(warmup_rgb, sky_processor, sky_model, device)
                sync_accelerator(device)
            if do_subj and subj_model is not None:
                get_birefnet_mask(warmup_rgb, subj_model, device)
                sync_accelerator(device)
            
        if do_yolo:
            def load_yolo(target_device):
                model_path = os.path.join(DATA_ROOT, "_AI_Models", "YOLO", "yolo26n-seg.pt")
                if not os.path.exists(model_path): model_path = os.path.join(DATA_ROOT, "_AI_Models", "YOLO", "yolov8n-seg.pt")
                return YOLO(model_path).to(target_device)

            try:
                yolo_model = load_yolo(device)
            except Exception as e: 
                if device != "cpu" and is_accelerator_error(e):
                    try:
                        yolo_model, device = retry_on_cpu(load_yolo, "YOLO", e)
                        move_loaded_models_to_cpu()
                    except Exception as cpu_e:
                        device = "cpu"
                        msg_queue.put(('status', f"YOLO failed to load and was disabled: {compact_error(cpu_e)[:180]}")); do_yolo = False
                else:
                    msg_queue.put(('status', f"YOLO failed to load and was disabled: {compact_error(e)[:180]}")); do_yolo = False
        if do_sky:
            def load_sky(target_device):
                sky_dir = os.path.join(DATA_ROOT, "_AI_Models", "MaskFormer")
                processor = MaskFormerImageProcessor.from_pretrained(sky_dir, local_files_only=True)
                model = MaskFormerForInstanceSegmentation.from_pretrained(sky_dir, local_files_only=True).to(target_device, dtype=torch.float32)
                model.eval()
                return processor, model

            try:
                sky_processor, sky_model = load_sky(device)
            except Exception as e: 
                if device != "cpu" and is_accelerator_error(e):
                    try:
                        move_loaded_models_to_cpu()
                        (sky_processor, sky_model), device = retry_on_cpu(load_sky, "MaskFormer", e)
                    except Exception as cpu_e:
                        device = "cpu"
                        msg_queue.put(('status', f"MaskFormer failed to load and was disabled: {compact_error(cpu_e)[:180]}")); do_sky = False
                else:
                    msg_queue.put(('status', f"MaskFormer failed to load and was disabled: {compact_error(e)[:180]}")); do_sky = False
        if do_subj:
            def load_subject(target_device):
                model = AutoModelForImageSegmentation.from_pretrained(os.path.join(DATA_ROOT, "_AI_Models", "BiRefNet"), trust_remote_code=True, local_files_only=True).to(target_device, dtype=torch.float32)
                model.eval()
                return model

            try:
                subj_model = load_subject(device)
            except Exception as e:
                if device != "cpu" and is_accelerator_error(e):
                    try:
                        move_loaded_models_to_cpu()
                        subj_model, device = retry_on_cpu(load_subject, "BiRefNet", e)
                    except Exception as cpu_e:
                        device = "cpu"
                        msg_queue.put(('status', f"BiRefNet failed to load and was disabled: {compact_error(cpu_e)[:180]}")); do_subj = False
                else:
                    msg_queue.put(('status', f"BiRefNet failed to load and was disabled: {compact_error(e)[:180]}")); do_subj = False

        if device != "cpu" and (do_yolo or do_sky or do_subj):
            try:
                msg_queue.put(('status', "Testing AI models on the selected accelerator..."))
                warmup_loaded_models()
            except Exception as e:
                if is_accelerator_error(e):
                    msg_queue.put(('status', f"AI model test failed on {device}; using CPU masks instead. {compact_error(e)[:180]}"))
                    device = "cpu"
                    move_loaded_models_to_cpu()
                    try:
                        msg_queue.put(('status', "Testing AI models on CPU..."))
                        warmup_loaded_models()
                    except Exception as cpu_e:
                        msg_queue.put(('status', f"CPU AI model test failed; masks may be disabled by model errors: {compact_error(cpu_e)[:180]}"))
                else:
                    msg_queue.put(('status', f"AI model warm-up failed: {compact_error(e)[:180]}"))
            
    AI_RUNTIME_DEVICE = device
    return do_yolo, do_subj, do_sky, yolo_model, subj_model, sky_processor, sky_model, device

def handle_cancel(msg="Processing safely aborted."):
    msg_queue.put(('status', "Cancelled by user."))
    msg_queue.put(('done', msg))

def run_tests_backend(cfg):
    global cancel_flag
    try:
        initialize_ai_libraries()
        out_dir = cfg["output_dir"]
        in_type = cfg["input_type"]
        if out_dir == "" or not os.path.isdir(out_dir):
            msg_queue.put(('error', "Please select a valid Output Folder first.")); return
        images_to_process, base_dest = [], ""
        folder_dict = cfg["folder_dict"]

        if cfg["mode"] == "single":
            if in_type in ["video_file", "folder_360"]:
                filepath = cfg["input_path"]
                if not os.path.isfile(filepath): return
                msg_queue.put(('progress', 1, 1, "Extracting Single Test Frame..."))
                cap = cv2.VideoCapture(filepath)
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) // 2) 
                ret, frame = cap.read()
                cap.release()
                if not ret: return
                base_dest = os.path.join(out_dir, "_Single_Image_Test")
                os.makedirs(base_dest, exist_ok=True); create_ignore_marker(base_dest)
                temp_img_path = os.path.join(base_dest, "temp_video_frame.jpg")
                cv2_imwrite(temp_img_path, frame)
                if in_type == "folder_360":
                    msg_queue.put(('status', "Unrolling 360 Test Frame..."))
                    extract_360_views(temp_img_path, base_dest, cfg["out_fmt"], cfg.get("jpg_quality", 100), cfg.get("view_360_mode", "Standard 14 views"), cfg.get("include_360_bottom_views", True))
                    ext = ".png" if cfg["out_fmt"]=="PNG" else ".tif" if cfg["out_fmt"]=="TIFF" else ".jpg"
                    views = sorted([os.path.join(base_dest, name) for name in os.listdir(base_dest) if name.startswith("temp_video_frame_v") and name.lower().endswith(ext)])
                    if views:
                        images_to_process.append(views[0])
                else: images_to_process.append(temp_img_path)
            else:
                filepath = cfg.get("single_test_path", "")
                if not filepath: return
                images_to_process.append(filepath)
                base_dest = os.path.join(out_dir, "_Single_Image_Test")
                os.makedirs(base_dest, exist_ok=True); create_ignore_marker(base_dest)
                
        elif cfg["mode"] == "speed":
            if in_type in ["video_file", "folder_360"]:
                filepath = cfg["input_path"]
                if not os.path.isfile(filepath):
                    msg_queue.put(('error', "Please select a valid Video File.")); return
                cap = cv2.VideoCapture(filepath)
                total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
                base_dest = os.path.join(out_dir, "_Speed_Test_Output")
                temp_dir = os.path.join(base_dest, "_Temp_Speed_Frames")
                os.makedirs(temp_dir, exist_ok=True); create_ignore_marker(temp_dir)
                for i in range(10):
                    if cancel_flag: break
                    time.sleep(0.001)
                    msg_queue.put(('progress', i+1, 10, "Extracting Test Frames..."))
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(total_frames * ((i + 0.5) / 10.0)))
                    ret, frame = cap.read()
                    if ret:
                        temp_img_path = os.path.join(temp_dir, f"speed_test_frame_{i+1:02d}.jpg")
                        cv2_imwrite(temp_img_path, frame)
                        if in_type == "folder_360":
                            extract_360_views(temp_img_path, temp_dir, cfg["out_fmt"], cfg.get("jpg_quality", 100), cfg.get("view_360_mode", "Standard 14 views"), cfg.get("include_360_bottom_views", True))
                            ext = ".png" if cfg["out_fmt"]=="PNG" else ".tif" if cfg["out_fmt"]=="TIFF" else ".jpg"
                            views = sorted([os.path.join(temp_dir, name) for name in os.listdir(temp_dir) if name.startswith(f"speed_test_frame_{i+1:02d}_v") and name.lower().endswith(ext)])
                            if views:
                                images_to_process.append(views[0])
                        else: images_to_process.append(temp_img_path)
                cap.release()
                if not images_to_process or cancel_flag: return handle_cancel()
            else:
                in_dir = cfg["input_path"]
                if in_dir == "" or not os.path.isdir(in_dir):
                    msg_queue.put(('error', "Please select a valid Input Folder.")); return
                all_imgs = get_valid_images(in_dir, build_allowed_formats(cfg.get("image_type_flags")), cfg.get("subfolder_mode", "recursive"), cfg.get("folder_search_depth"))
                if not all_imgs: 
                    msg_queue.put(('error', "No valid images found to test.")); return
                all_imgs_time = sorted([(f, get_time(f)) for f in all_imgs], key=lambda x: (x[1], os.path.basename(x[0]))) 
                images_to_process = [x[0] for x in all_imgs_time[:10]]
                base_dest = os.path.join(out_dir, "_Speed_Test_Output")
                os.makedirs(base_dest, exist_ok=True); create_ignore_marker(base_dest)

        do_yolo, do_subj, do_sky, yolo_model, subj_model, sky_processor, sky_model, device = build_ai_pipeline(cfg)
        if cancel_flag: return handle_cancel()
        
        final_out_path = ""
        total_items = len(images_to_process)
        completed_count = 0
        test_threads = get_effective_worker_count(max(1, (os.cpu_count() or 2) - 1), (do_yolo or do_subj or do_sky), device)
        with ThreadPoolExecutor(max_workers=test_threads) as executor:
            futures = {executor.submit(process_single_image, f, base_dest, (in_type != "image_folder"), do_yolo, do_subj, do_sky, cfg["ev_boost"], cfg["tone_method"], cfg["denoise_method"], cfg["clahe_clip"], cfg["clahe_grid"], cfg["clahe_sat"], cfg["do_sharp"], cfg["yolo_people"], cfg["yolo_acc"], cfg["yolo_vehicle"], cfg["mask_output_type"], cfg["out_fmt"], yolo_model, subj_model, sky_processor, sky_model, device, folder_dict, False, (cfg["mode"]=="single"), cfg.get("jpg_quality", 100), cfg.get("output_exists_mode", "Overwrite"), cfg.get("invert_masks", False), cfg.get("contrast_controls"), False, cfg.get("mask_360_bottom", False), in_type == "folder_360", cfg.get("sharpen_controls")): f for f in images_to_process}
            for future in as_completed(futures):
                if cancel_flag: break
                time.sleep(0.05) 
                res = future.result()
                completed_count += 1
                msg_queue.put(('progress', completed_count, total_items, "Processing Test Images..."))
                if cfg["mode"] == "single" and isinstance(res, tuple) and len(res) >= 4 and isinstance(res[3], str) and "Cancelled" not in res[3] and "Error" not in res[3]:
                    final_out_path = res[3]
        if cancel_flag: return handle_cancel()
        if cfg["mode"] == "single" and final_out_path: 
            msg_queue.put(('preview', (images_to_process[0], final_out_path)))
            msg_queue.put(('done', "Single Image Test Complete. See preview window."))
        else: msg_queue.put(('done', f"Success! Results saved to:\n{base_dest}"))
    except Exception as e:
        msg_queue.put(('error', f"Critical Testing Error: {str(e)}"))
    finally:
        gc.collect()

def run_sorting_process_backend(cfg):
    global cancel_flag
    try:
        msg_queue.put(('status', "Initializing Tool..."))
        initialize_ai_libraries()
        input_type, input_path, output_dir = cfg["input_type"], cfg["input_path"], cfg["output_dir"]
        do_sort = cfg["do_sort"]
        do_blur = cfg["do_blur"]
        blur_mode = cfg["blur_mode"]
        tone_method = cfg["tone_method"]
        smart_bypass = cfg["smart_bypass"]
        out_fmt = cfg["out_fmt"]
        denoise_method = cfg["denoise_method"]
        do_sharp = cfg["do_sharp"]
        mask_output_type = cfg["mask_output_type"]
        folder_dict = cfg["folder_dict"]
        allowed_formats = build_allowed_formats(cfg.get("image_type_flags")) if input_type == "image_folder" else SUPPORTED_FORMATS
        subfolder_mode = cfg.get("subfolder_mode", "recursive")
        preserve_originals = cfg.get("preserve_originals", False)
        if input_type == "image_folder" and not allowed_formats:
            msg_queue.put(('error', "Please select at least one image file type.")); return
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            create_ignore_marker(output_dir)
        
        # RAM Safety Cap for massive multi-core CPUs
        max_threads = cfg["max_threads"]
        
        process_input_path, video_cache_dir, timing_log = input_path, "", [
            "--- BATCH RUN TIMING LOG ---",
            f"Run started: {datetime.now().isoformat(timespec='seconds')}",
        ]
        if cfg.get("del_cache") and not cancel_flag:
            removed_preview_items = cleanup_preview_artifacts(output_dir, remove_display_files=True, timing_log=timing_log)
            if removed_preview_items:
                timing_log.append(f"[CACHE] Removed {removed_preview_items} old preview cache item(s).")
        
        if input_type in ["video_file", "folder_360", "video_folder"]:
            do_sort = False 
            if input_type == "video_folder":
                if not os.path.isdir(input_path):
                    msg_queue.put(('error', "Please select a valid folder of videos.")); return
                video_depth = cfg.get("folder_search_depth")
                video_sources = get_valid_videos(input_path, recursive=(parse_folder_search_depth(video_depth) != 0), max_depth=video_depth)
                if not video_sources:
                    msg_queue.put(('error', "No supported video files found in the selected folder.")); return
                safe_vid_name = re.sub(r'[\\/*?:"<>|]', "", os.path.basename(input_path)).replace(" ", "_")
                video_identity = "|".join(f"{p}|{os.path.getsize(p)}|{int(os.path.getmtime(p))}" for p in video_sources)
            else:
                if not os.path.isfile(input_path):
                    msg_queue.put(('error', "Please select a valid Video File.")); return
                video_sources = [input_path]
                safe_vid_name = re.sub(r'[\\/*?:"<>|]', "", os.path.splitext(os.path.basename(input_path))[0]).replace(" ", "_")
                video_identity = str(input_path)
            video_cache_dir = os.path.join(output_dir, f"_Video_Cache_{safe_vid_name}")
            settings_str = "|".join([
                "scanprep-video-cache-v2",
                str(input_type),
                video_identity,
                str(cfg.get("folder_search_depth", "Unlimited")),
                str(cfg["vid_ext_mode"]),
                str(cfg["vid_ext_val"]),
                str(cfg["vid_split"]),
                str(cfg.get("scene_sensitivity", "Normal")),
                str(cfg.get("scene_min_seconds", 4)),
                str(cfg["vid_res"]),
                str(out_fmt),
                str(cfg.get("jpg_quality", 100)),
                str(cfg.get("view_360_mode", "Standard 14 views")),
                str(cfg.get("include_360_bottom_views", True)),
            ])
            settings_file = os.path.join(video_cache_dir, "cache_settings.txt")
            do_extract = True
            if os.path.exists(video_cache_dir) and os.path.exists(settings_file) and open(settings_file, "r").read().strip() == settings_str:
                do_extract = False; msg_queue.put(('status', "Video Cache Hit! Skipping extraction..."))
            if do_extract:
                shutil.rmtree(video_cache_dir, ignore_errors=True); os.makedirs(video_cache_dir, exist_ok=True)
                create_ignore_marker(video_cache_dir)
                for video_idx, video_path in enumerate(video_sources, start=1):
                    if cancel_flag: break
                    if input_type == "video_folder":
                        msg_queue.put(('status', f"Extracting video {video_idx} of {len(video_sources)}: {os.path.basename(video_path)}"))
                    extract_video_frames(video_path, video_cache_dir, cfg["vid_ext_mode"], cfg["vid_ext_val"], cfg["vid_split"], cfg["vid_res"], out_fmt, timing_log, cfg.get("jpg_quality", 100), cfg)
                if not cancel_flag:
                    with open(settings_file, "w") as f: f.write(settings_str)
            process_input_path = video_cache_dir 
            if input_type == "folder_360" and not cancel_flag:
                pano_cache_dir = os.path.join(output_dir, f"_360_Extraction_Cache_{safe_vid_name}")
                if do_extract or not os.path.exists(pano_cache_dir):
                    shutil.rmtree(pano_cache_dir, ignore_errors=True); os.makedirs(pano_cache_dir, exist_ok=True)
                    create_ignore_marker(pano_cache_dir)
                    all_raw_frames = get_valid_images(video_cache_dir)
                    total_raw = len(all_raw_frames)
                    view_count = len(build_360_view_list(cfg.get("view_360_mode", "Standard 14 views"), cfg.get("include_360_bottom_views", True)))
                    for idx, frame_path in enumerate(all_raw_frames):
                        if cancel_flag: break
                        time.sleep(0.001) 
                        msg_queue.put(('progress', idx+1, total_raw, f"Unwrapping 360 frames into {view_count}-view arrays..."))
                        extract_360_views(frame_path, pano_cache_dir, out_fmt, cfg.get("jpg_quality", 100), cfg.get("view_360_mode", "Standard 14 views"), cfg.get("include_360_bottom_views", True))
                process_input_path = pano_cache_dir

        if cancel_flag: return handle_cancel()
        image_search_depth = cfg.get("folder_search_depth") if input_type == "image_folder" else None
        images_data = get_valid_images(process_input_path, allowed_formats, subfolder_mode if input_type == "image_folder" else "recursive", image_search_depth)
        if not images_data: msg_queue.put(('error', "No valid images found to process.")); return
        images_with_time = sorted([(f, get_time(f)) for f in images_data], key=lambda x: (x[1], os.path.basename(x[0]))) 

        session_groups = {}
        if input_type == "image_folder" and subfolder_mode == "sessions":
            for f, _ in images_with_time:
                rel = os.path.relpath(os.path.dirname(f), process_input_path)
                session_name = rel if rel != "." else "Scan_Session_001"
                session_groups.setdefault(session_name, []).append(f)
        elif do_sort and input_type == "image_folder":
            folder_idx = get_next_session_number(output_dir); last_t, last_f = None, None
            total_sort_items = len(images_with_time)
            for idx, (f, t) in enumerate(images_with_time):
                if cancel_flag: break
                time.sleep(0.001) 
                msg_queue.put(('progress', idx+1, total_sort_items, "Sorting and bridging images..."))
                if last_t and (t - last_t).total_seconds() > cfg["time_thresh"]:
                    if not (cfg["sim_check"] and last_f and check_image_bridge(*get_sift_features(last_f), *get_sift_features(f), cfg["sim_thresh"])):
                        folder_idx += 1
                s_name = f"Scan_Session_{folder_idx:03d}"
                session_groups.setdefault(s_name, []).append(f)
                last_t, last_f = t, f
            session_groups = {s if len(files) >= cfg["min_imgs"] else os.path.join("_Small_Datasets", s): files for s, files in session_groups.items()}
        else:
            for f, _ in images_with_time:
                rel = os.path.relpath(os.path.dirname(f), process_input_path)
                session_groups.setdefault(rel if rel != "." else "", []).append(f)

        if cancel_flag: return handle_cancel()

        do_yolo, do_subj, do_sky, yolo_model, subj_model, sky_processor, sky_model, device = build_ai_pipeline(cfg)
        timing_log.extend(get_ai_runtime_log_lines(device))
        if cancel_flag: return handle_cancel()

        is_blurry_dict, session_needs_tonemap = {}, {}
        needs_prescan = do_blur or (smart_bypass and "None" not in tone_method)

        for session_name, files in session_groups.items():
            if cancel_flag: break
            session_scores, session_dark_ratios = {}, []
            if needs_prescan:
                total_f = len(files)
                for idx, f in enumerate(files):
                    if cancel_flag: break
                    msg_queue.put(('progress', idx+1, total_f, f"Analyzing sharpness & exposure ({session_name})..."))
                    score, shadow_ratio = get_fast_blur_and_lighting(f)
                    session_scores[f], session_dark_ratios = score, session_dark_ratios + [shadow_ratio]
                session_needs_tonemap[session_name] = not (smart_bypass and (np.mean(session_dark_ratios) if session_dark_ratios else 0.0) < 0.15)
            else: session_needs_tonemap[session_name] = True
                
            if do_blur:
                is_blurry_dict.update(get_sharpness_isolation_map(files, session_scores, cfg))

        source_items_handled, originals_routed, masks_created, process_created = 0, 0, 0, 0
        total_images_to_process = sum(len(f) for f in session_groups.values())
        images_processed_so_far = 0
        
        max_threads = get_effective_worker_count(max_threads, (do_yolo or do_subj or do_sky), device)
        if not cancel_flag: msg_queue.put(('status', f"Using {max_threads} worker{'' if max_threads == 1 else 's'}..."))
        
        for session_name, files in session_groups.items():
            if cancel_flag: break
            base_dest = resolve_session_output_base(output_dir, session_name, cfg)
            session_tone = tone_method if session_needs_tonemap.get(session_name, True) else "None (Original Lighting)"
            with ThreadPoolExecutor(max_workers=max_threads) as executor:
                futures = {}
                for f in files:
                    futures[executor.submit(process_single_image, f, base_dest, (input_type != "image_folder"), do_yolo, do_subj, do_sky, cfg["ev_boost"], session_tone, denoise_method, cfg["clahe_clip"], cfg["clahe_grid"], cfg["clahe_sat"], do_sharp, cfg["yolo_people"], cfg["yolo_acc"], cfg["yolo_vehicle"], mask_output_type, out_fmt, yolo_model, subj_model, sky_processor, sky_model, device, folder_dict, is_blurry_dict.get(f, False), False, cfg.get("jpg_quality", 100), cfg.get("output_exists_mode", "Overwrite"), cfg.get("invert_masks", False), cfg.get("contrast_controls"), False, cfg.get("mask_360_bottom", False), input_type == "folder_360", cfg.get("sharpen_controls"))] = (f, is_blurry_dict.get(f, False))
                    time.sleep(0.05) # Add a micro-delay to prevent brutal RAM spikes when allocating 16 RAW files at once.
                    
                for future in as_completed(futures):
                    if cancel_flag: break
                    time.sleep(0.001) 
                    filepath, is_blurry = futures[future]
                    try:
                        res = future.result()
                        images_processed_so_far += 1
                        msg_queue.put(('progress', images_processed_so_far, total_images_to_process, "Processing AI & Core Adjustments..."))
                        if not isinstance(res, tuple) or len(res) < 4: continue
                        if res[3] == "Cancelled" or "Error" in res[3]: continue 
                        m_count, p_count, _metadata_result, t_log_str = res
                        masks_created += m_count; process_created += p_count; timing_log.append(t_log_str)
                        if not cancel_flag and (do_sort or is_blurry or input_type != "image_folder"):
                            final_dest = os.path.join(base_dest, folder_dict["blur"]) if is_blurry else base_dest
                            if is_blurry:
                                os.makedirs(final_dest, exist_ok=True)
                                create_ignore_marker(final_dest)
                            route_original_file(
                                filepath,
                                final_dest,
                                preserve_originals=(input_type != "image_folder" or preserve_originals),
                                timing_log=timing_log,
                            )
                            originals_routed += 1
                        if not cancel_flag: source_items_handled += 1
                    except Exception as e:
                        timing_log.append(f"[ROUTE] Failed after processing {os.path.basename(filepath)}: {compact_error(e)}")
                        msg_queue.put(('status', f"Warning: could not finish routing {os.path.basename(filepath)}. See debug log."))
            gc.collect()

        if cancel_flag: return handle_cancel()
        if cfg["debug_log"] and not cancel_flag:
            try: open(os.path.join(output_dir, "_debug_timing_log.txt"), "w", encoding="utf-8").write("\n".join(timing_log) + "\n")
            except: pass
        if input_type != "image_folder" and cfg["del_cache"] and video_cache_dir and not cancel_flag:
            try: shutil.rmtree(video_cache_dir, ignore_errors=True)
            except: pass

        msg_queue.put(('done', build_completion_message(source_items_handled, masks_created, process_created, originals_routed)))
    except Exception as e:
        msg_queue.put(('error', f"Critical Tool Error: {str(e)}"))


def run_ai_diagnostics_cli():
    print("=== ScanPrep AI Diagnostics ===")
    for line in get_ai_runtime_log_lines("not selected yet"):
        print(line)

    if not AI_LIBRARIES_LOADED:
        print("FAIL: AI libraries did not import.")
        return 1

    device = select_ai_device()
    print(f"Selected device: {device}")
    while not msg_queue.empty():
        msg = msg_queue.get()
        if len(msg) >= 2:
            print(f"{msg[0]}: {msg[1]}")

    tests_failed = 0

    def run_test(name, fn):
        nonlocal tests_failed
        print(f"\n--- {name} ---")
        try:
            result = fn()
            sync_accelerator(device)
            print(f"OK: {result if result is not None else ''}")
        except Exception as e:
            tests_failed += 1
            print(f"FAILED: {compact_error(e)}")
            print(traceback.format_exc(limit=8))

    def torch_test():
        if not str(device).startswith("cuda"):
            return "skipped; selected device is not CUDA"
        x = torch.randn((1, 3, 256, 256), device=device)
        conv = torch.nn.Conv2d(3, 16, 3, padding=1).to(device).eval()
        with torch.no_grad():
            y = conv(x).relu()
        return tuple(y.shape)

    def yolo_test():
        model_path = os.path.join(DATA_ROOT, "_AI_Models", "YOLO", "yolo26n-seg.pt")
        if not os.path.exists(model_path):
            model_path = os.path.join(DATA_ROOT, "_AI_Models", "YOLO", "yolov8n-seg.pt")
        model = YOLO(model_path).to(device)
        img = np.zeros((256, 256, 3), dtype=np.uint8)
        mask = get_yolo_mask(img, model, True, True, True, device)
        return f"mask shape {mask.shape}"

    def maskformer_test():
        model_dir = os.path.join(DATA_ROOT, "_AI_Models", "MaskFormer")
        processor = MaskFormerImageProcessor.from_pretrained(model_dir, local_files_only=True)
        model = MaskFormerForInstanceSegmentation.from_pretrained(model_dir, local_files_only=True).to(device, dtype=torch.float32).eval()
        img = Image.fromarray(np.zeros((256, 256, 3), dtype=np.uint8))
        with torch.no_grad():
            inputs = processor(images=img, return_tensors="pt").to(device)
            outputs = model(**inputs)
        return tuple(outputs.class_queries_logits.shape)

    def birefnet_test():
        model_dir = os.path.join(DATA_ROOT, "_AI_Models", "BiRefNet")
        model = AutoModelForImageSegmentation.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True).to(device, dtype=torch.float32).eval()
        img = np.zeros((256, 256, 3), dtype=np.uint8)
        mask = get_birefnet_mask(img, model, device)
        return f"mask shape {mask.shape}"

    run_test("Torch CUDA convolution", torch_test)
    run_test("YOLO segmentation model", yolo_test)
    run_test("MaskFormer sky model", maskformer_test)
    run_test("BiRefNet subject model", birefnet_test)

    print()
    if tests_failed:
        print(f"AI diagnostics failed: {tests_failed} test(s) failed.")
        return 1
    print("AI diagnostics passed.")
    return 0

def get_system_diagnostics_payload(cfg=None):
    cfg = cfg or {}
    output_dir = cfg.get("output_dir", "")
    debug_log_path = os.path.join(output_dir, "_debug_timing_log.txt") if output_dir else ""
    torch_info = {
        "loaded": AI_LIBRARIES_LOADED,
        "version": "",
        "cuda_build": "",
        "cuda_available": False,
        "arch_list": [],
        "devices": [],
    }
    if AI_LIBRARIES_LOADED:
        try:
            torch_info["version"] = getattr(torch, "__version__", "")
            torch_info["cuda_build"] = getattr(torch.version, "cuda", "") or ""
            torch_info["cuda_available"] = bool(torch.cuda.is_available())
            try:
                torch_info["arch_list"] = list(torch.cuda.get_arch_list())
            except Exception:
                torch_info["arch_list"] = []
            if torch_info["cuda_available"]:
                for idx in range(torch.cuda.device_count()):
                    major, minor = torch.cuda.get_device_capability(idx)
                    torch_info["devices"].append({
                        "index": idx,
                        "name": torch.cuda.get_device_name(idx),
                        "capability": f"sm_{major}{minor}",
                    })
        except Exception as e:
            torch_info["error"] = compact_error(e)

    model_root = os.path.join(DATA_ROOT, "_AI_Models")
    return {
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "details": platform.platform(),
        },
        "paths": {
            "app_root": APP_ROOT,
            "data_root": DATA_ROOT,
            "input_path": cfg.get("input_path", ""),
            "output_dir": output_dir,
            "debug_log_path": debug_log_path,
            "debug_log_exists": bool(debug_log_path and os.path.exists(debug_log_path)),
        },
        "libraries": {
            "opencv": getattr(cv2, "__version__", ""),
            "numpy": getattr(np, "__version__", ""),
            "rawpy": getattr(rawpy, "__version__", ""),
            "pillow": getattr(Image, "__version__", ""),
            "heic_support": HEIC_SUPPORT_AVAILABLE,
            "imageio_ffmpeg": IMAGEIO_FFMPEG_AVAILABLE,
            "ffmpeg_path": get_ffmpeg_executable(),
        },
        "ai": {
            "torch": torch_info,
            "models": {
                "yolo": os.path.exists(os.path.join(model_root, "YOLO", "yolo26n-seg.pt")) or os.path.exists(os.path.join(model_root, "YOLO", "yolov8n-seg.pt")),
                "maskformer": os.path.isdir(os.path.join(model_root, "MaskFormer")),
                "birefnet": os.path.isdir(os.path.join(model_root, "BiRefNet")),
            },
        },
    }

def run_system_diagnostics_json_cli(config_path=""):
    cfg = {}
    if config_path:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            emit_cli_event("error", message=f"Could not read diagnostics config: {compact_error(e)}")
            return 1
    emit_cli_event("system_diagnostics", diagnostics=get_system_diagnostics_payload(cfg))
    return 0


def emit_cli_event(event_type, **payload):
    payload["type"] = event_type
    payload.setdefault("time", datetime.now().isoformat(timespec="seconds"))
    print(json.dumps(payload, ensure_ascii=False), flush=True)

def drain_backend_messages_for_cli():
    saw_error = False
    while not msg_queue.empty():
        msg = msg_queue.get()
        if not isinstance(msg, tuple) or not msg:
            continue
        msg_type = msg[0]
        if msg_type == "status":
            emit_cli_event("status", message=msg[1] if len(msg) > 1 else "")
        elif msg_type == "progress":
            emit_cli_event("progress", current=msg[1], total=msg[2], message=msg[3] if len(msg) > 3 else "")
        elif msg_type == "done":
            emit_cli_event("done", message=msg[1] if len(msg) > 1 else "Complete.")
        elif msg_type == "error":
            saw_error = True
            emit_cli_event("error", message=msg[1] if len(msg) > 1 else "Unknown error.")
        elif msg_type == "preview":
            preview_data = msg[1] if len(msg) > 1 else None
            if isinstance(preview_data, tuple) and len(preview_data) >= 2:
                emit_cli_event("preview", original=preview_data[0], processed=preview_data[1])
            else:
                emit_cli_event("preview", data=preview_data)
        else:
            emit_cli_event("message", name=str(msg_type), data=list(msg[1:]))
    return saw_error

def run_backend_config_cli(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        emit_cli_event("error", message=f"Could not read config: {compact_error(e)}")
        return 1

    while not msg_queue.empty():
        try: msg_queue.get_nowait()
        except queue.Empty: break

    emit_cli_event("status", message="Starting ScanPrep tool...")
    worker = threading.Thread(target=run_sorting_process_backend, args=(cfg,), daemon=True)
    worker.start()

    saw_error = False
    while worker.is_alive() or not msg_queue.empty():
        saw_error = drain_backend_messages_for_cli() or saw_error
        time.sleep(0.1)
    saw_error = drain_backend_messages_for_cli() or saw_error
    return 1 if saw_error else 0

def get_preview_video_frame_count(cfg, sample_limit):
    if cfg.get("input_type") == "folder_360":
        view_count = len(build_360_view_list(cfg.get("view_360_mode", "Standard 14 views"), cfg.get("include_360_bottom_views", True)))
        return max(1, min(5, sample_limit // max(1, view_count)))
    return max(1, sample_limit)

def prepare_video_preview_sources(cfg, preview_root, sample_limit=50):
    input_path = cfg.get("input_path", "")
    input_type = cfg.get("input_type")
    if input_type == "video_folder":
        video_depth = cfg.get("folder_search_depth")
        video_sources = get_valid_videos(input_path, recursive=(parse_folder_search_depth(video_depth) != 0), max_depth=video_depth)
        if not video_sources:
            emit_cli_event("error", message="Choose a folder containing supported video files first.")
            return []
        input_path = video_sources[0]
        emit_cli_event("status", message=f"Previewing first video in folder: {os.path.basename(input_path)}")
    elif not input_path or not os.path.isfile(input_path):
        emit_cli_event("error", message="Choose a valid video file first.")
        return []

    video_frame_count = get_preview_video_frame_count(cfg, max(1, int(sample_limit)))
    video_cache_dir = os.path.join(preview_root, "_Preview_Video_Frames")
    shutil.rmtree(video_cache_dir, ignore_errors=True)
    os.makedirs(video_cache_dir, exist_ok=True)
    create_ignore_marker(video_cache_dir)
    timing_log = []

    if video_frame_count == 1:
        seek_ratio = float(np.clip(float(cfg.get("preview_seek_ratio", 0.5)), 0.0, 1.0))
        emit_cli_event("status", message="Grabbing one preview frame from video...")
        preview_frame = extract_video_preview_frame(
            input_path,
            video_cache_dir,
            cfg.get("vid_res", "Native"),
            "JPG",
            min(95, int(cfg.get("jpg_quality", 92))),
            seek_ratio,
            timing_log,
        )
        if not preview_frame:
            emit_cli_event("error", message="Could not grab a preview frame from the selected video.")
            return []
    else:
        emit_cli_event("status", message=f"Extracting {video_frame_count} preview frame(s) from video...")
        extract_video_frames(
            input_path,
            video_cache_dir,
            "Target Amount of Frames",
            str(video_frame_count),
            False,
            cfg.get("vid_res", "Native"),
            "JPG",
            timing_log,
            min(95, int(cfg.get("jpg_quality", 92))),
        )
        if cancel_flag:
            return []

    if input_type == "folder_360":
        view_mode = cfg.get("view_360_mode", "Standard 14 views")
        include_bottom_views = cfg.get("include_360_bottom_views", True)
        view_count = len(build_360_view_list(view_mode, include_bottom_views))
        pano_dir = os.path.join(preview_root, "_Preview_360_Views")
        shutil.rmtree(pano_dir, ignore_errors=True)
        os.makedirs(pano_dir, exist_ok=True)
        create_ignore_marker(pano_dir)
        frames = get_valid_images(video_cache_dir, JPG_FORMATS, "recursive")
        emit_cli_event("status", message=f"Creating {view_count}-view 360 preview sample...")
        for idx, frame_path in enumerate(frames, start=1):
            emit_cli_event("progress", current=idx, total=max(1, len(frames)), message="Unwrapping 360 preview frame...")
            extract_360_views(frame_path, pano_dir, "JPG", min(95, int(cfg.get("jpg_quality", 92))), view_mode, include_bottom_views)
        return get_valid_images(pano_dir, JPG_FORMATS, "recursive")

    return get_valid_images(video_cache_dir, JPG_FORMATS, "recursive")

def choose_source_preview_image(paths, cfg):
    if not paths:
        return ""
    paths = sorted(paths, key=lambda p: os.path.basename(p).lower())
    if cfg.get("input_type") == "folder_360":
        if cfg.get("mask_360_bottom") and cfg.get("include_360_bottom_views", True):
            bottom_views = [p for p in paths if "_p-" in os.path.basename(p).lower()]
            if bottom_views:
                return bottom_views[0]
        side_views = [p for p in paths if "_p+00" in os.path.basename(p).lower()]
        if side_views:
            return side_views[0]
    return paths[0]

def run_source_preview_config_cli(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        emit_cli_event("error", message=f"Could not read preview config: {compact_error(e)}")
        return 1

    input_type = cfg.get("input_type", "image_folder")
    input_path = cfg.get("input_path", "")
    output_dir = cfg.get("output_dir") or default_output_dir_for_input(input_path)
    os.makedirs(output_dir, exist_ok=True)
    create_ignore_marker(output_dir)
    if cfg.get("del_cache", True):
        cleanup_preview_artifacts(output_dir, remove_display_files=False)
    preview_root = os.path.join(get_preview_cache_dir(output_dir), f"source_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(preview_root, exist_ok=True)
    create_ignore_marker(preview_root)

    if input_type in ["video_file", "folder_360", "video_folder"]:
        paths = prepare_video_preview_sources(cfg, preview_root, sample_limit=1)
        preview_image = choose_source_preview_image(paths, cfg)
    else:
        allowed_formats = build_allowed_formats(cfg.get("image_type_flags"))
        paths = get_valid_images(input_path, allowed_formats, cfg.get("subfolder_mode", "recursive"), cfg.get("folder_search_depth")) if os.path.isdir(input_path) else []
        preview_image = choose_source_preview_image(paths, cfg)

    if not preview_image:
        emit_cli_event("error", message="Could not create a preview image from the selected source.")
        return 1

    display_path = make_display_preview_image(preview_image, output_dir, max_edge=int(cfg.get("max_edge", 2200)), quality=int(cfg.get("jpg_quality", 92)))
    emit_cli_event("image_preview", original=preview_image, display=display_path, converted=(display_path != preview_image))
    emit_cli_event("done", message="Preview source image ready.")
    return 0

def run_sharpness_preview_config_cli(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        emit_cli_event("error", message=f"Could not read preview config: {compact_error(e)}")
        return 1

    input_type = cfg.get("input_type", "image_folder")
    input_path = cfg.get("input_path", "")
    output_dir = cfg.get("output_dir", "")
    if not output_dir:
        output_dir = default_output_dir_for_input(input_path)
    os.makedirs(output_dir, exist_ok=True)
    create_ignore_marker(output_dir)
    if cfg.get("del_cache", True):
        cleanup_preview_artifacts(output_dir, remove_display_files=True)

    sample_limit = max(1, int(cfg.get("sample_limit", 50)))
    preview_root = os.path.join(output_dir, f"_Sharpness_Preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(preview_root, exist_ok=True)
    create_ignore_marker(preview_root)

    if input_type in ["video_file", "folder_360", "video_folder"]:
        images = prepare_video_preview_sources(cfg, preview_root, sample_limit)
    else:
        if not input_path or not os.path.isdir(input_path):
            emit_cli_event("error", message="Choose a valid image input folder before previewing sharpness.")
            return 1
        allowed_formats = build_allowed_formats(cfg.get("image_type_flags"))
        if not allowed_formats:
            emit_cli_event("error", message="Please select at least one image file type.")
            return 1
        subfolder_mode = cfg.get("subfolder_mode", "recursive")
        images = get_valid_images(input_path, allowed_formats, subfolder_mode, cfg.get("folder_search_depth"))

    if not images:
        emit_cli_event("error", message="No valid images found for sharpness preview.")
        return 1

    images = [f for f, _ in sorted([(f, get_time(f)) for f in images], key=lambda x: (x[1], os.path.basename(x[0])))]
    if len(images) > sample_limit:
        sample_indices = np.linspace(0, len(images) - 1, sample_limit, dtype=int)
        sample = [images[int(i)] for i in sample_indices]
    else:
        sample = images

    preview_note = ""
    blur_mode = cfg.get("blur_mode", "")
    if "Sharpest" in blur_mode or "Best X" in blur_mode:
        target_frames = max(1, int(cfg.get("target_frames", 300)))
        if len(images) <= target_frames:
            preview_note = f"{len(images)} images found; keep count is {target_frames}, so all images are preserved."
            emit_cli_event("status", message=preview_note)

    preserved_dir = os.path.join(preview_root, "Preserved")
    isolated_dir = os.path.join(preview_root, "Isolated")
    os.makedirs(preserved_dir, exist_ok=True)
    os.makedirs(isolated_dir, exist_ok=True)

    emit_cli_event("status", message=f"Previewing sharpness on {len(sample)} of {len(images)} images...")
    scores = {}
    for idx, filepath in enumerate(sample, start=1):
        emit_cli_event("progress", current=idx, total=len(sample), message="Scoring sharpness preview...")
        score, _shadow_ratio = get_fast_blur_and_lighting(filepath)
        scores[filepath] = score

    isolation_map = get_sharpness_isolation_map(sample, scores, cfg)
    preserved_count, isolated_count = 0, 0
    for idx, filepath in enumerate(sample, start=1):
        emit_cli_event("progress", current=idx, total=len(sample), message="Creating sharpness preview folders...")
        target_dir = isolated_dir if isolation_map.get(filepath, False) else preserved_dir
        target_path = get_available_output_path(os.path.join(target_dir, os.path.basename(filepath)))
        try:
            shutil.copy2(filepath, target_path)
            if target_dir == isolated_dir:
                isolated_count += 1
            else:
                preserved_count += 1
        except Exception as e:
            emit_cli_event("status", message=f"Could not copy preview file {os.path.basename(filepath)}: {compact_error(e)}")

    emit_cli_event(
        "sharpness_preview",
        preview_dir=preview_root,
        preserved=preserved_count,
        isolated=isolated_count,
        sampled=len(sample),
        total=len(images),
        note=preview_note,
    )
    emit_cli_event("done", message=f"Sharpness preview complete. {preserved_count} preserved, {isolated_count} isolated.")
    return 0

def get_first_preview_output(preview_dir, preferred_parts):
    candidates = []
    for root, _dirs, files in os.walk(preview_dir):
        for name in files:
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
                full = os.path.join(root, name)
                score = 0
                lowered = full.lower()
                for part in preferred_parts:
                    if part.lower() in lowered:
                        score += 1
                candidates.append((score, full))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]

def label_mask_preview_path(mask_path):
    normalized = mask_path.replace("\\", "/").lower()
    if "_transparent_subject" in normalized or "_masks_subject" in normalized:
        return "Subject"
    if "_transparent_environment" in normalized:
        return "Transparent"
    if "_masks_environment_yolo" in normalized:
        return "People/Objects"
    if "_masks_environment_sky" in normalized:
        return "Sky"
    if "_masks_environment_360bottom" in normalized:
        return "360 Bottom"
    if "_masks_environment" in normalized:
        return "Combined"
    return os.path.splitext(os.path.basename(mask_path))[0]

def collect_mask_preview_outputs(preview_dir):
    masks = []
    for root, _dirs, files in os.walk(preview_dir):
        for name in files:
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
                full = os.path.join(root, name)
                lowered = full.replace("\\", "/").lower()
                if "_masks" not in lowered and "_transparent" not in lowered:
                    continue
                masks.append({"label": label_mask_preview_path(full), "path": full})
    order = {"Combined": 0, "People/Objects": 1, "Sky": 2, "360 Bottom": 3, "Subject": 4, "Transparent": 5}
    masks.sort(key=lambda item: (order.get(item["label"], 99), item["path"]))
    return masks

def load_preview_config(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        emit_cli_event("error", message=f"Could not read preview config: {compact_error(e)}")
        return None
    preview_image = cfg.get("preview_image", "")
    if not preview_image or not os.path.isfile(preview_image):
        emit_cli_event("error", message="Choose a preview image first.")
        return None
    output_dir = cfg.get("output_dir") or default_output_dir_for_input(preview_image)
    os.makedirs(output_dir, exist_ok=True)
    create_ignore_marker(output_dir)
    cfg["output_dir"] = output_dir
    if cfg.get("del_cache", True):
        cleanup_preview_artifacts(output_dir, keep_paths=[preview_image], remove_display_files=False)
    return cfg

def run_display_preview_config_cli(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        emit_cli_event("error", message=f"Could not read preview config: {compact_error(e)}")
        return 1
    preview_image = cfg.get("preview_image", "")
    if not preview_image or not os.path.isfile(preview_image):
        emit_cli_event("error", message="Choose a preview image first.")
        return 1
    try:
        output_dir = cfg.get("output_dir", "")
        if cfg.get("del_cache", True) and output_dir:
            cleanup_preview_artifacts(output_dir, keep_paths=[preview_image], remove_display_files=True)
        display_path = make_display_preview_image(
            preview_image,
            output_dir,
            max_edge=int(cfg.get("max_edge", 2200)),
            quality=int(cfg.get("jpg_quality", 92)),
        )
        emit_cli_event("image_preview", original=preview_image, display=display_path, converted=(display_path != preview_image))
        emit_cli_event("done", message="Preview image ready.")
        return 0
    except Exception as e:
        emit_cli_event("error", message=f"Could not prepare preview image: {compact_error(e)}")
        return 1

def run_contrast_preview_config_cli(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        emit_cli_event("error", message=f"Could not read preview config: {compact_error(e)}")
        return 1
    preview_image = cfg.get("preview_image", "")
    output_dir = cfg.get("output_dir") or default_output_dir_for_input(preview_image or cfg.get("input_path", APP_ROOT))
    os.makedirs(output_dir, exist_ok=True)
    create_ignore_marker(output_dir)
    cfg["output_dir"] = output_dir
    if cfg.get("del_cache", True):
        cleanup_preview_artifacts(output_dir, keep_paths=[preview_image], remove_display_files=False)
    has_processing = (
        "None" not in cfg.get("tone_method", "None")
        or cfg.get("do_sharp", False)
        or bool(cfg.get("contrast_controls", {}).get("enabled", False))
    )
    if not has_processing:
        emit_cli_event("error", message="Enable Adjust Contrast, Local Contrast Boost, Exposure Fusion Look, or Feature Sharpening before previewing.")
        return 1

    preview_dir = os.path.join(cfg["output_dir"], f"_Contrast_Preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(preview_dir, exist_ok=True)
    create_ignore_marker(preview_dir)

    if not preview_image or not os.path.isfile(preview_image):
        if cfg.get("input_type") in ["video_file", "folder_360", "video_folder"]:
            source_preview_root = os.path.join(preview_dir, "_Source")
            paths = prepare_video_preview_sources(cfg, source_preview_root, sample_limit=1)
            preview_image = choose_source_preview_image(paths, cfg)
            if not preview_image:
                emit_cli_event("error", message="Could not create a video frame for processing preview.")
                return 1
            cfg["preview_image"] = preview_image
            emit_cli_event("image_preview", original=preview_image, display=preview_image, converted=False)
        else:
            emit_cli_event("error", message="Choose a preview image first.")
            return 1

    folder_dict = cfg.get("folder_dict", {
        "proc": "_Processed", "proc_blur": "_Processed_Blurry", "mask": "_Masks_Environment",
        "blur": "_Blurry_Originals", "subj": "_Masks_Subject",
        "trans_env": "_Transparent_Environment", "trans_subj": "_Transparent_Subject",
    })
    preview_label = cfg.get("preview_label", "Processing Preview")
    emit_cli_event("status", message="Creating processing preview...")
    res = process_single_image(
        preview_image,
        preview_dir,
        False,
        False, False, False,
        cfg.get("ev_boost", 0.0),
        cfg.get("tone_method", "None (Original Lighting)"),
        cfg.get("denoise_method", "None"),
        cfg.get("clahe_clip", 1.5),
        cfg.get("clahe_grid", 32),
        cfg.get("clahe_sat", False),
        cfg.get("do_sharp", False),
        False, False, False,
        "Unified Black & White Masks",
        cfg.get("out_fmt", "JPG"),
        None, None, None, None,
        "cpu",
        folder_dict,
        False,
        False,
        cfg.get("jpg_quality", 100),
        "Auto-number",
        False,
        cfg.get("contrast_controls"),
        sharpen_controls=cfg.get("sharpen_controls"),
    )
    processed_path = ""
    if isinstance(res, tuple) and len(res) >= 3 and res[2]:
        processed_path = res[2][1]
    if not processed_path or not os.path.exists(processed_path):
        processed_path = get_first_preview_output(preview_dir, ["_Processed"])
    if not processed_path:
        emit_cli_event("error", message="Contrast preview did not create an output image.")
        return 1
    try:
        display_path = make_display_preview_image(
            preview_image,
            cfg.get("output_dir", ""),
            max_edge=int(cfg.get("max_edge", 2200)),
            quality=int(cfg.get("jpg_quality", 92)),
        )
    except Exception:
        display_path = preview_image
    emit_cli_event("contrast_preview", original=preview_image, display=display_path, processed=processed_path, preview_dir=preview_dir, label=preview_label)
    emit_cli_event("done", message=f"{preview_label} complete.")
    return 0

def run_mask_preview_config_cli(config_path):
    cfg = load_preview_config(config_path)
    if not cfg:
        return 1
    preview_image = cfg["preview_image"]
    if not any([cfg.get("yolo_people"), cfg.get("yolo_acc"), cfg.get("yolo_vehicle"), cfg.get("do_sky"), cfg.get("do_subj"), cfg.get("mask_360_bottom")]):
        emit_cli_event("error", message="Enable at least one mask type before previewing.")
        return 1

    initialize_ai_libraries()
    preview_dir = os.path.join(cfg["output_dir"], f"_Mask_Preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(preview_dir, exist_ok=True)
    create_ignore_marker(preview_dir)
    folder_dict = cfg.get("folder_dict", {
        "proc": "_Processed", "proc_blur": "_Processed_Blurry", "mask": "_Masks_Environment",
        "blur": "_Blurry_Originals", "subj": "_Masks_Subject",
        "trans_env": "_Transparent_Environment", "trans_subj": "_Transparent_Subject",
    })
    emit_cli_event("status", message="Creating mask preview...")
    do_yolo, do_subj, do_sky, yolo_model, subj_model, sky_processor, sky_model, device = build_ai_pipeline(cfg)
    res = process_single_image(
        preview_image,
        preview_dir,
        False,
        do_yolo, do_subj, do_sky,
        0.0,
        "None (Original Lighting)",
        "None",
        cfg.get("clahe_clip", 1.5),
        cfg.get("clahe_grid", 32),
        cfg.get("clahe_sat", False),
        False,
        cfg.get("yolo_people", False),
        cfg.get("yolo_acc", False),
        cfg.get("yolo_vehicle", False),
        cfg.get("mask_output_type", "Unified Black & White Masks"),
        cfg.get("out_fmt", "JPG"),
        yolo_model, subj_model, sky_processor, sky_model,
        device,
        folder_dict,
        False,
        False,
        cfg.get("jpg_quality", 100),
        "Auto-number",
        cfg.get("invert_masks", False),
        None,
        True,
        cfg.get("mask_360_bottom", False),
        cfg.get("input_type") == "folder_360" or cfg.get("mask_360_bottom", False),
    )
    if not isinstance(res, tuple) or len(res) < 4 or "FAILED" in str(res[3]):
        emit_cli_event("error", message="Mask preview failed. See runtime notes for details.")
        return 1
    masks = collect_mask_preview_outputs(preview_dir)
    if not masks:
        emit_cli_event("error", message="Mask preview did not create a mask file.")
        return 1
    emit_cli_event("mask_preview", original=preview_image, mask=masks[0]["path"], masks=masks, preview_dir=preview_dir)
    emit_cli_event("done", message=f"Mask preview complete. {len(masks)} mask view(s) ready.")
    return 0

def run_gpu_test_json_cli():
    emit_cli_event("status", message="Checking acceleration support...")
    for line in get_ai_runtime_log_lines("not selected yet"):
        emit_cli_event("diagnostic", message=line)

    if not AI_LIBRARIES_LOADED:
        emit_cli_event("error", message="AI libraries did not import. ScanPrep can still run non-AI features.")
        return 1

    device = select_ai_device()
    drain_backend_messages_for_cli()

    ok, reason = smoke_test_torch_device(device)
    if ok and str(device).startswith("cuda"):
        emit_cli_event("done", message=f"GPU test passed. Using {device}.")
        return 0
    if ok:
        emit_cli_event("done", message="GPU acceleration is not active. CPU fallback is ready.")
        return 0

    emit_cli_event("error", message=f"Acceleration test failed. CPU fallback should be used. {reason}")
    return 1



# =========================================================================================
# ==================== PART 2: UI LAUNCHER & MULTIPROCESSING LOCK =========================
# =========================================================================================

# 🚨 This lock guarantees PyInstaller child processes NEVER accidentally trigger the GUI 🚨
if __name__ == '__main__':
    multiprocessing.freeze_support()

    cancelable_cli_commands = {
        "--gpu-test-json",
        "--run-config",
        "--sharpness-preview-config",
        "--display-preview-config",
        "--source-preview-config",
        "--contrast-preview-config",
        "--mask-preview-config",
    }
    if any(command in sys.argv for command in cancelable_cli_commands):
        start_stdin_cancel_watcher()

    if "--ai-diagnostics" in sys.argv:
        sys.exit(run_ai_diagnostics_cli())
    if "--gpu-test-json" in sys.argv:
        sys.exit(run_gpu_test_json_cli())
    if "--system-diagnostics-json" in sys.argv:
        arg_idx = sys.argv.index("--system-diagnostics-json")
        config_path = sys.argv[arg_idx + 1] if len(sys.argv) > arg_idx + 1 else ""
        sys.exit(run_system_diagnostics_json_cli(config_path))
    if "--run-config" in sys.argv:
        arg_idx = sys.argv.index("--run-config")
        config_path = sys.argv[arg_idx + 1] if len(sys.argv) > arg_idx + 1 else ""
        sys.exit(run_backend_config_cli(config_path))
    if "--sharpness-preview-config" in sys.argv:
        arg_idx = sys.argv.index("--sharpness-preview-config")
        config_path = sys.argv[arg_idx + 1] if len(sys.argv) > arg_idx + 1 else ""
        sys.exit(run_sharpness_preview_config_cli(config_path))
    if "--display-preview-config" in sys.argv:
        arg_idx = sys.argv.index("--display-preview-config")
        config_path = sys.argv[arg_idx + 1] if len(sys.argv) > arg_idx + 1 else ""
        sys.exit(run_display_preview_config_cli(config_path))
    if "--source-preview-config" in sys.argv:
        arg_idx = sys.argv.index("--source-preview-config")
        config_path = sys.argv[arg_idx + 1] if len(sys.argv) > arg_idx + 1 else ""
        sys.exit(run_source_preview_config_cli(config_path))
    if "--contrast-preview-config" in sys.argv:
        arg_idx = sys.argv.index("--contrast-preview-config")
        config_path = sys.argv[arg_idx + 1] if len(sys.argv) > arg_idx + 1 else ""
        sys.exit(run_contrast_preview_config_cli(config_path))
    if "--mask-preview-config" in sys.argv:
        arg_idx = sys.argv.index("--mask-preview-config")
        config_path = sys.argv[arg_idx + 1] if len(sys.argv) > arg_idx + 1 else ""
        sys.exit(run_mask_preview_config_cli(config_path))

    print("ScanPrep Tool backend service. Launch the Electron UI with 07_run_electron_gui.bat.")
    sys.exit(0)
