import json
import logging
import sys
import threading
import winreg
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw
from plyer import notification
from watchdog.observers import Observer

from fileorganizer.organizer import FileOrganizer
from fileorganizer.watcher import OrganizeHandler

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SETTINGS_FILE = Path.home() / ".file_organizer_settings.json"
REGISTRY_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_NAME = "FileOrganizer"

GREEN          = "#22c55e"
RED            = "#ef4444"
MUTED          = "#94a3b8"
BTN_RED        = ("#dc2626", "#dc2626")
BTN_RED_HOVER  = ("#b91c1c", "#b91c1c")
BTN_BLUE       = ("#2563eb", "#2563eb")
BTN_BLUE_HOVER = ("#1d4ed8", "#1d4ed8")
BTN_GRAY       = ("#475569", "#475569")
BTN_GRAY_HOVER = ("#334155", "#334155")


def _config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "config" / "rules.yaml"
    return Path(__file__).parent.parent.parent / "config" / "rules.yaml"


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
        self.geometry("700x720")
        self.resizable(False, False)

        self.observer: Observer | None = None
        self.organizer: FileOrganizer | None = None
        self.running = False
        self._log_handler: _GUILogHandler | None = None
        self._tray_icon: pystray.Icon | None = None

        self._build_ui()
        self._attach_logger()
        self._setup_tray()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load_settings(self) -> dict:
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "watch_folder":      str(Path.home() / "Downloads"),
            "output_folder":     str(Path.home() / "Documents" / "Organizado"),
            "delay":             "3",
            "organize_existing": True,
        }

    def _save_settings(self):
        data = {
            "watch_folder":      self.watch_entry.get(),
            "output_folder":     self.output_entry.get(),
            "delay":             self.delay_entry.get(),
            "organize_existing": self.existing_var.get(),
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        cfg = self._load_settings()

        # Header
        header = ctk.CTkFrame(self, fg_color="#0f172a", corner_radius=0)
        header.pack(fill="x")
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left", padx=24, pady=12)
        ctk.CTkLabel(
            title_frame, text="File Organizer",
            font=("Segoe UI", 22, "bold"), text_color="white",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_frame, text="© 2026 Cano SAS Dev",
            font=("Segoe UI", 10), text_color="#64748b",
        ).pack(anchor="w")
        self.status_label = ctk.CTkLabel(
            header, text="● Detenido",
            font=("Segoe UI", 12), text_color=RED,
        )
        self.status_label.pack(side="right", padx=24)

        # Settings card
        card = ctk.CTkFrame(self, corner_radius=10)
        card.pack(fill="x", padx=20, pady=(16, 8))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text="Carpeta a monitorear", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 2),
        )
        self.watch_entry = ctk.CTkEntry(card, height=34, placeholder_text="Ej: C:/Users/TuUsuario/Downloads")
        self.watch_entry.grid(row=1, column=0, sticky="ew", padx=(16, 8), pady=(0, 10))
        self.watch_entry.insert(0, cfg.get("watch_folder", ""))
        ctk.CTkButton(card, text="Buscar", width=88, height=34, command=self._browse_watch).grid(
            row=1, column=1, padx=(0, 16), pady=(0, 10),
        )

        ctk.CTkLabel(card, text="Carpeta de destino", font=("Segoe UI", 12, "bold")).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 2),
        )
        self.output_entry = ctk.CTkEntry(card, height=34, placeholder_text="Ej: C:/Users/TuUsuario/Documents/Organizado")
        self.output_entry.grid(row=3, column=0, sticky="ew", padx=(16, 8), pady=(0, 10))
        self.output_entry.insert(0, cfg.get("output_folder", ""))
        ctk.CTkButton(card, text="Buscar", width=88, height=34, command=self._browse_output).grid(
            row=3, column=1, padx=(0, 16), pady=(0, 10),
        )

        # Fila de opciones 1: delay + organizar existentes
        opts1 = ctk.CTkFrame(card, fg_color="transparent")
        opts1.grid(row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 6))
        ctk.CTkLabel(opts1, text="Delay antes de mover:").pack(side="left")
        self.delay_entry = ctk.CTkEntry(opts1, width=44, height=30)
        self.delay_entry.pack(side="left", padx=(6, 4))
        self.delay_entry.insert(0, cfg.get("delay", "3"))
        ctk.CTkLabel(opts1, text="seg", text_color=MUTED).pack(side="left", padx=(0, 20))
        self.existing_var = ctk.BooleanVar(value=cfg.get("organize_existing", True))
        ctk.CTkCheckBox(opts1, text="Organizar archivos existentes al iniciar", variable=self.existing_var).pack(side="left")

        # Fila de opciones 2: iniciar con Windows
        opts2 = ctk.CTkFrame(card, fg_color="transparent")
        opts2.grid(row=5, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 14))
        self.autostart_var = ctk.BooleanVar(value=self._is_autostart_enabled())
        ctk.CTkCheckBox(
            opts2, text="Iniciar con Windows",
            variable=self.autostart_var,
            command=self._toggle_autostart,
        ).pack(side="left")

        # Fila de botones: Iniciar/Detener + Deshacer
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 10))
        btn_row.columnconfigure(0, weight=1)

        self.start_btn = ctk.CTkButton(
            btn_row, text="▶   Iniciar",
            font=("Segoe UI", 14, "bold"), height=44, corner_radius=8,
            fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER,
            command=self._toggle,
        )
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.undo_btn = ctk.CTkButton(
            btn_row, text="↩  Deshacer",
            font=("Segoe UI", 13), height=44, width=140, corner_radius=8,
            fg_color=BTN_GRAY, hover_color=BTN_GRAY_HOVER,
            command=self._undo,
        )
        self.undo_btn.grid(row=0, column=1)

        # Log
        log_card = ctk.CTkFrame(self, corner_radius=10)
        log_card.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        ctk.CTkLabel(log_card, text="Actividad en tiempo real", font=("Segoe UI", 12, "bold")).pack(
            anchor="w", padx=14, pady=(10, 4),
        )
        self.log_box = ctk.CTkTextbox(log_card, font=("Consolas", 11), state="disabled", corner_radius=6)
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Stats + mensaje de bandeja
        self.stats_label = ctk.CTkLabel(
            self, text="Movidos: 0   |   Saltados: 0   |   Errores: 0",
            font=("Segoe UI", 11), text_color=MUTED,
        )
        self.stats_label.pack()
        ctk.CTkLabel(
            self, text="Cerrar ventana minimiza al área de notificaciones",
            font=("Segoe UI", 10), text_color=MUTED,
        ).pack(pady=(2, 10))

    def _attach_logger(self):
        self._log_handler = _GUILogHandler(self._append_log)
        logging.getLogger("FileOrganizer").addHandler(self._log_handler)

    # ── System Tray ───────────────────────────────────────────────────────────

    def _setup_tray(self):
        image = _create_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("Mostrar ventana", self._show_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", self._quit_app),
        )
        self._tray_icon = pystray.Icon("FileOrganizer", image, "File Organizer", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _hide_to_tray(self):
        self.withdraw()

    def _show_window(self, icon=None, item=None):
        self.after(0, self.deiconify)
        self.after(0, self.lift)
        self.after(0, self.focus_force)

    def _quit_app(self, icon=None, item=None):
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self._do_quit)

    def _do_quit(self):
        if self.running:
            self._stop()
        self.destroy()

    # ── Arranque con Windows ──────────────────────────────────────────────────

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
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_SET_VALUE)
            if enable:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    script = str(Path(__file__).parent.parent.parent / "main_gui.py")
                    cmd = f'"{sys.executable}" "{script}"'
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
                    app_name="File Organizer",
                    timeout=4,
                )
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    # ── Acciones ──────────────────────────────────────────────────────────────

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
        watch_folder = Path(self.watch_entry.get().strip())
        output_folder = self.output_entry.get().strip()
        delay_str = self.delay_entry.get().strip()

        if not watch_folder.exists():
            self._append_log("ERROR: La carpeta a monitorear no existe.")
            return
        if not output_folder:
            self._append_log("ERROR: Especifica una carpeta de destino.")
            return

        delay = int(delay_str) if delay_str.isdigit() else 3
        self._save_settings()

        self.organizer = FileOrganizer(
            str(_config_path()), output_folder, move_delay=delay,
            on_file_moved=self._notify,
        )

        if self.existing_var.get():
            threading.Thread(
                target=self.organizer.organize_existing, args=(watch_folder,), daemon=True
            ).start()

        handler = OrganizeHandler(self.organizer, watch_folder)
        self.observer = Observer()
        self.observer.schedule(handler, str(watch_folder), recursive=False)
        self.observer.start()

        self.running = True
        self.start_btn.configure(text="■   Detener", fg_color=BTN_RED, hover_color=BTN_RED_HOVER)
        self.status_label.configure(text="● Activo", text_color=GREEN)
        self._poll_stats()

    def _stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        self.running = False
        self.start_btn.configure(text="▶   Iniciar", fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER)
        self.status_label.configure(text="● Detenido", text_color=RED)
        if self.organizer:
            s = self.organizer.stats
            self._append_log(
                f"Sesión terminada — Movidos: {s['movidos']} | Saltados: {s['saltados']} | Errores: {s['errores']}"
            )

    def _undo(self):
        if not self.organizer:
            self._append_log("Iniciá el organizador primero para poder deshacer movimientos.")
            return
        if not self.organizer.move_history:
            self._append_log("No hay movimientos recientes para deshacer.")
            return
        self.organizer.undo_last()

    def _poll_stats(self):
        if self.running and self.organizer:
            s = self.organizer.stats
            self.stats_label.configure(
                text=f"Movidos: {s['movidos']}   |   Saltados: {s['saltados']}   |   Errores: {s['errores']}"
            )
            self.after(500, self._poll_stats)

    def _append_log(self, msg: str):
        self.log_box.after(0, self._do_append, msg)

    def _do_append(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
