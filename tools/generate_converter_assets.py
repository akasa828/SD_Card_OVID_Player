#!/usr/bin/env python3
"""Generate the original Windows icon used by OVID Converter builds."""

from pathlib import Path

from PIL import Image, ImageDraw


def generate_icon(output: Path) -> None:
    size = 256
    image = Image.new("RGBA", (size, size), (63, 81, 181, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((34, 50, 222, 206), radius=28, fill=(20, 20, 24, 255))
    draw.rounded_rectangle((48, 64, 208, 192), radius=18, outline=(232, 234, 246, 255), width=7)
    pixels = [(101, 94), (101, 116), (101, 138), (123, 105), (123, 127), (145, 116)]
    for x, y in pixels:
        draw.rectangle((x, y, x + 17, y + 17), fill=(255, 255, 255, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    generate_icon(Path(__file__).resolve().parent / "build" / "ovid_converter.ico")

