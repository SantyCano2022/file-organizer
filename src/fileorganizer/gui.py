import fnmatch
import json
import logging
import shutil
import sys
import threading
import winreg
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, simpledialog

import customtkinter as ctk
import pystray
import yaml
from PIL import Image, ImageDraw
from plyer import notification
from watchdog.observers import Observer

from fileorganizer import history as hist
from fileorganizer.organizer import FileOrganizer
from fileorganizer.scheduler import Scheduler
from fileorganizer.updater import VERSION, download_and_apply, get_latest_release, is_newer
from fileorganizer.watcher import OrganizeHandler

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SETTINGS_FILE = Path.home() / ".file_organizer_settings.json"
PROFILES_DIR  = Path.home() / ".file_organizer_profiles"
REGISTRY_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_NAME = "FileOrganizer"

GREEN        = "#22c55e"
RED          = "#ef4444"
AMBER        = "#f59e0b"
MUTED        = "#94a3b8"
BTN_RED      = ("#dc2626", "#dc2626")
BTN_RED_HV   = ("#b91c1c", "#b91c1c")
BTN_BLUE     = ("#2563eb", "#2563eb")
BTN_BLUE_HV  = ("#1d4ed8", "#1d4ed8")
BTN_GRAY     = ("#475569", "#475569")
BTN_GRAY_HV  = ("#334155", "#334155")
BTN_GREEN    = ("#16a34a", "#16a34a")
BTN_GREEN_HV = ("#15803d", "#15803d")
SEL_BG       = ("#1e3a5f", "#1e3a5f")


def _embedded_config() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "config" / "rules.yaml"
    return Path(__file__).parent.parent.parent / "config" / "rules.yaml"


def _get_rules_path(profile: str = "default") -> Path:
    if profile == "default":
        p = Path.home() / ".file_organizer_rules.yaml"
    else:
        PROFILES_DIR.mkdir(exist_ok=True)
        p = PROFILES_DIR / f"{profile}.yaml"
    if not p.exists():
        shutil.copy(str(_embedded_config()), str(p))
    return p


def _list_profiles() -> list:
    profiles = ["default"]
    if PROFILES_DIR.exists():
        profiles += sorted(f.stem for f in PROFILES_DIR.glob("*.yaml"))
    return profiles


def _create_tray_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill="#2563eb")
    draw.rectangle([18, 14, 24, 50], fill="white")
    draw.rectangle([18, 14, 44, 22], fill="white")
    draw.rectangle([18, 30, 40, 37], fill="white")
    return img


class _GUILogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            self.callback(self.format(record))
        except Exception:
            pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("File Organizer")
        self.geometry("960x780")
        self.resizable(True, True)
        self.minsize(820, 640)

        self.observer: Observer | None = None
        self.organizer: FileOrganizer | None = None
        self.running = False
        self._log_handler: _GUILogHandler | None = None
        self._tray = None
        self._scheduler = Scheduler()
        self._rules_data: dict = {}
        self._selected_category: str = ""
        self._cat_buttons: dict = {}

        self._build_header()
        self._build_tabs()
        self._attach_logger()
        self._setup_tray()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.after(2500, lambda: threading.Thread(
            target=self._check_for_updates, daemon=True).start())
        self._init_scheduler_from_settings()
        self.after(800, self._maybe_show_welcome)

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="#080f1a", corner_radius=0)
        header.pack(fill="x")
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", padx=24, pady=14)
        title_row = ctk.CTkFrame(left, fg_color="transparent")
        title_row.pack(anchor="w")
        ctk.CTkLabel(title_row, text="⚡",
                     font=("Segoe UI", 20), text_color="#3b82f6").pack(side="left", padx=(0, 8))
        ctk.CTkLabel(title_row, text="File Organizer",
                     font=("Segoe UI", 22, "bold"), text_color="white").pack(side="left")
        ctk.CTkLabel(left, text="© 2026 Cano SAS Dev",
                     font=("Segoe UI", 10), text_color="#3b4f6a").pack(anchor="w", pady=(2, 0))
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", padx=24)
        version_badge = ctk.CTkFrame(right, fg_color="#1e293b", corner_radius=6)
        version_badge.pack(anchor="e", pady=(0, 6))
        ctk.CTkLabel(version_badge, text=f"  v{VERSION}  ",
                     font=("Segoe UI", 10, "bold"), text_color="#64748b").pack()
        self.status_label = ctk.CTkLabel(
            right, text="⬤  Detenido", font=("Segoe UI", 12, "bold"), text_color=RED)
        self.status_label.pack(anchor="e")
        ctk.CTkFrame(self, fg_color="#1d4ed8", height=2, corner_radius=0).pack(fill="x")

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(self, anchor="nw")
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        for name in ("Inicio", "Reglas", "Historial", "Estadísticas", "Programar", "Manual"):
            self.tabs.add(name)
        self._build_inicio_tab(self.tabs.tab("Inicio"))
        self._build_reglas_tab(self.tabs.tab("Reglas"))
        self._build_historial_tab(self.tabs.tab("Historial"))
        self._build_stats_tab(self.tabs.tab("Estadísticas"))
        self._build_programar_tab(self.tabs.tab("Programar"))
        self._build_ayuda_tab(self.tabs.tab("Manual"))
        self.tabs.set("Inicio")

    # ── Tab: Inicio ───────────────────────────────────────────────────────────

    def _build_inicio_tab(self, tab):
        cfg = self._load_settings()
        card = ctk.CTkFrame(tab, corner_radius=12, border_width=1, border_color="#1e293b")
        card.pack(fill="x", pady=(4, 8))
        card.columnconfigure(0, weight=1)

        fields = [
            ("Carpeta a monitorear", "watch_entry", "watch_folder",
             "Ej: C:/Users/TuUsuario/Downloads", self._browse_watch),
            ("Carpeta de destino", "output_entry", "output_folder",
             "Ej: C:/Users/TuUsuario/Documents/Organizado", self._browse_output),
        ]
        for i, (label, attr, key, placeholder, cmd) in enumerate(fields):
            ctk.CTkLabel(card, text=label, font=("Segoe UI", 12, "bold")).grid(
                row=i * 2, column=0, columnspan=2, sticky="w", padx=16,
                pady=(14 if i == 0 else 4, 2))
            entry = ctk.CTkEntry(card, height=34, placeholder_text=placeholder)
            entry.grid(row=i * 2 + 1, column=0, sticky="ew", padx=(16, 8), pady=(0, 10))
            entry.insert(0, cfg.get(key, ""))
            setattr(self, attr, entry)
            ctk.CTkButton(card, text="Buscar", width=88, height=34, command=cmd).grid(
                row=i * 2 + 1, column=1, padx=(0, 16), pady=(0, 10))

        opts = ctk.CTkFrame(card, fg_color="transparent")
        opts.grid(row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 4))
        ctk.CTkLabel(opts, text="Delay:").pack(side="left")
        self.delay_entry = ctk.CTkEntry(opts, width=44, height=30)
        self.delay_entry.pack(side="left", padx=(6, 4))
        self.delay_entry.insert(0, cfg.get("delay", "3"))
        ctk.CTkLabel(opts, text="seg", text_color=MUTED).pack(side="left", padx=(0, 20))
        self.existing_var = ctk.BooleanVar(value=cfg.get("organize_existing", True))
        ctk.CTkCheckBox(opts, text="Organizar archivos existentes al iniciar",
                        variable=self.existing_var).pack(side="left", padx=(0, 16))
        self.existing_folders_var = ctk.BooleanVar(
            value=cfg.get("organize_existing_folders", False))
        ctk.CTkCheckBox(opts, text="Organizar carpetas existentes al iniciar",
                        variable=self.existing_folders_var).pack(side="left")

        opts2 = ctk.CTkFrame(card, fg_color="transparent")
        opts2.grid(row=5, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 14))
        self.autostart_var = ctk.BooleanVar(value=self._is_autostart_enabled())
        ctk.CTkCheckBox(opts2, text="Iniciar con Windows", variable=self.autostart_var,
                        command=self._toggle_autostart).pack(side="left")

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 8))
        btn_row.columnconfigure(0, weight=1)
        self.start_btn = ctk.CTkButton(
            btn_row, text="▶   Iniciar",
            font=("Segoe UI", 14, "bold"), height=44, corner_radius=8,
            fg_color=BTN_BLUE, hover_color=BTN_BLUE_HV, command=self._toggle)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            btn_row, text="↩  Deshacer último",
            font=("Segoe UI", 13), height=44, width=160, corner_radius=8,
            fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV, command=self._undo
        ).grid(row=0, column=1)
        ctk.CTkButton(
            btn_row, text="🔍  Vista previa",
            font=("Segoe UI", 13), height=44, width=150, corner_radius=8,
            fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV, command=self._dry_run
        ).grid(row=0, column=2, padx=(8, 0))

        log_card = ctk.CTkFrame(tab, corner_radius=12, border_width=1, border_color="#1e293b")
        log_card.pack(fill="both", expand=True, pady=(0, 4))
        log_hdr = ctk.CTkFrame(log_card, fg_color="#0a1120", corner_radius=0)
        log_hdr.pack(fill="x")
        ctk.CTkLabel(log_hdr, text="  ● Actividad en tiempo real",
                     font=("Segoe UI", 11, "bold"),
                     text_color="#64748b").pack(anchor="w", padx=8, pady=7)
        self.log_box = ctk.CTkTextbox(log_card, font=("Consolas", 11),
                                      fg_color="#060d18",
                                      state="disabled", corner_radius=0)
        self.log_box.pack(fill="both", expand=True, padx=0, pady=0)

        self.stats_label = ctk.CTkLabel(
            tab, text="Movidos: 0   |   Saltados: 0   |   Errores: 0",
            font=("Segoe UI", 11), text_color=MUTED)
        self.stats_label.pack(pady=(0, 4))

    # ── Tab: Reglas ───────────────────────────────────────────────────────────

    def _build_reglas_tab(self, tab):
        cfg = self._load_settings()

        pbar = ctk.CTkFrame(tab, fg_color="transparent")
        pbar.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(pbar, text="Perfil:", font=("Segoe UI", 12, "bold")).pack(
            side="left", padx=(0, 6))
        self._profile_var = ctk.StringVar(value=cfg.get("active_profile", "default"))
        self._profile_menu = ctk.CTkOptionMenu(
            pbar, variable=self._profile_var, values=_list_profiles(),
            width=160, command=self._on_profile_change)
        self._profile_menu.pack(side="left", padx=(0, 8))
        ctk.CTkButton(pbar, text="+ Nuevo", width=80,
                      fg_color=BTN_GREEN, hover_color=BTN_GREEN_HV,
                      command=self._new_profile).pack(side="left", padx=(0, 4))
        ctk.CTkButton(pbar, text="✕ Eliminar", width=90,
                      fg_color=BTN_RED, hover_color=BTN_RED_HV,
                      command=self._delete_profile).pack(side="left")

        split = ctk.CTkFrame(tab, fg_color="transparent")
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=0)
        split.columnconfigure(1, weight=1)
        split.rowconfigure(0, weight=1)

        left = ctk.CTkFrame(split, width=215, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_propagate(False)
        ctk.CTkLabel(left, text="Categorías",
                     font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self._cat_listbox = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._cat_listbox.pack(fill="both", expand=True, padx=6)
        left_btns = ctk.CTkFrame(left, fg_color="transparent")
        left_btns.pack(fill="x", padx=6, pady=8)
        ctk.CTkButton(left_btns, text="+ Agregar", height=30,
                      fg_color=BTN_GREEN, hover_color=BTN_GREEN_HV,
                      command=self._add_category).pack(
            side="left", expand=True, fill="x", padx=(0, 3))
        ctk.CTkButton(left_btns, text="✕", height=30, width=36,
                      fg_color=BTN_RED, hover_color=BTN_RED_HV,
                      command=self._delete_category).pack(side="left")

        right = ctk.CTkScrollableFrame(split, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(right, text="Editar categoría",
                     font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=16, pady=(12, 8))

        ctk.CTkLabel(right, text="Nombre", text_color=MUTED).pack(anchor="w", padx=16)
        self._cat_name_entry = ctk.CTkEntry(right, height=32)
        self._cat_name_entry.pack(fill="x", padx=16, pady=(2, 10))

        ctk.CTkLabel(right, text="Carpeta destino (relativa al output)",
                     text_color=MUTED).pack(anchor="w", padx=16)
        self._cat_dest_entry = ctk.CTkEntry(right, height=32)
        self._cat_dest_entry.pack(fill="x", padx=16, pady=(2, 10))

        ck_row = ctk.CTkFrame(right, fg_color="transparent")
        ck_row.pack(anchor="w", padx=16, pady=(0, 10))
        self._año_var = ctk.BooleanVar()
        self._mes_var = ctk.BooleanVar()
        ctk.CTkCheckBox(ck_row, text="Subcarpeta por año", variable=self._año_var,
                        command=self._on_año_toggle).pack(side="left", padx=(0, 16))
        self._mes_check = ctk.CTkCheckBox(ck_row, text="Subcarpeta por mes",
                                          variable=self._mes_var)
        self._mes_check.pack(side="left")

        ctk.CTkLabel(right, text="Extensiones (una por línea)",
                     text_color=MUTED).pack(anchor="w", padx=16)
        self._ext_box = ctk.CTkTextbox(right, height=130, font=("Consolas", 12))
        self._ext_box.pack(fill="x", padx=16, pady=(2, 10))

        ctk.CTkButton(right, text="💾 Guardar categoría",
                      fg_color=BTN_BLUE, hover_color=BTN_BLUE_HV,
                      command=self._save_category).pack(anchor="w", padx=16, pady=(0, 12))

        ctk.CTkFrame(right, fg_color="#1e293b", height=1).pack(fill="x", padx=16, pady=(0, 10))

        conf_row = ctk.CTkFrame(right, fg_color="transparent")
        conf_row.pack(anchor="w", padx=16, pady=(0, 10))
        ctk.CTkLabel(conf_row, text="Conflicto de nombres:").pack(side="left", padx=(0, 8))
        self._conflict_var = ctk.StringVar(value="renombrar")
        ctk.CTkOptionMenu(conf_row, variable=self._conflict_var,
                          values=["renombrar", "saltar", "reemplazar"],
                          width=130).pack(side="left")
        ctk.CTkButton(conf_row, text="Guardar", width=80,
                      fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV,
                      command=self._save_conflict).pack(side="left", padx=(8, 0))

        ctk.CTkFrame(right, fg_color="#1e293b", height=1).pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(right, text="Patrones de exclusión",
                     font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16)
        ctk.CTkLabel(right, text="Archivos que coincidan serán ignorados (fnmatch, uno por línea)",
                     text_color=MUTED, font=("Segoe UI", 10)).pack(anchor="w", padx=16, pady=(0, 4))
        ctk.CTkLabel(right, text="Ej:  *.tmp   desktop.ini   ~$*   thumb*",
                     text_color=MUTED, font=("Consolas", 10)).pack(anchor="w", padx=16, pady=(0, 4))
        self._excl_box = ctk.CTkTextbox(right, height=80, font=("Consolas", 12))
        self._excl_box.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(right, text="💾 Guardar exclusiones",
                      fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV,
                      command=self._save_exclusions).pack(anchor="w", padx=16, pady=(0, 16))

        self._load_rules_for_editor()
        self._load_exclusions_for_editor()

    def _on_año_toggle(self):
        if self._año_var.get():
            self._mes_check.configure(state="normal")
        else:
            self._mes_var.set(False)
            self._mes_check.configure(state="disabled")

    def _load_rules_for_editor(self):
        cfg = self._load_settings()
        profile = cfg.get("active_profile", "default")
        path = _get_rules_path(profile)
        try:
            with open(path, encoding="utf-8") as f:
                self._rules_data = yaml.safe_load(f) or {}
        except Exception:
            self._rules_data = {}
        self._conflict_var.set(self._rules_data.get("conflicto", "renombrar"))
        self._refresh_cat_list()

    def _refresh_cat_list(self):
        for w in self._cat_listbox.winfo_children():
            w.destroy()
        self._cat_buttons = {}
        for cat in list(self._rules_data.get("categorias", {}).keys()):
            btn = ctk.CTkButton(
                self._cat_listbox, text=cat, height=30, anchor="w",
                fg_color="transparent", hover_color=("#1e293b", "#1e293b"),
                text_color="white", command=lambda c=cat: self._select_category(c))
            btn.pack(fill="x", padx=4, pady=2)
            self._cat_buttons[cat] = btn

    def _select_category(self, name: str):
        for n, b in self._cat_buttons.items():
            b.configure(fg_color=SEL_BG if n == name else "transparent")
        self._selected_category = name
        data = self._rules_data.get("categorias", {}).get(name, {})
        self._cat_name_entry.delete(0, "end")
        self._cat_name_entry.insert(0, name)
        self._cat_dest_entry.delete(0, "end")
        self._cat_dest_entry.insert(0, data.get("destino", ""))
        self._año_var.set(data.get("subcarpeta_por_año", False))
        self._mes_var.set(data.get("subcarpeta_por_mes", False))
        self._on_año_toggle()
        self._ext_box.delete("1.0", "end")
        self._ext_box.insert("1.0", "\n".join(data.get("extensiones", [])))

    def _save_category(self):
        name = self._cat_name_entry.get().strip()
        dest = self._cat_dest_entry.get().strip()
        if not name or not dest:
            self._append_log("ERROR: Nombre y destino son requeridos.")
            return
        exts = [e.strip() for e in self._ext_box.get("1.0", "end").strip().splitlines()
                if e.strip()]
        cats = self._rules_data.setdefault("categorias", {})
        if self._selected_category and self._selected_category != name:
            cats.pop(self._selected_category, None)
        cats[name] = {
            "destino": dest,
            "subcarpeta_por_año": self._año_var.get(),
            "subcarpeta_por_mes": self._mes_var.get(),
            "extensiones": exts,
        }
        self._selected_category = name
        self._write_rules()
        self._refresh_cat_list()
        if name in self._cat_buttons:
            self._cat_buttons[name].configure(fg_color=SEL_BG)
        self._append_log(f"Categoría '{name}' guardada.")

    def _add_category(self):
        self._selected_category = ""
        for b in self._cat_buttons.values():
            b.configure(fg_color="transparent")
        self._cat_name_entry.delete(0, "end")
        self._cat_dest_entry.delete(0, "end")
        self._año_var.set(False)
        self._mes_var.set(False)
        self._ext_box.delete("1.0", "end")

    def _delete_category(self):
        if not self._selected_category:
            return
        self._rules_data.get("categorias", {}).pop(self._selected_category, None)
        self._selected_category = ""
        self._write_rules()
        self._refresh_cat_list()
        self._cat_name_entry.delete(0, "end")
        self._cat_dest_entry.delete(0, "end")
        self._ext_box.delete("1.0", "end")

    def _save_conflict(self):
        self._rules_data["conflicto"] = self._conflict_var.get()
        self._write_rules()
        self._append_log(f"Conflicto → {self._conflict_var.get()}")

    def _write_rules(self):
        cfg = self._load_settings()
        profile = cfg.get("active_profile", "default")
        path = _get_rules_path(profile)
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(self._rules_data, f, allow_unicode=True,
                          default_flow_style=False, sort_keys=False)
        except Exception as e:
            self._append_log(f"Error guardando reglas: {e}")

    def _on_profile_change(self, profile: str):
        cfg = self._load_settings()
        cfg["active_profile"] = profile
        self._write_settings(cfg)
        self._load_rules_for_editor()
        self._load_exclusions_for_editor()

    def _new_profile(self):
        name = simpledialog.askstring("Nuevo perfil", "Nombre del perfil:", parent=self)
        if not name:
            return
        name = name.strip().replace(" ", "_")
        if not name:
            return
        _get_rules_path(name)
        profiles = _list_profiles()
        self._profile_menu.configure(values=profiles)
        self._profile_var.set(name)
        self._on_profile_change(name)

    def _delete_profile(self):
        profile = self._profile_var.get()
        if profile == "default":
            self._append_log("No se puede eliminar el perfil default.")
            return
        (PROFILES_DIR / f"{profile}.yaml").unlink(missing_ok=True)
        profiles = _list_profiles()
        self._profile_menu.configure(values=profiles)
        self._profile_var.set("default")
        self._on_profile_change("default")

    def _load_exclusions_for_editor(self):
        cfg = self._load_settings()
        self._excl_box.delete("1.0", "end")
        self._excl_box.insert("1.0", "\n".join(cfg.get("exclusion_patterns", [])))

    def _save_exclusions(self):
        patterns = [p.strip() for p in self._excl_box.get("1.0", "end").strip().splitlines()
                    if p.strip()]
        cfg = self._load_settings()
        cfg["exclusion_patterns"] = patterns
        self._write_settings(cfg)
        self._append_log(f"Exclusiones: {len(patterns)} patrones guardados.")

    # ── Tab: Historial ────────────────────────────────────────────────────────

    def _build_historial_tab(self, tab):
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(top, text="Historial de movimientos",
                     font=("Segoe UI", 14, "bold")).pack(side="left")
        ctk.CTkButton(top, text="🗑 Limpiar", width=100,
                      fg_color=BTN_RED, hover_color=BTN_RED_HV,
                      command=self._clear_history).pack(side="right")
        ctk.CTkButton(top, text="↻ Actualizar", width=110,
                      fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV,
                      command=self._refresh_history).pack(side="right", padx=(0, 6))

        search_row = ctk.CTkFrame(tab, fg_color="transparent")
        search_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(search_row, text="🔍", font=("Segoe UI", 13)).pack(side="left", padx=(0, 6))
        self._hist_search_var = ctk.StringVar()
        ctk.CTkEntry(search_row, textvariable=self._hist_search_var,
                     placeholder_text="Buscar por nombre, categoría o destino...",
                     height=32).pack(side="left", fill="x", expand=True)
        self._hist_search_var.trace_add("write", lambda *_: self._refresh_history())

        hdr = ctk.CTkFrame(tab, fg_color="#0f172a", corner_radius=6)
        hdr.pack(fill="x", pady=(0, 4))
        for text in ["Hora", "Archivo", "Categoría", "Destino", ""]:
            ctk.CTkLabel(hdr, text=text, font=("Segoe UI", 11, "bold"),
                         text_color=MUTED).pack(side="left", padx=10, pady=6)

        self._hist_scroll = ctk.CTkScrollableFrame(tab, corner_radius=8)
        self._hist_scroll.pack(fill="both", expand=True)
        self._refresh_history()

    def _refresh_history(self):
        for w in self._hist_scroll.winfo_children():
            w.destroy()
        moves = hist.load()
        q = getattr(self, "_hist_search_var", None)
        q = q.get().strip().lower() if q else ""
        if q:
            moves = [m for m in moves if
                     q in m.get("fn", "").lower() or
                     q in m.get("cat", "").lower() or
                     q in m.get("dst", "").lower()]
        if not moves:
            msg = "Sin resultados." if q else "Sin historial aún."
            ctk.CTkLabel(self._hist_scroll, text=msg, text_color=MUTED).pack(pady=20)
            return
        for m in reversed(moves[-300:]):
            self._add_history_row(m)

    def _add_history_row(self, m: dict):
        row = ctk.CTkFrame(self._hist_scroll, fg_color="#141e2e", corner_radius=6)
        row.pack(fill="x", pady=2, padx=2)
        ts  = m.get("ts", "")[:16]
        fn  = m.get("fn", m.get("filename", ""))
        cat = m.get("cat", "?")
        dst = m.get("dst", "")
        src = m.get("src", "")
        ctk.CTkLabel(row, text=ts, font=("Consolas", 10),
                     text_color=MUTED, width=110).pack(side="left", padx=(8, 4), pady=6)
        ctk.CTkLabel(row, text=(fn[:28] + "…" if len(fn) > 28 else fn),
                     font=("Segoe UI", 11), anchor="w").pack(
            side="left", padx=4, expand=True, fill="x")
        ctk.CTkLabel(row, text=cat, font=("Segoe UI", 10),
                     text_color=AMBER, width=90).pack(side="left", padx=4)
        dst_short = Path(dst).name[:22] if dst else "?"
        ctk.CTkLabel(row, text=f"→ {dst_short}", font=("Segoe UI", 10),
                     text_color=MUTED, width=170).pack(side="left", padx=4)
        if dst and Path(dst).exists():
            ctk.CTkButton(row, text="↩", width=36, height=26,
                          fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV,
                          command=lambda s=src, d=dst, r=row: self._undo_history_move(s, d, r)
                          ).pack(side="right", padx=(4, 8), pady=4)

    def _undo_history_move(self, src: str, dst: str, row_frame):
        src_p, dst_p = Path(src), Path(dst)
        try:
            src_p.parent.mkdir(parents=True, exist_ok=True)
            target = src_p
            if target.exists():
                c = 1
                while target.exists():
                    target = src_p.parent / f"{src_p.stem}_{c}{src_p.suffix}"
                    c += 1
            shutil.move(str(dst_p), str(target))
            self._append_log(f"[Deshacer] {dst_p.name}  →  {target.parent}")
            row_frame.destroy()
        except Exception as e:
            self._append_log(f"Error al deshacer: {e}")

    def _clear_history(self):
        hist.clear()
        self._refresh_history()

    # ── Tab: Estadísticas ─────────────────────────────────────────────────────

    def _build_stats_tab(self, tab):
        cards_row = ctk.CTkFrame(tab, fg_color="transparent")
        cards_row.pack(fill="x", pady=(4, 12))
        for i in range(4):
            cards_row.columnconfigure(i, weight=1)
        self._stat_cards = {}
        for i, (key, label, color) in enumerate([
            ("total",   "Total movidos", "#3b82f6"),
            ("today",   "Hoy",           GREEN),
            ("week",    "Esta semana",   AMBER),
            ("top_cat", "Categoría top", "#a855f7"),
        ]):
            c = ctk.CTkFrame(cards_row, corner_radius=10, fg_color="#141e2e",
                             border_width=1, border_color=color)
            c.grid(row=0, column=i, sticky="ew", padx=4)
            ctk.CTkLabel(c, text=label, font=("Segoe UI", 11),
                         text_color=MUTED).pack(anchor="w", padx=12, pady=(10, 2))
            lbl = ctk.CTkLabel(c, text="—", font=("Segoe UI", 22, "bold"), text_color=color)
            lbl.pack(anchor="w", padx=12, pady=(0, 10))
            self._stat_cards[key] = lbl

        ctk.CTkButton(tab, text="↻ Actualizar estadísticas",
                      fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV,
                      command=self._refresh_stats).pack(anchor="e", pady=(0, 8))

        breakdown = ctk.CTkFrame(tab, corner_radius=10, border_width=1, border_color="#1e293b")
        breakdown.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(breakdown, text="Por categoría",
                     font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(10, 6))
        self._breakdown_frame = ctk.CTkScrollableFrame(
            breakdown, fg_color="transparent", height=160)
        self._breakdown_frame.pack(fill="x", padx=10, pady=(0, 10))

        days_card = ctk.CTkFrame(tab, corner_radius=10, border_width=1, border_color="#1e293b")
        days_card.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(days_card, text="Últimos 7 días",
                     font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(10, 6))
        self._days_inner = ctk.CTkFrame(days_card, fg_color="transparent")
        self._days_inner.pack(fill="x", padx=10, pady=(0, 14))

        self._refresh_stats()

    def _refresh_stats(self):
        moves = hist.load()
        today_str = datetime.now().strftime("%Y-%m-%d")
        week_ago  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        total    = len(moves)
        today_c  = sum(1 for m in moves if m.get("ts", "").startswith(today_str))
        week_c   = sum(1 for m in moves if m.get("ts", "") >= week_ago)
        by_cat: dict = {}
        for m in moves:
            cat = m.get("cat", "Otros")
            by_cat[cat] = by_cat.get(cat, 0) + 1
        top_cat = max(by_cat, key=by_cat.get) if by_cat else "—"

        self._stat_cards["total"].configure(text=str(total))
        self._stat_cards["today"].configure(text=str(today_c))
        self._stat_cards["week"].configure(text=str(week_c))
        self._stat_cards["top_cat"].configure(text=top_cat[:14])

        for w in self._breakdown_frame.winfo_children():
            w.destroy()
        if by_cat:
            max_v = max(by_cat.values())
            for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
                r = ctk.CTkFrame(self._breakdown_frame, fg_color="transparent")
                r.pack(fill="x", pady=3)
                ctk.CTkLabel(r, text=cat, width=140, anchor="w").pack(side="left")
                bar = ctk.CTkProgressBar(r, width=220, height=14,
                                         progress_color="#3b82f6")
                bar.set(count / max_v)
                bar.pack(side="left", padx=8)
                ctk.CTkLabel(r, text=str(count), text_color=MUTED,
                             font=("Segoe UI", 11)).pack(side="left")

        for w in self._days_inner.winfo_children():
            w.destroy()
        by_day = hist.stats_by_day(7, moves)
        max_d = max(by_day.values()) if by_day else 1
        if max_d == 0:
            max_d = 1
        for day, count in by_day.items():
            col = ctk.CTkFrame(self._days_inner, fg_color="transparent")
            col.pack(side="left", padx=10)
            bar = ctk.CTkProgressBar(col, width=14, height=70,
                                     progress_color=GREEN, orientation="vertical")
            bar.set(count / max_d)
            bar.pack()
            ctk.CTkLabel(col, text=str(count), font=("Segoe UI", 10)).pack()
            ctk.CTkLabel(col, text=day, font=("Segoe UI", 9),
                         text_color=MUTED).pack()

    # ── Tab: Programar ────────────────────────────────────────────────────────

    def _build_programar_tab(self, tab):
        cfg = self._load_settings()
        card = ctk.CTkFrame(tab, corner_radius=12, border_width=1, border_color="#1e293b")
        card.pack(fill="x", padx=4, pady=(4, 12))

        ctk.CTkLabel(card, text="Programar organización automática",
                     font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            card,
            text="Organiza la carpeta vigilada automáticamente a la hora y días configurados.",
            text_color=MUTED).pack(anchor="w", padx=16, pady=(0, 12))

        self._sched_var = ctk.BooleanVar(value=cfg.get("schedule_enabled", False))
        ctk.CTkCheckBox(card, text="Activar programación automática",
                        variable=self._sched_var,
                        command=self._toggle_schedule).pack(anchor="w", padx=16, pady=(0, 10))

        time_row = ctk.CTkFrame(card, fg_color="transparent")
        time_row.pack(anchor="w", padx=16, pady=(0, 10))
        ctk.CTkLabel(time_row, text="Hora:").pack(side="left")
        self._sched_hour = ctk.CTkEntry(time_row, width=52, height=32)
        self._sched_hour.insert(0, str(cfg.get("schedule_hour", 22)))
        self._sched_hour.pack(side="left", padx=(6, 4))
        ctk.CTkLabel(time_row, text=":").pack(side="left")
        self._sched_min = ctk.CTkEntry(time_row, width=52, height=32)
        self._sched_min.insert(0, str(cfg.get("schedule_minute", 0)).zfill(2))
        self._sched_min.pack(side="left", padx=(4, 0))

        ctk.CTkLabel(card, text="Días:", text_color=MUTED).pack(
            anchor="w", padx=16, pady=(4, 2))
        days_row = ctk.CTkFrame(card, fg_color="transparent")
        days_row.pack(anchor="w", padx=16, pady=(0, 12))
        saved_days = set(cfg.get("schedule_days", list(range(7))))
        self._day_vars = []
        for i, name in enumerate(["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]):
            v = ctk.BooleanVar(value=i in saved_days)
            self._day_vars.append(v)
            ctk.CTkCheckBox(days_row, text=name, variable=v, width=66).pack(
                side="left", padx=3)

        ctk.CTkButton(card, text="💾 Guardar programación", width=200,
                      fg_color=BTN_BLUE, hover_color=BTN_BLUE_HV,
                      command=self._save_schedule).pack(anchor="w", padx=16, pady=(0, 16))

        self._sched_status = ctk.CTkLabel(
            tab, text="", text_color=MUTED, font=("Segoe UI", 11))
        self._sched_status.pack(anchor="w", padx=8, pady=4)
        self._update_sched_status()

    def _toggle_schedule(self):
        if self._sched_var.get():
            self._save_schedule()
        else:
            self._scheduler.stop()
            cfg = self._load_settings()
            cfg["schedule_enabled"] = False
            self._write_settings(cfg)
            self._update_sched_status()

    def _save_schedule(self):
        try:
            hour   = int(self._sched_hour.get())
            minute = int(self._sched_min.get())
        except ValueError:
            self._append_log("ERROR: Hora/minuto inválidos.")
            return
        days = {i for i, v in enumerate(self._day_vars) if v.get()}
        cfg = self._load_settings()
        cfg.update({
            "schedule_enabled": self._sched_var.get(),
            "schedule_hour":    hour,
            "schedule_minute":  minute,
            "schedule_days":    list(days),
        })
        self._write_settings(cfg)
        self._scheduler.configure(hour, minute, days, self._scheduled_organize)
        if self._sched_var.get():
            self._scheduler.start()
        else:
            self._scheduler.stop()
        self._update_sched_status()
        self._append_log(f"Programación guardada: {hour:02d}:{minute:02d}")

    def _update_sched_status(self):
        if self._scheduler.enabled:
            h, m = self._scheduler.hour, self._scheduler.minute
            self._sched_status.configure(
                text=f"✓ Programado para las {h:02d}:{m:02d}", text_color=GREEN)
        else:
            self._sched_status.configure(
                text="— Sin programación activa", text_color=MUTED)

    def _scheduled_organize(self):
        watch  = Path(self.watch_entry.get().strip())
        output = self.output_entry.get().strip()
        if not watch.exists() or not output:
            return
        cfg = self._load_settings()
        organizer = FileOrganizer(
            str(_get_rules_path(cfg.get("active_profile", "default"))),
            output, move_delay=3,
            exclusion_patterns=cfg.get("exclusion_patterns", []))
        threading.Thread(
            target=organizer.organize_existing, args=(watch,), daemon=True).start()
        self._append_log(
            f"[Programado] {watch.name} a las {datetime.now().strftime('%H:%M')}")

    def _init_scheduler_from_settings(self):
        cfg = self._load_settings()
        if cfg.get("schedule_enabled", False):
            h = cfg.get("schedule_hour", 22)
            m = cfg.get("schedule_minute", 0)
            d = set(cfg.get("schedule_days", list(range(7))))
            self._scheduler.configure(h, m, d, self._scheduled_organize)
            self._scheduler.start()

    # ── Tab: Ayuda ────────────────────────────────────────────────────────────

    _HELP_TOPICS = [
        ("🏠", "Inicio",        "inicio",    "#3b82f6",
         "Configura y arranca la app"),
        ("📋", "Reglas",        "reglas",    "#a855f7",
         "¿Qué archivo va dónde?"),
        ("🕐", "Historial",     "historial", "#22c55e",
         "Todo lo que se ha movido"),
        ("📊", "Estadísticas",  "stats",     "#f59e0b",
         "Cuánto has organizado"),
        ("⏰", "Programar",     "programar", "#06b6d4",
         "Organización automática"),
        ("📁", "Carpetas",      "carpetas",  "#ec4899",
         "Organiza carpetas enteras"),
        ("💡", "Consejos",      "consejos",  "#84cc16",
         "Sácale el máximo provecho"),
    ]

    _HELP_CONTENT = {
        "inicio": [
            ("hero",    ("🏠", "Pestaña Inicio",
                         "Tu base de operaciones. Desde aquí controlas todo.", "#3b82f6")),
            ("section", "¿Cómo empiezo?"),
            ("body",    "Solo necesitas hacer dos cosas antes de presionar Iniciar:\n"
                        "  1️⃣  Elegir la carpeta que quieres vigilar (ej. Descargas)\n"
                        "  2️⃣  Elegir dónde quieres que queden los archivos organizados"),
            ("tip",     "¿Primera vez? Haz clic en 'Buscar' para elegir las carpetas "
                        "fácilmente, sin tener que escribir rutas largas."),
            ("section", "📂 Carpeta a monitorear"),
            ("body",    "La app mira esta carpeta todo el tiempo. Cada vez que llegue "
                        "un archivo nuevo, lo organizará automáticamente. "
                        "Normalmente es tu carpeta de Descargas."),
            ("section", "📬 Carpeta de destino"),
            ("body",    "Aquí es donde la app crea las subcarpetas ordenadas. "
                        "Por ejemplo: si destino es 'Documentos/Organizado', "
                        "la app creará carpetas como:\n"
                        "  → Documentos/Organizado/Imágenes/\n"
                        "  → Documentos/Organizado/PDFs/\n"
                        "  → Documentos/Organizado/Videos/"),
            ("section", "⏱ Delay (segundos)"),
            ("body",    "Cuántos segundos espera la app antes de mover un archivo nuevo. "
                        "Sirve para no interrumpir archivos que se están descargando todavía."),
            ("tip",     "3 segundos funciona bien para la mayoría. "
                        "Si tienes internet lento, súbelo a 10."),
            ("section", "✅ Organizar existentes / carpetas al iniciar"),
            ("body",    "Cuando activas estas opciones, al presionar Iniciar la app también "
                        "organiza todo lo que YA estaba en la carpeta, no solo lo nuevo.\n"
                        "  • Archivos existentes → mueve archivos sueltos\n"
                        "  • Carpetas existentes → entra a subcarpetas y organiza su contenido"),
            ("section", "▶ Botón Iniciar / Detener"),
            ("body",    "Presiónalo para activar el vigilante. Cuando está activo, "
                        "la app sigue funcionando aunque cierres la ventana "
                        "(queda en la bandeja del sistema, esquina inferior derecha)."),
            ("section", "↩ Deshacer último"),
            ("body",    "¿Moviste algo sin querer? Este botón regresa el último "
                        "archivo a donde estaba."),
        ],
        "reglas": [
            ("hero",    ("📋", "Pestaña Reglas",
                         "Tú decides qué va dónde. Personaliza cada detalle.", "#a855f7")),
            ("section", "¿Qué son los perfiles?"),
            ("body",    "Un perfil es un grupo de reglas. Puedes tener uno para el trabajo "
                        "y otro para uso personal, cada uno con sus propias carpetas y categorías.\n"
                        "Cámbialo desde el menú desplegable antes de iniciar."),
            ("tip",     "El perfil 'default' siempre existe y no se puede borrar. "
                        "Crea nuevos con el botón '+ Nuevo'."),
            ("section", "📋 Categorías"),
            ("body",    "Cada categoría le dice a la app: 'todos los archivos con estas "
                        "extensiones van a esta carpeta'. Por ejemplo:\n"
                        "  • Categoría 'Imágenes' → .jpg, .png, .gif → carpeta Imágenes/\n"
                        "  • Categoría 'PDFs' → .pdf → carpeta Documentos/\n\n"
                        "Haz clic en una categoría de la lista izquierda para editarla."),
            ("section", "📅 Subcarpeta por año / mes"),
            ("body",    "Actívalo si quieres que los archivos también se clasifiquen por fecha:\n"
                        "  Imágenes/2024/Agosto/foto_vacaciones.jpg\n\n"
                        "La app lee la fecha del nombre del archivo si la tiene, "
                        "o usa la fecha de última modificación."),
            ("section", "⚡ Conflicto de nombres"),
            ("body",    "¿Qué pasa si ya hay un archivo con el mismo nombre en destino?\n"
                        "  • Renombrar → guarda como archivo_1.pdf, archivo_2.pdf...\n"
                        "  • Saltar → no mueve nada, deja el archivo donde está\n"
                        "  • Reemplazar → borra el existente y pone el nuevo"),
            ("warn",    "Reemplazar borra el archivo que ya estaba. No hay vuelta atrás."),
            ("section", "🚫 Patrones de exclusión"),
            ("body",    "Lista de archivos que NUNCA se moverán, pase lo que pase. "
                        "Muy útil para archivos del sistema o que no deben tocarse:\n"
                        "  desktop.ini  →  archivo oculto del sistema\n"
                        "  *.tmp        →  cualquier archivo temporal\n"
                        "  ~$*          →  archivos temporales de Word/Excel\n"
                        "  *.lnk        →  accesos directos"),
        ],
        "historial": [
            ("hero",    ("🕐", "Pestaña Historial",
                         "Un registro de todo lo que se ha movido. Nada se pierde.", "#22c55e")),
            ("section", "¿Para qué sirve?"),
            ("body",    "Aquí puedes ver exactamente qué archivos movió la app, "
                        "cuándo los movió y a dónde fueron. "
                        "Se ordena del más reciente al más antiguo."),
            ("section", "↩ Deshacer por archivo"),
            ("body",    "¿Ves el botón '↩' al lado de una fila? Presiónalo y ese archivo "
                        "vuelve a su lugar original. No importa cuándo se movió.\n\n"
                        "El botón solo aparece si el archivo todavía existe en el destino."),
            ("tip",     "Diferente al 'Deshacer último' de Inicio: este te permite "
                        "revertir cualquier movimiento específico del historial, no solo el último."),
            ("section", "↻ Actualizar"),
            ("body",    "Recarga la lista desde el archivo de datos. "
                        "Úsalo si acabas de terminar una sesión de organización."),
            ("section", "🗑 Limpiar"),
            ("body",    "Borra el historial completo. "
                        "No mueve ni recupera archivos, solo limpia la lista."),
            ("tip",     "La app guarda hasta 2,000 movimientos. "
                        "Cuando se llena, los más viejos se eliminan automáticamente."),
        ],
        "stats": [
            ("hero",    ("📊", "Pestaña Estadísticas",
                         "Visualiza cuánto has organizado y qué tipos de archivos predominan.",
                         "#f59e0b")),
            ("section", "Las 4 tarjetas de arriba"),
            ("body",    "De un vistazo ves lo más importante:\n"
                        "  🔵 Total movidos — todos los archivos organizados en la historia\n"
                        "  🟢 Hoy — lo que se organizó hoy\n"
                        "  🟡 Esta semana — los últimos 7 días\n"
                        "  🟣 Categoría top — el tipo de archivo que más aparece"),
            ("section", "📊 Barras por categoría"),
            ("body",    "Muestra qué tipos de archivos se organizan más. "
                        "La barra más larga = el 100%. Muy útil para ver si tienes "
                        "muchos PDFs, imágenes, etc."),
            ("section", "📅 Últimos 7 días"),
            ("body",    "Barras verticales con la actividad de cada día. "
                        "Te permite ver si tu carpeta de descargas tiene picos "
                        "de actividad en días específicos."),
            ("tip",     "Presiona '↻ Actualizar estadísticas' después de una sesión "
                        "para ver los datos más recientes."),
        ],
        "programar": [
            ("hero",    ("⏰", "Pestaña Programar",
                         "La app organiza sola mientras tú haces otra cosa.", "#06b6d4")),
            ("section", "¿Cómo funciona?"),
            ("body",    "Configuras una hora y días de la semana. "
                        "Cuando llegue ese momento, la app organiza automáticamente "
                        "todos los archivos de tu carpeta vigilada, "
                        "sin que tengas que hacer nada."),
            ("tip",     "Ideal para programar una limpieza nocturna. "
                        "Por ejemplo: todos los días a las 11pm, "
                        "la app ordena lo que se descargó durante el día."),
            ("section", "⚙️ Cómo configurarlo"),
            ("body",    "  1️⃣  Activa el checkbox 'Activar programación automática'\n"
                        "  2️⃣  Escribe la hora en formato 24h (ej. 22 para las 10pm)\n"
                        "  3️⃣  Elige los días de la semana\n"
                        "  4️⃣  Haz clic en 'Guardar programación'"),
            ("section", "📌 Importante"),
            ("warn",    "La app tiene que estar abierta (aunque sea minimizada en la bandeja) "
                        "para que la programación funcione. No corre si la cerraste completamente."),
            ("body",    "Para que corra siempre en segundo plano, activa "
                        "'Iniciar con Windows' en la pestaña Inicio."),
        ],
        "carpetas": [
            ("hero",    ("📁", "Organización de Carpetas",
                         "¿Tienes una carpeta llena de caos? La app la ordena entera.", "#ec4899")),
            ("section", "¿Qué puede hacer con carpetas?"),
            ("body",    "No solo organiza archivos sueltos. Si tiras una carpeta entera "
                        "dentro de tu carpeta vigilada, la app detecta todos los archivos "
                        "que hay adentro y los organiza uno por uno."),
            ("section", "📥 Carpeta nueva que llega"),
            ("body",    "Imagina que alguien te manda una carpeta 'Proyecto cliente' "
                        "con 80 archivos mezclados. La arrastras a Descargas y...\n\n"
                        "La app muestra un aviso: '📁 Proyecto cliente — 80 archivos. "
                        "¿Organizarlos?' Tú decides si quieres o no."),
            ("section", "📁 Carpetas que ya estaban"),
            ("body",    "En la pestaña Inicio hay un checkbox: "
                        "'Organizar carpetas existentes al iniciar'.\n\n"
                        "Si lo activas, cuando presiones Iniciar la app revisará "
                        "todas las subcarpetas que ya existen en tu carpeta vigilada "
                        "y organizará todo lo que encuentre adentro."),
            ("section", "🧹 ¿Qué pasa con la carpeta original?"),
            ("body",    "Cuando todos sus archivos se mueven, si la carpeta queda vacía "
                        "se elimina automáticamente. Si quedó algún archivo que no se pudo "
                        "mover (por error de permisos, etc.), la carpeta se mantiene."),
            ("tip",     "Perfecto para esa carpeta 'Cosas viejas' que llevas meses "
                        "sin ordenar y tiene archivos de todo tipo mezclados."),
        ],
        "consejos": [
            ("hero",    ("💡", "Consejos",
                         "Trucos para sacarle el máximo provecho a la app.", "#84cc16")),
            ("section", "🚀 Para empezar bien"),
            ("body",    "  1️⃣  Elige tu carpeta de Descargas como carpeta a monitorear\n"
                        "  2️⃣  Crea una carpeta 'Organizado' dentro de Documentos\n"
                        "  3️⃣  Revisa las categorías en Reglas (ya vienen preconfiguradas)\n"
                        "  4️⃣  Activa 'Iniciar con Windows' para que corra siempre\n"
                        "  5️⃣  Presiona Iniciar y olvídate"),
            ("section", "🛡️ Protege archivos importantes"),
            ("body",    "Si hay archivos que nunca deben moverse, agrégalos en "
                        "Reglas → Patrones de exclusión:\n"
                        "  desktop.ini  →  evita mover archivos del sistema\n"
                        "  *.lnk        →  accesos directos del escritorio\n"
                        "  *.url        →  enlaces guardados\n"
                        "  ~$*          →  archivos abiertos en Office"),
            ("tip",     "Los archivos .tmp, .crdownload y .part NUNCA se mueven, "
                        "sin importar las reglas. Son descargas en progreso."),
            ("section", "👔 Perfiles para distintos usos"),
            ("body",    "Crea un perfil 'Trabajo' que organiza hacia una carpeta de proyectos, "
                        "y uno 'Personal' para fotos y música. "
                        "Cambia el perfil según lo que vayas a hacer."),
            ("section", "🔕 La app en segundo plano"),
            ("body",    "Cuando cierras la ventana con la X, la app NO termina: "
                        "se minimiza a la bandeja del sistema "
                        "(busca el ícono ⚡ en la esquina inferior derecha de la pantalla).\n\n"
                        "Para cerrarla de verdad: clic derecho en ese ícono → Salir."),
            ("warn",    "Si la cierras desde el Administrador de Tareas, "
                        "algún archivo podría quedar a medias en movimiento."),
            ("section", "⏱ ¿Cuánto delay usar?"),
            ("body",    "  • 1 segundo  →  para organizar archivos que ya descargaste\n"
                        "  • 3 segundos →  uso normal del día a día\n"
                        "  • 10+ segundos →  internet lento o archivos muy grandes"),
        ],
    }

    def _build_ayuda_tab(self, tab):
        split = ctk.CTkFrame(tab, fg_color="transparent")
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=0)
        split.columnconfigure(1, weight=1)
        split.rowconfigure(0, weight=1)

        left = ctk.CTkFrame(split, width=200, corner_radius=12,
                            fg_color="#0d1829",
                            border_width=1, border_color="#1e293b")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_propagate(False)

        ctk.CTkLabel(left, text="📖  Manual de uso",
                     font=("Segoe UI", 13, "bold"),
                     text_color="#60a5fa").pack(anchor="w", padx=14, pady=(16, 4))
        ctk.CTkLabel(left, text="Selecciona un tema",
                     font=("Segoe UI", 10), text_color="#334155").pack(
            anchor="w", padx=14, pady=(0, 10))
        ctk.CTkFrame(left, fg_color="#1e293b", height=1).pack(fill="x", padx=10, pady=(0, 8))

        self._help_topic_buttons: dict = {}
        self._help_content_frame = ctk.CTkScrollableFrame(
            split, corner_radius=12, border_width=1, border_color="#1e293b",
            fg_color="#0a1120")
        self._help_content_frame.grid(row=0, column=1, sticky="nsew")

        for emoji, label, key, color, subtitle in self._HELP_TOPICS:
            btn_frame = ctk.CTkFrame(left, fg_color="transparent")
            btn_frame.pack(fill="x", padx=8, pady=2)
            btn = ctk.CTkButton(
                btn_frame, text=f"{emoji}  {label}", height=40, anchor="w",
                font=("Segoe UI", 12, "bold"),
                fg_color="transparent", hover_color="#1e293b",
                text_color="#e2e8f0", corner_radius=8,
                command=lambda k=key: self._show_help_topic(k))
            btn.pack(fill="x")
            self._help_topic_buttons[key] = (btn, color)

        self._show_help_welcome()

    def _show_help_welcome(self):
        for w in self._help_content_frame.winfo_children():
            w.destroy()
        for k, (b, c) in self._help_topic_buttons.items():
            b.configure(fg_color="transparent", text_color="#e2e8f0")

        ctk.CTkLabel(self._help_content_frame, text="👋  ¡Bienvenido!",
                     font=("Segoe UI", 22, "bold"),
                     text_color="white").pack(anchor="w", padx=24, pady=(24, 4))
        ctk.CTkLabel(self._help_content_frame,
                     text="File Organizer mantiene tus carpetas ordenadas automáticamente.\n"
                          "Selecciona un tema en la izquierda para aprender cómo usarlo.",
                     font=("Segoe UI", 13), text_color="#94a3b8",
                     justify="left", wraplength=560).pack(anchor="w", padx=24, pady=(0, 20))

        grid = ctk.CTkFrame(self._help_content_frame, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=(0, 10))
        grid.columnconfigure((0, 1), weight=1)

        cards_data = [
            (t[0], t[1], t[2], t[3], t[4]) for t in self._HELP_TOPICS
        ]
        for i, (emoji, label, key, color, subtitle) in enumerate(cards_data):
            card = ctk.CTkFrame(grid, fg_color="#111c2e", corner_radius=12,
                                border_width=1, border_color=color, cursor="hand2")
            card.grid(row=i // 2, column=i % 2, padx=6, pady=6, sticky="ew")
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", padx=14, pady=12)
            ctk.CTkLabel(inner, text=emoji,
                         font=("Segoe UI", 22)).pack(anchor="w")
            ctk.CTkLabel(inner, text=label,
                         font=("Segoe UI", 13, "bold"),
                         text_color=color).pack(anchor="w", pady=(4, 2))
            ctk.CTkLabel(inner, text=subtitle,
                         font=("Segoe UI", 11), text_color="#64748b",
                         wraplength=200, justify="left").pack(anchor="w")
            card.bind("<Button-1>", lambda e, k=key: self._show_help_topic(k))
            for w in card.winfo_children() + inner.winfo_children():
                w.bind("<Button-1>", lambda e, k=key: self._show_help_topic(k))

    def _show_help_topic(self, key: str):
        for k, (b, c) in self._help_topic_buttons.items():
            if k == key:
                b.configure(fg_color=("#1e3a5f", "#1e3a5f"), text_color="white")
            else:
                b.configure(fg_color="transparent", text_color="#e2e8f0")

        for w in self._help_content_frame.winfo_children():
            w.destroy()

        # Back button
        back = ctk.CTkButton(self._help_content_frame,
                             text="← Inicio",
                             width=90, height=28,
                             font=("Segoe UI", 11),
                             fg_color="transparent",
                             hover_color="#1e293b",
                             text_color="#60a5fa",
                             anchor="w",
                             command=self._show_help_welcome)
        back.pack(anchor="w", padx=16, pady=(12, 0))

        blocks = self._HELP_CONTENT.get(key, [])
        for kind, content in blocks:
            if kind == "hero":
                emoji, title, subtitle, color = content
                hero = ctk.CTkFrame(self._help_content_frame,
                                    fg_color="#111c2e", corner_radius=12,
                                    border_width=1, border_color=color)
                hero.pack(fill="x", padx=16, pady=(8, 18))
                row = ctk.CTkFrame(hero, fg_color="transparent")
                row.pack(anchor="w", padx=18, pady=(16, 8))
                ctk.CTkLabel(row, text=emoji,
                             font=("Segoe UI", 28)).pack(side="left", padx=(0, 12))
                col = ctk.CTkFrame(row, fg_color="transparent")
                col.pack(side="left")
                ctk.CTkLabel(col, text=title,
                             font=("Segoe UI", 17, "bold"),
                             text_color=color, anchor="w").pack(anchor="w")
                ctk.CTkLabel(col, text=subtitle,
                             font=("Segoe UI", 12),
                             text_color="#94a3b8", anchor="w",
                             wraplength=480, justify="left").pack(anchor="w", pady=(2, 0))
                ctk.CTkFrame(hero, fg_color=color, height=2,
                             corner_radius=0).pack(fill="x", pady=(8, 0))
            elif kind == "section":
                ctk.CTkLabel(self._help_content_frame, text=content,
                             font=("Segoe UI", 13, "bold"),
                             text_color="#93c5fd", anchor="w",
                             ).pack(anchor="w", padx=20, pady=(16, 3))
            elif kind == "body":
                ctk.CTkLabel(self._help_content_frame, text=content,
                             font=("Segoe UI", 12),
                             text_color="#cbd5e1", anchor="w",
                             justify="left", wraplength=570,
                             ).pack(anchor="w", padx=28, pady=(0, 4))
            elif kind == "tip":
                box = ctk.CTkFrame(self._help_content_frame,
                                   fg_color="#0f2610", corner_radius=10,
                                   border_width=1, border_color="#166534")
                box.pack(fill="x", padx=20, pady=(6, 4))
                ctk.CTkLabel(box, text=f"💡  {content}",
                             font=("Segoe UI", 12),
                             text_color="#86efac", anchor="w",
                             justify="left", wraplength=550,
                             ).pack(anchor="w", padx=14, pady=10)
            elif kind == "warn":
                box = ctk.CTkFrame(self._help_content_frame,
                                   fg_color="#1a0e00", corner_radius=10,
                                   border_width=1, border_color="#92400e")
                box.pack(fill="x", padx=20, pady=(6, 4))
                ctk.CTkLabel(box, text=f"⚠️  {content}",
                             font=("Segoe UI", 12),
                             text_color="#fcd34d", anchor="w",
                             justify="left", wraplength=550,
                             ).pack(anchor="w", padx=14, pady=10)

        ctk.CTkFrame(self._help_content_frame,
                     fg_color="transparent", height=24).pack()

    # ── Bienvenida (primer inicio) ────────────────────────────────────────────

    _WELCOME_STEPS = [
        {
            "emoji": "👋",
            "title": "¡Bienvenido a File Organizer!",
            "subtitle": "Organiza tus archivos automáticamente sin mover un dedo. Este manual te explica cómo usarlo.",
            "items": [
                ("1", "Elige la carpeta a vigilar",
                 "Normalmente tu carpeta de Descargas. La app la revisa todo el tiempo."),
                ("2", "Elige dónde se guardan",
                 "La app crea subcarpetas ordenadas ahí: Imágenes/, PDFs/, Videos/, etc."),
                ("3", "Presiona Iniciar",
                 "Desde ese momento, cada archivo nuevo se mueve solo al lugar correcto."),
                ("4", "Listo, ya no haces nada más",
                 "La app sigue activa en la bandeja del sistema aunque cierres la ventana."),
            ],
        },
        {
            "emoji": "🏠",
            "title": "Cómo usar la pestaña Inicio",
            "subtitle": "Sigue estos pasos para configurar y arrancar la app por primera vez.",
            "items": [
                ("1", "Haz clic en Buscar → 'Carpeta a monitorear'",
                 "Selecciona la carpeta que quieres vigilar, por ejemplo: C:/Users/TuNombre/Downloads"),
                ("2", "Haz clic en Buscar → 'Carpeta destino'",
                 "Elige dónde quieres que queden los archivos ordenados. Si no existe, la app la crea."),
                ("3", "Deja el Delay en 3 segundos",
                 "Así evitas que mueva archivos que todavía se están descargando. Súbelo si tienes internet lento."),
                ("4", "Presiona el botón Iniciar ▶",
                 "El estado cambia a 'Activo'. Para en cualquier momento con el mismo botón."),
            ],
        },
        {
            "emoji": "📋",
            "title": "Cómo personalizar las Reglas",
            "subtitle": "Define qué extensiones van a qué carpeta. Cada regla se llama 'categoría'.",
            "items": [
                ("1", "Abre la pestaña Reglas y selecciona una categoría",
                 "En el panel izquierdo verás las categorías existentes: Imágenes, PDFs, Videos, etc."),
                ("2", "Edita el nombre, la carpeta destino y las extensiones",
                 "Escribe una extensión por línea: .jpg  .png  .gif — la app las reconoce todas."),
                ("3", "Activa 'Subcarpeta por año/mes' si lo deseas",
                 "Los archivos quedarán en rutas como: Imágenes/2024/Agosto/foto.jpg"),
                ("4", "Guarda con el botón 'Guardar categoría'",
                 "Puedes crear perfiles distintos (trabajo, personal) con el botón + Nuevo arriba."),
            ],
        },
        {
            "emoji": "🕐",
            "title": "Historial, Estadísticas y Deshacer",
            "subtitle": "Consulta todo lo que se ha organizado y deshaz movimientos si es necesario.",
            "items": [
                ("1", "Pestaña Historial → ver qué se movió",
                 "Lista completa con fecha, nombre, origen y destino. Usa el buscador para filtrar."),
                ("2", "Botón 'Deshacer último' en la pestaña Inicio",
                 "Regresa el último archivo movido a donde estaba. Funciona hasta 20 movimientos atrás."),
                ("3", "Pestaña Estadísticas → ver actividad",
                 "Gráfica de barras por día y torta por categoría. Útil para ver qué tipo de archivos más llegan."),
                ("4", "Botón Limpiar en Historial",
                 "Borra el registro almacenado cuando ya no lo necesitas."),
            ],
        },
        {
            "emoji": "⚙️",
            "title": "Funciones avanzadas",
            "subtitle": "Automatiza aún más y adapta la app a tu flujo de trabajo.",
            "items": [
                ("1", "Pestaña Programar → organización automática por horario",
                 "Elige un día y hora fijos para que la app organice todo lo acumulado automáticamente."),
                ("2", "Carpetas completas en Descargas",
                 "Si mueves una carpeta a Descargas, la app la detecta y te pregunta si organizar su contenido."),
                ("3", "Patrones de exclusión en Reglas",
                 "Archivos como desktop.ini o *.tmp nunca se moverán. Agrégalos en la sección Exclusiones."),
                ("4", "Pestaña Manual siempre disponible",
                 "Consulta la guía detallada de cada sección en cualquier momento desde la pestaña Manual."),
            ],
        },
    ]

    def _maybe_show_welcome(self):
        self._show_welcome_wizard()

    def _show_welcome_wizard(self):
        STEPS = self._WELCOME_STEPS
        N = len(STEPS)

        dlg = ctk.CTkToplevel(self)
        dlg.title("Bienvenida")
        dlg.geometry("600x510")
        dlg.resizable(False, False)
        dlg.configure(fg_color="#080f1a")
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()

        step = [0]

        # ── Header ──
        hdr = ctk.CTkFrame(dlg, fg_color="#0d1829", corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        hdr_title = ctk.CTkLabel(hdr, text="Tour de bienvenida",
                                  font=("Segoe UI", 13, "bold"), text_color="#60a5fa")
        hdr_title.pack(side="left", padx=20, pady=14)
        prog_lbl = ctk.CTkLabel(hdr, text="", font=("Segoe UI", 11), text_color="#475569")
        prog_lbl.pack(side="right", padx=20)
        ctk.CTkFrame(dlg, fg_color="#1d4ed8", height=2, corner_radius=0).pack(fill="x")

        # ── Content ──
        content = ctk.CTkFrame(dlg, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(18, 8))

        # ── Footer ──
        footer = ctk.CTkFrame(dlg, fg_color="#0d1829", corner_radius=0, height=70)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        dots_frame = ctk.CTkFrame(footer, fg_color="transparent")
        dots_frame.place(relx=0.0, rely=0.5, x=24, anchor="w")
        dot_labels = []
        for _ in range(N):
            d = ctk.CTkLabel(dots_frame, text="⬤", font=("Segoe UI", 9),
                             text_color="#243447")
            d.pack(side="left", padx=4)
            dot_labels.append(d)

        btn_frame = ctk.CTkFrame(footer, fg_color="transparent")
        btn_frame.place(relx=1.0, rely=0.5, x=-20, anchor="e")
        prev_btn = ctk.CTkButton(btn_frame, text="← Anterior", width=120, height=40,
                                  font=("Segoe UI", 13),
                                  fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV)
        prev_btn.pack(side="left", padx=(0, 10))
        next_btn = ctk.CTkButton(btn_frame, text="Siguiente →", width=140, height=40,
                                  font=("Segoe UI", 13, "bold"),
                                  fg_color=BTN_BLUE, hover_color=BTN_BLUE_HV)
        next_btn.pack(side="left")

        def render(s):
            for w in content.winfo_children():
                w.destroy()
            data = STEPS[s]

            top = ctk.CTkFrame(content, fg_color="transparent")
            top.pack(anchor="w", pady=(0, 14))
            ctk.CTkLabel(top, text=data["emoji"],
                         font=("Segoe UI", 38)).pack(side="left", padx=(0, 14))
            txt = ctk.CTkFrame(top, fg_color="transparent")
            txt.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(txt, text=data["title"],
                         font=("Segoe UI", 17, "bold"), text_color="white",
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(txt, text=data["subtitle"],
                         font=("Segoe UI", 11), text_color="#94a3b8",
                         wraplength=400, justify="left", anchor="w").pack(anchor="w", pady=(3, 0))

            ctk.CTkFrame(content, fg_color="#1e293b", height=1).pack(fill="x", pady=(0, 12))

            for icon, title, desc in data["items"]:
                row = ctk.CTkFrame(content, fg_color="#0d1829", corner_radius=8)
                row.pack(fill="x", pady=3)
                badge = ctk.CTkFrame(row, fg_color="#1d4ed8", corner_radius=14,
                                     width=28, height=28)
                badge.pack(side="left", padx=(12, 0), pady=10)
                badge.pack_propagate(False)
                ctk.CTkLabel(badge, text=icon, font=("Segoe UI", 12, "bold"),
                             text_color="white").place(relx=0.5, rely=0.5, anchor="center")
                info = ctk.CTkFrame(row, fg_color="transparent")
                info.pack(side="left", padx=12, pady=8, fill="x", expand=True)
                ctk.CTkLabel(info, text=title, font=("Segoe UI", 12, "bold"),
                             text_color="#e2e8f0", anchor="w").pack(anchor="w")
                ctk.CTkLabel(info, text=desc, font=("Segoe UI", 11),
                             text_color="#64748b", anchor="w",
                             wraplength=390, justify="left").pack(anchor="w")

            prog_lbl.configure(text=f"{s + 1} / {N}")
            for i, d in enumerate(dot_labels):
                d.configure(text_color="#3b82f6" if i == s else "#243447")
            prev_btn.configure(state="normal" if s > 0 else "disabled")
            if s == N - 1:
                next_btn.configure(text="¡Empezar!",
                                   fg_color=BTN_GREEN, hover_color=BTN_GREEN_HV)
            else:
                next_btn.configure(text="Siguiente →",
                                   fg_color=BTN_BLUE, hover_color=BTN_BLUE_HV)

        def go_next():
            if step[0] == N - 1:
                close_wizard()
            else:
                step[0] += 1
                render(step[0])

        def go_prev():
            if step[0] > 0:
                step[0] -= 1
                render(step[0])

        def close_wizard():
            cfg = self._load_settings()
            cfg["first_run"] = False
            self._write_settings(cfg)
            dlg.destroy()

        next_btn.configure(command=go_next)
        prev_btn.configure(command=go_prev)
        dlg.protocol("WM_DELETE_WINDOW", close_wizard)
        render(0)

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load_settings(self) -> dict:
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "watch_folder":       str(Path.home() / "Downloads"),
            "output_folder":      str(Path.home() / "Documents" / "Organizado"),
            "delay":              "3",
            "organize_existing":          True,
            "organize_existing_folders":  False,
            "active_profile":     "default",
            "exclusion_patterns": [],
            "schedule_enabled":   False,
            "schedule_hour":      22,
            "schedule_minute":    0,
            "schedule_days":      list(range(7)),
            "first_run":          True,
        }

    def _save_settings(self):
        cfg = self._load_settings()
        cfg.update({
            "watch_folder":               self.watch_entry.get(),
            "output_folder":              self.output_entry.get(),
            "delay":                      self.delay_entry.get(),
            "organize_existing":          self.existing_var.get(),
            "organize_existing_folders":  self.existing_folders_var.get(),
        })
        self._write_settings(cfg)

    def _write_settings(self, data: dict):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # ── Actualizaciones ───────────────────────────────────────────────────────

    def _check_for_updates(self):
        result = get_latest_release()
        if result and is_newer(result[0]):
            self.after(0, self._show_update_dialog, result[0], result[1])

    def _show_update_dialog(self, tag: str, url: str):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Actualización disponible")
        dialog.geometry("420x200")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.lift()
        ctk.CTkLabel(dialog, text=f"Nueva versión disponible: {tag}",
                     font=("Segoe UI", 15, "bold")).pack(pady=(24, 6))
        ctk.CTkLabel(
            dialog,
            text="El programa se cerrará, se actualizará\ny se volverá a abrir.",
            font=("Segoe UI", 12), text_color=MUTED).pack(pady=(0, 20))
        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.pack()
        ctk.CTkButton(row, text="Actualizar ahora", width=150,
                      fg_color=BTN_BLUE, hover_color=BTN_BLUE_HV,
                      command=lambda: self._do_update(dialog, url)).pack(
            side="left", padx=8)
        ctk.CTkButton(row, text="Ahora no", width=110,
                      fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV,
                      command=dialog.destroy).pack(side="left", padx=8)

    def _do_update(self, dialog, url: str):
        dialog.destroy()
        self._append_log("Descargando actualización...")
        def run():
            ok = download_and_apply(
                url, on_progress=lambda p: self._append_log(
                    f"  Descargando... {int(p * 100)}%"))
            if ok:
                self._append_log("Descarga completa. Cerrando para aplicar...")
                self.after(1500, self._do_quit)
            else:
                self._append_log("Error al descargar. Intentá de nuevo más tarde.")
        threading.Thread(target=run, daemon=True).start()

    # ── System Tray ───────────────────────────────────────────────────────────

    def _setup_tray(self):
        image = _create_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("Mostrar ventana", self._show_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", self._quit_app),
        )
        self._tray = pystray.Icon("FileOrganizer", image, "File Organizer", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _hide_to_tray(self):
        self.withdraw()

    def _show_window(self, icon=None, item=None):
        self.after(0, self.deiconify)
        self.after(0, self.lift)
        self.after(0, self.focus_force)

    def _quit_app(self, icon=None, item=None):
        if self._tray:
            self._tray.stop()
        self.after(0, self._do_quit)

    def _do_quit(self):
        if self.running:
            self._stop()
        self.destroy()

    # ── Autostart ─────────────────────────────────────────────────────────────

    def _is_autostart_enabled(self) -> bool:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY)
            winreg.QueryValueEx(key, REGISTRY_NAME)
            winreg.CloseKey(key)
            return True
        except (FileNotFoundError, OSError):
            return False

    def _toggle_autostart(self):
        enable = self.autostart_var.get()
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0,
                                 winreg.KEY_SET_VALUE)
            if enable:
                cmd = (f'"{sys.executable}"' if getattr(sys, "frozen", False)
                       else f'"{sys.executable}" '
                            f'"{Path(__file__).parent.parent.parent / "main_gui.py"}"')
                winreg.SetValueEx(key, REGISTRY_NAME, 0, winreg.REG_SZ, cmd)
                self._append_log("Arranque con Windows activado.")
            else:
                try:
                    winreg.DeleteValue(key, REGISTRY_NAME)
                except FileNotFoundError:
                    pass
                self._append_log("Arranque con Windows desactivado.")
            winreg.CloseKey(key)
        except Exception as e:
            self._append_log(f"Error al configurar arranque: {e}")
            self.autostart_var.set(not enable)

    # ── Notificaciones ────────────────────────────────────────────────────────

    def _notify(self, filename: str, destination: str):
        def _do():
            try:
                notification.notify(
                    title="File Organizer",
                    message=f"{filename}\n→ {Path(destination).name}",
                    app_name="File Organizer", timeout=4)
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _attach_logger(self):
        self._log_handler = _GUILogHandler(self._append_log)
        logging.getLogger("FileOrganizer").addHandler(self._log_handler)

    def _browse_watch(self):
        folder = filedialog.askdirectory(title="Selecciona la carpeta a monitorear")
        if folder:
            self.watch_entry.delete(0, "end")
            self.watch_entry.insert(0, folder)

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Selecciona la carpeta de destino")
        if folder:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, folder)

    def _toggle(self):
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        watch_folder  = Path(self.watch_entry.get().strip())
        output_folder = self.output_entry.get().strip()
        delay_str     = self.delay_entry.get().strip()
        if not watch_folder.exists():
            self._append_log("ERROR: La carpeta a monitorear no existe.")
            return
        if not output_folder:
            self._append_log("ERROR: Especifica una carpeta de destino.")
            return
        delay = int(delay_str) if delay_str.isdigit() else 3
        self._save_settings()
        cfg = self._load_settings()
        self.organizer = FileOrganizer(
            str(_get_rules_path(cfg.get("active_profile", "default"))),
            output_folder, move_delay=delay,
            on_file_moved=self._notify,
            exclusion_patterns=cfg.get("exclusion_patterns", []))
        if self.existing_var.get():
            threading.Thread(
                target=self.organizer.organize_existing,
                args=(watch_folder,), daemon=True).start()
        if self.existing_folders_var.get():
            threading.Thread(
                target=self._organize_existing_folders,
                args=(watch_folder,), daemon=True).start()
        handler = OrganizeHandler(self.organizer, watch_folder,
                                  on_folder_detected=self._on_folder_detected)
        self.observer = Observer()
        self.observer.schedule(handler, str(watch_folder), recursive=False)
        self.observer.start()
        self.running = True
        self.start_btn.configure(
            text="■   Detener", fg_color=BTN_RED, hover_color=BTN_RED_HV)
        self.status_label.configure(text="⬤  Activo", text_color=GREEN)
        self._poll_stats()

    def _stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        self.running = False
        self.start_btn.configure(
            text="▶   Iniciar", fg_color=BTN_BLUE, hover_color=BTN_BLUE_HV)
        self.status_label.configure(text="⬤  Detenido", text_color=RED)
        if self.organizer:
            s = self.organizer.stats
            self._append_log(
                f"Sesión — Movidos: {s['movidos']} | "
                f"Saltados: {s['saltados']} | Errores: {s['errores']}")

    def _undo(self):
        if not self.organizer:
            self._append_log("Inicia el organizador primero.")
            return
        if not self.organizer.move_history:
            self._append_log("No hay movimientos para deshacer.")
            return
        self.organizer.undo_last()

    def _dry_run(self):
        watch_folder = Path(self.watch_entry.get().strip())
        output_folder = self.output_entry.get().strip()
        if not watch_folder.exists():
            self._append_log("ERROR: La carpeta a monitorear no existe.")
            return
        if not output_folder:
            self._append_log("ERROR: Especifica una carpeta de destino.")
            return
        cfg = self._load_settings()
        organizer = FileOrganizer(
            str(_get_rules_path(cfg.get("active_profile", "default"))),
            output_folder, move_delay=0,
            exclusion_patterns=cfg.get("exclusion_patterns", []))
        temp_exts = {".tmp", ".crdownload", ".part", ".download"}
        results, skipped = [], []
        try:
            files = [f for f in watch_folder.iterdir() if f.is_file()]
        except PermissionError:
            self._append_log("ERROR: Sin permiso para leer la carpeta.")
            return
        for f in files:
            if f.suffix.lower() in temp_exts:
                skipped.append(f.name)
                continue
            excluded = any(
                fnmatch.fnmatch(f.name.lower(), pat.lower())
                for pat in organizer.exclusion_patterns)
            if excluded:
                skipped.append(f.name)
                continue
            dest = organizer.classify(f)
            results.append((f.name, dest))
        self._show_dryrun_dialog(results, skipped, output_folder)

    def _show_dryrun_dialog(self, results: list, skipped: list, output_folder: str):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Vista previa")
        dlg.geometry("640x520")
        dlg.resizable(False, False)
        dlg.configure(fg_color="#080f1a")
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()

        hdr = ctk.CTkFrame(dlg, fg_color="#0d1829", corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🔍  Vista previa — sin mover nada",
                     font=("Segoe UI", 13, "bold"), text_color="#60a5fa").pack(
            side="left", padx=20, pady=14)
        ctk.CTkFrame(dlg, fg_color="#1d4ed8", height=2, corner_radius=0).pack(fill="x")

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=12)

        if not results:
            ctk.CTkLabel(body, text="No hay archivos para organizar en esta carpeta.",
                         font=("Segoe UI", 13), text_color=MUTED).pack(pady=40)
        else:
            n = len(results)
            ctk.CTkLabel(
                body,
                text=f"{n} archivo{'s' if n != 1 else ''} "
                     f"{'serían' if n != 1 else 'sería'} organizado{'s' if n != 1 else ''}:",
                font=("Segoe UI", 12, "bold"), text_color="white",
                anchor="w").pack(anchor="w", pady=(0, 6))

            col_hdr = ctk.CTkFrame(body, fg_color="#0f172a", corner_radius=6)
            col_hdr.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(col_hdr, text="Archivo", font=("Segoe UI", 11, "bold"),
                         text_color=MUTED, width=230, anchor="w").pack(
                side="left", padx=10, pady=6)
            ctk.CTkLabel(col_hdr, text="Destino (relativo)", font=("Segoe UI", 11, "bold"),
                         text_color=MUTED, anchor="w").pack(side="left", padx=4)

            scroll = ctk.CTkScrollableFrame(body, corner_radius=8, fg_color="#0a1120")
            scroll.pack(fill="both", expand=True)

            out_path = Path(output_folder)
            for fn, dest in results:
                row = ctk.CTkFrame(scroll, fg_color="#141e2e", corner_radius=6)
                row.pack(fill="x", pady=2, padx=2)
                fn_short = (fn[:28] + "…") if len(fn) > 28 else fn
                ctk.CTkLabel(row, text=fn_short, font=("Segoe UI", 11),
                             width=230, anchor="w").pack(side="left", padx=(8, 4), pady=5)
                try:
                    rel = dest.relative_to(out_path)
                    dst_display = str(rel)
                except ValueError:
                    dst_display = dest.name
                ctk.CTkLabel(row, text=f"→ {dst_display}", font=("Segoe UI", 10),
                             text_color=AMBER, anchor="w").pack(side="left", padx=4)

        if skipped:
            ctk.CTkLabel(body,
                         text=f"Omitidos (temporales/excluidos): {len(skipped)}",
                         font=("Segoe UI", 10), text_color="#475569").pack(
                anchor="w", pady=(6, 0))

        footer = ctk.CTkFrame(dlg, fg_color="#0d1829", corner_radius=0)
        footer.pack(fill="x", side="bottom")
        ctk.CTkButton(footer, text="Cerrar", width=100, height=36,
                      fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV,
                      command=dlg.destroy).pack(side="right", padx=20, pady=12)
        if results:
            def _do_start():
                dlg.destroy()
                if not self.running:
                    self._start()
            ctk.CTkButton(footer, text="▶  Iniciar ahora", width=145, height=36,
                          fg_color=BTN_BLUE, hover_color=BTN_BLUE_HV,
                          command=_do_start).pack(side="right", padx=(0, 8), pady=12)

    def _poll_stats(self):
        if self.running and self.organizer:
            s = self.organizer.stats
            self.stats_label.configure(
                text=f"Movidos: {s['movidos']}   |   "
                     f"Saltados: {s['saltados']}   |   Errores: {s['errores']}")
            self.after(500, self._poll_stats)

    def _organize_existing_folders(self, watch_folder: Path):
        folders = [d for d in watch_folder.iterdir() if d.is_dir()]
        if not folders:
            return
        self._append_log(f"Organizando {len(folders)} carpeta(s) existente(s)...")
        for folder in folders:
            if self.organizer:
                self.organizer.organize_folder(folder)

    def _on_folder_detected(self, folder: Path, count: int):
        self.after(0, self._show_folder_confirm_dialog, folder, count)

    def _show_folder_confirm_dialog(self, folder: Path, count: int):
        if not self.organizer:
            return
        dlg = ctk.CTkToplevel(self)
        dlg.title("Carpeta detectada")
        dlg.geometry("480x310")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()

        hdr = ctk.CTkFrame(dlg, fg_color="#080f1a", corner_radius=0, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="📁", font=("Segoe UI", 22)).pack(
            side="left", padx=(20, 8), pady=12)
        title_col = ctk.CTkFrame(hdr, fg_color="transparent")
        title_col.pack(side="left", anchor="center")
        ctk.CTkLabel(title_col, text="Carpeta detectada",
                     font=("Segoe UI", 14, "bold"), text_color="white").pack(anchor="w")
        ctk.CTkLabel(title_col, text="en el directorio vigilado",
                     font=("Segoe UI", 10), text_color="#3b4f6a").pack(anchor="w")
        ctk.CTkFrame(dlg, fg_color="#1d4ed8", height=2, corner_radius=0).pack(fill="x")

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=16)

        name_box = ctk.CTkFrame(body, fg_color="#0a1120", corner_radius=8,
                                border_width=1, border_color="#1e3a5f")
        name_box.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(name_box, text=f"  {folder.name}",
                     font=("Consolas", 13, "bold"), anchor="w",
                     text_color="#60a5fa").pack(anchor="w", padx=12, pady=10)

        ctk.CTkLabel(body,
                     text=f"Contiene {count} archivo{'s' if count != 1 else ''} "
                          f"que pueden ser organizados.",
                     font=("Segoe UI", 12), text_color="white", anchor="w").pack(anchor="w")
        ctk.CTkLabel(body,
                     text="⚠  Los archivos se moverán fuera de esta carpeta a sus destinos.",
                     font=("Segoe UI", 11), text_color=AMBER, anchor="w").pack(
            anchor="w", pady=(8, 0))

        btn_row = ctk.CTkFrame(dlg, fg_color="#080f1a", corner_radius=0)
        btn_row.pack(fill="x", side="bottom")
        ctk.CTkButton(btn_row, text="✓  Organizar ahora",
                      fg_color=BTN_BLUE, hover_color=BTN_BLUE_HV,
                      width=180, height=40, font=("Segoe UI", 13, "bold"),
                      command=lambda: self._confirm_organize_folder(folder, dlg)).pack(
            side="left", padx=(20, 8), pady=14)
        ctk.CTkButton(btn_row, text="Ignorar",
                      fg_color=BTN_GRAY, hover_color=BTN_GRAY_HV,
                      width=100, height=40,
                      command=dlg.destroy).pack(side="left", pady=14)

    def _confirm_organize_folder(self, folder: Path, dlg):
        dlg.destroy()
        if not self.organizer:
            return
        self._append_log(f"[Carpeta] Organizando '{folder.name}'...")
        threading.Thread(
            target=self.organizer.organize_folder, args=(folder,), daemon=True).start()

    def _append_log(self, msg: str):
        self.log_box.after(0, self._do_append, msg)

    def _do_append(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
