# 参与贡献 / Contributing

感谢你愿意改进这个项目。提交 Issue 或 Pull Request 前，请先确认问题属于播放器本身，而不是接线、供电或素材转换错误。

Thank you for helping improve this project. Before opening an Issue or Pull Request, please confirm that the problem belongs to the player rather than wiring, power, or source-material conversion.

## 开发流程 / Development workflow

1. Fork 仓库，从最新的 `main` 创建用途明确的分支。
2. 打开根目录的 `SD_Card_OVID_Player.code-workspace`；STM32 固件位于 `STM32F103/`。
3. 一个提交只完成一个可以独立说明的改动，并在提交前执行相关测试。
4. 提交 Pull Request 时说明测试过的硬件；没有实机测试也请明确写出。

1. Fork the repository and create a focused branch from the latest `main`.
2. Open `SD_Card_OVID_Player.code-workspace`; the STM32 firmware is under `STM32F103/`.
3. Keep each commit focused on one independently describable change and run the relevant tests.
4. State which hardware was tested in the Pull Request. If no target-board test was performed, say so explicitly.

## Commit 格式 / Commit format

使用英文 Conventional Commits：

Use Conventional Commits with an English imperative summary:

```text
type(scope): imperative summary
```

允许的类型为 `feat`（增加功能）、`fix`（修复问题）、`refactor`（重构代码，但不改变功能）、`perf`（性能优化）、`docs`（文档修改）、`test`（测试代码）、`build`（构建系统、CMake、工具链）、`ci`（GitHub Actions 等自动化配置）、`chore`（仓库整理、资源更新等杂项）和 `revert`（撤销某次修改）。scope 可以省略，标题不要以句号结尾。

Allowed types are `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `build`, `ci`, `chore`, and `revert`. The scope is optional. Do not end the subject with a period.

```text
feat(ui): add a card information page
fix(player): reject truncated OVID files
refactor(sd): decouple the SPI transport
```

不要使用 `update`、`修改` 或单独的版本号作为提交标题。版本使用 Git tag 表示。

Do not use vague subjects such as `update` or a version number by itself. Releases are represented by Git tags.

## 本地检查 / Local checks

Python 工具测试只依赖标准库：

The Python tool tests use only the standard library:

```powershell
python -m unittest discover -s tools/tests -v
python tools/check_commit_messages.py --head HEAD
```

在已安装 GNU Arm Embedded Toolchain、CMake 和 Ninja 的环境中，可以从固件目录构建：

With GNU Arm Embedded Toolchain, CMake, and Ninja installed:

```powershell
cd STM32F103
cmake --preset Debug
cmake --build --preset Debug
cmake --preset Release
cmake --build --preset Release
```

## 硬件问题需要的信息 / Hardware report details

请至少提供以下信息：

Please include at least:

- 固件版本或 commit SHA / firmware version or commit SHA
- STM32 板卡与 Flash 容量 / STM32 board and Flash capacity
- OLED 控制器、分辨率和 I2C 速率 / OLED controller, resolution, and I2C clock
- SD 卡容量、文件系统和模块型号 / SD capacity, filesystem, and module
- OVID 分辨率、FPS、帧数和版本 / OVID dimensions, FPS, frame count, and version
- 串口日志、复现步骤和预期结果 / UART log, reproduction steps, and expected result

## Pull Request 检查 / Pull Request checklist

- Debug 与 Release 构建通过 / Debug and Release build successfully.
- Python 工具测试通过 / Python tool tests pass.
- 没有加入本机绝对路径或构建产物 / No machine-specific paths or build artifacts are committed.
- 用户可见行为同步更新中英文文档 / User-visible behavior is reflected in both languages.
- 明确说明实机测试范围 / Target-board test coverage is stated.
