# 🎬 视频目录工具箱（B站视频下载 & 管理）

基于 `yt-dlp` + `ffmpeg` 的 B 站视频下载、目录合并、文件传输一体化 GUI 工具。

## ✨ 功能概览

### 📌 脚本说明

| 脚本 | 说明 |
|------|------|
| `1-get-video-files.py` | 最简命令行版 — 输入 B 站 URL 直接下载合集 |
| `2-get-video-files-ui.py` | GUI 下载器 — 带解析、勾选、进度条的单功能下载界面 |
| `3-bilibili-video-tool.py` | **视频目录工具箱** — 集下载、合并、传输于一体的全功能 GUI 工具 |

### 🛠 工具箱三大功能（`3-bilibili-video-tool.py`）

#### ⬇ 下载视频

- 输入 B 站视频/合集/收藏夹 URL
- 优先通过 Bilibili API 快速解析条目列表，失败则回退到 `yt-dlp` 解析
- 支持勾选需要下载的视频条目（全选/全不选）
- 自动以 `最佳视频+最佳音频` 合并为 MP4 格式
- 下载文件保存到带时间戳的目录：`download/20260531150000_视频标题/`
- 实时进度条 + 日志输出，每个视频下载间隔 3~5 秒随机延时

#### 🔗 合并目录

- 扫描指定源目录下所有视频子目录
- 按系列名称（自动去除时间戳前缀）智能分组
- 将同系列的多个下载目录合并到 `00-merged-系列名` 目录
- 支持展开详情查看每个目录的视频数量
- 文件名冲突时智能处理：相同文件自动跳过，不同文件可覆盖/重命名/跳过
- 可选合并后删除来源目录

#### 📤 传输文件

- 将下载/合并后的视频目录传输到指定目标路径（如 NAS、移动硬盘）
- 支持整个目录移动或逐文件复制
- 同名文件冲突处理（与合并相同的智能冲突策略）
- 可选传输后删除来源目录

### 🎨 界面特性

- 暗色主题 GUI（基于 tkinter）
- 三个功能选项卡切换
- 彩色日志输出（信息/成功/警告/错误分色显示）
- 实时进度条和状态栏
- 按钮悬停变色效果
- 跨平台目录打开（Windows / macOS / Linux）

---

## 📁 项目结构

```
lab-bilibili-video/
├── 1-get-video-files.py          # 命令行版下载脚本
├── 2-get-video-files-ui.py       # GUI 下载器
├── 3-bilibili-video-tool.py      # 视频目录工具箱（主程序）
├── icon/
│   └── cai.jpg                   # 程序图标
├── download/                     # 下载输出目录（已 gitignore）
├── .gitignore
└── README.md
```

---

## 🚀 环境配置

### 1. Python

要求 **Python 3.10+**（使用了 `X | Y` 类型联合语法）。

下载地址：https://www.python.org/downloads/

### 2. yt-dlp

```bash
pip install yt-dlp
```

> yt-dlp 是核心下载引擎，负责解析视频 URL 和下载视频流。

### 3. ffmpeg

**必须安装 ffmpeg**，yt-dlp 依赖它来合并视频流和音频流。

#### Windows（推荐）

1. 下载 ffmpeg：https://www.gyan.dev/ffmpeg/builds/（选择 `release essentials`）
2. 解压到某个目录，例如 `D:\0_env\ffmpeg\`
3. 确保目录结构为：`D:\0_env\ffmpeg\bin\ffmpeg.exe`

#### 其他安装方式

- **macOS**：`brew install ffmpeg`
- **Linux**：`sudo apt install ffmpeg` 或 `sudo yum install ffmpeg`

#### 配置 ffmpeg 路径

脚本中默认 ffmpeg 路径为：

```python
FFMPEG_DIR = r"D:\0_env\ffmpeg\bin"
```

如果你的 ffmpeg 安装在其他位置，请修改脚本顶部的 `FFMPEG_DIR` 变量。

> 如果 ffmpeg 已加入系统 PATH，脚本会自动回退使用 PATH 中的 ffmpeg，无需额外配置。

### 4. Pillow（可选）

```bash
pip install Pillow
```

> 用于加载自定义程序图标（`icon/cai.jpg`）。未安装时图标不显示，不影响功能。

### 5. 一次性安装所有依赖

```bash
pip install yt-dlp Pillow
```

---

## 📖 使用方法

### 启动主程序

#### 命令行启动

```bash
python 3-bilibili-video-tool.py
```

#### VS Code Task 启动

项目已配置 VS Code Task，支持一键运行各脚本：

| Task 名称 | 脚本 |
|------------|------|
| ▶ 1-命令行版下载 | `1-get-video-files.py` |
| ▶ 2-GUI下载器 | `2-get-video-files-ui.py` |
| ▶ 3-视频目录工具箱 | `3-bilibili-video-tool.py` |

操作方式：`Ctrl+Shift+P` → 输入 `Tasks: Run Task` → 选择对应任务。

### 下载视频

1. 切换到「⬇ 下载视频」选项卡
2. 输入 B 站视频 URL（如 `https://www.bilibili.com/video/BVxxxxxx`）
3. 点击「🔍 解析条目」
4. 勾选需要下载的视频
5. 点击「⬇ 下载选中条目」

### 合并目录

1. 切换到「🔗 合并目录」选项卡
2. 设置源目录（默认为 `download` 文件夹）
3. 点击「🔍 扫描目录」
4. 勾选需要合并的系列
5. 点击「🔗 合并选中系列」

### 传输文件

1. 切换到「📤 传输文件」选项卡
2. 设置源目录和目标目录
3. 点击「🔍 扫描」
4. 勾选需要传输的目录
5. 点击「📤 传输选中目录」

---

## ⚙️ 默认配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `FFMPEG_DIR` | `D:\0_env\ffmpeg\bin` | ffmpeg 安装路径 |
| `DEFAULT_OUTPUT_ROOT` | `./download` | 下载输出根目录 |
| `DEFAULT_TRANSFER_TARGET` | `D:\video` | 传输目标目录 |

可在脚本顶部修改这些常量来自定义配置。

---

## 📝 注意事项

- 下载 B 站视频时，部分视频可能需要登录 Cookie（脚本中保留了 `--cookies-from-browser` 的注释选项，可按需启用）
- 下载过程中每个视频之间有 3~5 秒随机延时，避免触发频率限制
- 合并功能会自动跳过 `00-merged-*` 前缀的目录，避免重复合并
- 文件冲突时提供图形化对话框，可对比文件大小和时间后选择覆盖或跳过

## 📜 License

MIT