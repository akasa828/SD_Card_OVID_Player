#!/usr/bin/env python3
"""Reusable application services for the desktop OVID converter."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Iterable

from media2ovid import ConversionOptions, ConversionProgress, SourceInfo, estimate_output_bytes
from ovid_codec import OvidSummary, frame_bytes


TARGET_PROFILES = {
    "stm32f103-128x64": ("STM32F103C8T6 · 128×64", 128, 64),
    "stm32f103-128x32": ("STM32F103C8T6 · 128×32", 128, 32),
    "stm32f103-96x64": ("STM32F103C8T6 · 96×64", 96, 64),
    "stm32f103-128x128": ("STM32F103C8T6 · 128×128", 128, 128),
    "custom": ("自定义屏幕", 0, 0),
}


def application_data_dir() -> Path:
    root = os.getenv("FLET_APP_STORAGE_DATA")
    if root:
        return Path(root)
    return Path(os.getenv("LOCALAPPDATA", Path.home())) / "OVID Converter"


@dataclass(frozen=True)
class ConversionPreset:
    name: str
    width: int = 128
    height: int = 64
    fps: int = 15
    fit: str = "contain"
    dither: str = "threshold"
    threshold: int = 128
    invert: bool = False
    background: str = "black"
    recursive: bool = False
    workers: int = 0
    fast_video: bool = False
    target_profile: str = "stm32f103-128x64"
    builtin: bool = False

    @classmethod
    def from_options(
        cls,
        name: str,
        options: ConversionOptions,
        target_profile: str,
        *,
        builtin: bool = False,
    ) -> "ConversionPreset":
        return cls(
            name=name,
            width=options.width,
            height=options.height,
            fps=options.fps,
            fit=options.fit,
            dither=options.dither,
            threshold=options.threshold,
            invert=options.invert,
            background=options.background,
            recursive=options.recursive,
            workers=options.workers,
            fast_video=options.fast_video,
            target_profile=target_profile,
            builtin=builtin,
        )

    def apply(self, options: ConversionOptions) -> ConversionOptions:
        return replace(
            options,
            width=self.width,
            height=self.height,
            fps=self.fps,
            fit=self.fit,
            dither=self.dither,
            threshold=self.threshold,
            invert=self.invert,
            background=self.background,
            recursive=self.recursive,
            workers=self.workers,
            fast_video=self.fast_video,
        )


BUILTIN_PRESETS = (
    ConversionPreset("STM32F103 · 128×64 · 15 FPS", builtin=True),
    ConversionPreset(
        "STM32F103 · 128×32 · 15 FPS",
        width=128,
        height=32,
        target_profile="stm32f103-128x32",
        builtin=True,
    ),
    ConversionPreset(
        "96×64 · 15 FPS",
        width=96,
        height=64,
        target_profile="stm32f103-96x64",
        builtin=True,
    ),
    ConversionPreset(
        "128×128 · 15 FPS",
        width=128,
        height=128,
        target_profile="stm32f103-128x128",
        builtin=True,
    ),
)


class PresetStore:
    def __init__(self, path: Path | None = None):
        self.path = path or application_data_dir() / "presets.json"

    def load_user_presets(self) -> list[ConversionPreset]:
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            presets = []
            for value in values:
                value = dict(value)
                value["builtin"] = False
                preset = ConversionPreset(**value)
                if preset.name.strip():
                    presets.append(preset)
            return presets
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []

    def all_presets(self) -> list[ConversionPreset]:
        return [*BUILTIN_PRESETS, *self.load_user_presets()]

    def save_user_presets(self, presets: Iterable[ConversionPreset]) -> None:
        values = [asdict(replace(preset, builtin=False)) for preset in presets if not preset.builtin]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def upsert(self, preset: ConversionPreset) -> None:
        if not preset.name.strip():
            raise ValueError("预设名称不能为空")
        if any(item.name == preset.name and item.builtin for item in BUILTIN_PRESETS):
            raise ValueError("内置预设不能被覆盖")
        values = self.load_user_presets()
        replacement = replace(preset, builtin=False)
        for index, item in enumerate(values):
            if item.name.casefold() == preset.name.casefold():
                values[index] = replacement
                break
        else:
            values.append(replacement)
        self.save_user_presets(values)

    def delete(self, name: str) -> None:
        values = [item for item in self.load_user_presets() if item.name != name]
        self.save_user_presets(values)

    def reset(self) -> None:
        self.path.unlink(missing_ok=True)


def otsu_threshold(gray) -> int:
    """Return a deterministic Otsu threshold for a Pillow grayscale image."""
    histogram = gray.convert("L").histogram()[:256]
    total = sum(histogram)
    if total == 0:
        return 128
    weighted_sum = sum(index * count for index, count in enumerate(histogram))
    background_weight = 0
    background_sum = 0
    best_threshold = 128
    best_variance = -1.0
    for threshold, count in enumerate(histogram):
        background_weight += count
        if background_weight == 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0:
            break
        background_sum += threshold * count
        background_mean = background_sum / background_weight
        foreground_mean = (weighted_sum - background_sum) / foreground_weight
        variance = background_weight * foreground_weight * (background_mean - foreground_mean) ** 2
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return best_threshold


def suggested_threshold(gray, mode: str = "standard") -> int:
    offsets = {"standard": 0, "dark-detail": -16, "noise-reduction": 16}
    if mode not in offsets:
        raise ValueError(f"未知自动阈值模式：{mode}")
    return min(255, max(0, otsu_threshold(gray) + offsets[mode]))


@dataclass(frozen=True)
class CompatibilityIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class CompatibilityReport:
    frame_bytes: int
    estimated_bytes: int | None
    required_oled_width: int
    required_oled_height: int
    required_gram_bytes: int
    issues: tuple[CompatibilityIssue, ...]

    @property
    def can_convert(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def check_compatibility(
    options: ConversionOptions,
    info: SourceInfo,
    target_profile: str = "stm32f103-128x64",
    *,
    custom_target: tuple[int, int] | None = None,
) -> CompatibilityReport:
    issues: list[CompatibilityIssue] = []
    try:
        options.validate()
    except (OSError, ValueError) as exc:
        issues.append(CompatibilityIssue("error", "options", str(exc)))
    per_frame = frame_bytes(options.width, options.height)
    required_height = ((options.height + 7) // 8) * 8
    required_gram = frame_bytes(options.width, required_height)
    profile = TARGET_PROFILES.get(target_profile, TARGET_PROFILES["custom"])
    target_width, target_height = profile[1], profile[2]
    if target_profile == "custom" and custom_target is not None:
        target_width, target_height = custom_target
    if target_width and (options.width > target_width or options.height > target_height):
        issues.append(
            CompatibilityIssue(
                "error",
                "screen-size",
                f"输出 {options.width}×{options.height} 超过目标屏幕 {target_width}×{target_height}",
            )
        )
    estimate = estimate_output_bytes(options, info)
    parent = options.output.parent
    if not parent.is_dir():
        issues.append(CompatibilityIssue("error", "output-directory", f"输出目录不存在：{parent}"))
    else:
        if not os.access(parent, os.W_OK):
            issues.append(
                CompatibilityIssue("error", "output-permission", f"输出目录不可写：{parent}")
            )
        try:
            free_bytes = shutil.disk_usage(parent).free
            if estimate is not None and free_bytes < estimate:
                issues.append(
                    CompatibilityIssue(
                        "error", "disk-space", f"磁盘剩余空间不足，预计需要 {estimate} B"
                    )
                )
        except OSError as exc:
            issues.append(CompatibilityIssue("warning", "disk-space", f"无法读取剩余空间：{exc}"))
    if options.output.suffix.casefold() != ".bin":
        issues.append(CompatibilityIssue("error", "extension", "输出文件扩展名必须是 .BIN"))
    if len(options.output.name) > 63:
        issues.append(
            CompatibilityIssue("warning", "filename", "文件名超过播放器当前 63 字符 LFN 上限")
        )
    if required_gram * 2 + options.width > 20 * 1024:
        issues.append(
            CompatibilityIssue(
                "warning",
                "ram",
                "仅 OLED 双缓冲和页临时缓冲已接近或超过 STM32F103C8T6 的 20 KiB RAM",
            )
        )
    return CompatibilityReport(
        per_frame,
        estimate,
        options.width,
        required_height,
        required_gram,
        tuple(issues),
    )


def unique_output_path(path: Path, *, reserved: set[Path] | None = None) -> Path:
    reserved = reserved or set()
    if not path.exists() and path.resolve() not in reserved:
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists() and candidate.resolve() not in reserved:
            return candidate
    raise FileExistsError(f"无法为输出生成不重复的文件名：{path}")


class ConversionLogger:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or application_data_dir() / "logs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "converter.log"
        self.logger = logging.getLogger(f"ovid-converter-{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        handler = logging.handlers.RotatingFileHandler(
            self.path,
            maxBytes=1024 * 1024,
            backupCount=4,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)

    def event(self, stage: str, message: str, *, level: int = logging.INFO) -> None:
        self.logger.log(level, "[%s] %s", stage, message)

    def read(self, limit: int = 200_000) -> str:
        try:
            data = self.path.read_text(encoding="utf-8", errors="replace")
            return data[-limit:]
        except OSError:
            return ""

    def export(self, path: Path) -> None:
        path.write_text(self.read(limit=10_000_000), encoding="utf-8")


@dataclass
class QueueJob:
    options: ConversionOptions
    target_profile: str = "stm32f103-128x64"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "queued"
    progress: ConversionProgress | None = None
    summary: OvidSummary | None = None
    error: str = ""
    selected: bool = True
    frozen: bool = False
    created_at: float = field(default_factory=time.time)


class ConversionQueue:
    VALID_STATES = frozenset({"queued", "running", "completed", "failed", "cancelled"})

    def __init__(self):
        self._jobs: list[QueueJob] = []
        self._lock = threading.RLock()

    def snapshot(self) -> tuple[QueueJob, ...]:
        with self._lock:
            return tuple(self._jobs)

    def add(
        self,
        options: ConversionOptions,
        *,
        target_profile: str = "stm32f103-128x64",
    ) -> QueueJob:
        if not options.force:
            with self._lock:
                reserved = {job.options.output.resolve() for job in self._jobs}
            output = unique_output_path(options.output, reserved=reserved)
            options = replace(options, output=output)
        job = QueueJob(options, target_profile=target_profile)
        with self._lock:
            self._jobs.append(job)
        return job

    def next_queued(self) -> QueueJob | None:
        with self._lock:
            return next((job for job in self._jobs if job.state == "queued"), None)

    def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        progress: ConversionProgress | None = None,
        summary: OvidSummary | None = None,
        error: str | None = None,
    ) -> QueueJob:
        if state is not None and state not in self.VALID_STATES:
            raise ValueError(f"未知队列状态：{state}")
        with self._lock:
            job = self.find(job_id)
            if state is not None:
                job.state = state
            if progress is not None:
                job.progress = progress
            if summary is not None:
                job.summary = summary
            if error is not None:
                job.error = error
            return job

    def find(self, job_id: str) -> QueueJob:
        for job in self._jobs:
            if job.id == job_id:
                return job
        raise KeyError(job_id)

    def retry(self, job_id: str) -> QueueJob:
        with self._lock:
            job = self.find(job_id)
            job.state = "queued"
            job.progress = None
            job.summary = None
            job.error = ""
            return job

    def replace_options(
        self,
        job_id: str,
        options: ConversionOptions,
        *,
        target_profile: str | None = None,
    ) -> QueueJob:
        with self._lock:
            job = self.find(job_id)
            if job.state == "running" or job.frozen:
                raise ValueError("正在转换的任务不能修改参数")
            job.options = options
            if target_profile is not None:
                job.target_profile = target_profile
            job.progress = None
            job.summary = None
            job.error = ""
            job.state = "queued"
            return job

    def set_selected(self, job_id: str, selected: bool) -> QueueJob:
        with self._lock:
            job = self.find(job_id)
            if job.frozen:
                return job
            job.selected = bool(selected)
            return job

    def freeze_selected(self) -> tuple[QueueJob, ...]:
        with self._lock:
            jobs = tuple(
                job
                for job in self._jobs
                if job.selected and job.state != "running" and not job.frozen
            )
            for job in jobs:
                if job.state in {"completed", "failed", "cancelled"}:
                    job.state = "queued"
                    job.progress = None
                    job.summary = None
                    job.error = ""
                job.frozen = True
            return jobs

    def unfreeze(self, job_id: str) -> QueueJob:
        with self._lock:
            job = self.find(job_id)
            job.frozen = False
            return job

    def remove(self, job_id: str) -> None:
        with self._lock:
            job = self.find(job_id)
            if job.state == "running":
                raise ValueError("正在转换的任务不能直接移除，请先取消")
            self._jobs.remove(job)

    def clear_completed(self) -> None:
        with self._lock:
            self._jobs[:] = [job for job in self._jobs if job.state not in {"completed", "cancelled"}]
