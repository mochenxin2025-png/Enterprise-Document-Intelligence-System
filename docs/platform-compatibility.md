# EDIS 平台兼容性

## 已验证系统

| 系统 | 版本 | Python | 状态 |
|---|---|---|---|
| Windows 10/11 | x86_64 | 3.11 | ✅ 主要开发平台 |
| macOS | Apple Silicon / Intel | 3.10+ | 🟡 理论兼容，待实测 |
| Linux (Ubuntu/Debian) | x86_64 | 3.10+ | 🟡 理论兼容，待实测 |

## 硬件支持

| 硬件 | Embedding | OCR | LLM |
|---|---|---|---|
| CPU only | ✅ 默认 | ✅ | N/A (API) |
| NVIDIA CUDA | ✅ `device: cuda` | ✅ | N/A |
| Apple Silicon MPS | ✅ `device: mps` | 🟡 | N/A |

## sqlite-vec 平台支持

sqlite-vec 通过 pip 安装预编译 wheel，支持:
- Windows x86_64
- macOS x86_64 / arm64
- Linux x86_64

无需单独编译。

## OCR 依赖说明

| 平台 | PaddleOCR 支持 |
|---|---|
| Windows | ✅ pip install paddleocr |
| macOS | 🟡 需 paddlepaddle (CPU only) |
| Linux | 🟡 需系统依赖 libgomp1, libgl1 |

如无法安装 PaddleOCR，OCR 功能自动跳过，文本类文档不受影响。

## CPU-only 部署

EDIS 完全支持 CPU-only 部署:
- Embedding: BGE 模型在 CPU 上运行（首次加载 ~5s）
- 检索: sqlite-vec L2 距离计算在 CPU 上
- LLM: 全部通过 API 调用，不消耗本地 GPU

推荐配置: 4+ CPU 核心，8GB+ RAM。

## 安装方式

```bash
# Windows
.\scripts\install_windows.ps1

# macOS
bash scripts/install_macos.sh

# Linux
bash scripts/install_linux.sh
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `EDIS_HOME` | 数据/日志/缓存根目录 | 当前工作目录 |
| `EDIS_PROFILE` | 强制指定 runtime profile | auto-detect |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `MINIMAX_API_KEY` | MiniMax Vision API | — |
