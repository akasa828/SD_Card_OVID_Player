"""Display-only inspection of a captured OLED preview frame."""

from __future__ import annotations

from dataclasses import dataclass
import math

import flet as ft


@dataclass(frozen=True)
class PreviewSnapshot:
    png: bytes
    width: int
    height: int
    caption: str


def inspector_viewport(width: float | None, height: float | None) -> tuple[int, int]:
    def dimension(value, fallback):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return fallback
        return number if math.isfinite(number) and number > 0 else fallback

    return (
        round(max(240, min(1000, dimension(width, 1120) - 128))),
        round(max(160, min(520, dimension(height, 760) - 300))),
    )


class PixelInspector:
    SCALES = (1, 2, 4, 8)

    def __init__(self, page: ft.Page, snapshot: PreviewSnapshot):
        self.page = page
        self.snapshot = snapshot
        self.closed = False
        self.scale = 4
        self.viewport_width, self.viewport_height = inspector_viewport(page.width, page.height)
        self.image = ft.Image(
            src=snapshot.png,
            gapless_playback=True,
            fit=ft.BoxFit.FILL,
            filter_quality=ft.FilterQuality.NONE,
            anti_alias=False,
        )
        self.canvas = ft.Container(
            content=self.image,
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.BLACK,
        )
        self.viewer = ft.InteractiveViewer(
            content=self.canvas,
            width=self.viewport_width,
            height=self.viewport_height,
            constrained=False,
            scale_enabled=False,
            min_scale=1,
            max_scale=1,
            pan_enabled=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self.scale_picker = ft.Dropdown(
            label="查看倍数",
            value="4",
            width=140,
            options=[ft.DropdownOption(key=str(value), text=f"{value}×") for value in self.SCALES],
            on_select=self.change_scale,
        )
        self.dimensions = ft.Text(size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.status = ft.Text(size=12, color=ft.Colors.ERROR, visible=False)
        self._size_image()
        self.dialog = ft.AlertDialog(
            title=ft.Text("OLED 像素查看"),
            scrollable=True,
            content=ft.Column(
                [
                    ft.Text(snapshot.caption, selectable=True),
                    ft.Row([self.scale_picker, self.dimensions], wrap=True),
                    self.viewer,
                    ft.Text(
                        "固定当前帧；拖动画面查看超出区域。倍数按界面逻辑像素计算，不改变输出文件。",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    self.status,
                ],
                tight=True,
                width=self.viewport_width,
                spacing=12,
            ),
            actions=[ft.TextButton("关闭", on_click=self.close)],
            on_dismiss=self.dismiss,
        )

    @property
    def is_open(self) -> bool:
        return not self.closed and self.dialog.open

    def show(self) -> None:
        self.page.show_dialog(self.dialog)

    def _size_image(self) -> None:
        self.image.width = self.snapshot.width * self.scale
        self.image.height = self.snapshot.height * self.scale
        self.canvas.width = max(self.viewport_width, self.image.width)
        self.canvas.height = max(self.viewport_height, self.image.height)
        self.dimensions.value = (
            f"{self.snapshot.width}×{self.snapshot.height} 像素 · "
            f"显示 {self.image.width}×{self.image.height}"
        )

    async def change_scale(self, event) -> None:
        if not self.is_open:
            return
        try:
            value = int(event.control.value)
        except (TypeError, ValueError):
            value = self.scale
        if value not in self.SCALES:
            value = self.scale
        self.scale_picker.value = str(value)
        if value == self.scale:
            self.page.update(self.scale_picker)
            return
        self.scale = value
        self._size_image()
        self.status.visible = False
        self.page.update(self.canvas, self.dimensions, self.scale_picker, self.status)
        try:
            await self.viewer.reset()
        except Exception:
            if self.is_open:
                self.status.value = "画面定位未响应，可关闭此窗口后重新查看。输出参数没有改变。"
                self.status.visible = True
                self.page.update(self.status)

    def dismiss(self, _=None) -> None:
        self.closed = True

    def close(self, _=None) -> None:
        if not self.is_open:
            return
        self.closed = True
        self.dialog.open = False
        self.page.update(self.dialog)
