# 已办事项

更新日期：2026-10-14。未完成的验收见 [TODO.md](TODO.md)。

## macOS 支持与便携包

- [x] 接入 Apple Silicon MLX/Metal 推理适配层，增加设备探测、参数及前端设备显示，保留 CPU/CUDA 路径。
- [x] 构建自带可迁移 Python、依赖、静态 FFmpeg/FFprobe 和前端的 macOS arm64 ZIP；默认不含模型，无需用户安装开发工具。
- [x] 增加首次信任入口，要求用户确认路径并输入 `TRUST`，仅处理该包隔离标记；取消不修改包。这不是 Apple 公证。
- [x] 补齐 `httpx[socks]` / `socksio`，修复 SOCKS 代理下载缺失依赖问题；Hugging Face 模型配置的代理 HEAD 请求已验证，不代表完整权重下载完成。

## 工程与交付结构

- [x] 平台脚本归入 `scripts/windows/` 和 `scripts/macos/`，共用启动器归入 `scripts/common/`；根目录源码 `.command` 已迁入 macOS 目录。
- [x] 两个平台构建器统一输出至 `release/`，已有 macOS ZIP 和解压目录完成迁移，保留模型和用户数据。
- [x] 完善 [从源码构建两个平台便携包的方法](PORTABLE_BUILD.md)，包含环境准备、构建、缓存、验证和发布检查。
- [x] 增加文档维护约定及已办、待办记录。

## 2026-10-14 验证结果

- 后端测试：98 通过、1 项 CUDA 专项测试跳过；前端生产构建通过，仍有资源体积提示。
- Windows 包组装模拟测试通过；随后完成当前重构版本的 Windows 原生构建和本机隔离验证，见下节。
- macOS 实际 ZIP：中文/空格路径解压、整包迁移、私有运行时、首次信任取消/确认、Metal 探测、字幕烧录、MKV 封装、HTTP/JS、端口冲突、重复启动和退出验证通过。
- 本地成品约 383.9 MiB：`release/MediaTool-Portable-macOS-arm64.zip`；校验文件为同名 `.zip.sha256`，本地验证记录为 `release/MediaTool-Portable-macOS-arm64.validation.json`。生成文件不提交 Git。
- macOS 真实模型推理、干净机器和最低系统版本验收尚未完成。

历史 Windows 版本曾在 2026-10-09 完成便携包验证，见 [验证记录](../VALIDATION.md)；该结果不能替代当前重构版本验收。

## Windows 当前版本原生构建与验证

本轮从 2026-10-14 开始，跨日完成。基线提交 `c96121c266f3fdd2a7567c8450268b8e851515a1`，应用源码与该提交一致；本轮另外补齐许可证、增强验证脚本并更新文档，未改变识别业务逻辑。

- [x] Windows 11 build 26200、RTX 5090 D v2 / 24455 MiB、驱动 617.42；Python 3.12.15、Node 24.14.1、FFmpeg 9.0.2。补齐 socksio 1.0.0，重新完整封装运行时，`pip check` 通过。
- [x] 当前后端回归 93 passed / 8 skipped（7 个 macOS 专项及 1 个显式 CUDA 专项）；CUDA 取消专项单独执行 1 passed。TypeScript/Vite 构建通过，保留既有资源体积提示。
- [x] 实际 ZIP 经校验后在中文空格目录解压，清除开发环境 PATH/PYTHONPATH；首次初始化、迁移重建、迁移前模型/数据标记保留、HTTP/JS、端口冲突、重复启动、正常停止和 session 清理通过。
- [x] 使用旧测试目录中的完整 small 缓存，复制到新测试包离线验证：CPU int8 与 CUDA float16 识别，字幕校对、TXT/SRT、libx264 / H.264 NVENC / HEVC NVENC MP4、MKV、取消与重试通过。源缓存和发行 ZIP 不被写入测试结果。
- [x] 实际 Start-MediaTool.cmd / Stop-MediaTool.cmd 启动、停止、重启和包内 `pip check` 通过；测试使用 `--no-browser`，不作为自动打开浏览器 UI 验收。
- [x] 核对包内应用、前端、共用启动器字节与当前源码/构建产物一致；补充官方 v4.6.2 CTranslate2 MIT 许可证，核对 FFmpeg、前端和主要运行库许可证；默认包无模型。

成品：`release/MediaTool-Portable-Windows-x64.zip`，1,507,154,684 字节（约 1.40 GiB）。SHA256：

```text
f44351d5b254932d8e3844feaab727c225e1b8ef0e68ecd73c472aa70b20aa0b
```

证据：`.test-work/portable-verification/report.json`（最终离线完整验证）、`.test-work/windows-skip-inference-report.json`、`.test-work/windows-release-audit.json`、`.test-work/windows-entrypoint-report.json`；可公开摘要为 `release/MediaTool-Portable-Windows-x64.validation.json`，以上生成物不提交 Git。

本轮首次联网下载未验收：Xet 与普通 HTTP 都未完成权重传输，已停止对应测试并保留本地日志。最终功能测试明确使用缓存且关闭下载。干净 Windows 机器、自动打开浏览器和目标笔记本性能仍保留在 TODO，不以本机短片结果代替。
