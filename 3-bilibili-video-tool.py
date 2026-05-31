import datetime
import hashlib
import json
import os
import platform
import random
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime as dt
from tkinter import filedialog, messagebox, ttk

FFMPEG_DIR = r"D:\0_env\ffmpeg\bin"
DEFAULT_OUTPUT_ROOT = os.path.join(os.getcwd(), "download")
DEFAULT_TRANSFER_TARGET = r"D:\video"

# ─────────────────── 通用工具函数 ───────────────────


def open_directory(path: str):
    if not os.path.isdir(path):
        return
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def extract_series_name(dir_name: str) -> str:
    match = re.match(r"^\d{14}_(.+)$", dir_name)
    return match.group(1) if match else dir_name


def get_video_extensions() -> set:
    return {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".ts"}


def is_video_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in get_video_extensions()


def file_md5(filepath: str, chunk_size: int = 8192) -> str:
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            md5.update(chunk)
    return md5.hexdigest()


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_timestamp(timestamp: float) -> str:
    try:
        return dt.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError):
        return "未知"


def count_files_in_dir(path: str) -> int:
    if not os.path.isdir(path):
        return 0
    return sum(1 for f in os.listdir(path) if is_video_file(f))


def normalize_dir_name(name: str) -> str:
    if not name:
        return "未知"
    value = name.strip()
    if value.upper() == "NA" or value in {"未知NA", "NA"}:
        return "未知"
    return value


def safe_dir_name(name: str) -> str:
    name = normalize_dir_name(name)
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip() or "未知"


def timestamped_folder_name(name: str) -> str:
    prefix = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{safe_dir_name(name)}"


# ─────────────────── B站下载相关函数 ───────────────────


def parse_json_from_stdout(stdout: str) -> dict:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        first = stdout.find("{")
        last = stdout.rfind("}")
        if first != -1 and last != -1 and last > first:
            try:
                return json.loads(stdout[first:last + 1])
            except json.JSONDecodeError:
                pass
        raise


def extract_bvid(url: str) -> str | None:
    match = re.search(r"(BV[\w]+)", url)
    return match.group(1) if match else None


def fetch_bilibili_api(url: str) -> tuple[str, list[dict]] | None:
    bvid = extract_bvid(url)
    if not bvid:
        return None
    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    req = urllib.request.Request(api_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None
    if data.get("code") != 0:
        return None
    video_info = data["data"]
    title = video_info.get("title") or "未知"
    pages = video_info.get("pages") or []
    if not pages:
        return None
    items = []
    for page in pages:
        page_num = page.get("page", 0)
        part_title = page.get("part") or f"视频 {page_num}"
        items.append({"index": page_num, "title": part_title,
                      "url": f"https://www.bilibili.com/video/{bvid}?p={page_num}"})
    return title, items


def run_yt_dlp_json(url: str) -> dict:
    cmd = ["yt-dlp", "--dump-single-json", "--no-warnings", "--skip-download", url]
    if os.path.isdir(FFMPEG_DIR):
        cmd += ["--ffmpeg-location", FFMPEG_DIR]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace")
    stdout, stderr = proc.communicate(timeout=300)
    if not stdout:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)
    info = parse_json_from_stdout(stdout)
    if proc.returncode != 0:
        info["_yt_dlp_warning"] = stderr.strip() or f"yt-dlp exited with code {proc.returncode}"
    return info


def build_entries(info: dict, url: str) -> tuple[str, list[dict]]:
    playlist_title = info.get("playlist_title") or info.get("title") or "未知"
    entries = info.get("entries")
    if entries:
        items = []
        for idx, entry in enumerate(entries, start=1):
            if not entry:
                continue
            entry_index = entry.get("playlist_index") or idx
            entry_title = entry.get("title") or entry.get("display_id") or f"视频 {entry_index}"
            entry_url = entry.get("webpage_url") or entry.get("url") or url
            items.append({"index": entry_index, "title": entry_title, "url": entry_url})
        return playlist_title, items
    single_title = info.get("title") or "未知标题"
    return single_title, [{"index": 1, "title": single_title, "url": url}]


def parse_progress_percent(line: str) -> float | None:
    match = re.search(r"\[download\]\s+([\d.]+)%", line)
    return float(match.group(1)) if match else None


def run_download_single_video(url, item, output_dir, log_cb, status_cb, progress_cb):
    output_pattern = os.path.join(output_dir, "[P%(playlist_index)s] %(title)s.%(ext)s")
    cmd = ["yt-dlp", "-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4",
           "-o", output_pattern, "--playlist-items", str(item["index"]),
           "--retries", "3", "--fragment-retries", "3", "--newline"]
    if os.path.isdir(FFMPEG_DIR):
        cmd += ["--ffmpeg-location", FFMPEG_DIR]
    cmd.append(url)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1, universal_newlines=True)
    for raw_line in process.stdout or []:
        if raw_line is None:
            continue
        line = raw_line.replace("\r", "\n")
        for part in line.split("\n"):
            if not part:
                continue
            log_cb(part + "\n", "normal")
            if "[download]" in part and "%" in part:
                status_cb(part.strip())
                pct = parse_progress_percent(part)
                if pct is not None:
                    progress_cb(pct)
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"yt-dlp 下载「{item['title']}」失败，退出码 {process.returncode}")


def run_download(url, items, output_dir, log_cb, status_cb, progress_cb, video_cb=None):
    if not items:
        raise ValueError("没有选择任何下载条目。")
    os.makedirs(output_dir, exist_ok=True)
    total = len(items)
    for i, item in enumerate(items):
        current = i + 1
        video_name = f"[{current}/{total}] {item['title']}"
        status_cb(f"正在下载 {video_name}")
        if video_cb:
            video_cb(video_name)
        progress_cb(0)
        log_cb(f"\n{'━' * 50}\n", "separator")
        log_cb(f"  [{current}/{total}] 开始下载: {item['title']}\n", "info")
        log_cb(f"{'━' * 50}\n\n", "separator")
        run_download_single_video(url, item, output_dir, log_cb, status_cb, progress_cb)
        progress_cb(100)
        log_cb(f"\n✅ [{current}/{total}] 下载完成: {item['title']}\n", "success")
        if i < total - 1:
            delay = random.uniform(3, 5)
            log_cb(f"⏳ 等待 {delay:.1f} 秒后继续下载下一个视频...\n", "warning")
            status_cb(f"等待 {delay:.1f} 秒后继续下载...")
            time.sleep(delay)


# ─────────────────── 合并相关数据模型与逻辑 ───────────────────


class DirectoryInfo:
    def __init__(self, dir_path: str):
        self.path = dir_path
        self.name = os.path.basename(dir_path)
        self.series_name = extract_series_name(self.name)
        self.files: list[str] = []
        self._scan()

    def _scan(self):
        self.files = []
        if not os.path.isdir(self.path):
            return
        for fname in sorted(os.listdir(self.path)):
            if is_video_file(fname):
                self.files.append(fname)

    @property
    def file_count(self) -> int:
        return len(self.files)


class SeriesGroup:
    def __init__(self, series_name: str):
        self.series_name = series_name
        self.dirs: list[DirectoryInfo] = []

    def add_dir(self, d: DirectoryInfo):
        self.dirs.append(d)

    @property
    def total_files(self) -> int:
        return sum(d.file_count for d in self.dirs)

    @property
    def display_label(self) -> str:
        return f"{self.series_name}  ({len(self.dirs)} 个目录, {self.total_files} 个视频)"


def scan_source_directories(source_root: str) -> list[SeriesGroup]:
    if not os.path.isdir(source_root):
        return []
    groups: dict[str, SeriesGroup] = {}
    for entry in sorted(os.listdir(source_root)):
        full = os.path.join(source_root, entry)
        if not os.path.isdir(full):
            continue
        if entry.startswith("00-merged-"):
            continue
        d = DirectoryInfo(full)
        if d.file_count == 0:
            continue
        sn = d.series_name
        if sn not in groups:
            groups[sn] = SeriesGroup(sn)
        groups[sn].add_dir(d)
    return list(groups.values())


def collect_all_files(group: SeriesGroup) -> dict[str, list[tuple[str, str]]]:
    files_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for d in group.dirs:
        for fname in d.files:
            files_map[fname].append((d.path, os.path.join(d.path, fname)))
    return files_map


def resolve_conflict(src_dir, src_file, existing_file, parent_window=None) -> str:
    src_size = os.path.getsize(src_file)
    dst_size = os.path.getsize(existing_file)
    src_ctime = format_timestamp(os.path.getctime(src_file))
    dst_ctime = format_timestamp(os.path.getctime(existing_file))
    src_mtime = format_timestamp(os.path.getmtime(src_file))
    dst_mtime = format_timestamp(os.path.getmtime(existing_file))
    result = {"choice": "skip"}

    dialog = tk.Toplevel(parent_window)
    dialog.title("文件名冲突")
    dialog.geometry("560x340")
    dialog.resizable(False, False)
    dialog.transient(parent_window)
    dialog.grab_set()
    dialog.configure(bg="#2d2d2d")

    tk.Label(dialog, text="⚠ 发现同名文件（大小不同）",
             font=("Microsoft YaHei UI", 12, "bold"), bg="#2d2d2d", fg="#f44747").pack(pady=(16, 8))
    info = tk.Frame(dialog, bg="#2d2d2d")
    info.pack(fill="x", padx=20, pady=4)
    tk.Label(info, text=f"文件名：{os.path.basename(src_file)}",
             font=("Microsoft YaHei UI", 9, "bold"), bg="#2d2d2d", fg="#d4d4d4").pack(anchor="w")
    tk.Label(info, text=f"\n📤 新文件（来源）", font=("Microsoft YaHei UI", 9, "bold"),
             bg="#2d2d2d", fg="#569cd6").pack(anchor="w")
    tk.Label(info, text=f"   目录：{src_dir}", font=("Consolas", 8),
             bg="#2d2d2d", fg="#d4d4d4").pack(anchor="w")
    tk.Label(info, text=f"   大小：{format_size(src_size)}　创建：{src_ctime}　修改：{src_mtime}",
             font=("Consolas", 8), bg="#2d2d2d", fg="#d4d4d4").pack(anchor="w")
    tk.Label(info, text=f"\n📥 已有文件（目标）", font=("Microsoft YaHei UI", 9, "bold"),
             bg="#2d2d2d", fg="#6a9955").pack(anchor="w")
    tk.Label(info, text=f"   大小：{format_size(dst_size)}　创建：{dst_ctime}　修改：{dst_mtime}",
             font=("Consolas", 8), bg="#2d2d2d", fg="#d4d4d4").pack(anchor="w")

    bf = tk.Frame(dialog, bg="#2d2d2d")
    bf.pack(pady=16)

    def on_overwrite():
        result["choice"] = "overwrite"; dialog.destroy()
    def on_skip():
        result["choice"] = "skip"; dialog.destroy()

    tk.Button(bf, text="使用新文件（覆盖）", command=on_overwrite,
              bg="#2563eb", fg="white", activebackground="#3b82f6", relief="flat",
              padx=14, pady=5, font=("Microsoft YaHei UI", 10), cursor="hand2").pack(side="left", padx=8)
    tk.Button(bf, text="保留已有文件（跳过）", command=on_skip,
              bg="#6b7280", fg="white", activebackground="#9ca3af", relief="flat",
              padx=14, pady=5, font=("Microsoft YaHei UI", 10), cursor="hand2").pack(side="left", padx=8)
    dialog.protocol("WM_DELETE_WINDOW", on_skip)
    dialog.wait_window()
    return result["choice"]


def _handle_file_conflict(src_path, dst_path, log_cb, conflict_cb, parent_window, counters):
    """通用文件冲突处理。counters = [processed, total]"""
    processed, total = counters
    if not os.path.exists(dst_path):
        shutil.copy2(src_path, dst_path)
        log_cb(f"  [{processed}/{total}] 复制：{os.path.basename(src_path)}\n", "normal")
    else:
        src_size = os.path.getsize(src_path)
        dst_size = os.path.getsize(dst_path)
        if src_size == dst_size:
            if file_md5(src_path) == file_md5(dst_path):
                log_cb(f"  [{processed}/{total}] 跳过（相同文件）：{os.path.basename(src_path)}\n", "warning")
                return
            base, ext = os.path.splitext(os.path.basename(src_path))
            dst_dir = os.path.dirname(dst_path)
            counter = 2
            new_dst = os.path.join(dst_dir, f"{base} ({counter}){ext}")
            while os.path.exists(new_dst):
                counter += 1
                new_dst = os.path.join(dst_dir, f"{base} ({counter}){ext}")
            log_cb(f"  [{processed}/{total}] 重命名复制：{os.path.basename(src_path)} -> {os.path.basename(new_dst)}\n", "warning")
            shutil.copy2(src_path, new_dst)
        else:
            log_cb(f"  [{processed}/{total}] 冲突（大小不同）：{os.path.basename(src_path)}，等待用户选择...\n", "warning")
            choice = conflict_cb(os.path.dirname(src_path), src_path, dst_path, parent_window)
            if choice == "overwrite":
                log_cb(f"  [{processed}/{total}] 用户选择覆盖：{os.path.basename(src_path)}\n", "info")
                shutil.copy2(src_path, dst_path)
            else:
                log_cb(f"  [{processed}/{total}] 用户选择跳过：{os.path.basename(src_path)}\n", "warning")


def do_merge(group, source_root, delete_source, log_cb, status_cb, progress_cb, conflict_cb, check_cancelled, parent_window=None):
    merged_dir = os.path.join(source_root, f"00-merged-{group.series_name}")
    os.makedirs(merged_dir, exist_ok=True)
    files_map = collect_all_files(group)
    total = sum(len(v) for v in files_map.values())
    processed = 0

    log_cb(f"\n{'━' * 50}\n", "separator")
    log_cb(f"  合并目标：\n  {merged_dir}\n", "info")
    log_cb(f"  共 {total} 个文件\n", "info")
    log_cb(f"{'━' * 50}\n\n", "separator")

    for fname, sources in files_map.items():
        if check_cancelled():
            log_cb("\n⚠ 合并被用户取消。\n", "warning"); return
        for src_dir_path, src_file_path in sources:
            processed += 1
            progress_cb(processed / total * 100)
            status_cb(f"正在处理 [{processed}/{total}] {fname}")
            _handle_file_conflict(src_file_path, os.path.join(merged_dir, fname),
                                  log_cb, conflict_cb, parent_window, [processed, total])

    log_cb(f"\n{'━' * 50}\n", "separator")
    log_cb(f"  ✅ 文件合并完成！\n  目标：{merged_dir}\n", "success")
    log_cb(f"{'━' * 50}\n", "separator")

    if delete_source:
        log_cb(f"\n开始删除来源目录...\n", "warning")
        for d in group.dirs:
            if os.path.isdir(d.path):
                try:
                    shutil.rmtree(d.path)
                    log_cb(f"  已删除：{d.name}\n", "info")
                except Exception as e:
                    log_cb(f"  删除失败：{d.name} - {e}\n", "error")
        log_cb("✅ 来源目录清理完成。\n", "success")
    progress_cb(100)
    status_cb("合并完成。")


# ─────────────────── 传输逻辑 ───────────────────


def scan_transfer_source(source_root: str) -> list[tuple[str, str, int]]:
    if not os.path.isdir(source_root):
        return []
    items = []
    for entry in sorted(os.listdir(source_root)):
        full = os.path.join(source_root, entry)
        if not os.path.isdir(full):
            continue
        fc = count_files_in_dir(full)
        if fc > 0:
            items.append((full, entry, fc))
    return items


def do_transfer(source_dirs, target_root, delete_source, log_cb, status_cb, progress_cb, conflict_cb, check_cancelled, parent_window=None):
    os.makedirs(target_root, exist_ok=True)
    total_files = sum(fc for _, _, fc in source_dirs)
    processed = 0

    log_cb(f"\n{'━' * 50}\n", "separator")
    log_cb(f"  传输目标：\n  {target_root}\n", "info")
    log_cb(f"  共 {len(source_dirs)} 个目录, {total_files} 个文件\n", "info")
    log_cb(f"{'━' * 50}\n\n", "separator")

    for src_path, src_name, file_count in source_dirs:
        if check_cancelled():
            log_cb("\n⚠ 传输被用户取消。\n", "warning"); return
        dst_dir = os.path.join(target_root, src_name)
        log_cb(f"  处理目录：{src_name} ({file_count} 个视频)\n", "info")

        if not os.path.exists(dst_dir):
            if delete_source:
                log_cb(f"    移动目录：{src_name}\n", "normal")
                shutil.move(src_path, dst_dir)
            else:
                log_cb(f"    复制目录：{src_name}\n", "normal")
                shutil.copytree(src_path, dst_dir)
            processed += file_count
            progress_cb(processed / total_files * 100)
            status_cb(f"正在处理 [{processed}/{total_files}] 目录 {src_name}")
            continue

        log_cb(f"    目标已存在，逐文件处理：{src_name}\n", "warning")
        for fname in sorted(os.listdir(src_path)):
            if not is_video_file(fname):
                continue
            if check_cancelled():
                log_cb("\n⚠ 传输被用户取消。\n", "warning"); return
            processed += 1
            progress_cb(processed / total_files * 100)
            status_cb(f"正在处理 [{processed}/{total_files}] {fname}")
            _handle_file_conflict(os.path.join(src_path, fname), os.path.join(dst_dir, fname),
                                  log_cb, conflict_cb, parent_window, [processed, total_files])

        if delete_source and os.path.isdir(src_path):
            try:
                shutil.rmtree(src_path)
                log_cb(f"    已删除来源目录：{src_name}\n", "info")
            except Exception as e:
                log_cb(f"    删除失败：{src_name} - {e}\n", "error")

    log_cb(f"\n{'━' * 50}\n", "separator")
    log_cb(f"  ✅ 传输完成！\n  目标：{target_root}\n", "success")
    log_cb(f"{'━' * 50}\n", "separator")
    progress_cb(100)
    status_cb("传输完成。")


# ─────────────────── 主 GUI ───────────────────


class AppGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("视频目录工具箱")
        self.root.geometry("960x750")
        self.root.resizable(True, True)

        # 下载页状态
        self.dl_url_var = tk.StringVar()
        self.dl_output_var = tk.StringVar(value=DEFAULT_OUTPUT_ROOT)
        self.dl_playlist_title = "未知"
        self.dl_items: list[dict] = []
        self.dl_check_vars: list[tuple[tk.BooleanVar, dict]] = []
        self.dl_latest_dir = None

        # 合并页状态
        self.merge_source_var = tk.StringVar(value=DEFAULT_OUTPUT_ROOT)
        self.merge_groups: list[SeriesGroup] = []
        self.merge_check_vars: list[tuple[tk.BooleanVar, SeriesGroup]] = []
        self.merge_delete_var = tk.BooleanVar(value=False)
        self.merge_show_details = False

        # 传输页状态
        self.tf_source_var = tk.StringVar(value=DEFAULT_OUTPUT_ROOT)
        self.tf_target_var = tk.StringVar(value=DEFAULT_TRANSFER_TARGET)
        self.tf_items: list[tuple[str, str, int]] = []
        self.tf_check_vars: list[tuple[tk.BooleanVar, tuple]] = []
        self.tf_delete_var = tk.BooleanVar(value=False)

        self._cancelled = False

        self._build_ui()
        self._setup_icon()

    def _setup_icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon", "cai.jpg")
        if os.path.exists(icon_path):
            try:
                from PIL import Image, ImageTk
                img = Image.open(icon_path).resize((64, 64), Image.LANCZOS)
                icon = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, icon)
                self._icon_ref = icon
            except Exception:
                try:
                    icon = tk.PhotoImage(file=icon_path)
                    self.root.iconphoto(True, icon)
                    self._icon_ref = icon
                except Exception:
                    pass

    @staticmethod
    def _btn(parent, text, cmd, bg="#3a3a3a", fg="white", hover_bg="#505050",
             hover_fg=None, padx=12, pady=4, font=("Microsoft YaHei UI", 9), **kw):
        hover_fg = hover_fg or fg
        btn = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                        activebackground=hover_bg, activeforeground=hover_fg,
                        relief="flat", bd=0, padx=padx, pady=pady,
                        font=font, cursor="hand2", **kw)
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg, fg=hover_fg) if str(btn["state"]) != "disabled" else None)
        btn.bind("<Leave>", lambda e: btn.config(bg=bg, fg=fg) if str(btn["state"]) != "disabled" else None)
        return btn

    @staticmethod
    def _make_log_panel(parent) -> tuple[tk.Text, ttk.Progressbar, ttk.Label]:
        lf = ttk.LabelFrame(parent, text="日志与进度", padding=8)
        lf.pack(fill="both", expand=True)
        lc = ttk.Frame(lf)
        lc.pack(fill="both", expand=True)
        lt = tk.Text(lc, wrap="word", state="disabled", height=20, font=("Consolas", 9),
                     bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4",
                     selectbackground="#264f78", relief="flat", padx=6, pady=6)
        ls = ttk.Scrollbar(lc, orient="vertical", command=lt.yview)
        lt.configure(yscrollcommand=ls.set)
        lt.pack(side="left", fill="both", expand=True)
        ls.pack(side="right", fill="y")
        for tag, color in [("normal", "#d4d4d4"), ("info", "#569cd6"), ("success", "#6a9955"),
                           ("error", "#f44747"), ("warning", "#dcdcaa"), ("separator", "#808080")]:
            lt.tag_configure(tag, foreground=color)
        pf = ttk.Frame(lf)
        pf.pack(fill="x", pady=(6, 0))
        ttk.Label(pf, text="进度:").pack(side="left")
        pb = ttk.Progressbar(pf, orient="horizontal", mode="determinate", length=300, maximum=100)
        pb.pack(side="left", fill="x", expand=True, padx=(8, 8))
        pl = ttk.Label(pf, text="0%", width=6)
        pl.pack(side="right")
        return lt, pb, pl

    @staticmethod
    def _make_scroll_list(parent) -> tuple[tk.Canvas, ttk.Frame]:
        c = ttk.Frame(parent)
        c.pack(fill="both", expand=True)
        canvas = tk.Canvas(c, highlightthickness=0)
        sb = ttk.Scrollbar(c, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return canvas, inner

    def _log(self, text_widget, msg, tag="normal"):
        text_widget.configure(state="normal")
        text_widget.insert("end", msg, tag)
        text_widget.see("end")
        text_widget.configure(state="disabled")

    def _resolve_conflict_gui(self, src_dir, src_file, existing_file, parent_window=None):
        result = {"choice": "skip"}
        def _show():
            result["choice"] = resolve_conflict(src_dir, src_file, existing_file, parent_window)
        if threading.current_thread() is threading.main_thread():
            _show()
        else:
            event = threading.Event()
            def _run():
                try: _show()
                finally: event.set()
            self.root.after(0, _run)
            event.wait()
        return result["choice"]

    # ── 构建 UI ──
    def _build_ui(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10, "bold"), padding=(20, 6))

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        # Tab 1: 下载
        self.tab_dl = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_dl, text="  ⬇ 下载视频  ")
        self._build_download_tab()

        # Tab 2: 合并
        self.tab_merge = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_merge, text="  🔗 合并目录  ")
        self._build_merge_tab()

        # Tab 3: 传输
        self.tab_transfer = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_transfer, text="  📤 传输文件  ")
        self._build_transfer_tab()

        # 底部状态栏
        bf = ttk.Frame(self.root, padding=(12, 8, 12, 12))
        bf.pack(fill="x")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bf, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        self._btn(bf, "✕ 关闭", self._on_close, bg="#dc2626", hover_bg="#ef4444",
                  padx=14, pady=5, font=("Microsoft YaHei UI", 9, "bold")).pack(side="right", padx=(8, 0))

        # 默认选中第一个选项卡
        self.notebook.select(0)

    # ══════════════════ 下载选项卡 ══════════════════
    def _build_download_tab(self):
        tab = self.tab_dl

        # 顶部 URL 输入
        top = ttk.Frame(tab, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="视频 URL:", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.dl_url_var, width=70).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        top.columnconfigure(1, weight=1)

        bg = ttk.Frame(top)
        bg.grid(row=0, column=2, sticky="e")
        self.dl_parse_btn = self._btn(bg, "🔍 解析条目", self._dl_parse,
                                       bg="#2563eb", hover_bg="#3b82f6", padx=16, pady=6,
                                       font=("Microsoft YaHei UI", 10, "bold"))
        self.dl_parse_btn.pack(side="left", padx=(0, 4))
        self.dl_clear_btn = self._btn(bg, "🗑 清空", self._dl_clear,
                                       bg="#6b7280", hover_bg="#9ca3af", padx=10, pady=6,
                                       font=("Microsoft YaHei UI", 10))
        self.dl_clear_btn.pack(side="left")

        # 输出目录
        of = ttk.Frame(tab, padding=(12, 0, 12, 0))
        of.pack(fill="x")
        ttk.Label(of, text="输出目录:").grid(row=0, column=0, sticky="w")
        ttk.Label(of, textvariable=self.dl_output_var).grid(row=0, column=1, sticky="w", padx=(8, 8))
        of.columnconfigure(1, weight=1)
        self._btn(of, "📂 选择", self._dl_choose_dir,
                  bg="#475569", hover_bg="#64748b").grid(row=0, column=2, padx=(4, 0))
        self._btn(of, "📁 打开", self._dl_open_dir,
                  bg="#475569", hover_bg="#64748b").grid(row=0, column=3, padx=(4, 0))

        # 中部
        center = ttk.Frame(tab, padding=12)
        center.pack(fill="both", expand=True)

        # 左侧条目
        left = ttk.LabelFrame(center, text="可选下载条目", padding=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=(0, 8))
        bf2 = ttk.Frame(left)
        bf2.pack(fill="x", pady=(0, 6))
        self._btn(bf2, "☑ 全选", self._dl_sel_all, bg="#0d9488", hover_bg="#14b8a6", width=8).pack(side="left", padx=(0, 4))
        self._btn(bf2, "☐ 全不选", self._dl_desel_all, bg="#6b7280", hover_bg="#9ca3af", width=8).pack(side="left")
        self.dl_count_var = tk.StringVar(value="共 0 个条目")
        ttk.Label(bf2, textvariable=self.dl_count_var).pack(side="right")

        self.dl_canvas, self.dl_list_frame = self._make_scroll_list(left)

        # 右侧日志
        right = ttk.Frame(center)
        right.pack(side="right", fill="both", expand=True, pady=(0, 8))

        # 当前视频名
        vf = ttk.Frame(right)
        vf.pack(fill="x")
        ttk.Label(vf, text="当前视频:").pack(side="left")
        self.dl_video_var = tk.StringVar(value="-")
        ttk.Label(vf, textvariable=self.dl_video_var, foreground="#4ec9b0").pack(side="left", padx=(4, 0))

        self.dl_log, self.dl_progress, self.dl_pct = self._make_log_panel(right)

        # 底部
        bb = ttk.Frame(tab, padding=(12, 4, 12, 8))
        bb.pack(fill="x")
        self.dl_open_dl_btn = self._btn(bb, "📁 打开下载目录", self._dl_open_download_dir,
                                          bg="#475569", hover_bg="#64748b", padx=12, pady=5)
        self.dl_open_dl_btn.pack(side="left")
        self.dl_open_dl_btn.config(state="disabled")
        self.dl_btn = self._btn(bb, "⬇ 下载选中条目", self._dl_start,
                                 bg="#16a34a", hover_bg="#22c55e", padx=16, pady=5,
                                 font=("Microsoft YaHei UI", 9, "bold"))
        self.dl_btn.pack(side="right")

    def _dl_choose_dir(self):
        s = filedialog.askdirectory(initialdir=self.dl_output_var.get(), title="选择输出目录")
        if s: self.dl_output_var.set(s)

    def _dl_open_dir(self):
        p = self.dl_output_var.get().strip()
        if p and os.path.isdir(p): open_directory(p)
        else: messagebox.showwarning("目录不存在", "输出目录不存在。")

    def _dl_open_download_dir(self):
        if self.dl_latest_dir and os.path.isdir(self.dl_latest_dir):
            open_directory(self.dl_latest_dir)
        else:
            messagebox.showwarning("目录不存在", "下载目录尚未创建。")

    def _dl_sel_all(self):
        for v, _ in self.dl_check_vars: v.set(True)

    def _dl_desel_all(self):
        for v, _ in self.dl_check_vars: v.set(False)

    def _dl_clear(self):
        self.dl_url_var.set("")
        self._dl_clear_items()
        self.dl_log.configure(state="normal"); self.dl_log.delete("1.0", "end"); self.dl_log.configure(state="disabled")
        self.dl_progress["value"] = 0; self.dl_pct.configure(text="0%")
        self.dl_video_var.set("-")
        self.status_var.set("已清空。")

    def _dl_clear_items(self):
        for w in self.dl_list_frame.winfo_children(): w.destroy()
        self.dl_check_vars.clear()
        self.dl_items.clear()
        self.dl_count_var.set("共 0 个条目")

    def _dl_parse(self):
        url = self.dl_url_var.get().strip()
        if not url:
            messagebox.showwarning("输入错误", "请输入视频 URL。"); return
        self.status_var.set("正在解析 URL...")
        self._log(self.dl_log, f"解析中：{url}\n", "info")
        self._dl_clear_items()

        def worker():
            try:
                api_result = fetch_bilibili_api(url)
                if api_result:
                    title, items = api_result
                    self.root.after(0, self._log, self.dl_log, "✅ Bilibili API 快速解析成功。\n", "success")
                else:
                    self.root.after(0, self._log, self.dl_log, "正在通过 yt-dlp 解析...\n", "warning")
                    info = run_yt_dlp_json(url)
                    title, items = build_entries(info, url)
                    if info.get("_yt_dlp_warning"):
                        self.root.after(0, self._log, self.dl_log, f"⚠ yt-dlp 警告：{info['_yt_dlp_warning']}\n", "warning")
                self.dl_playlist_title = normalize_dir_name(title)
                self.root.after(0, self._dl_show_items, items)
                self.root.after(0, self._log, self.dl_log, f"解析完成，共 {len(items)} 个条目。\n", "success")
                self.root.after(0, setattr, self, 'status_var', self.status_var)
                self.root.after(0, self.status_var.set, "解析完成，选择需要下载的条目。")
            except Exception as exc:
                self.root.after(0, self._log, self.dl_log, f"❌ 解析失败：{exc}\n", "error")
                self.root.after(0, self.status_var.set, "解析失败。")
                self.root.after(0, messagebox.showerror, "解析失败", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _dl_show_items(self, items: list[dict]):
        self._dl_clear_items()
        self.dl_items = list(items)
        self.dl_count_var.set(f"共 {len(items)} 个条目")
        for item in items:
            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(self.dl_list_frame, text=f"{item['index']}. {item['title']}", variable=var)
            cb.pack(anchor="w", pady=2)
            self.dl_check_vars.append((var, item))

    def _dl_start(self):
        selected = [item for v, item in self.dl_check_vars if v.get()]
        if not selected:
            messagebox.showwarning("未选择条目", "请先选择要下载的条目。"); return
        output_root = self.dl_output_var.get().strip() or DEFAULT_OUTPUT_ROOT
        folder = timestamped_folder_name(self.dl_playlist_title)
        target = os.path.join(output_root, folder)
        self.dl_latest_dir = target

        self.dl_parse_btn.config(state="disabled")
        self.dl_btn.config(state="disabled")
        self.dl_open_dl_btn.config(state="normal")
        self.status_var.set("开始下载...")
        self.dl_progress["value"] = 0

        def worker():
            try:
                run_download(
                    self.dl_url_var.get().strip(), selected, target,
                    log_cb=lambda m, t="normal": self.root.after(0, self._log, self.dl_log, m, t),
                    status_cb=lambda m: self.root.after(0, self.status_var.set, m),
                    progress_cb=lambda p: self.root.after(0, self._dl_update_progress, p),
                    video_cb=lambda n: self.root.after(0, self.dl_video_var.set, n),
                )
                self.root.after(0, self._log, self.dl_log, f"\n✅ 全部下载完成！\n", "success")
                self.root.after(0, self.status_var.set, "下载完成。")
                self.root.after(0, self._dl_update_progress, 100)
                self.root.after(0, self.dl_video_var.set, "全部完成")
            except Exception as exc:
                self.root.after(0, self._log, self.dl_log, f"\n❌ 下载失败：{exc}\n", "error")
                self.root.after(0, self.status_var.set, "下载失败。")
                self.root.after(0, messagebox.showerror, "下载失败", str(exc))
            finally:
                self.root.after(0, self.dl_parse_btn.config, {"state": "normal"})
                self.root.after(0, self.dl_btn.config, {"state": "normal"})

        threading.Thread(target=worker, daemon=True).start()

    def _dl_update_progress(self, pct):
        self.dl_progress["value"] = pct
        self.dl_pct.configure(text=f"{pct:.0f}%")

    # ══════════════════ 合并选项卡 ══════════════════
    def _build_merge_tab(self):
        tab = self.tab_merge

        top = ttk.Frame(tab, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="源目录:", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.merge_source_var).grid(row=0, column=1, sticky="w", padx=(8, 8))
        top.columnconfigure(1, weight=1)
        bg = ttk.Frame(top); bg.grid(row=0, column=2, sticky="e")
        self.merge_scan_btn = self._btn(bg, "🔍 扫描目录", self._merge_scan,
                                         bg="#2563eb", hover_bg="#3b82f6", padx=16, pady=6,
                                         font=("Microsoft YaHei UI", 10, "bold"))
        self.merge_scan_btn.pack(side="left", padx=(0, 4))
        self._btn(bg, "📂 选择", self._merge_choose_src, bg="#475569", hover_bg="#64748b",
                  padx=10, pady=6, font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 4))
        self.merge_clear_btn = self._btn(bg, "🗑 清空", self._merge_clear,
                                          bg="#6b7280", hover_bg="#9ca3af", padx=10, pady=6,
                                          font=("Microsoft YaHei UI", 10))
        self.merge_clear_btn.pack(side="left")

        opt = ttk.Frame(tab, padding=(12, 0, 12, 0)); opt.pack(fill="x")
        ttk.Checkbutton(opt, text="合并后删除来源目录", variable=self.merge_delete_var).pack(side="left")
        self.merge_count_var = tk.StringVar(value="共 0 个系列")
        ttk.Label(opt, textvariable=self.merge_count_var, style="Status.TLabel").pack(side="right")

        center = ttk.Frame(tab, padding=12); center.pack(fill="both", expand=True)
        left = ttk.LabelFrame(center, text="可选系列目录", padding=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=(0, 8))
        bf = ttk.Frame(left); bf.pack(fill="x", pady=(0, 6))
        self._btn(bf, "☑ 全选", self._merge_sel_all, bg="#0d9488", hover_bg="#14b8a6", width=8).pack(side="left", padx=(0, 4))
        self._btn(bf, "☐ 全不选", self._merge_desel_all, bg="#6b7280", hover_bg="#9ca3af", width=8).pack(side="left")
        self.merge_details_btn = self._btn(bf, "📋 展开详情", self._merge_toggle_details,
                                            bg="#7c3aed", hover_bg="#8b5cf6", width=10)
        self.merge_details_btn.pack(side="left", padx=(8, 0))
        self.merge_canvas, self.merge_list = self._make_scroll_list(left)

        right = ttk.Frame(center); right.pack(side="right", fill="both", expand=True, pady=(0, 8))
        self.merge_log, self.merge_progress, self.merge_pct = self._make_log_panel(right)

        bb = ttk.Frame(tab, padding=(12, 4, 12, 8)); bb.pack(fill="x")
        self._btn(bb, "📁 打开输出目录", self._merge_open_out,
                  bg="#475569", hover_bg="#64748b", padx=12, pady=5).pack(side="left")
        self.merge_btn = self._btn(bb, "🔗 合并选中系列", self._merge_start,
                                    bg="#16a34a", hover_bg="#22c55e", padx=16, pady=5,
                                    font=("Microsoft YaHei UI", 9, "bold"))
        self.merge_btn.pack(side="right")

    def _merge_choose_src(self):
        s = filedialog.askdirectory(initialdir=self.merge_source_var.get(), title="选择源目录")
        if s: self.merge_source_var.set(s)

    def _merge_scan(self):
        src = self.merge_source_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("目录不存在", "请选择有效源目录。"); return
        self._merge_clear_items()
        self._log(self.merge_log, f"正在扫描：{src}\n", "info")
        def w():
            try:
                groups = scan_source_directories(src)
                self.root.after(0, self._merge_show, groups)
                self.root.after(0, self._log, self.merge_log, f"扫描完成，共 {len(groups)} 个系列。\n", "success")
                self.root.after(0, self.status_var.set, "合并 - 扫描完成。")
            except Exception as e:
                self.root.after(0, self._log, self.merge_log, f"❌ 扫描失败：{e}\n", "error")
        threading.Thread(target=w, daemon=True).start()

    def _merge_show(self, groups):
        self._merge_clear_items()
        self.merge_groups = groups
        self.merge_count_var.set(f"共 {len(groups)} 个系列")
        for g in groups:
            v = tk.BooleanVar(value=True)
            ttk.Checkbutton(self.merge_list, text=g.display_label, variable=v).pack(anchor="w", pady=2)
            self.merge_check_vars.append((v, g))
            if self.merge_show_details:
                for d in g.dirs:
                    tk.Label(self.merge_list, text=f"    └ {d.name}  ({d.file_count} 视频)",
                             font=("Consolas", 8), fg="#808080", anchor="w").pack(anchor="w", padx=(16, 0))

    def _merge_toggle_details(self):
        self.merge_show_details = not self.merge_show_details
        self.merge_details_btn.config(text="📋 收起详情" if self.merge_show_details else "📋 展开详情")
        if self.merge_groups: self._merge_show(self.merge_groups)

    def _merge_sel_all(self):
        for v, _ in self.merge_check_vars: v.set(True)

    def _merge_desel_all(self):
        for v, _ in self.merge_check_vars: v.set(False)

    def _merge_clear(self):
        self._merge_clear_items()
        self.merge_log.configure(state="normal"); self.merge_log.delete("1.0", "end"); self.merge_log.configure(state="disabled")
        self.merge_progress["value"] = 0; self.merge_pct.configure(text="0%")
        self.status_var.set("合并 - 已清空。")

    def _merge_clear_items(self):
        for w in self.merge_list.winfo_children(): w.destroy()
        self.merge_check_vars.clear(); self.merge_groups.clear()
        self.merge_count_var.set("共 0 个系列")

    def _merge_open_out(self):
        s = self.merge_source_var.get().strip()
        if s and os.path.isdir(s): open_directory(s)

    def _merge_start(self):
        sel = [g for v, g in self.merge_check_vars if v.get()]
        if not sel: messagebox.showwarning("未选择", "请先选择要合并的系列。"); return
        src = self.merge_source_var.get().strip()
        if not src or not os.path.isdir(src): messagebox.showwarning("错误", "源目录无效。"); return
        self._cancelled = False
        self.merge_scan_btn.config(state="disabled"); self.merge_btn.config(state="disabled")
        self.status_var.set("开始合并..."); self.merge_progress["value"] = 0

        def w():
            try:
                for i, g in enumerate(sel):
                    if self._cancelled: break
                    self.root.after(0, self._log, self.merge_log, f"\n{'━' * 50}\n  [{i+1}/{len(sel)}] 合并：{g.series_name}\n{'━' * 50}\n", "info")
                    do_merge(g, src, self.merge_delete_var.get(),
                             lambda m, t="normal": self.root.after(0, self._log, self.merge_log, m, t),
                             lambda m: self.root.after(0, self.status_var.set, m),
                             lambda p: self.root.after(0, self._merge_update_p, p),
                             self._resolve_conflict_gui,
                             lambda: self._cancelled, self.root)
                if not self._cancelled:
                    self.root.after(0, self._log, self.merge_log, "\n✅ 全部合并完成！\n", "success")
                    self.root.after(0, self.status_var.set, "合并完成。")
                else:
                    self.root.after(0, self.status_var.set, "合并已取消。")
            except Exception as e:
                self.root.after(0, self._log, self.merge_log, f"\n❌ 合并失败：{e}\n", "error")
            finally:
                self.root.after(0, self.merge_scan_btn.config, {"state": "normal"})
                self.root.after(0, self.merge_btn.config, {"state": "normal"})

        threading.Thread(target=w, daemon=True).start()

    def _merge_update_p(self, p):
        self.merge_progress["value"] = p; self.merge_pct.configure(text=f"{p:.0f}%")

    # ══════════════════ 传输选项卡 ══════════════════
    def _build_transfer_tab(self):
        tab = self.tab_transfer

        top = ttk.Frame(tab, padding=12); top.pack(fill="x")
        ttk.Label(top, text="源目录:", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.tf_source_var).grid(row=0, column=1, sticky="w", padx=(8, 8))
        top.columnconfigure(1, weight=1)
        sb = ttk.Frame(top); sb.grid(row=0, column=2, sticky="e")
        self.tf_scan_btn = self._btn(sb, "🔍 扫描", self._tf_scan,
                                      bg="#2563eb", hover_bg="#3b82f6", padx=12, pady=6,
                                      font=("Microsoft YaHei UI", 10, "bold"))
        self.tf_scan_btn.pack(side="left", padx=(0, 4))
        self._btn(sb, "📂 选择", self._tf_choose_src, bg="#475569", hover_bg="#64748b",
                  padx=8, pady=6, font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 4))
        self.tf_clear_btn = self._btn(sb, "🗑 清空", self._tf_clear,
                                       bg="#6b7280", hover_bg="#9ca3af", padx=8, pady=6,
                                       font=("Microsoft YaHei UI", 10))
        self.tf_clear_btn.pack(side="left")

        ttk.Label(top, text="目标目录:", style="Title.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(top, textvariable=self.tf_target_var).grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(8, 0))
        db = ttk.Frame(top); db.grid(row=1, column=2, sticky="e", pady=(8, 0))
        self._btn(db, "📂 选择", self._tf_choose_dst, bg="#475569", hover_bg="#64748b",
                  padx=8, pady=6, font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 4))
        self._btn(db, "📁 打开", self._tf_open_dst, bg="#475569", hover_bg="#64748b",
                  padx=8, pady=6, font=("Microsoft YaHei UI", 10)).pack(side="left")

        opt = ttk.Frame(tab, padding=(12, 0, 12, 0)); opt.pack(fill="x")
        ttk.Checkbutton(opt, text="传输后删除来源目录", variable=self.tf_delete_var).pack(side="left")
        self.tf_count_var = tk.StringVar(value="共 0 个目录")
        ttk.Label(opt, textvariable=self.tf_count_var, style="Status.TLabel").pack(side="right")

        center = ttk.Frame(tab, padding=12); center.pack(fill="both", expand=True)
        left = ttk.LabelFrame(center, text="可选传输目录", padding=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=(0, 8))
        bf = ttk.Frame(left); bf.pack(fill="x", pady=(0, 6))
        self._btn(bf, "☑ 全选", self._tf_sel_all, bg="#0d9488", hover_bg="#14b8a6", width=8).pack(side="left", padx=(0, 4))
        self._btn(bf, "☐ 全不选", self._tf_desel_all, bg="#6b7280", hover_bg="#9ca3af", width=8).pack(side="left")
        self.tf_canvas, self.tf_list = self._make_scroll_list(left)

        right = ttk.Frame(center); right.pack(side="right", fill="both", expand=True, pady=(0, 8))
        self.tf_log, self.tf_progress, self.tf_pct = self._make_log_panel(right)

        bb = ttk.Frame(tab, padding=(12, 4, 12, 8)); bb.pack(fill="x")
        self._btn(bb, "📁 打开源目录", self._tf_open_src,
                  bg="#475569", hover_bg="#64748b", padx=12, pady=5).pack(side="left")
        self.tf_btn = self._btn(bb, "📤 传输选中目录", self._tf_start,
                                 bg="#16a34a", hover_bg="#22c55e", padx=16, pady=5,
                                 font=("Microsoft YaHei UI", 9, "bold"))
        self.tf_btn.pack(side="right")

    def _tf_choose_src(self):
        s = filedialog.askdirectory(initialdir=self.tf_source_var.get(), title="选择源目录")
        if s: self.tf_source_var.set(s)

    def _tf_choose_dst(self):
        s = filedialog.askdirectory(initialdir=self.tf_target_var.get(), title="选择目标目录")
        if s: self.tf_target_var.set(s)

    def _tf_open_dst(self):
        p = self.tf_target_var.get().strip()
        if p and os.path.isdir(p): open_directory(p)

    def _tf_open_src(self):
        p = self.tf_source_var.get().strip()
        if p and os.path.isdir(p): open_directory(p)

    def _tf_scan(self):
        src = self.tf_source_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("错误", "请选择有效源目录。"); return
        self._tf_clear_items()
        self._log(self.tf_log, f"正在扫描：{src}\n", "info")
        def w():
            try:
                items = scan_transfer_source(src)
                self.root.after(0, self._tf_show, items)
                self.root.after(0, self._log, self.tf_log, f"扫描完成，共 {len(items)} 个目录。\n", "success")
                self.root.after(0, self.status_var.set, "传输 - 扫描完成。")
            except Exception as e:
                self.root.after(0, self._log, self.tf_log, f"❌ 扫描失败：{e}\n", "error")
        threading.Thread(target=w, daemon=True).start()

    def _tf_show(self, items):
        self._tf_clear_items()
        self.tf_items = items
        self.tf_count_var.set(f"共 {len(items)} 个目录")
        for item in items:
            _, name, fc = item
            v = tk.BooleanVar(value=True)
            ttk.Checkbutton(self.tf_list, text=f"{name}  ({fc} 个视频)", variable=v).pack(anchor="w", pady=2)
            self.tf_check_vars.append((v, item))

    def _tf_sel_all(self):
        for v, _ in self.tf_check_vars: v.set(True)

    def _tf_desel_all(self):
        for v, _ in self.tf_check_vars: v.set(False)

    def _tf_clear(self):
        self._tf_clear_items()
        self.tf_log.configure(state="normal"); self.tf_log.delete("1.0", "end"); self.tf_log.configure(state="disabled")
        self.tf_progress["value"] = 0; self.tf_pct.configure(text="0%")
        self.status_var.set("传输 - 已清空。")

    def _tf_clear_items(self):
        for w in self.tf_list.winfo_children(): w.destroy()
        self.tf_check_vars.clear(); self.tf_items.clear()
        self.tf_count_var.set("共 0 个目录")

    def _tf_start(self):
        sel = [item for v, item in self.tf_check_vars if v.get()]
        if not sel: messagebox.showwarning("未选择", "请先选择要传输的目录。"); return
        dst = self.tf_target_var.get().strip()
        if not dst: messagebox.showwarning("错误", "请设置目标目录。"); return
        self._cancelled = False
        self.tf_scan_btn.config(state="disabled"); self.tf_btn.config(state="disabled")
        self.status_var.set("开始传输..."); self.tf_progress["value"] = 0

        def w():
            try:
                do_transfer(sel, dst, self.tf_delete_var.get(),
                            lambda m, t="normal": self.root.after(0, self._log, self.tf_log, m, t),
                            lambda m: self.root.after(0, self.status_var.set, m),
                            lambda p: self.root.after(0, self._tf_update_p, p),
                            self._resolve_conflict_gui,
                            lambda: self._cancelled, self.root)
                if not self._cancelled:
                    self.root.after(0, self._log, self.tf_log, "\n✅ 全部传输完成！\n", "success")
                    self.root.after(0, self.status_var.set, "传输完成。")
                else:
                    self.root.after(0, self.status_var.set, "传输已取消。")
            except Exception as e:
                self.root.after(0, self._log, self.tf_log, f"\n❌ 传输失败：{e}\n", "error")
            finally:
                self.root.after(0, self.tf_scan_btn.config, {"state": "normal"})
                self.root.after(0, self.tf_btn.config, {"state": "normal"})

        threading.Thread(target=w, daemon=True).start()

    def _tf_update_p(self, p):
        self.tf_progress["value"] = p; self.tf_pct.configure(text=f"{p:.0f}%")

    # ── 通用 ──
    def _on_close(self):
        self._cancelled = True
        self.root.quit()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AppGUI().run()