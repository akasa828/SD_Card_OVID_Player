<a id="top"></a>

<p align="center">
  <a href="OVID_FORMAT.md">中文</a> · <strong>English</strong>
</p>

# 📦 OVID File Format

[← Back to the project README](../README_EN.md)

The current firmware uses OVID v2. Each file starts with a fixed 16-byte little-endian header:

| Offset | Length | Field | Requirement |
|---:|---:|---|---|
| 0 | 4 | `magic` | ASCII `OVID` |
| 4 | 1 | `width` | 1–255 and no greater than `OLED_WIDTH` |
| 5 | 1 | `height` | 1–255, does not have to be a multiple of 8, and no greater than `OLED_HEIGHT` |
| 6 | 1 | `version` | Fixed at 2 |
| 7 | 1 | `flags` | bit0 indicates per-frame CRC32 |
| 8 | 4 | `frame_count` | Number of frames; must be greater than 0 |
| 12 | 2 | `fps` | 1–120 |
| 14 | 2 | `header_crc16` | CRC16-CCITT of the first 14 bytes |

The byte count of one frame is:

```text
frame_bytes = ceil(height / 8) × width
```

Pixels are stored in OLED page-major order: all `width` columns of page 0 come first, followed by page 1, and so on. The video height does not have to be an exact multiple of 8; the firmware masks unused bits in the final page. A 4-byte little-endian CRC32 follows every frame. If a frame fails validation, the previous frame remains on screen while the player continues with the next frame.

The complete file length must satisfy this equation exactly:

```text
file_size = 16 + frame_count × (frame_bytes + 4)
```

<p align="right"><a href="#top">⬆️ Back to top</a></p>
