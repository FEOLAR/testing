"""Окно WhiteHole Setup (customtkinter). Вся работа — в whitehole_setup.core,
здесь только интерфейс. Долгие операции идут в фоновых потоках, в UI-поток
результаты возвращаются через очередь (self._ui)."""
from __future__ import annotations

import os
import queue
import threading
import traceback
import webbrowser
from tkinter import messagebox
from typing import Callable, Optional

import customtkinter as ctk

from . import VERSION, core, texts
from .core import DeviceInfo, Engine, SetupError

from .theme import (ACCENT, ACCENT_HOVER, ACCENT_PRESSED, ACCENT_TEXT, BG, BORDER, DANGER, DANGER_HOVER,
                    DISABLED_BG, DISABLED_TEXT, FOCUS, LOG_BG, MUTED, PANEL, RAISED, SUCCESS, TEXT, TITLE, WARN)

CARD = RAISED  # карточки и второстепенные кнопки внутри панелей

STEPS = [
    ("find", "Найти телевизор", ""),
    ("install", "Установить", ""),
    ("login", "Вход", "через Telegram"),
    ("ads", "Убрать рекламу", "для продвинутых"),
    ("restore", "Вернуть как было", ""),
]


def set_enabled(widget, enabled: bool) -> None:
    """Включает/выключает виджет; у голубых кнопок в выключенном виде — серый фон."""
    try:
        widget.configure(state="normal" if enabled else "disabled")
        normal = getattr(widget, "_wh_fill", None)
        if normal is not None:
            widget.configure(fg_color=normal if enabled else DISABLED_BG)
    except Exception:
        pass  # виджет мог быть уже удалён


def accent_button(parent, danger: bool = False, **kw) -> ctk.CTkButton:
    """Основная кнопка: голубая заливка, тёмный текст, светлее при наведении, темнее при нажатии."""
    fill = DANGER if danger else ACCENT
    b = ctk.CTkButton(parent, fg_color=fill, hover_color=DANGER_HOVER if danger else ACCENT_HOVER,
                      text_color=ACCENT_TEXT, text_color_disabled=DISABLED_TEXT, **kw)
    b._wh_fill = fill
    if not danger:
        def press(_e):
            if b.cget("state") == "normal":
                b.configure(fg_color=ACCENT_PRESSED, hover_color=ACCENT_PRESSED)

        def release(_e):
            if b.cget("state") == "normal":
                b.configure(fg_color=fill, hover_color=ACCENT_HOVER)
        b.bind("<ButtonPress-1>", press, add="+")
        b.bind("<ButtonRelease-1>", release, add="+")
    return b


def focus_ring(entry) -> None:
    entry.bind("<FocusIn>", lambda e: entry.configure(border_color=FOCUS), add="+")
    entry.bind("<FocusOut>", lambda e: entry.configure(border_color=BORDER), add="+")


class StepRow(ctk.CTkFrame):
    """Строка шага в боковой колонке: номер/галочка + название (+ пометка).
    Текущий шаг — голубой, пройденный — голубая галочка, ожидающий — серый."""

    def __init__(self, parent, number: int, name: str, tag: str, font, small_font, command):
        super().__init__(parent, fg_color="transparent", corner_radius=12, border_width=1, border_color=PANEL,
                         height=52)
        self._command = command
        self._state = "normal"
        self._number = number
        self._current = False
        self.grid_columnconfigure(1, weight=1)
        self.mark = ctk.CTkLabel(self, text=str(number), width=26, font=font, text_color=MUTED)
        self.mark.grid(row=0, column=0, rowspan=2, padx=(12, 6), pady=8, sticky="w")
        self.name = ctk.CTkLabel(self, text=name, font=font, text_color=MUTED, anchor="w")
        self.name.grid(row=0, column=1, sticky="w", pady=(8 if tag else 12, 0 if tag else 12))
        self.tag = None
        if tag:
            self.tag = ctk.CTkLabel(self, text=tag, font=small_font, text_color=MUTED, anchor="w", height=16)
            self.tag.grid(row=1, column=1, sticky="w", pady=(0, 8))
        for w in (self, self.mark, self.name) + ((self.tag,) if self.tag else ()):
            w.bind("<Button-1>", self._click, add="+")
            w.bind("<Enter>", lambda e: self._hover(True), add="+")
            w.bind("<Leave>", lambda e: self._hover(False), add="+")

    def _click(self, _e=None) -> None:
        if self._state == "normal":
            self._command()

    def invoke(self) -> None:
        self._click()

    def _hover(self, on: bool) -> None:
        if not self._current:
            super().configure(fg_color=RAISED if (on and self._state == "normal") else "transparent")

    def set_look(self, current: bool, done: bool) -> None:
        self._current = current
        super().configure(fg_color=RAISED if current else "transparent", border_color=ACCENT if current else PANEL)
        self.mark.configure(text="✓" if done else str(self._number),
                            text_color=ACCENT if (done or current) else MUTED)
        self.name.configure(text_color=ACCENT if current else (TEXT if done else MUTED))

    def configure(self, require_redraw=False, **kw):
        if "state" in kw:
            self._state = kw.pop("state")
            try:
                self.configure_cursor()
            except Exception:
                pass
        if kw:
            super().configure(require_redraw=require_redraw, **kw)

    def configure_cursor(self) -> None:
        super().configure(cursor="hand2" if self._state == "normal" else "arrow")

    def cget(self, key):
        if key == "state":
            return self._state
        return super().cget(key)


class App(ctk.CTk):
    def __init__(self, engine: Optional[Engine] = None, start_adb: bool = True):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=BG)
        self.title("WhiteHole Setup")
        self.geometry("920x640")
        self.minsize(860, 600)
        self._set_icon(self)

        self._q: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._lanes: dict = {}               # lane -> token активной фоновой задачи
        self._token = 0
        self._cancel = threading.Event()     # ожидание разрешения на ТВ
        self._scan_cancel = threading.Event()
        self._found: list = []
        self.device: Optional[DeviceInfo] = None
        self.done: set = set()
        self._action_buttons: list = []
        self._dev_buttons: list = []
        self._log_open = False

        family = "Segoe UI" if os.name == "nt" else None
        self.f_title = ctk.CTkFont(family=family, size=26, weight="bold")
        self.f_h1 = ctk.CTkFont(family=family, size=22, weight="bold")
        self.f_body = ctk.CTkFont(family=family, size=14)
        self.f_small = ctk.CTkFont(family=family, size=12)
        self.f_btn = ctk.CTkFont(family=family, size=16, weight="bold")
        self.f_step = ctk.CTkFont(family=family, size=15)
        self.f_mono = ctk.CTkFont(family="Consolas" if os.name == "nt" else "monospace", size=11)

        if engine is None:
            adb = core.Adb(core.find_adb(), log=self.log)
            engine = Engine(adb, log=self.log)
        else:
            engine.log = self.log
            engine.adb.log = self.log
        self.engine = engine

        self._build()
        self.show_step("find")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self._pump)
        if start_adb:
            self.run_task(self._start_adb, busy_text="Запускаю adb…")

    # ------------------------------------------------------------ каркас

    def _set_icon(self, win) -> None:
        ico = core.resource_path("assets", "icon.ico")
        if os.name == "nt" and ico.exists():
            try:
                win.iconbitmap(str(ico))
            except Exception:
                pass

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Шапка
        head = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(18, 8))
        logo = core.resource_path("assets", "logo.png")
        if logo.exists():
            try:
                from PIL import Image

                img = ctk.CTkImage(Image.open(logo), size=(44, 44))
                ctk.CTkLabel(head, image=img, text="").pack(side="left", padx=(0, 12))
            except Exception:
                pass
        ctk.CTkLabel(head, text="WhiteHole", font=self.f_title, text_color=TITLE).pack(side="left")
        ctk.CTkLabel(head, text="  настройка телевизора", font=self.f_body, text_color=MUTED).pack(
            side="left", pady=(8, 0))

        # Боковая колонка с шагами
        side = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=16, width=250, border_width=1,
                            border_color=BORDER)
        side.grid(row=1, column=0, sticky="nsw", padx=(24, 12), pady=8)
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        self.step_buttons: dict = {}
        for i, (key, name, tag) in enumerate(STEPS):
            b = StepRow(side, i + 1, name, tag, self.f_step, self.f_small, lambda k=key: self.show_step(k))
            b.grid(row=i, column=0, sticky="ew", padx=10, pady=(12 if i == 0 else 3, 3))
            self.step_buttons[key] = b
        side.grid_rowconfigure(len(STEPS), weight=1)
        self.device_label = ctk.CTkLabel(side, text="Телевизор:\nне выбран", font=self.f_small,
                                         text_color=MUTED, justify="left", anchor="w", wraplength=220)
        self.device_label.grid(row=len(STEPS) + 1, column=0, sticky="ew", padx=18, pady=(0, 8))
        ctk.CTkButton(side, text="Как включить отладку на ТВ", height=36, corner_radius=10,
                      font=self.f_small, fg_color=CARD, hover_color=BORDER, text_color=TEXT,
                      command=self.show_help).grid(row=len(STEPS) + 2, column=0, sticky="ew",
                                                   padx=12, pady=(0, 14))

        # Страницы шагов
        self.content = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=16, border_width=1,
                                    border_color=BORDER)
        self.content.grid(row=1, column=1, sticky="nsew", padx=(12, 24), pady=8)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.pages = {
            "find": self._page_find(),
            "install": self._page_install(),
            "login": self._page_login(),
            "ads": self._page_ads(),
            "restore": self._page_restore(),
        }

        # Строка статуса + прогресс
        bar = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=24, pady=(6, 0))
        bar.grid_columnconfigure(1, weight=1)
        self.log_toggle = ctk.CTkButton(bar, text="▸ Подробности", width=130, height=28, corner_radius=8,
                                        font=self.f_small, fg_color="transparent", hover_color=CARD,
                                        text_color=MUTED, command=self.toggle_log)
        self.log_toggle.grid(row=0, column=0, sticky="w")
        self.status = ctk.CTkLabel(bar, text="", font=self.f_small, text_color=MUTED, anchor="w")
        self.status.grid(row=0, column=1, sticky="ew", padx=12)
        self.progress = ctk.CTkProgressBar(bar, width=200, height=8, progress_color=ACCENT, fg_color=CARD)
        self.progress.set(0)
        self.progress.grid(row=0, column=2, sticky="e")
        self.progress.grid_remove()

        # Журнал (скрыт по умолчанию)
        self.log_frame = ctk.CTkFrame(self, fg_color=LOG_BG, corner_radius=12, border_width=1,
                                      border_color=BORDER)
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_box = ctk.CTkTextbox(self.log_frame, height=150, font=self.f_mono, fg_color=LOG_BG,
                                      text_color=MUTED, wrap="word")
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        self.log_box.configure(state="disabled")
        ctk.CTkButton(self.log_frame, text="Скопировать для поддержки", height=26, width=200,
                      font=self.f_small, fg_color=CARD, hover_color=BORDER,
                      command=self.copy_log).grid(row=1, column=0, sticky="e", padx=8, pady=(0, 8))

        # Подвал
        foot = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        foot.grid(row=4, column=0, columnspan=2, sticky="ew", padx=24, pady=(4, 12))
        ctk.CTkLabel(foot, text=f"WhiteHole Setup {VERSION}", font=self.f_small, text_color=MUTED).pack(
            side="left")
        sup = ctk.CTkLabel(foot, text="Поддержка", font=self.f_small, text_color=ACCENT, cursor="hand2")
        sup.pack(side="right")
        sup.bind("<Button-1>", lambda e: webbrowser.open(core.SUPPORT_URL))

    def _page(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self.content, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        return f

    def _h1(self, parent, text: str, row: int, tag: str = "") -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=0, sticky="w", padx=28, pady=(20, 6))
        ctk.CTkLabel(box, text=text, font=self.f_h1, text_color=TEXT).pack(side="left")
        if tag:
            ctk.CTkLabel(box, text=f" {tag} ", font=self.f_small, text_color=MUTED, fg_color=RAISED,
                         corner_radius=8).pack(side="left", padx=12)

    def _p(self, parent, text: str, row: int, color: str = MUTED, font=None, pady=(0, 10)) -> ctk.CTkLabel:
        lab = ctk.CTkLabel(parent, text=text, font=font or self.f_body, text_color=color, justify="left",
                           anchor="w", wraplength=520)
        lab.grid(row=row, column=0, sticky="ew", padx=28, pady=pady)
        return lab

    def _big_button(self, parent, text: str, command, row: int, danger: bool = False) -> ctk.CTkButton:
        b = accent_button(parent, danger=danger, text=text, command=command, height=52, corner_radius=26,
                          font=self.f_btn)
        b.grid(row=row, column=0, sticky="w", padx=28, pady=(6, 12), ipadx=24)
        self._action_buttons.append(b)
        return b

    def _small_button(self, parent, text: str, command, **kw) -> ctk.CTkButton:
        b = ctk.CTkButton(parent, text=text, command=command, height=40, corner_radius=20, font=self.f_body,
                          fg_color=CARD, hover_color=BORDER, text_color=TEXT, border_width=1,
                          border_color=BORDER, **kw)
        self._action_buttons.append(b)
        return b

    # ------------------------------------------------------------ страницы

    def _page_find(self) -> ctk.CTkFrame:
        f = self._page()
        self._h1(f, "Найди телевизор", 0)
        self._p(f, "Телевизор и компьютер должны быть подключены к одному роутеру, а на телевизоре "
                   "должна быть включена отладка по сети.", 1)
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.grid(row=2, column=0, sticky="w", padx=28, pady=(6, 12))
        self.btn_scan = accent_button(top, text="Найти телевизор", command=self.on_scan, height=52, corner_radius=26,
                                      font=self.f_btn)
        self.btn_scan.pack(side="left", ipadx=24)
        self._action_buttons.append(self.btn_scan)
        self.btn_cancel = ctk.CTkButton(top, text="Отмена", command=self.on_cancel_scan, height=52,
                                        corner_radius=26, font=self.f_btn, fg_color=CARD, hover_color=BORDER,
                                        text_color=TEXT, border_width=1, border_color=BORDER)
        self.btn_next1 = ctk.CTkButton(top, text="Дальше →", command=lambda: self.show_step("install"), height=52,
                                       corner_radius=26, font=self.f_btn, fg_color=CARD, hover_color=BORDER,
                                       text_color=ACCENT, border_width=1, border_color=ACCENT)
        self.dev_list = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        self.dev_list.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 10))
        self.dev_list.grid_columnconfigure(0, weight=1)
        self._dev_placeholder()

        row = ctk.CTkFrame(f, fg_color="transparent")
        row.grid(row=4, column=0, sticky="w", padx=28, pady=(0, 6))
        ctk.CTkLabel(row, text="Ввести IP вручную:", font=self.f_body, text_color=MUTED).pack(side="left")
        self.ip_entry = ctk.CTkEntry(row, width=190, height=40, corner_radius=12, font=self.f_body,
                                     placeholder_text="192.168.1.50", fg_color=CARD, border_color=BORDER)
        self.ip_entry.pack(side="left", padx=10)
        focus_ring(self.ip_entry)
        self.ip_entry.bind("<Return>", lambda e: self.on_manual())
        # Ручной ввод не блокируется никогда (даже во время поиска).
        self.btn_manual = ctk.CTkButton(row, text="Подключить", command=self.on_manual, height=40, width=130,
                                        corner_radius=20, font=self.f_body, fg_color=CARD, hover_color=BORDER,
                                        text_color=TEXT, border_width=1, border_color=BORDER)
        self.btn_manual.pack(side="left")

        self.find_msg = self._p(f, "", 5, color=MUTED, pady=(6, 10))
        return f

    def _page_install(self) -> ctk.CTkFrame:
        f = self._page()
        self._h1(f, "Установить WhiteHole", 0)
        self._p(f, texts.INSTALL_INTRO, 1)
        self.with_happ = ctk.CTkCheckBox(f, text="Также установить Happ", font=self.f_body, text_color=TEXT,
                                         fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=MUTED,
                                         checkmark_color=ACCENT_TEXT)
        self.with_happ.grid(row=2, column=0, sticky="w", padx=28, pady=(4, 0))
        self.reinstall_happ = self.with_happ  # совместимость
        self.happ_note = self._p(f, texts.HAPP_OPTIONAL, 3, font=self.f_small, pady=(2, 8))
        self._big_button(f, "Установить", self.on_install, 4)
        self.install_msg = self._p(f, "", 5, color=TEXT)
        return f

    def _refresh_install_page(self) -> None:
        d = self.device
        if d is not None and d.needs_happ:
            self.with_happ.select()
            self.with_happ.configure(text="Также установить Happ (нужен на этом телевизоре)")
            self.happ_note.configure(text=texts.HAPP_REQUIRED.format(android=d.android or "?"), text_color=WARN)
        else:
            self.with_happ.configure(text="Также установить Happ")
            self.happ_note.configure(text=texts.HAPP_OPTIONAL, text_color=MUTED)

    def _page_login(self) -> ctk.CTkFrame:
        f = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        self._h1(f, "Вход", 0)
        self._p(f, texts.LOGIN_STEPS, 1, color=TEXT)
        self._big_button(f, "Открыть WhiteHole на ТВ", self.on_open_launcher, 2)
        self.login_msg = self._p(f, "", 3, color=TEXT, pady=(0, 6))

        # Разрешение VPN заранее (необязательно)
        self._h2(f, "Разрешить VPN заранее", 4, "по желанию")
        self._p(f, texts.VPN_GRANT, 5, font=self.f_small)
        b = self._small_button(f, "Разрешить VPN заранее", self.on_grant_vpn, width=230)
        b.grid(row=6, column=0, sticky="w", padx=28, pady=(2, 6))
        self.vpn_msg = self._p(f, "", 7, color=TEXT, pady=(0, 8))

        # Старые телевизоры: подписка в Happ
        self.happ_box = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        self.happ_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.happ_box, text="Для Happ (старые телевизоры)", font=self.f_btn, text_color=TEXT,
                     anchor="w").grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(self.happ_box, text=texts.SUB_HINT, font=self.f_small, text_color=MUTED, justify="left",
                     anchor="w", wraplength=480).grid(row=1, column=0, columnspan=2, sticky="w", padx=14)
        self.sub_entry = ctk.CTkEntry(self.happ_box, height=40, corner_radius=12, font=self.f_body, fg_color=PANEL,
                                      border_color=BORDER, placeholder_text="https://…")
        self.sub_entry.grid(row=2, column=0, sticky="ew", padx=(14, 0), pady=8)
        focus_ring(self.sub_entry)
        self._small_button(self.happ_box, "Вставить", self.paste_sub, width=100).grid(row=2, column=1, padx=14)
        self._small_button(self.happ_box, "Отправить в Happ на телевизоре", self.on_sub, width=280).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 6))
        self.sub_msg = ctk.CTkLabel(self.happ_box, text="", font=self.f_small, text_color=TEXT, justify="left",
                                    anchor="w", wraplength=480)
        self.sub_msg.grid(row=4, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 10))
        return f

    def _h2(self, parent, text: str, row: int, tag: str = "") -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=0, sticky="w", padx=28, pady=(14, 4))
        ctk.CTkLabel(box, text=text, font=self.f_btn, text_color=TEXT).pack(side="left")
        if tag:
            ctk.CTkLabel(box, text=f" {tag} ", font=self.f_small, text_color=MUTED, fg_color=RAISED,
                         corner_radius=8).pack(side="left", padx=10)

    def _refresh_login_page(self) -> None:
        d = self.device
        if d is not None and (d.has_happ or d.needs_happ):
            self.happ_box.grid(row=8, column=0, sticky="ew", padx=28, pady=(6, 12))
        else:
            self.happ_box.grid_remove()

    def _page_ads(self) -> ctk.CTkFrame:
        f = self._page()
        self._h1(f, "Убрать рекламу", 0, "для продвинутых")
        self.ads_warn = self._p(f, texts.ADS_WARNING_GENERIC, 1, color=ACCENT, font=self.f_btn, pady=(0, 4))
        self.ads_info = self._p(f, "Выбери, что отключить. Показываю только то, что есть на твоём телевизоре. "
                                   "Перед отключением сохраню резервную копию на этом компьютере.", 2,
                                font=self.f_small, pady=(0, 6))
        self.ads_list = ctk.CTkScrollableFrame(f, height=150, fg_color=CARD, corner_radius=12)
        self.ads_list.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 8))
        self.ads_list.grid_columnconfigure(0, weight=1)
        self._ads_vars: dict = {}
        self._ads_checks: list = []
        self._ads_choices: dict = {}
        self._ads_empty("Нажми «Проверить телевизор»")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.grid(row=4, column=0, sticky="w", padx=28, pady=(4, 0))
        self.btn_ads = accent_button(row, text="Убрать рекламу", command=self.on_ads, height=52,
                                     corner_radius=26, font=self.f_btn)
        self.btn_ads.pack(side="left", ipadx=24)
        self._action_buttons.append(self.btn_ads)
        self._small_button(row, "Проверить телевизор", self.on_ads_check, width=190).pack(side="left", padx=12)
        self.ads_msg = self._p(f, "", 5, color=TEXT, pady=(10, 10))
        return f

    def _ads_empty(self, text: str) -> None:
        self._clear_ads()
        ctk.CTkLabel(self.ads_list, text=text, font=self.f_small, text_color=MUTED, justify="left",
                     wraplength=520).grid(row=0, column=0, sticky="w", padx=10, pady=10)

    def _clear_ads(self) -> None:
        self._ads_vars, self._ads_checks, self._ads_choices = {}, [], {}
        for w in self.ads_list.winfo_children():
            w.destroy()

    def _show_ads_choices(self, choices) -> None:
        self._clear_ads()
        badge = {"verified": ("проверено", SUCCESS), "reported": ("по отзывам", WARN),
                 "home": ("родной экран", DANGER)}
        r = 0
        for c in choices:
            var = ctk.BooleanVar(value=c.checked)
            text = c.pkg.desc + ("  — уже отключено" if c.already_disabled else "")
            cb = ctk.CTkCheckBox(self.ads_list, text=text, variable=var, font=self.f_small, text_color=TEXT,
                                 fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=MUTED, checkmark_color=ACCENT_TEXT)
            cb.grid(row=r, column=0, sticky="w", padx=10, pady=(8, 0))
            try:
                cb._text_label.configure(wraplength=340, justify="left")
            except Exception:
                pass
            if c.already_disabled:
                cb.configure(state="disabled")
            else:
                self._ads_checks.append(cb)
            b_text, b_color = badge.get(c.pkg.confidence, ("", MUTED))
            ctk.CTkLabel(self.ads_list, text=b_text, font=self.f_small, text_color=b_color).grid(
                row=r, column=1, sticky="ne", padx=10, pady=(8, 0))
            r += 1
            note = c.pkg.name + (f"\n⚠ {c.pkg.warning}" if c.pkg.warning else "")
            ctk.CTkLabel(self.ads_list, text=note, font=self.f_small, text_color=MUTED, justify="left",
                         anchor="w", wraplength=440).grid(row=r, column=0, columnspan=2, sticky="w",
                                                          padx=(42, 10), pady=(0, 4))
            r += 1
            self._ads_vars[c.pkg.name] = var
            self._ads_choices[c.pkg.name] = c

    def _page_restore(self) -> ctk.CTkFrame:
        f = self._page()
        self._h1(f, "Вернуть как было", 0)
        self._p(f, "Включу обратно всё, что отключал на шаге «Убрать рекламу», и верну тот домашний экран, "
                   "который был до WhiteHole (Яндекс ТВ, Google TV, PatchWall и т. д.). Резервная копия "
                   "берётся с этого компьютера; если её нет — включу отключённые пакеты из известных списков.", 1)
        self.uninstall_launcher = ctk.CTkCheckBox(f, text="Ещё и удалить лаунчер WhiteHole с телевизора",
                                                  font=self.f_body, text_color=TEXT, fg_color=ACCENT,
                                                  hover_color=ACCENT_HOVER, border_color=MUTED, checkmark_color=ACCENT_TEXT)
        self.uninstall_launcher.grid(row=2, column=0, sticky="w", padx=28, pady=(4, 8))
        self._big_button(f, "Вернуть как было", self.on_restore, 3)
        self.restore_msg = self._p(f, "", 4, color=TEXT)
        return f

    # ------------------------------------------------------------ навигация

    def show_step(self, key: str) -> None:
        for k, page in self.pages.items():
            if k == key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()
        self.current = key
        self._refresh_steps()
        if key == "install":
            self._refresh_install_page()
        if key == "login":
            self._refresh_login_page()
        if key == "ads" and self.device and not self._busy:
            self.on_ads_check()

    def _refresh_steps(self) -> None:
        cur = getattr(self, "current", "")
        for key, *_ in STEPS:
            self.step_buttons[key].set_look(current=key == cur, done=key in self.done)

    def mark_done(self, key: str) -> None:
        self.done.add(key)
        self._refresh_steps()

    # ------------------------------------------------------------ фон / UI-поток

    def _ui(self, fn: Callable, *args) -> None:
        """Из любого потока: выполнить fn в UI-потоке (через очередь, которую читает _pump)."""
        self._q.put(lambda: fn(*args))

    def _pump(self) -> None:
        try:
            for _ in range(500):
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    break
                try:
                    item()
                except Exception:
                    self._append_log_safe(traceback.format_exc())
        finally:
            try:
                self.after(50, self._pump)
            except Exception:
                pass  # окно уже закрыто

    @property
    def _busy(self) -> bool:
        return bool(self._lanes)

    def _apply_busy(self, text: str = "") -> None:
        """Включает/выключает кнопки по текущим фоновым задачам. Ручной ввод IP не трогаем."""
        busy = self._busy
        for b in self._action_buttons + self._dev_buttons + self._ads_checks + list(self.step_buttons.values()):
            set_enabled(b, not busy)
        if "scan" in self._lanes:
            # во время поиска можно выбрать уже найденный ТВ
            for b in self._dev_buttons:
                set_enabled(b, True)
            if not self.btn_cancel.winfo_manager():
                self.btn_cancel.pack(side="left", padx=12, ipadx=12)
        else:
            self.btn_cancel.pack_forget()
        try:
            if busy:
                self.progress.grid()
                if self.progress.cget("mode") != "indeterminate":
                    self.progress.configure(mode="indeterminate")
                self.progress.start()
                if text:
                    self.set_status(text)
            else:
                self.progress.stop()
                self.progress.grid_remove()
        except Exception:
            pass

    def set_busy(self, busy: bool, text: str = "") -> None:  # совместимость
        if not busy:
            self._lanes.clear()
        self._apply_busy(text)

    def set_status(self, text: str, color: str = MUTED) -> None:
        self.status.configure(text=text, text_color=color)

    def set_progress(self, frac: Optional[float], text: str) -> None:
        if frac is None:
            if self.progress.cget("mode") != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start()
        else:
            if self.progress.cget("mode") != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
            self.progress.set(max(0.0, min(1.0, frac)))
        if text:
            self.set_status(text)

    def progress_cb(self, frac: Optional[float], text: str) -> None:  # вызывается из фона
        self._ui(self.set_progress, frac, text)

    def run_task(self, work: Callable[[], object], on_ok: Optional[Callable[[object], None]] = None,
                 on_err: Optional[Callable[[SetupError], None]] = None, busy_text: str = "",
                 lane: str = "main", watchdog_s: Optional[float] = None,
                 on_timeout: Optional[Callable[[], None]] = None) -> bool:
        """Запускает work() в фоне. Состояние «занято» снимается ВСЕГДА: в finally потока,
        а если поток завис — по сторожевому таймеру watchdog_s."""
        if lane in self._lanes:
            return False
        self._token += 1
        token = self._token
        self._lanes[lane] = token
        self._apply_busy(busy_text or "Работаю…")

        def runner():
            outcome = None
            try:
                outcome = ("ok", work())
            except SetupError as e:
                if e.details:
                    self.log(e.details)
                self.log("Ошибка: " + e.message)
                outcome = ("err", e)
            except BaseException as e:  # noqa: BLE001 — показываем по-человечески
                self.log(traceback.format_exc())
                outcome = ("err", SetupError("Что-то пошло не так. Открой «Подробности» и пришли текст "
                                             "в поддержку.", "crash", repr(e)))
            finally:
                if outcome is None:
                    outcome = ("err", SetupError("Операция прервана.", "crash"))
                self._ui(self._finish, lane, token, outcome, on_ok, on_err)

        threading.Thread(target=runner, daemon=True, name=f"task-{lane}").start()
        if watchdog_s:
            def watchdog():
                if self._lanes.get(lane) == token:
                    self.log(f"Сторожевой таймер: задача «{lane}» не закончилась за {int(watchdog_s)} с")
                    if on_timeout:
                        try:
                            on_timeout()
                        except Exception:
                            self._append_log_safe(traceback.format_exc())
                    self._finish(lane, token, ("err", SetupError(
                        "Слишком долго нет ответа. Попробуй ещё раз или введи IP вручную.", "timeout")),
                        None, on_err)
            self.after(int(watchdog_s * 1000), watchdog)
        return True

    def _finish(self, lane: str, token: int, outcome, on_ok, on_err) -> None:
        if self._lanes.get(lane) != token:
            return  # задачу уже сняли сторожевым таймером — поздний результат игнорируем
        try:
            del self._lanes[lane]
            self._apply_busy()
        finally:
            kind, val = outcome
            try:
                if kind == "ok":
                    self.set_status("Готово", SUCCESS)
                    if on_ok:
                        on_ok(val)
                else:
                    self.set_status(val.message, DANGER)
                    if on_err:
                        on_err(val)
                    elif val.kind not in ("cancelled",):
                        messagebox.showerror("WhiteHole Setup", val.message, parent=self)
            except Exception:
                self._append_log_safe(traceback.format_exc())

    def _finish_ok(self, res, on_ok) -> None:  # совместимость со старым кодом
        self._finish("main", self._lanes.get("main", -1), ("ok", res), on_ok, None)

    def _append_log_safe(self, msg: str) -> None:
        try:
            self._append_log(msg)
        except Exception:
            pass

    # ------------------------------------------------------------ журнал

    def log(self, msg: str) -> None:  # потокобезопасно
        self._q.put(lambda: self._append_log(msg))

    def _append_log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg.rstrip() + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def toggle_log(self) -> None:
        self._log_open = not self._log_open
        extra = 210  # примерная высота панели журнала
        w, h = self.winfo_width(), self.winfo_height()
        try:
            scale = float(self._get_window_scaling())
        except Exception:
            scale = 1.0
        if self._log_open:
            self.log_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=24, pady=(6, 0))
            self.log_toggle.configure(text="▾ Подробности")
            # Если экран позволяет — увеличиваем окно, чтобы шаги не сжимались.
            if (h + extra * scale) < self.winfo_screenheight() - 80 * scale:
                self.geometry(f"{round(w / scale)}x{round(h / scale) + extra}")
                self._grown = True
        else:
            self.log_frame.grid_remove()
            self.log_toggle.configure(text="▸ Подробности")
            if getattr(self, "_grown", False):
                self.geometry(f"{round(w / scale)}x{max(640, round(h / scale) - extra)}")
                self._grown = False

    def copy_log(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.log_box.get("1.0", "end"))
        self.set_status("Журнал скопирован — отправь его в поддержку", SUCCESS)

    # ------------------------------------------------------------ шаг 1

    def _start_adb(self):
        self.log(f"adb: {self.engine.adb.path or 'не найден'}")
        self.engine.adb.start_server()

    def _dev_placeholder(self, text: str = "Здесь появятся найденные телевизоры") -> None:
        self._clear_devices()
        ctk.CTkLabel(self.dev_list, text=text, font=self.f_small, text_color=MUTED).grid(
            row=0, column=0, sticky="w", padx=10, pady=10)

    def _show_devices(self, devs: "list[DeviceInfo]") -> None:
        if not devs:
            self._dev_placeholder("Телевизоры не нашлись. Проверь, что отладка по сети включена, "
                                  "или введи IP вручную.")
            return
        self._clear_devices()
        for i, d in enumerate(devs[:6]):
            state = {"device": "готов", "unauthorized": "нужно разрешение на ТВ"}.get(d.state, d.state)
            ctk.CTkLabel(self.dev_list, text=f"{d.title}  —  {state}", font=self.f_body, text_color=TEXT,
                         anchor="w").grid(row=i, column=0, sticky="ew", padx=10, pady=4)
            b = accent_button(self.dev_list, text="Выбрать", width=100, height=32, corner_radius=16,
                              font=self.f_small, command=lambda dv=d: self.select_device(dv))
            b.grid(row=i, column=1, padx=10, pady=4)
            self._dev_buttons.append(b)

    def _clear_devices(self) -> None:
        self._dev_buttons = []
        for w in self.dev_list.winfo_children():
            w.destroy()

    SCAN_TIMEOUT = 20.0

    def on_scan(self) -> None:
        if "scan" in self._lanes:
            return
        self.find_msg.configure(text="", text_color=MUTED)
        self._found = []
        self._dev_placeholder("Ищу… Уже подключённые телевизоры появятся сразу.")
        self._scan_cancel = threading.Event()
        cancel = self._scan_cancel

        def found(dev: DeviceInfo) -> None:  # из фонового потока
            self._ui(self._add_found, dev)

        def done(devs):
            if cancel.is_set():
                if not self._found:
                    self._dev_placeholder("Поиск остановлен.")
                return
            self._show_devices(self._found or devs)
            devs = self._found or devs
            if len(devs) == 1 and self.device is None:
                self.select_device(devs[0])
            elif not devs:
                self._not_found()
            elif self.device is None:
                self.find_msg.configure(text="Нашёл несколько устройств — выбери свой телевизор.", text_color=TEXT)

        def err(e: SetupError):
            if self._found:
                self._show_devices(self._found)
            else:
                self._not_found(e.message)

        self.run_task(lambda: self.engine.discover(progress=self.progress_cb, on_found=found, cancel=cancel,
                                                   timeout=self.SCAN_TIMEOUT),
                      done, err, busy_text="Ищу телевизоры…", lane="scan",
                      watchdog_s=self.SCAN_TIMEOUT + 25, on_timeout=cancel.set)

    def _add_found(self, dev: DeviceInfo) -> None:
        if any(d.serial == dev.serial for d in self._found):
            return
        self._found.append(dev)
        self._show_devices(self._found)
        self._apply_busy()

    def _not_found(self, reason: str = "") -> None:
        self._dev_placeholder("Телевизор не нашёлся автоматически.")
        self.find_msg.configure(
            text=(reason + "\n" if reason else "")
            + "Введи IP телевизора вручную и нажми «Подключить». Где его посмотреть: на телевизоре "
              "Настройки → Сеть (и Интернет) → твоя сеть / «О сети» — строка «IP-адрес». "
              "Ещё проверь, что отладка включена (кнопка «Как включить отладку на ТВ»).",
            text_color=WARN)
        try:
            self.ip_entry.focus_set()
        except Exception:
            pass

    def on_cancel_scan(self) -> None:
        self._scan_cancel.set()
        self.set_status("Останавливаю поиск…")

    def on_manual(self) -> None:
        text = self.ip_entry.get()
        try:
            serial = core.normalize_ip(text)
        except SetupError as e:
            self.find_msg.configure(text=e.message, text_color=DANGER)
            return
        self._scan_cancel.set()  # ручной ввод важнее автопоиска

        def err(e: SetupError):
            self.find_msg.configure(text=e.message, text_color=DANGER)

        def ok(d: DeviceInfo):
            self._show_devices([d])
            self.select_device(d, detected=True)

        if not self.run_task(lambda: self.engine.connect(serial), ok, err,
                             busy_text=f"Подключаюсь к {serial}…", lane="manual", watchdog_s=40):
            self.find_msg.configure(text="Уже подключаюсь — подожди пару секунд.", text_color=MUTED)

    def select_device(self, d: DeviceInfo, detected: bool = False) -> None:
        self._scan_cancel.set()
        if d.state == "unauthorized":
            self.find_msg.configure(text=texts.UNAUTHORIZED, text_color=WARN)
            self._cancel = threading.Event()
            cancel = self._cancel

            def err(e: SetupError):
                self.find_msg.configure(text=e.message, text_color=DANGER)

            self.run_task(lambda: self.engine.wait_authorized(d.serial, 60, cancel, self.progress_cb),
                          self._device_ready, err, busy_text="Жду разрешения на телевизоре…",
                          watchdog_s=90, on_timeout=cancel.set)
            return
        if d.state != "device":
            self.find_msg.configure(text="Телевизор не отвечает (offline). Перезагрузи его и попробуй снова.",
                                    text_color=DANGER)
            return
        if detected or d.profile_id:
            self._device_ready(d)
            return

        def err(e: SetupError):
            self.find_msg.configure(text=e.message, text_color=DANGER)

        self.run_task(lambda: self.engine.device_info(d.serial, "device"), self._device_ready, err,
                      busy_text="Определяю модель и платформу…", watchdog_s=90)

    def _device_ready(self, d: DeviceInfo) -> None:
        self.device = d
        self._show_devices([d])
        self.device_label.configure(text="Телевизор:\n" + (d.platform_line or d.title)
                                    + (f"\n{d.ip}" if d.ip else ""), text_color=TEXT)
        msg = f"Подключено: {d.platform_line or d.title}. Можно ставить!"
        color = SUCCESS
        if not d.is_tv:
            msg += ("\nПохоже, это не Android TV (нет режима телевизора — телефон, планшет или необычная "
                    "приставка). Установить можно, но лаунчер рассчитан на телевизор и пульт.")
            color = WARN
        self.find_msg.configure(text=msg, text_color=color)
        self._ads_empty("Нажми «Проверить телевизор»")
        self.btn_next1.pack(side="left", padx=12, ipadx=12)
        self.mark_done("find")

    def _need_device(self) -> bool:
        if self.device is None:
            messagebox.showinfo("WhiteHole Setup", "Сначала найди телевизор (шаг 1).", parent=self)
            self.show_step("find")
            return False
        return True

    # ------------------------------------------------------------ шаг 2

    def on_install(self) -> None:
        if not self._need_device():
            return
        d = self.device
        with_happ = bool(self.with_happ.get())
        self.install_msg.configure(text="")

        def ok(done):
            home_ok = any("теперь домашний экран" in x for x in done)
            self.install_msg.configure(
                text="\n".join(("✓ " if (home_ok or "домашн" not in x.lower()) else "⚠ ") + x for x in done)
                + ("\n\nНажми «Домой» на пульте — увидишь WhiteHole. Дальше — шаг «Вход»." if home_ok else ""),
                text_color=SUCCESS if home_ok else WARN)
            self.device_label.configure(text="Телевизор:\n" + (d.platform_line or d.title)
                                        + (f"\n{d.ip}" if d.ip else ""))
            self.mark_done("install")

        def err(e: SetupError):
            self.install_msg.configure(text=e.message, text_color=DANGER)

        self.run_task(lambda: self.engine.install_all(d, progress=self.progress_cb, with_happ=with_happ), ok, err,
                      busy_text="Готовлюсь к установке…")

    # ------------------------------------------------------------ шаг 3: вход

    def on_open_launcher(self) -> None:
        if not self._need_device():
            return
        d = self.device

        def ok(_):
            self.login_msg.configure(text="✓ WhiteHole открыт на телевизоре — нажми там «Войти через Telegram».",
                                     text_color=SUCCESS)
            self.mark_done("login")

        def err(e: SetupError):
            self.login_msg.configure(text=e.message, text_color=DANGER)

        self.run_task(lambda: self.engine.open_launcher(d), ok, err, busy_text="Открываю WhiteHole на ТВ…")

    def on_grant_vpn(self) -> None:
        if not self._need_device():
            return
        d = self.device

        def ok(_):
            self.vpn_msg.configure(text="✓ Готово: окно «Разрешить подключение к VPN?» на телевизоре "
                                        "появляться не должно.", text_color=SUCCESS)

        def err(e: SetupError):
            self.vpn_msg.configure(text=e.message, text_color=WARN if e.kind == "appops" else DANGER)

        self.run_task(lambda: self.engine.grant_vpn(d), ok, err, busy_text="Выдаю разрешение VPN…")

    def paste_sub(self) -> None:
        try:
            text = self.clipboard_get()
        except Exception:
            text = ""
        self.sub_entry.delete(0, "end")
        self.sub_entry.insert(0, text.strip())

    def on_sub(self) -> None:
        if not self._need_device():
            return
        d = self.device
        text = self.sub_entry.get()
        try:
            core.build_happ_link(text)
        except SetupError as e:
            self.sub_msg.configure(text=e.message, text_color=DANGER)
            return

        def ok(_):
            self.sub_msg.configure(text="✓ Отправил. На телевизоре открылся Happ — подтверди добавление "
                                        "подписки пультом и нажми «Подключиться».", text_color=SUCCESS)
            self.mark_done("login")

        def err(e: SetupError):
            self.sub_msg.configure(text=e.message, text_color=DANGER)

        self.run_task(lambda: self.engine.send_subscription(d, text), ok, err, busy_text="Отправляю в Happ…")

    # ------------------------------------------------------------ шаг 4

    def on_ads_check(self) -> None:
        if not self._need_device():
            return
        d = self.device
        self._ads_empty("Проверяю…")

        def ok(st: core.AdsStatus):
            self.ads_warn.configure(text=texts.ADS_WARNING if st.profile_id == "yandex"
                                    else texts.ADS_WARNING_GENERIC)
            if not st.choices:
                self._ads_empty(f"Платформа: {st.profile_title}. Для неё нет проверенного списка — "
                                "ничего не отключаю. Если «Домой» открывает WhiteHole, всё уже хорошо.")
                self.ads_msg.configure(text="", text_color=MUTED)
                return
            self._show_ads_choices(st.choices)
            if not st.launcher_installed:
                self.ads_msg.configure(text="Сначала установи WhiteHole (шаг 2) — иначе у телевизора не "
                                            "останется домашнего экрана.", text_color=WARN)
            elif all(c.already_disabled for c in st.choices):
                self.ads_msg.configure(text="Всё из списка уже отключено ✓", text_color=SUCCESS)
            elif any(c.checked for c in st.choices):
                self.ads_msg.configure(text=f"Платформа: {st.profile_title}. Отмеченное по умолчанию — "
                                            "проверено на реальном ТВ; остальное — только по твоему выбору.",
                                       text_color=TEXT)
            else:
                self.ads_msg.configure(text=f"Платформа: {st.profile_title}. Ничего не отмечено: для этой "
                                            "платформы список собран по отзывам и на нашем ТВ не проверен — "
                                            "отмечай только то, что точно нужно.", text_color=WARN)

        def err(e: SetupError):
            self._ads_empty("Не получилось проверить телевизор.")
            self.ads_msg.configure(text=e.message, text_color=DANGER)

        self.run_task(lambda: self.engine.ads_status(d), ok, err, busy_text="Проверяю телевизор…")

    def selected_ads(self) -> "list[str]":
        return [name for name, var in self._ads_vars.items()
                if var.get() and not self._ads_choices[name].already_disabled]

    def on_ads(self) -> None:
        if not self._need_device():
            return
        d = self.device
        if not self._ads_choices:
            self.on_ads_check()
            return
        sel = self.selected_ads()
        if not sel:
            self.ads_msg.configure(text="Ничего не отмечено.", text_color=WARN)
            return
        lines = []
        for name in sel:
            c = self._ads_choices[name]
            lines.append(f"• {c.pkg.desc} ({name})" + (f"\n   ⚠ {c.pkg.warning}" if c.pkg.warning else ""))
        warn = texts.ADS_WARNING if d.profile_id == "yandex" else texts.ADS_WARNING_GENERIC
        if not messagebox.askyesno("Убрать рекламу", "Отключить:\n" + "\n".join(lines) + "\n\n" + warn,
                                   parent=self):
            return

        def ok(done):
            if done:
                self.ads_msg.configure(text="✓ Отключено: " + ", ".join(done)
                                       + f"\nРезервная копия: {self.engine.backup_path(d)}", text_color=SUCCESS)
            else:
                self.ads_msg.configure(text="Отключать было нечего — всё уже сделано.", text_color=SUCCESS)
            self.mark_done("ads")
            self.after(100, self.on_ads_check)

        def err(e: SetupError):
            self.ads_msg.configure(text=e.message, text_color=DANGER)

        self.run_task(lambda: self.engine.remove_ads(d, sel, self.progress_cb), ok, err,
                      busy_text="Убираю рекламу…")

    # ------------------------------------------------------------ шаг 5

    def on_restore(self) -> None:
        if not self._need_device():
            return
        d = self.device
        uninstall = bool(self.uninstall_launcher.get())
        q = "Вернуть телевизор как было?" + ("\nЛаунчер WhiteHole будет удалён." if uninstall else "")
        if not messagebox.askyesno("Вернуть как было", q, parent=self):
            return

        def ok(done):
            self.restore_msg.configure(text="\n".join("✓ " + x for x in done) or "Всё и так было на месте.",
                                       text_color=SUCCESS)
            self.done.discard("ads")
            if uninstall:
                self.done.discard("install")
            self.mark_done("restore")

        def err(e: SetupError):
            self.restore_msg.configure(text=e.message, text_color=DANGER)

        self.run_task(lambda: self.engine.restore(d, uninstall, self.progress_cb), ok, err,
                      busy_text="Возвращаю как было…")

    # ------------------------------------------------------------ справка / выход

    def show_help(self) -> None:
        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title(texts.HELP_TITLE)
        win.geometry("660x560")
        win.transient(self)
        win.after(250, lambda: self._set_icon(win))
        ctk.CTkLabel(win, text=texts.HELP_TITLE, font=self.f_h1, text_color=TEXT).pack(
            anchor="w", padx=20, pady=(16, 8))
        box = ctk.CTkTextbox(win, font=self.f_body, fg_color=PANEL, text_color=TEXT, wrap="word",
                             corner_radius=12, border_width=1, border_color=BORDER)
        box.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        try:
            box._textbox.tag_configure("h", foreground=ACCENT, font=self.f_btn)
        except Exception:
            pass
        for line in texts.HELP_TEXT.splitlines(keepends=True):
            box.insert("end", line, ("h",) if line.strip() in texts.HELP_HEADINGS else ())
        box.configure(state="disabled")
        accent_button(win, text="Понятно", command=win.destroy, height=40, corner_radius=20,
                      font=self.f_body).pack(pady=(0, 14))
        win.after(100, win.focus_force)

    def on_close(self) -> None:
        if self._busy and not messagebox.askyesno(
                "WhiteHole Setup", "Сейчас идёт работа с телевизором. Точно закрыть?", parent=self):
            return
        self._cancel.set()
        self._scan_cancel.set()
        t = threading.Thread(target=self._kill_adb, daemon=True)
        t.start()
        t.join(timeout=5)
        self.destroy()

    def _kill_adb(self) -> None:
        try:
            self.engine.adb.kill_server()
        except Exception:
            pass


def main() -> None:
    App().mainloop()
