## Summary / 变更概述

<!-- Explain one focused change and why it is needed. / 说明一个明确改动及其原因。 -->

## Type / 类型

- [ ] `feat` New behavior / 新功能
- [ ] `fix` Bug fix / 错误修复
- [ ] `refactor` Internal restructuring / 内部重构
- [ ] `docs` Documentation / 文档
- [ ] `test` or `ci` Tests and automation / 测试与自动化

## Verification / 验证

- [ ] Debug build
- [ ] Release build
- [ ] `python -m unittest discover -s tools/tests -v`
- [ ] Target-board test / 实机测试
- [ ] Not hardware-tested; reason provided / 未实机测试，已说明原因

Hardware, OLED, SD card, and OVID file used / 使用的硬件、OLED、SD 卡和 OVID 文件：

## Checklist / 检查

- [ ] Commits follow `type(scope): imperative summary`.
- [ ] No generated build output or machine-specific absolute path is included.
- [ ] User-visible changes are reflected in Chinese and English documentation.
- [ ] Existing OVID and driver compatibility is preserved or clearly documented.
