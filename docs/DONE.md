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
- Windows 包组装模拟测试通过；当前重构版本未在 Windows 原生系统构建和验证。
- macOS 实际 ZIP：中文/空格路径解压、整包迁移、私有运行时、首次信任取消/确认、Metal 探测、字幕烧录、MKV 封装、HTTP/JS、端口冲突、重复启动和退出验证通过。
- 本地成品约 383.9 MiB：`release/MediaTool-Portable-macOS-arm64.zip`；校验文件为同名 `.zip.sha256`，本地验证记录为 `release/MediaTool-Portable-macOS-arm64.validation.json`。生成文件不提交 Git。
- macOS 真实模型推理、干净机器和最低系统版本验收尚未完成。

历史 Windows 版本曾在 2026-10-09 完成便携包验证，见 [验证记录](../VALIDATION.md)；该结果不能替代当前重构版本验收。
