import datetime
import json
import os
import platform
import random
import re
import subprocess
import threading
import time
import tkinter as tk
import urllib.request
import urllib.error
from tkinter import filedialog, messagebox, ttk

FFMPEG_DIR = r"D:\0_env\ffmpeg\bin"
DEFAULT_OUTPUT_ROOT = os.path.join(os.getcwd(), "download")


def normalize_dir_name(name: str) -> str:
    if not name:
        return "未知"
    value = name.strip()
    if value.upper() == "NA" or value in {"未知NA", "NA"}:
        return "未知"
    return value


def safe_dir_name(name: str) -> str:
    name = normalize_dir_name(name)
    invalid_chars = '<>:"/\\|?*'
    for ch in invalid_chars:
        name = name.replace(ch, "_")
    return name.strip() or "未知"


def timestamped_folder_name(name: str) -> str:
    prefix = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{safe_dir_name(name)}"


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
    """从 URL 中提取 BV 号。"""
    match = re.search(r"(BV[\w]+)", url)
    return match.group(1) if match else None


def fetch_bilibili_api(url: str) -> tuple[str, list[dict]] | None:
    """通过 Bilibili API 快速获取视频列表（仅限 B 站链接）。"""
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
        items.append({
            "index": page_num,
            "title": part_title,
            "url": f"https://www.bilibili.com/video/{bvid}?p={page_num}",
        })

    return title, items


def run_yt_dlp_json(url: str) -> dict:
    cmd = ["yt-dlp", "--dump-single-json", "--no-warnings", "--skip-download", url]
    if os.path.isdir(FFMPEG_DIR):
        cmd += ["--ffmpeg-location", FFMPEG_DIR]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    stdout, stderr = proc.communicate(timeout=300)

    if not stdout:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)

    info = parse_json_from_stdout(stdout)
    if proc.returncode != 0:
        warning = stderr.strip() or f"yt-dlp exited with code {proc.returncode}"
        info["_yt_dlp_warning"] = warning
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
            items.append({
                "index": entry_index,
                "title": entry_title,
                "url": entry_url,
            })
        return playlist_title, items

    single_title = info.get("title") or "未知标题"
    return single_title, [{"index": 1, "title": single_title, "url": url}]


def parse_progress_percent(line: str) -> float | None:
    """从 yt-dlp 输出行中提取下载百分比。"""
    match = re.search(r"\[download\]\s+([\d.]+)%", line)
    if match:
        return float(match.group(1))
    return None


def run_download_single_video(url: str, item: dict, output_dir: str, log_callback, status_callback, progress_callback):
    """下载单个视频条目。"""
    output_pattern = os.path.join(output_dir, "[P%(playlist_index)s] %(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "-o", output_pattern,
        "--playlist-items", str(item["index"]),
        "--retries", "3",
        "--fragment-retries", "3",
        "--newline",
    ]

    if os.path.isdir(FFMPEG_DIR):
        cmd += ["--ffmpeg-location", FFMPEG_DIR]

    cmd.append(url)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    for raw_line in process.stdout or []:
        if raw_line is None:
            continue
        line = raw_line.replace("\r", "\n")
        for part in line.split("\n"):
            if not part:
                continue
            log_callback(part + "\n", "normal")
            if "[download]" in part and "%" in part:
                status_callback(part.strip())
                pct = parse_progress_percent(part)
                if pct is not None:
                    progress_callback(pct)

    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"yt-dlp 下载「{item['title']}」失败，退出码 {process.returncode}")


def run_download(url: str, items: list[dict], output_dir: str, log_callback, status_callback, progress_callback, video_callback=None):
    """逐个下载选中的视频，每个视频下载完成后随机等待 3~5 秒再继续。"""
    if not items:
        raise ValueError("没有选择任何下载条目。")

    os.makedirs(output_dir, exist_ok=True)
    total = len(items)

    for i, item in enumerate(items):
        current = i + 1
        video_name = f"[{current}/{total}] {item['title']}"
        status_callback(f"正在下载 {video_name}")
        if video_callback:
            video_callback(video_name)
        progress_callback(0)
        log_callback(f"\n{'━' * 50}\n", "separator")
        log_callback(f"  [{current}/{total}] 开始下载: {item['title']}\n", "info")
        log_callback(f"{'━' * 50}\n\n", "separator")

        run_download_single_video(url, item, output_dir, log_callback, status_callback, progress_callback)

        progress_callback(100)
        log_callback(f"\n✅ [{current}/{total}] 下载完成: {item['title']}\n", "success")

        # 每下载完一个视频后随机间隔 3~5 秒（最后一个不需要等待）
        if i < total - 1:
            delay = random.uniform(3, 5)
            log_callback(f"⏳ 等待 {delay:.1f} 秒后继续下载下一个视频...\n", "warning")
            status_callback(f"等待 {delay:.1f} 秒后继续下载...")
            time.sleep(delay)


def ensure_default_output_root() -> str:
    os.makedirs(DEFAULT_OUTPUT_ROOT, exist_ok=True)
    return DEFAULT_OUTPUT_ROOT


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


class BiliDownloaderGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("B站视频下载器")
        self.root.geometry("960x750")
        self.root.resizable(True, True)

        self.url_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=ensure_default_output_root())
        self.playlist_title = "未知"
        self.items = []
        self.check_vars = []
        self.latest_download_dir = None

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
            except ImportError:
                try:
                    icon = tk.PhotoImage(file=icon_path)
                    self.root.iconphoto(True, icon)
                    self._icon_ref = icon
                except Exception:
                    pass
            except Exception:
                pass

    @staticmethod
    def _make_button(parent, text, command, bg="#3a3a3a", fg="white", hover_bg="#505050", hover_fg=None, active_bg=None, active_fg=None, padx=12, pady=4, font=("Microsoft YaHei UI", 9), **kw):
        """创建统一风格的美化按钮，支持悬停变色。"""
        hover_fg = hover_fg or fg
        active_bg = active_bg or hover_bg
        active_fg = active_fg or hover_fg
        btn = tk.Button(
            parent, text=text, command=command,
            bg=bg, fg=fg,
            activebackground=active_bg, activeforeground=active_fg,
            relief="flat", bd=0, padx=padx, pady=pady,
            font=font, cursor="hand2",
            **kw,
        )
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg, fg=hover_fg) if str(btn["state"]) != "disabled" else None)
        btn.bind("<Leave>", lambda e: btn.config(bg=bg, fg=fg) if str(btn["state"]) != "disabled" else None)
        return btn

    def _build_ui(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 9))

        # ─── 顶部：URL 输入区 ───
        top_frame = ttk.Frame(self.root, padding=12)
        top_frame.pack(fill="x")

        ttk.Label(top_frame, text="视频 URL:", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        url_entry = ttk.Entry(top_frame, textvariable=self.url_var, width=70)
        url_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        top_frame.columnconfigure(1, weight=1)

        btn_group = ttk.Frame(top_frame)
        btn_group.grid(row=0, column=2, sticky="e")

        parse_button = self._make_button(btn_group, "🔍 解析条目", self.parse_url, bg="#2563eb", hover_bg="#3b82f6", padx=16, pady=6, font=("Microsoft YaHei UI", 10, "bold"))
        parse_button.pack(side="left", padx=(0, 4))
        self.parse_button = parse_button

        clear_button = self._make_button(btn_group, "🗑 清空", self._clear_all, bg="#6b7280", hover_bg="#9ca3af", padx=10, pady=6, font=("Microsoft YaHei UI", 10))
        clear_button.pack(side="left")
        self.clear_button = clear_button

        # ─── 输出目录区 ───
        output_frame = ttk.Frame(self.root, padding=(12, 0, 12, 0))
        output_frame.pack(fill="x")

        ttk.Label(output_frame, text="输出目录:").grid(row=0, column=0, sticky="w")
        self.output_label = ttk.Label(output_frame, textvariable=self.output_dir_var)
        self.output_label.grid(row=0, column=1, sticky="w", padx=(8, 8))
        output_frame.columnconfigure(1, weight=1)

        choose_button = self._make_button(output_frame, "📂 选择目录", self.choose_output_dir, bg="#475569", hover_bg="#64748b")
        choose_button.grid(row=0, column=2, sticky="e", padx=(4, 0))

        open_button = self._make_button(output_frame, "📁 打开目录", self._open_output_dir, bg="#475569", hover_bg="#64748b")
        open_button.grid(row=0, column=3, sticky="e", padx=(4, 0))

        # ─── 中部：左侧条目列表 + 右侧日志 ───
        center_frame = ttk.Frame(self.root, padding=12)
        center_frame.pack(fill="both", expand=True)

        # 左侧：条目列表
        entry_frame = ttk.LabelFrame(center_frame, text="可选下载条目", padding=8)
        entry_frame.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=(0, 8))

        # 全选/全不选按钮行
        btn_frame = ttk.Frame(entry_frame)
        btn_frame.pack(fill="x", pady=(0, 6))

        select_all_btn = self._make_button(btn_frame, "☑ 全选", self._select_all, bg="#0d9488", hover_bg="#14b8a6", width=8)
        select_all_btn.pack(side="left", padx=(0, 4))

        deselect_all_btn = self._make_button(btn_frame, "☐ 全不选", self._deselect_all, bg="#6b7280", hover_bg="#9ca3af", width=8)
        deselect_all_btn.pack(side="left")

        self.item_count_var = tk.StringVar(value="共 0 个条目")
        ttk.Label(btn_frame, textvariable=self.item_count_var).pack(side="right")

        # 条目滚动区域
        list_container = ttk.Frame(entry_frame)
        list_container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(list_container, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.canvas.yview)
        self.check_frame = ttk.Frame(self.canvas)

        self.check_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self.canvas.create_window((0, 0), window=self.check_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # 右侧：日志与进度
        right_frame = ttk.Frame(center_frame)
        right_frame.pack(side="right", fill="both", expand=True, pady=(0, 8))

        log_frame = ttk.LabelFrame(right_frame, text="日志与进度", padding=8)
        log_frame.pack(fill="both", expand=True)

        # 日志文本框（支持颜色）
        log_container = ttk.Frame(log_frame)
        log_container.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_container,
            wrap="word",
            state="disabled",
            height=20,
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            selectbackground="#264f78",
            relief="flat",
            padx=6,
            pady=6,
        )
        log_scrollbar = ttk.Scrollbar(log_container, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        self.log_text.pack(side="left", fill="both", expand=True)
        log_scrollbar.pack(side="right", fill="y")

        # 配置日志颜色标签
        self.log_text.tag_configure("normal", foreground="#d4d4d4")
        self.log_text.tag_configure("info", foreground="#569cd6")         # 蓝色 - 信息
        self.log_text.tag_configure("success", foreground="#6a9955")      # 绿色 - 成功
        self.log_text.tag_configure("error", foreground="#f44747")        # 红色 - 错误
        self.log_text.tag_configure("warning", foreground="#dcdcaa")      # 黄色 - 警告/等待
        self.log_text.tag_configure("separator", foreground="#808080")    # 灰色 - 分隔线
        self.log_text.tag_configure("progress", foreground="#4ec9b0")     # 青色 - 进度信息

        # 当前视频名称
        video_name_frame = ttk.Frame(log_frame)
        video_name_frame.pack(fill="x", pady=(6, 0))
        ttk.Label(video_name_frame, text="当前视频:").pack(side="left")
        self.current_video_var = tk.StringVar(value="-")
        ttk.Label(video_name_frame, textvariable=self.current_video_var, foreground="#4ec9b0").pack(side="left", padx=(4, 0))

        # 进度条
        progress_frame = ttk.Frame(log_frame)
        progress_frame.pack(fill="x", pady=(4, 0))

        ttk.Label(progress_frame, text="下载进度:").pack(side="left")
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            orient="horizontal",
            mode="determinate",
            length=300,
            maximum=100,
        )
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.progress_label = ttk.Label(progress_frame, text="0%", width=6)
        self.progress_label.pack(side="right")

        # ─── 底部状态栏 ───
        bottom_frame = ttk.Frame(self.root, padding=(12, 8, 12, 12))
        bottom_frame.pack(fill="x")

        self.status_var = tk.StringVar(value="等待输入 URL 并解析条目")
        status_label = ttk.Label(bottom_frame, textvariable=self.status_var, style="Status.TLabel")
        status_label.pack(side="left", anchor="w")

        close_button = self._make_button(bottom_frame, "✕ 关闭", self.root.quit, bg="#dc2626", hover_bg="#ef4444", padx=14, pady=5, font=("Microsoft YaHei UI", 9, "bold"))
        close_button.pack(side="right", padx=(8, 0))

        download_button = self._make_button(bottom_frame, "⬇ 下载选中条目", self.download_selected, bg="#16a34a", hover_bg="#22c55e", padx=16, pady=5, font=("Microsoft YaHei UI", 9, "bold"))
        download_button.pack(side="right")
        self.download_button = download_button

        open_dl_dir_btn = self._make_button(bottom_frame, "📁 打开下载目录", self._open_download_dir, bg="#475569", hover_bg="#64748b", padx=12, pady=5)
        open_dl_dir_btn.pack(side="right", padx=(8, 0))
        open_dl_dir_btn.config(state="disabled")
        self.open_dl_dir_button = open_dl_dir_btn

    def choose_output_dir(self):
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get(), title="选择输出目录")
        if selected:
            self.output_dir_var.set(selected)

    def _open_output_dir(self):
        path = self.output_dir_var.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showwarning("目录不存在", "输出目录不存在，请先选择一个有效的目录。")
            return
        open_directory(path)

    def _select_all(self):
        for var, _ in self.check_vars:
            var.set(True)

    def _deselect_all(self):
        for var, _ in self.check_vars:
            var.set(False)

    def _clear_all(self):
        """清空 URL 输入、条目列表和日志。"""
        self.url_var.set("")
        self._clear_items()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._update_progress(0)
        self._set_current_video("-")
        self._set_status("已清空，等待输入 URL 并解析条目。")

    def parse_url(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("输入错误", "请输入 B 站视频或合集 URL。")
            return

        self._set_status("正在解析 URL...")
        self._append_log(f"解析中：{url}\n", "info")
        self._clear_items()

        def worker():
            try:
                # 优先使用 Bilibili API 快速解析（仅 B 站链接可用）
                api_result = fetch_bilibili_api(url)
                if api_result:
                    playlist_title, items = api_result
                    self.root.after(0, self._append_log, "✅ Bilibili API 快速解析成功。\n", "success")
                else:
                    # 非 B 站链接或 API 失败，回退到 yt-dlp
                    self.root.after(0, self._append_log, "正在通过 yt-dlp 解析（可能较慢）...\n", "warning")
                    info = run_yt_dlp_json(url)
                    playlist_title, items = build_entries(info, url)
                    warning = info.get("_yt_dlp_warning")
                    if warning:
                        self.root.after(0, self._append_log, f"⚠ yt-dlp 警告：{warning}\n", "warning")

                self.root.after(0, self._show_items, playlist_title, items)
                self.root.after(0, self._set_status, "解析完成，选择需要下载的条目。")
                self.root.after(0, self._append_log, f"解析完成，共 {len(items)} 个条目。\n", "success")
            except subprocess.CalledProcessError as exc:
                error_message = exc.output if exc.output else str(exc)
                self.root.after(0, self._append_log, f"❌ 解析失败：{error_message}\n", "error")
                self.root.after(0, self._set_status, "解析失败，请检查 URL 或网络。")
                self.root.after(0, messagebox.showerror, "解析失败", error_message)
            except Exception as exc:
                self.root.after(0, self._append_log, f"❌ 解析异常：{exc}\n", "error")
                self.root.after(0, self._set_status, "解析异常。")
                self.root.after(0, messagebox.showerror, "解析异常", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_items(self, playlist_title: str, items: list[dict]):
        self.playlist_title = normalize_dir_name(playlist_title)
        self._clear_items()
        self.items = list(items)  # 复制一份，避免 _clear_items 误清
        self.item_count_var.set(f"共 {len(items)} 个条目")
        for item in items:
            var = tk.BooleanVar(value=True)
            label = f"{item['index']}. {item['title']}"
            cb = ttk.Checkbutton(self.check_frame, text=label, variable=var)
            cb.pack(anchor="w", pady=2)
            self.check_vars.append((var, item))

    def _clear_items(self):
        for widget in self.check_frame.winfo_children():
            widget.destroy()
        self.check_vars.clear()
        self.items.clear()
        self.item_count_var.set("共 0 个条目")

    def _append_log(self, message: str, tag: str = "normal"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message, tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_status(self, message: str):
        self.status_var.set(message)

    def _update_progress(self, pct: float):
        self.progress_bar["value"] = pct
        self.progress_label.configure(text=f"{pct:.0f}%")

    def _set_current_video(self, name: str):
        self.current_video_var.set(name)

    def _open_download_dir(self):
        if self.latest_download_dir and os.path.isdir(self.latest_download_dir):
            open_directory(self.latest_download_dir)
        else:
            messagebox.showwarning("目录不存在", "下载目录尚未创建。")

    def download_selected(self):
        selected = [item for var, item in self.check_vars if var.get()]
        if not selected:
            messagebox.showwarning("未选择条目", "请先选择要下载的条目。")
            return

        output_root = self.output_dir_var.get().strip() or ensure_default_output_root()
        if not output_root:
            messagebox.showwarning("输出目录", "请选择一个有效的输出目录。")
            return

        if not os.path.isdir(output_root):
            try:
                os.makedirs(output_root, exist_ok=True)
            except OSError as exc:
                messagebox.showerror("目录错误", f"无法创建输出目录：{exc}")
                return

        folder_name = timestamped_folder_name(self.playlist_title)
        target_dir = os.path.join(output_root, folder_name)
        self.latest_download_dir = target_dir

        self.parse_button.config(state="disabled")
        self.download_button.config(state="disabled")
        self.open_dl_dir_button.config(state="normal")
        self._set_status("开始下载，请稍候...")
        self._update_progress(0)
        self._set_current_video("-")
        self._append_log(f"\n{'━' * 50}\n", "separator")
        self._append_log(f"  开始下载到目录：\n  {target_dir}\n", "info")
        self._append_log(f"  共选择 {len(selected)} 个视频\n", "info")
        self._append_log(f"{'━' * 50}\n", "separator")

        def worker():
            try:
                run_download(
                    self.url_var.get().strip(),
                    selected,
                    target_dir,
                    log_callback=lambda msg, tag="normal": self.root.after(0, self._append_log, msg, tag),
                    status_callback=lambda msg: self.root.after(0, self._set_status, msg),
                    progress_callback=lambda pct: self.root.after(0, self._update_progress, pct),
                    video_callback=lambda name: self.root.after(0, self._set_current_video, name),
                )
                self.root.after(0, self._append_log, f"\n{'━' * 50}\n", "separator")
                self.root.after(0, self._append_log, "  ✅ 全部下载完成！\n", "success")
                self.root.after(0, self._append_log, f"{'━' * 50}\n", "separator")
                self.root.after(0, self._set_status, "下载完成。")
                self.root.after(0, self._update_progress, 100)
                self.root.after(0, self._set_current_video, "全部完成")
            except Exception as exc:
                self.root.after(0, self._append_log, f"\n❌ 下载失败：{exc}\n", "error")
                self.root.after(0, self._set_status, "下载失败，请查看日志。")
                self.root.after(0, messagebox.showerror, "下载失败", str(exc))
            finally:
                self.root.after(0, self.parse_button.config, {"state": "normal"})
                self.root.after(0, self.download_button.config, {"state": "normal"})

        threading.Thread(target=worker, daemon=True).start()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    BiliDownloaderGUI().run()