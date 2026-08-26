"""Track application dialogs without treating status snackbars as modal UI."""

from __future__ import annotations

import inspect

import flet as ft


class DialogHost:
    def __init__(self, page: ft.Page):
        self.page = page
        self._dialogs: dict[int, ft.AlertDialog] = {}

    @property
    def has_modal(self) -> bool:
        return any(dialog.open for dialog in self._dialogs.values())

    def show(self, dialog: ft.DialogControl) -> None:
        if not isinstance(dialog, ft.AlertDialog):
            self.page.show_dialog(dialog)
            return
        key = id(dialog)
        if key in self._dialogs:
            raise RuntimeError("Dialog is already displayed or waiting for dismissal")
        original_dismiss = dialog.on_dismiss
        finished = False

        async def dismiss(event):
            nonlocal finished
            if finished:
                return
            finished = True
            self._dialogs.pop(key, None)
            if dialog.on_dismiss is dismiss:
                dialog.on_dismiss = original_dismiss
            if original_dismiss is not None:
                result = original_dismiss(event)
                if inspect.isawaitable(result):
                    await result

        self._dialogs[key] = dialog
        dialog.on_dismiss = dismiss
        try:
            self.page.show_dialog(dialog)
        except Exception:
            finished = True
            self._dialogs.pop(key, None)
            if dialog.on_dismiss is dismiss:
                dialog.on_dismiss = original_dismiss
            raise
