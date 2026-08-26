"""Local, copyable error reports and their Material dialog presentation."""

from __future__ import annotations

import errno
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

import flet as ft

from converter_services import QueueJob
from converter_version import DISPLAY_NAME, VERSION


def error_summary(error: Exception) -> str:
    if isinstance(error, FileNotFoundError):
        return "找不到所需文件或目录。请检查路径是否仍然有效。"
    if isinstance(error, PermissionError):
        return "没有访问权限，或文件正被其他程序占用。请检查权限和占用情况。"
    if isinstance(error, FileExistsError):
        return "目标文件已存在。请选择其他名称，或确认需要覆盖后再试。"
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return "磁盘空间不足。请释放空间，或选择其他保存位置。"
    message = str(error).strip()
    if isinstance(error, ValueError) and message and len(message) <= 160 and "\n" not in message:
        return message
    return "操作未完成。请展开错误详情查看原因，必要时复制详情以便排查。"


@dataclass(frozen=True)
class ErrorReport:
    title: str
    summary: str
    details: str

    @classmethod
    def from_exception(cls, title: str, error: Exception) -> ErrorReport:
        details = (
            f"{DISPLAY_NAME} {VERSION}\n{title}\n\n"
            f"{type(error).__name__}: {error}"
        )
        return cls(title, error_summary(error), details)

    @classmethod
    def from_job(cls, job: QueueJob) -> ErrorReport:
        parameters = json.dumps(asdict(job.options), ensure_ascii=False, indent=2, default=str)
        details = (
            f"{DISPLAY_NAME} {VERSION}\n任务：{job.options.source.name}\n"
            f"状态：{job.state}\n目标屏幕：{job.target_profile}\n\n"
            f"错误：\n{job.error or '未记录具体错误'}\n\n参数快照：\n{parameters}"
        )
        return cls(
            "转换失败",
            f"{job.options.source.name}\n这项转换没有完成。可以查看详情，或返回该任务检查参数与输出位置。",
            details,
        )


class ErrorDetailsDialog:
    def __init__(
        self,
        page: ft.Page,
        clipboard: ft.Clipboard,
        report: ErrorReport,
        *,
        on_edit: Callable[[ErrorDetailsDialog], Awaitable[None]] | None = None,
    ):
        self.page = page
        self.clipboard = clipboard
        self.report = report
        self.on_edit = on_edit
        self.closed = False
        self.copying = False
        self.editing = False
        self.status = ft.Text(size=12, visible=False)
        self.details = ft.Text(report.details, selectable=True, size=12)
        self.details_section = ft.ExpansionTile(
            title=ft.Text("错误详情"),
            subtitle=ft.Text("可复制；分享前请检查是否含个人路径"),
            expanded=False,
            maintain_state=True,
            controls=[self.details],
            controls_padding=ft.Padding.only(left=16, right=16, bottom=12),
        )
        self.copy_button = ft.TextButton(
            "复制详情", icon=ft.Icons.CONTENT_COPY, on_click=self.copy,
        )
        self.edit_button = ft.FilledButton("修改任务参数", on_click=self.edit)
        actions = [self.copy_button, ft.TextButton("关闭", on_click=self.close)]
        if on_edit is not None:
            actions.append(self.edit_button)
        self.dialog = ft.AlertDialog(
            title=ft.Text(report.title),
            icon=ft.Icon(ft.Icons.ERROR_OUTLINE, color=ft.Colors.ERROR),
            scrollable=True,
            content=ft.Column(
                [ft.Text(report.summary, selectable=True), self.details_section, self.status],
                tight=True,
                spacing=12,
                width=520,
            ),
            actions=actions,
            actions_overflow_button_spacing=8,
            on_dismiss=self.dismiss,
        )

    @property
    def is_open(self) -> bool:
        return not self.closed and self.dialog.open

    def show(self, presenter: Callable[[ft.DialogControl], None] | None = None) -> None:
        (presenter or self.page.show_dialog)(self.dialog)

    def dismiss(self, _=None) -> None:
        self.closed = True

    def close(self, _=None) -> None:
        if not self.is_open:
            return
        self.closed = True
        self.dialog.open = False
        self.page.update(self.dialog)

    def show_status(self, text: str, *, error: bool = False) -> None:
        if not self.is_open:
            return
        self.status.value = text
        self.status.visible = True
        self.status.color = ft.Colors.ERROR if error else ft.Colors.ON_SURFACE_VARIANT
        self.page.update(self.status)

    async def copy(self, _=None) -> None:
        if not self.is_open or self.copying:
            return
        self.copying = True
        self.copy_button.disabled = True
        self.page.update(self.copy_button)
        try:
            await self.clipboard.set(self.report.details)
        except Exception:
            self.show_status("无法写入剪贴板。可展开错误详情，选中文字手动复制。", error=True)
        else:
            self.show_status("已复制错误详情；分享前请检查其中的文件路径。")
        finally:
            self.copying = False
            self.copy_button.disabled = False
            if self.is_open:
                self.page.update(self.copy_button)

    async def edit(self, _=None) -> None:
        if not self.is_open or self.editing or self.on_edit is None:
            return
        self.editing = True
        self.edit_button.disabled = True
        self.page.update(self.edit_button)
        try:
            await self.on_edit(self)
        finally:
            self.editing = False
            self.edit_button.disabled = False
            if self.is_open:
                self.page.update(self.edit_button)
