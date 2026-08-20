<a id="top"></a>

# 📦 OVID 文件格式

[← 返回项目 README](../README.md)

当前固件使用 OVID v2。文件以固定的 16 字节小端序文件头开始：

| 偏移 | 长度 | 字段 | 要求 |
|---:|---:|---|---|
| 0 | 4 | `magic` | ASCII `OVID` |
| 4 | 1 | `width` | 1–255，不能大于 `OLED_WIDTH` |
| 5 | 1 | `height` | 1–255，可不是 8 的倍数，不能大于 `OLED_HEIGHT` |
| 6 | 1 | `version` | 固定为 2 |
| 7 | 1 | `flags` | bit0 表示逐帧 CRC32 |
| 8 | 4 | `frame_count` | 帧数，必须大于 0 |
| 12 | 2 | `fps` | 1–120 |
| 14 | 2 | `header_crc16` | 前 14 字节的 CRC16-CCITT |

单帧字节数为：

```text
frame_bytes = ceil(height / 8) × width
```

画面按 OLED 页主序保存：先写第 0 页的 `width` 列，再写第 1 页。视频高度不必正好是 8 的倍数，固件会屏蔽最后一页的无效位。每帧后追加 4 字节小端 CRC32；校验失败时保持上一帧，并继续尝试下一帧。

完整文件长度必须严格满足：

```text
file_size = 16 + frame_count × (frame_bytes + 4)
```

<p align="right"><a href="#top">⬆️ 返回顶部</a></p>
