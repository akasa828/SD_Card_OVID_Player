from typing import Optional

import flet as ft


@ft.control("FletDropZone")
class FletDropZone(ft.LayoutControl):
    """A native desktop file drop target used by release builds."""

    message: str = "将图片、GIF、视频或图片目录拖到这里"
    active_message: str = "松开鼠标以添加素材"
    background_color: ft.ColorValue = "#0F000000"
    active_color: ft.ColorValue = "#246750A4"
    foreground_color: ft.ColorValue = "#6750A4"
    border_color: ft.ColorValue = "#79747E"
    on_drop: Optional[ft.ControlEventHandler["FletDropZone"]] = None
    on_hover_change: Optional[ft.ControlEventHandler["FletDropZone"]] = None
