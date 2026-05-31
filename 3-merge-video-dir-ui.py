import hashlib
import os
import platform
import shutil
import subprocess
import threading
import time
import tkinter as tk
from collections import defaultdict
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

DEFAULT_SOURCE_ROOT = os.path.join(os.getcwd(), "download")
DEFAULT_TRANSFER_TARGET = r"D:\video"

# ─────────────────── 工具函数 ───────────────────


def open_directory(path: str):
    """跨平台打开目录。"""
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
    """从目录名中提取系列名称（去掉时间戳前缀）。"""
    import re
    match = re.match(r"^\d{14}_(.+)$", dir_name)
    return match.group(1) if match else dir_name


def get_video_extensions() -> set:
    return {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".ts"}


def is_video_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in get_video_extensions()


def file_md5(filepath: str, chunk_size: int = 8192) -> str:
    """计算文件 MD5 哈希。"""
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            md5.update(chunk)
    return md5.hexdigest()


def format_size(size_bytes: int) -> str:
    """格式化文件大小。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_datetime(timestamp: float) -> str:
    """格式化时间戳。"""
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError):
        return "未知"


def count_files_in_dir(path: str) -> int:
    """统计目录中的视频文件数量。"""
    if not os.path.isdir(path):
        return 0
    return sum(1 for f in os.listdir(path) if is_video_file(f))


# ─────────────────── 数据模型 ───────────────────


class DirectoryInfo:
    """代表 download 下的一个子目录。"""

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

    @property
    def display_label(self) -> str:
        return f"{self.name}  ({self.file_count} 个视频)"


class SeriesGroup:
    """具有相同系列名称的一组目录。"""

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
        dir_count = len(self.dirs)
        return f"{self.series_name}  ({dir_count} 个目录, {self.total_files} 个视频)"


# ─────────────────── 核心合并逻辑 ───────────────────


def scan_source_directories(source_root: str) -> list[SeriesGroup]:
    """扫描源目录，按系列名分组。"""
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
    """收集该系列组下所有文件，返回 {文件名: [(源目录路径, 源文件路径), ...]}。"""
    files_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for d in group.dirs:
        for fname in d.files:
            src_file = os.path.join(d.path, fname)
            files_map[fname].append((d.path, src_file))
    return files_map


def resolve_conflict(src_dir: str, src_file: str, existing_file: str, parent_window=None) -> str:
    """当目标已存在同名文件且大小不同时，弹出对话框让用户选择。"""
    src_size = os.path.getsize(src_file)
    dst_size = os.path.getsize(existing_file)
    src_ctime = format_datetime(os.path.getctime(src_file))
    dst_ctime = format_datetime(os.path.getctime(existing_file))
    src_mtime = format_datetime(os.path.getmtime(src_file))
    dst_mtime = format_datetime(os.path.getmtime(existing_file))

    result = {"choice": "skip"}

    dialog = tk.Toplevel(parent_window)
    dialog.title("文件名冲突")
    dialog.geometry("560x340")
    dialog.resizable(False, False)
    dialog.transient(parent_window)
    dialog.grab_set()
    dialog.configure(bg="#2d2d2d")

    title_lbl = tk.Label(
        dialog, text="⚠ 发现同名文件（大小不同）", font=("Microsoft YaHei UI", 12, "bold"),
        bg="#2d2d2d", fg="#f44747"
    )
    title_lbl.pack(pady=(16, 8))

    info_frame = tk.Frame(dialog, bg="#2d2d2d")
    info_frame.pack(fill="x", padx=20, pady=4)

    basename = os.path.basename(src_file)
    tk.Label(info_frame, text=f"文件名：{basename}", font=("Microsoft YaHei UI", 9, "bold"),
             bg="#2d2d2d", fg="#d4d4d4").pack(anchor="w")

    tk.Label(info_frame, text="\n📤 新文件（来源）", font=("Microsoft YaHei UI", 9, "bold"),
             bg="#2d2d2d", fg="#569cd6").pack(anchor="w")
    tk.Label(info_frame, text=f"   目录：{src_dir}", font=("Consolas", 8),
             bg="#2d2d2d", fg="#d4d4d4").pack(anchor="w")
    tk.Label(info_frame, text=f"   大小：{format_size(src_size)}　创建时间：{src_ctime}　修改时间：{src_mtime}",
             font=("Consolas", 8), bg="#2d2d2d", fg="#d4d4d4").pack(anchor="w")

    tk.Label(info_frame, text="\n📥 已有文件（目标）", font=("Microsoft YaHei UI", 9, "bold"),
             bg="#2d2d2d", fg="#6a9955").pack(anchor="w")
    tk.Label(info_frame, text=f"   大小：{format_size(dst_size)}　创建时间：{dst_ctime}　修改时间：{dst_mtime}",
             font=("Consolas", 8), bg="#2d2d2d", fg="#d4d4d4").pack(anchor="w")

    btn_frame = tk.Frame(dialog, bg="#2d2d2d")
    btn_frame.pack(pady=16)

    def on_overwrite():
        result["choice"] = "overwrite"
        dialog.destroy()

    def on_skip():
        result["choice"] = "skip"
        dialog.destroy()

    tk.Button(
        btn_frame, text="使用新文件（覆盖）", command=on_overwrite,
        bg="#2563eb", fg="white", activebackground="#3b82f6", activeforeground="white",
        relief="flat", padx=14, pady=5, font=("Microsoft YaHei UI", 10), cursor="hand2"
    ).pack(side="left", padx=8)

    tk.Button(
        btn_frame, text="保留已有文件（跳过）", command=on_skip,
        bg="#6b7280", fg="white", activebackground="#9ca3af", activeforeground="white",
        relief="flat", padx=14, pady=5, font=("Microsoft YaHei UI", 10), cursor="hand2"
    ).pack(side="left", padx=8)

    dialog.protocol("WM_DELETE_WINDOW", on_skip)
    dialog.wait_window()
    return result["choice"]


def do_merge(
    group: SeriesGroup,
    source_root: str,
    delete_source: bool,
    log_callback,
    status_callback,
    progress_callback,
    conflict_callback,
    check_cancelled,
    parent_window=None,
):
    """执行合并操作。"""
    series_name = group.series_name
    merged_dir_name = f"00-merged-{series_name}"
    merged_dir = os.path.join(source_root, merged_dir_name)
    os.makedirs(merged_dir, exist_ok=True)

    files_map = collect_all_files(group)
    total_entries = sum(len(v) for v in files_map.values())
    processed = 0

    log_callback(f"\n{'━' * 50}\n", "separator")
    log_callback(f"  合并目标目录：\n  {merged_dir}\n", "info")
    log_callback(f"  共 {total_entries} 个文件需要处理\n", "info")
    log_callback(f"{'━' * 50}\n\n", "separator")

    for fname, sources in files_map.items():
        if check_cancelled():
            log_callback("\n⚠ 合并被用户取消。\n", "warning")
            return

        for src_dir_path, src_file_path in sources:
            processed += 1
            progress_callback(processed / total_entries * 100)
            status_callback(f"正在处理 [{processed}/{total_entries}] {fname}")

            dst_file = os.path.join(merged_dir, fname)

            if not os.path.exists(dst_file):
                log_callback(f"  [{processed}/{total_entries}] 复制：{fname}\n", "normal")
                shutil.copy2(src_file_path, dst_file)
            else:
                src_size = os.path.getsize(src_file_path)
                dst_size = os.path.getsize(dst_file)
                if src_size == dst_size:
                    src_md5 = file_md5(src_file_path)
                    dst_md5 = file_md5(dst_file)
                    if src_md5 == dst_md5:
                        log_callback(f"  [{processed}/{total_entries}] 跳过（相同文件）：{fname}\n", "warning")
                        continue
                    else:
                        base, ext = os.path.splitext(fname)
                        counter = 2
                        new_dst = os.path.join(merged_dir, f"{base} ({counter}){ext}")
                        while os.path.exists(new_dst):
                            counter += 1
                            new_dst = os.path.join(merged_dir, f"{base} ({counter}){ext}")
                        log_callback(f"  [{processed}/{total_entries}] 重命名复制：{fname} -> {os.path.basename(new_dst)}\n", "warning")
                        shutil.copy2(src_file_path, new_dst)
                else:
                    log_callback(f"  [{processed}/{total_entries}] 冲突（大小不同）：{fname}，等待用户选择...\n", "warning")
                    choice = conflict_callback(src_dir_path, src_file_path, dst_file, parent_window)
                    if choice == "overwrite":
                        log_callback(f"  [{processed}/{total_entries}] 用户选择覆盖：{fname}\n", "info")
                        shutil.copy2(src_file_path, dst_file)
                    else:
                        log_callback(f"  [{processed}/{total_entries}] 用户选择跳过：{fname}\n", "warning")

    log_callback(f"\n{'━' * 50}\n", "separator")
    log_callback(f"  ✅ 文件合并完成！\n", "success")
    log_callback(f"  目标目录：{merged_dir}\n", "success")
    log_callback(f"{'━' * 50}\n", "separator")

    if delete_source:
        log_callback(f"\n开始删除来源目录...\n", "warning")
        for d in group.dirs:
            if os.path.isdir(d.path):
                try:
                    shutil.rmtree(d.path)
                    log_callback(f"  已删除：{d.name}\n", "info")
                except Exception as e:
                    log_callback(f"  删除失败：{d.name} - {e}\n", "error")
        log_callback(f"✅ 来源目录清理完成。\n", "success")

    progress_callback(100)
    status_callback("合并完成。")


# ─────────────────── 传输逻辑 ───────────────────


def scan_transfer_source(source_root: str) -> list[tuple[str, str, int]]:
    """扫描传输源目录，返回 [(目录路径, 目录名, 视频数), ...]。"""
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


def do_transfer(
    source_dirs: list[tuple[str, str, int]],
    target_root: str,
    delete_source: bool,
    log_callback,
    status_callback,
    progress_callback,
    conflict_callback,
    check_cancelled,
    parent_window=None,
):
    """执行传输操作：将选中的源目录复制/移动到目标目录。"""
    os.makedirs(target_root, exist_ok=True)

    # 计算总文件数
    total_files = sum(fc for _, _, fc in source_dirs)
    processed = 0

    log_callback(f"\n{'━' * 50}\n", "separator")
    log_callback(f"  传输目标目录：\n  {target_root}\n", "info")
    log_callback(f"  共 {len(source_dirs)} 个目录, {total_files} 个文件\n", "info")
    log_callback(f"{'━' * 50}\n\n", "separator")

    for src_path, src_name, file_count in source_dirs:
        if check_cancelled():
            log_callback("\n⚠ 传输被用户取消。\n", "warning")
            return

        dst_dir = os.path.join(target_root, src_name)

        log_callback(f"  处理目录：{src_name} ({file_count} 个视频)\n", "info")

        # 如果目标目录不存在，直接移动/复制整个目录
        if not os.path.exists(dst_dir):
            if delete_source:
                log_callback(f"    移动目录：{src_name}\n", "normal")
                shutil.move(src_path, dst_dir)
            else:
                log_callback(f"    复制目录：{src_name}\n", "normal")
                shutil.copytree(src_path, dst_dir)
            processed += file_count
            progress_callback(processed / total_files * 100)
            status_callback(f"正在处理 [{processed}/{total_files}] 目录 {src_name}")
            continue

        # 目标目录已存在，逐文件处理
        log_callback(f"    目标已存在，逐文件处理：{src_name}\n", "warning")
        for fname in sorted(os.listdir(src_path)):
            if not is_video_file(fname):
                continue

            if check_cancelled():
                log_callback("\n⚠ 传输被用户取消。\n", "warning")
                return

            processed += 1
            progress_callback(processed / total_files * 100)
            status_callback(f"正在处理 [{processed}/{total_files}] {fname}")

            src_file = os.path.join(src_path, fname)
            dst_file = os.path.join(dst_dir, fname)

            if not os.path.exists(dst_file):
                log_callback(f"    [{processed}/{total_files}] 复制：{fname}\n", "normal")
                shutil.copy2(src_file, dst_file)
            else:
                src_size = os.path.getsize(src_file)
                dst_size = os.path.getsize(dst_file)
                if src_size == dst_size:
                    src_md5 = file_md5(src_file)
                    dst_md5 = file_md5(dst_file)
                    if src_md5 == dst_md5:
                        log_callback(f"    [{processed}/{total_files}] 跳过（相同文件）：{fname}\n", "warning")
                        continue
                    else:
                        base, ext = os.path.splitext(fname)
                        counter = 2
                        new_dst = os.path.join(dst_dir, f"{base} ({counter}){ext}")
                        while os.path.exists(new_dst):
                            counter += 1
                            new_dst = os.path.join(dst_dir, f"{base} ({counter}){ext}")
                        log_callback(f"    [{processed}/{total_files}] 重命名复制：{fname} -> {os.path.basename(new_dst)}\n", "warning")
                        shutil.copy2(src_file, new_dst)
                else:
                    log_callback(f"    [{processed}/{total_files}] 冲突：{fname}，等待用户选择...\n", "warning")
                    choice = conflict_callback(src_path, src_file, dst_file, parent_window)
                    if choice == "overwrite":
                        log_callback(f"    [{processed}/{total_files}] 用户选择覆盖：{fname}\n", "info")
                        shutil.copy2(src_file, dst_file)
                    else:
                        log_callback(f"    [{processed}/{total_files}] 用户选择跳过：{fname}\n", "warning")

        # 如果选择了删除源目录，且目录还存在，删除它
        if delete_source and os.path.isdir(src_path):
            try:
                shutil.rmtree(src_path)
                log_callback(f"    已删除来源目录：{src_name}\n", "info")
            except Exception as e:
                log_callback(f"    删除失败：{src_name} - {e}\n", "error")

    log_callback(f"\n{'━' * 50}\n", "separator")
    log_callback(f"  ✅ 传输完成！\n", "success")
    log_callback(f"  目标目录：{target_root}\n", "success")
    log_callback(f"{'━' * 50}\n", "separator")

    progress_callback(100)
    status_callback("传输完成。")


# ─────────────────── GUI ───────────────────


class MergeVideoDirGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("视频目录工具箱")
        self.root.geometry("960x750")
        self.root.resizable(True, True)

        # 合并页状态
        self.merge_source_var = tk.StringVar(value=DEFAULT_SOURCE_ROOT)
        self.merge_groups: list[SeriesGroup] = []
        self.merge_check_vars: list[tuple[tk.BooleanVar, SeriesGroup]] = []
        self.merge_delete_var = tk.BooleanVar(value=False)
        self.merge_show_details = False

        # 传输页状态
        self.transfer_source_var = tk.StringVar(value=DEFAULT_SOURCE_ROOT)
        self.transfer_target_var = tk.StringVar(value=DEFAULT_TRANSFER_TARGET)
        self.transfer_items: list[tuple[str, str, int]] = []
        self.transfer_check_vars: list[tuple[tk.BooleanVar, tuple]] = []
        self.transfer_delete_var = tk.BooleanVar(value=False)

        # 全局
        self._cancelled = False
        self._running = False

        self._build_ui()
        self._setup_icon()

    # ── 图标 ──
    def _setup_icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon", "cai.jpg")
        if os.path.exists(icon_path):
            try:
                from PIL import Image, ImageTk
                img = Image.open(icon_path).resize((64, 64), Image.LANCZOS)
                icon = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, icon)
                self._icon_ref = icon
            except ImportError:
                try:
                    icon = tk.PhotoImage(file=icon_path)
                    self.root.iconphoto(True, icon)
                    self._icon_ref = icon
                except Exception:
                    pass
            except Exception:
                pass

    # ── 统一风格按钮 ──
    @staticmethod
    def _make_button(parent, text, command, bg="#3a3a3a", fg="white", hover_bg="#505050",
                     hover_fg=None, active_bg=None, active_fg=None, padx=12, pady=4,
                     font=("Microsoft YaHei UI", 9), **kw):
        hover_fg = hover_fg or fg
        active_bg = active_bg or hover_bg
        active_fg = active_fg or hover_fg
        btn = tk.Button(
            parent, text=text, command=command,
            bg=bg, fg=fg,
            activebackground=active_bg, activeforeground=active_fg,
            relief="flat", bd=0, padx=padx, pady=pady,
            font=font, cursor="hand2", **kw,
        )
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg, fg=hover_fg) if str(btn["state"]) != "disabled" else None)
        btn.bind("<Leave>", lambda e: btn.config(bg=bg, fg=fg) if str(btn["state"]) != "disabled" else None)
        return btn

    # ── 构建日志控件（复用） ──
    @staticmethod
    def _build_log_panel(parent) -> tuple[tk.Text, ttk.Progressbar, ttk.Label]:
        """构建日志+进度条面板，返回 (log_text, progress_bar, progress_label)。"""
        log_frame = ttk.LabelFrame(parent, text="日志与进度", padding=8)
        log_frame.pack(fill="both", expand=True)

        log_container = ttk.Frame(log_frame)
        log_container.pack(fill="both", expand=True)

        log_text = tk.Text(
            log_container, wrap="word", state="disabled", height=20,
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="#d4d4d4", selectbackground="#264f78",
            relief="flat", padx=6, pady=6,
        )
        log_sb = ttk.Scrollbar(log_container, orient="vertical", command=log_text.yview)
        log_text.configure(yscrollcommand=log_sb.set)
        log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

        for tag, color in [("normal", "#d4d4d4"), ("info", "#569cd6"), ("success", "#6a9955"),
                           ("error", "#f44747"), ("warning", "#dcdcaa"), ("separator", "#808080"),
                           ("progress", "#4ec9b0")]:
            log_text.tag_configure(tag, foreground=color)

        pf = ttk.Frame(log_frame)
        pf.pack(fill="x", pady=(6, 0))
        ttk.Label(pf, text="进度:").pack(side="left")
        pb = ttk.Progressbar(pf, orient="horizontal", mode="determinate", length=300, maximum=100)
        pb.pack(side="left", fill="x", expand=True, padx=(8, 8))
        pl = ttk.Label(pf, text="0%", width=6)
        pl.pack(side="right")

        return log_text, pb, pl

    # ── 构建滚动列表（复用） ──
    @staticmethod
    def _build_scroll_list(parent) -> tuple[tk.Canvas, ttk.Scrollbar, ttk.Frame]:
        """构建可滚动的 checkbox 列表区域，返回 (canvas, scrollbar, inner_frame)。"""
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        return canvas, scrollbar, inner

    # ── 构建 UI ──
    def _build_ui(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10, "bold"), padding=(20, 6))

        # ─── Notebook 选项卡 ───
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        # 合并选项卡
        self.merge_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.merge_tab, text="  🔗 合并目录  ")
        self._build_merge_tab()

        # 传输选项卡
        self.transfer_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.transfer_tab, text="  📤 传输文件  ")
        self._build_transfer_tab()

        # ─── 底部状态栏（全局） ───
        bottom_frame = ttk.Frame(self.root, padding=(12, 8, 12, 12))
        bottom_frame.pack(fill="x")

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bottom_frame, textvariable=self.status_var, style="Status.TLabel").pack(side="left", anchor="w")

        self._make_button(bottom_frame, "✕ 关闭", self._on_close,
                          bg="#dc2626", hover_bg="#ef4444", padx=14, pady=5,
                          font=("Microsoft YaHei UI", 9, "bold")).pack(side="right", padx=(8, 0))

    # ══════════════════════════════════════════════
    #                 合并选项卡
    # ══════════════════════════════════════════════

    def _build_merge_tab(self):
        tab = self.merge_tab

        # ─── 顶部：源目录选择 ───
        top = ttk.Frame(tab, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="源目录:", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.merge_source_var).grid(row=0, column=1, sticky="w", padx=(8, 8))
        top.columnconfigure(1, weight=1)

        bg = ttk.Frame(top)
        bg.grid(row=0, column=2, sticky="e")

        self.merge_scan_btn = self._make_button(bg, "🔍 扫描目录", self._merge_scan,
                                                 bg="#2563eb", hover_bg="#3b82f6", padx=16, pady=6,
                                                 font=("Microsoft YaHei UI", 10, "bold"))
        self.merge_scan_btn.pack(side="left", padx=(0, 4))

        self._make_button(bg, "📂 选择目录", self._merge_choose_source,
                          bg="#475569", hover_bg="#64748b", padx=10, pady=6,
                          font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 4))

        self.merge_clear_btn = self._make_button(bg, "🗑 清空", self._merge_clear,
                                                  bg="#6b7280", hover_bg="#9ca3af", padx=10, pady=6,
                                                  font=("Microsoft YaHei UI", 10))
        self.merge_clear_btn.pack(side="left")

        # ─── 选项区 ───
        opt = ttk.Frame(tab, padding=(12, 0, 12, 0))
        opt.pack(fill="x")

        ttk.Checkbutton(opt, text="合并后删除来源目录", variable=self.merge_delete_var).pack(side="left")

        self.merge_count_var = tk.StringVar(value="共 0 个系列")
        ttk.Label(opt, textvariable=self.merge_count_var, style="Status.TLabel").pack(side="right")

        # ─── 中部 ───
        center = ttk.Frame(tab, padding=12)
        center.pack(fill="both", expand=True)

        # 左侧
        left = ttk.LabelFrame(center, text="可选系列目录", padding=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=(0, 8))

        bf = ttk.Frame(left)
        bf.pack(fill="x", pady=(0, 6))

        self._make_button(bf, "☑ 全选", self._merge_select_all,
                          bg="#0d9488", hover_bg="#14b8a6", width=8).pack(side="left", padx=(0, 4))
        self._make_button(bf, "☐ 全不选", self._merge_deselect_all,
                          bg="#6b7280", hover_bg="#9ca3af", width=8).pack(side="left")

        self.merge_details_btn = self._make_button(bf, "📋 展开详情", self._merge_toggle_details,
                                                    bg="#7c3aed", hover_bg="#8b5cf6", width=10)
        self.merge_details_btn.pack(side="left", padx=(8, 0))

        self.merge_canvas, self.merge_sb, self.merge_list_frame = self._build_scroll_list(left)

        # 右侧日志
        right = ttk.Frame(center)
        right.pack(side="right", fill="both", expand=True, pady=(0, 8))

        self.merge_log, self.merge_progress, self.merge_pct_label = self._build_log_panel(right)

        # ─── 底部操作栏 ───
        bbar = ttk.Frame(tab, padding=(12, 4, 12, 8))
        bbar.pack(fill="x")

        self._make_button(bbar, "📁 打开输出目录", self._merge_open_output,
                          bg="#475569", hover_bg="#64748b", padx=12, pady=5).pack(side="left")

        self.merge_btn = self._make_button(bbar, "🔗 合并选中系列", self._merge_start,
                                            bg="#16a34a", hover_bg="#22c55e", padx=16, pady=5,
                                            font=("Microsoft YaHei UI", 9, "bold"))
        self.merge_btn.pack(side="right")

    # ── 合并页操作 ──

    def _merge_choose_source(self):
        sel = filedialog.askdirectory(initialdir=self.merge_source_var.get(), title="选择源目录")
        if sel:
            self.merge_source_var.set(sel)

    def _merge_scan(self):
        src = self.merge_source_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("目录不存在", "请选择一个有效的源目录。")
            return

        self._merge_clear_items()
        self._merge_log(f"正在扫描目录：{src}\n", "info")

        def worker():
            try:
                groups = scan_source_directories(src)
                self.root.after(0, self._merge_show_groups, groups)
                self.root.after(0, self._merge_log, f"扫描完成，共发现 {len(groups)} 个系列。\n", "success")
                self.root.after(0, self._set_status, "合并 - 扫描完成，选择需要合并的系列。")
            except Exception as exc:
                self.root.after(0, self._merge_log, f"❌ 扫描失败：{exc}\n", "error")
                self.root.after(0, self._set_status, "合并 - 扫描失败。")

        threading.Thread(target=worker, daemon=True).start()

    def _merge_show_groups(self, groups: list[SeriesGroup]):
        self._merge_clear_items()
        self.merge_groups = groups
        self.merge_count_var.set(f"共 {len(groups)} 个系列")

        for group in groups:
            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(self.merge_list_frame, text=group.display_label, variable=var)
            cb.pack(anchor="w", pady=2)
            self.merge_check_vars.append((var, group))

            if self.merge_show_details:
                for d in group.dirs:
                    lbl = tk.Label(self.merge_list_frame,
                                   text=f"    └ {d.name}  ({d.file_count} 个视频)",
                                   font=("Consolas", 8), fg="#808080", bg="#f0f0f0", anchor="w")
                    lbl.pack(anchor="w", padx=(16, 0))

    def _merge_toggle_details(self):
        self.merge_show_details = not self.merge_show_details
        self.merge_details_btn.config(text="📋 收起详情" if self.merge_show_details else "📋 展开详情")
        if self.merge_groups:
            self._merge_show_groups(self.merge_groups)

    def _merge_select_all(self):
        for v, _ in self.merge_check_vars:
            v.set(True)

    def _merge_deselect_all(self):
        for v, _ in self.merge_check_vars:
            v.set(False)

    def _merge_clear(self):
        self._merge_clear_items()
        self.merge_log.configure(state="normal")
        self.merge_log.delete("1.0", "end")
        self.merge_log.configure(state="disabled")
        self._merge_update_progress(0)
        self._set_status("合并 - 已清空。")

    def _merge_clear_items(self):
        for w in self.merge_list_frame.winfo_children():
            w.destroy()
        self.merge_check_vars.clear()
        self.merge_groups.clear()
        self.merge_count_var.set("共 0 个系列")

    def _merge_log(self, msg: str, tag: str = "normal"):
        self.merge_log.configure(state="normal")
        self.merge_log.insert("end", msg, tag)
        self.merge_log.see("end")
        self.merge_log.configure(state="disabled")

    def _merge_update_progress(self, pct: float):
        self.merge_progress["value"] = pct
        self.merge_pct_label.configure(text=f"{pct:.0f}%")

    def _merge_open_output(self):
        src = self.merge_source_var.get().strip()
        if src and os.path.isdir(src):
            open_directory(src)
        else:
            messagebox.showwarning("目录不存在", "源目录不存在。")

    def _merge_start(self):
        selected = [g for v, g in self.merge_check_vars if v.get()]
        if not selected:
            messagebox.showwarning("未选择系列", "请先选择要合并的系列。")
            return

        src = self.merge_source_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("目录不存在", "请选择一个有效的源目录。")
            return

        delete = self.merge_delete_var.get()
        self._cancelled = False
        self._running = True
        self.merge_scan_btn.config(state="disabled")
        self.merge_btn.config(state="disabled")
        self._set_status("开始合并，请稍候...")
        self._merge_update_progress(0)

        def worker():
            try:
                for i, group in enumerate(selected):
                    if self._cancelled:
                        break
                    cur, total = i + 1, len(selected)
                    self.root.after(0, self._merge_log, f"\n{'━' * 50}\n", "separator")
                    self.root.after(0, self._merge_log, f"  [{cur}/{total}] 合并系列：{group.series_name}\n", "info")
                    self.root.after(0, self._merge_log, f"{'━' * 50}\n", "separator")

                    do_merge(
                        group=group, source_root=src, delete_source=delete,
                        log_callback=lambda m, t="normal": self.root.after(0, self._merge_log, m, t),
                        status_callback=lambda m: self.root.after(0, self._set_status, m),
                        progress_callback=lambda p: self.root.after(0, self._merge_update_progress, p),
                        conflict_callback=self._resolve_conflict_on_gui,
                        check_cancelled=lambda: self._cancelled,
                        parent_window=self.root,
                    )

                if not self._cancelled:
                    self.root.after(0, self._merge_log, "\n✅ 全部系列合并完成！\n", "success")
                    self.root.after(0, self._set_status, "合并完成。")
                    self.root.after(0, self._merge_update_progress, 100)
                else:
                    self.root.after(0, self._set_status, "合并已被取消。")
            except Exception as exc:
                self.root.after(0, self._merge_log, f"\n❌ 合并失败：{exc}\n", "error")
                self.root.after(0, self._set_status, "合并失败。")
            finally:
                self._running = False
                self.root.after(0, self.merge_scan_btn.config, {"state": "normal"})
                self.root.after(0, self.merge_btn.config, {"state": "normal"})

        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════
    #                 传输选项卡
    # ══════════════════════════════════════════════

    def _build_transfer_tab(self):
        tab = self.transfer_tab

        # ─── 顶部：源目录 + 目标目录 ───
        top = ttk.Frame(tab, padding=12)
        top.pack(fill="x")

        # 源目录行
        ttk.Label(top, text="源目录:", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.transfer_source_var).grid(row=0, column=1, sticky="w", padx=(8, 8))
        top.columnconfigure(1, weight=1)

        src_bg = ttk.Frame(top)
        src_bg.grid(row=0, column=2, sticky="e")

        self.transfer_scan_btn = self._make_button(src_bg, "🔍 扫描", self._transfer_scan,
                                                    bg="#2563eb", hover_bg="#3b82f6", padx=12, pady=6,
                                                    font=("Microsoft YaHei UI", 10, "bold"))
        self.transfer_scan_btn.pack(side="left", padx=(0, 4))

        self._make_button(src_bg, "📂 选择", self._transfer_choose_source,
                          bg="#475569", hover_bg="#64748b", padx=8, pady=6,
                          font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 4))

        self.transfer_clear_btn = self._make_button(src_bg, "🗑 清空", self._transfer_clear,
                                                     bg="#6b7280", hover_bg="#9ca3af", padx=8, pady=6,
                                                     font=("Microsoft YaHei UI", 10))
        self.transfer_clear_btn.pack(side="left")

        # 目标目录行
        ttk.Label(top, text="目标目录:", style="Title.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(top, textvariable=self.transfer_target_var).grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(8, 0))

        dst_bg = ttk.Frame(top)
        dst_bg.grid(row=1, column=2, sticky="e", pady=(8, 0))

        self._make_button(dst_bg, "📂 选择", self._transfer_choose_target,
                          bg="#475569", hover_bg="#64748b", padx=8, pady=6,
                          font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 4))

        self._make_button(dst_bg, "📁 打开", self._transfer_open_target,
                          bg="#475569", hover_bg="#64748b", padx=8, pady=6,
                          font=("Microsoft YaHei UI", 10)).pack(side="left")

        # ─── 选项区 ───
        opt = ttk.Frame(tab, padding=(12, 0, 12, 0))
        opt.pack(fill="x")

        ttk.Checkbutton(opt, text="传输后删除来源目录", variable=self.transfer_delete_var).pack(side="left")

        self.transfer_count_var = tk.StringVar(value="共 0 个目录")
        ttk.Label(opt, textvariable=self.transfer_count_var, style="Status.TLabel").pack(side="right")

        # ─── 中部 ───
        center = ttk.Frame(tab, padding=12)
        center.pack(fill="both", expand=True)

        # 左侧
        left = ttk.LabelFrame(center, text="可选传输目录", padding=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=(0, 8))

        bf = ttk.Frame(left)
        bf.pack(fill="x", pady=(0, 6))

        self._make_button(bf, "☑ 全选", self._transfer_select_all,
                          bg="#0d9488", hover_bg="#14b8a6", width=8).pack(side="left", padx=(0, 4))
        self._make_button(bf, "☐ 全不选", self._transfer_deselect_all,
                          bg="#6b7280", hover_bg="#9ca3af", width=8).pack(side="left")

        self.transfer_canvas, self.transfer_sb, self.transfer_list_frame = self._build_scroll_list(left)

        # 右侧日志
        right = ttk.Frame(center)
        right.pack(side="right", fill="both", expand=True, pady=(0, 8))

        self.transfer_log, self.transfer_progress, self.transfer_pct_label = self._build_log_panel(right)

        # ─── 底部操作栏 ───
        bbar = ttk.Frame(tab, padding=(12, 4, 12, 8))
        bbar.pack(fill="x")

        self._make_button(bbar, "📁 打开源目录", self._transfer_open_source,
                          bg="#475569", hover_bg="#64748b", padx=12, pady=5).pack(side="left")

        self.transfer_btn = self._make_button(bbar, "📤 传输选中目录", self._transfer_start,
                                               bg="#16a34a", hover_bg="#22c55e", padx=16, pady=5,
                                               font=("Microsoft YaHei UI", 9, "bold"))
        self.transfer_btn.pack(side="right")

    # ── 传输页操作 ──

    def _transfer_choose_source(self):
        sel = filedialog.askdirectory(initialdir=self.transfer_source_var.get(), title="选择源目录")
        if sel:
            self.transfer_source_var.set(sel)

    def _transfer_choose_target(self):
        sel = filedialog.askdirectory(initialdir=self.transfer_target_var.get(), title="选择目标目录")
        if sel:
            self.transfer_target_var.set(sel)

    def _transfer_open_target(self):
        p = self.transfer_target_var.get().strip()
        if p and os.path.isdir(p):
            open_directory(p)
        else:
            messagebox.showwarning("目录不存在", "目标目录不存在。")

    def _transfer_open_source(self):
        p = self.transfer_source_var.get().strip()
        if p and os.path.isdir(p):
            open_directory(p)
        else:
            messagebox.showwarning("目录不存在", "源目录不存在。")

    def _transfer_scan(self):
        src = self.transfer_source_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("目录不存在", "请选择一个有效的源目录。")
            return

        self._transfer_clear_items()
        self._transfer_append_log(f"正在扫描目录：{src}\n", "info")

        def worker():
            try:
                items = scan_transfer_source(src)
                self.root.after(0, self._transfer_show_items, items)
                self.root.after(0, self._transfer_append_log, f"扫描完成，共发现 {len(items)} 个目录。\n", "success")
                self.root.after(0, self._set_status, "传输 - 扫描完成，选择需要传输的目录。")
            except Exception as exc:
                self.root.after(0, self._transfer_append_log, f"❌ 扫描失败：{exc}\n", "error")
                self.root.after(0, self._set_status, "传输 - 扫描失败。")

        threading.Thread(target=worker, daemon=True).start()

    def _transfer_show_items(self, items: list[tuple[str, str, int]]):
        self._transfer_clear_items()
        self.transfer_items = items
        self.transfer_count_var.set(f"共 {len(items)} 个目录")

        for item in items:
            path, name, fc = item
            var = tk.BooleanVar(value=True)
            label = f"{name}  ({fc} 个视频)"
            cb = ttk.Checkbutton(self.transfer_list_frame, text=label, variable=var)
            cb.pack(anchor="w", pady=2)
            self.transfer_check_vars.append((var, item))

    def _transfer_select_all(self):
        for v, _ in self.transfer_check_vars:
            v.set(True)

    def _transfer_deselect_all(self):
        for v, _ in self.transfer_check_vars:
            v.set(False)

    def _transfer_clear(self):
        self._transfer_clear_items()
        self.transfer_log.configure(state="normal")
        self.transfer_log.delete("1.0", "end")
        self.transfer_log.configure(state="disabled")
        self._transfer_update_progress(0)
        self._set_status("传输 - 已清空。")

    def _transfer_clear_items(self):
        for w in self.transfer_list_frame.winfo_children():
            w.destroy()
        self.transfer_check_vars.clear()
        self.transfer_items.clear()
        self.transfer_count_var.set("共 0 个目录")

    def _transfer_append_log(self, msg: str, tag: str = "normal"):
        self.transfer_log.configure(state="normal")
        self.transfer_log.insert("end", msg, tag)
        self.transfer_log.see("end")
        self.transfer_log.configure(state="disabled")

    def _transfer_update_progress(self, pct: float):
        self.transfer_progress["value"] = pct
        self.transfer_pct_label.configure(text=f"{pct:.0f}%")

    def _transfer_start(self):
        selected = [item for v, item in self.transfer_check_vars if v.get()]
        if not selected:
            messagebox.showwarning("未选择目录", "请先选择要传输的目录。")
            return

        src = self.transfer_source_var.get().strip()
        dst = self.transfer_target_var.get().strip()

        if not src or not os.path.isdir(src):
            messagebox.showwarning("目录不存在", "请选择一个有效的源目录。")
            return

        if not dst:
            messagebox.showwarning("目标目录", "请设置目标目录路径。")
            return

        delete = self.transfer_delete_var.get()
        self._cancelled = False
        self._running = True
        self.transfer_scan_btn.config(state="disabled")
        self.transfer_btn.config(state="disabled")
        self._set_status("开始传输，请稍候...")
        self._transfer_update_progress(0)

        def worker():
            try:
                do_transfer(
                    source_dirs=selected, target_root=dst, delete_source=delete,
                    log_callback=lambda m, t="normal": self.root.after(0, self._transfer_append_log, m, t),
                    status_callback=lambda m: self.root.after(0, self._set_status, m),
                    progress_callback=lambda p: self.root.after(0, self._transfer_update_progress, p),
                    conflict_callback=self._resolve_conflict_on_gui,
                    check_cancelled=lambda: self._cancelled,
                    parent_window=self.root,
                )

                if not self._cancelled:
                    self.root.after(0, self._transfer_append_log, "\n✅ 全部传输完成！\n", "success")
                    self.root.after(0, self._set_status, "传输完成。")
                else:
                    self.root.after(0, self._set_status, "传输已被取消。")
            except Exception as exc:
                self.root.after(0, self._transfer_append_log, f"\n❌ 传输失败：{exc}\n", "error")
                self.root.after(0, self._set_status, "传输失败。")
            finally:
                self._running = False
                self.root.after(0, self.transfer_scan_btn.config, {"state": "normal"})
                self.root.after(0, self.transfer_btn.config, {"state": "normal"})

        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════
    #                  通用方法
    # ══════════════════════════════════════════════

    def _set_status(self, msg: str):
        self.status_var.set(msg)

    def _on_close(self):
        self._cancelled = True
        self.root.quit()
        self.root.destroy()

    def _resolve_conflict_on_gui(self, src_dir, src_file, existing_file, parent_window=None):
        """在 GUI 线程中解决冲突。"""
        result = {"choice": "skip"}

        def _show_dialog():
            result["choice"] = resolve_conflict(src_dir, src_file, existing_file, parent_window)

        if threading.current_thread() is threading.main_thread():
            _show_dialog()
        else:
            event = threading.Event()

            def _run_in_main():
                try:
                    _show_dialog()
                finally:
                    event.set()

            self.root.after(0, _run_in_main)
            event.wait()

        return result["choice"]

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    MergeVideoDirGUI().run()