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
from fileorganizer.updater import VERSION, download_and_apply, get_latest_release, is_newer
from fileorganizer.watcher import OrganizeHandler

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SETTINGS_FILE = Path.home() / ".file_organizer_settings.json"
REGISTRY_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_NAME = "FileOrganizer"

# ── Palette ───────────────────────────────────────────────────────────────────
BG_MAIN     = "#0d0f17"
BG_HEADER   = "#090b12"
BG_CARD     = "#141726"
BG_DEEP     = "#0f1120"
ACCENT      = "#6366f1"
ACCENT_HV   = "#4f46e5"
SUCCESS     = "#10b981"
SUCCESS_HV  = "#059669"
DANGER      = "#f43f5e"
DANGER_HV   = "#e11d48"
TEXT_MAIN   = "#f1f5f9"
TEXT_DIM    = "#94a3b8"
TEXT_MUTED  = "#475569"
BORDER      = "#1e2235"
BORDER_B    = "#2a2f4a"
LOG_TEXT    = "#c4ccf0"

BTN_START    = (SUCCESS, SUCCESS)
BTN_START_HV = (SUCCESS_HV, SUCCESS_HV)
BTN_STOP     = (DANGER, DANGER)
BTN_STOP_HV  = (DANGER_HV, DANGER_HV)
BTN_ACCENT   = (ACCENT, ACCENT)
BTN_ACCENT_HV= (ACCENT_HV, ACCENT_HV)
BTN_GHOST    = ("#1c2033", "#1c2033")
BTN_GHOST_HV = ("#252840", "#252840")


def _config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "config" / "rules.yaml"
    return Path(__file__).parent.parent.parent / "config" / "rules.yaml"


def _create_tray_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 62, 62], radius=13, fill="#4f46e5")
    d.rounded_rectangle([11, 16, 31, 24], radius=3, fill="white")   # tab
    d.rounded_rectangle([11, 21, 53, 47], radius=4, fill="white")   # body
    for i, xr in enumerate([42, 30, 40]):
        ly = 29 + i * 7
        d.rectangle([19, ly, xr, ly + 3], fill="#4338ca")           # sort lines
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
        self.geometry("720x760")
        self.resizable(False, False)
        self.configure(fg_color=BG_MAIN)

        self.observer: Observer | None = None
        self.organizer: FileOrganizer | None = None
        self.running = False
        self._log_handler: _GUILogHandler | None = None
        self._tray_icon: pystray.Icon | None = None

        self._build_ui()
        self._attach_logger()
        self._setup_tray()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.after(2500, lambda: threading.Thread(
            target=self._check_for_updates, daemon=True
        ).start())

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

        # Header ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)

        hL = ctk.CTkFrame(header, fg_color="transparent")
        hL.pack(side="left", padx=22, pady=(10, 8))

        title_row = ctk.CTkFrame(hL, fg_color="transparent")
        title_row.pack(anchor="w")
        ctk.CTkLabel(
            title_row, text="📂",
            font=("Segoe UI Emoji", 20), text_color="white",
        ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            title_row, text="File Organizer",
            font=("Segoe UI", 20, "bold"), text_color=TEXT_MAIN,
        ).pack(side="left")
        ver_bg = ctk.CTkFrame(title_row, fg_color=BORDER_B, corner_radius=8)
        ver_bg.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            ver_bg, text=f"v{VERSION}",
            font=("Segoe UI", 9), text_color=TEXT_DIM,
        ).pack(padx=7, pady=2)

        ctk.CTkLabel(
            hL, text="© 2026 Cano SAS Dev",
            font=("Segoe UI", 9), text_color=TEXT_MUTED,
        ).pack(anchor="w")

        hR = ctk.CTkFrame(header, fg_color="transparent")
        hR.pack(side="right", padx=22)
        self.status_label = ctk.CTkLabel(
            hR, text="● Detenido",
            font=("Segoe UI", 12, "bold"), text_color=DANGER,
        )
        self.status_label.pack()

        # Body ──────────────────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color=BG_MAIN)
        body.pack(fill="both", expand=True, padx=18, pady=(14, 0))

        ctk.CTkLabel(
            body, text="CONFIGURACIÓN",
            font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(0, 6))

        # Config card
        card = ctk.CTkFrame(
            body, fg_color=BG_CARD, corner_radius=12,
            border_width=1, border_color=BORDER,
        )
        card.pack(fill="x", pady=(0, 10))
        card.columnconfigure(0, weight=1)

        _rows = [
            ("Carpeta a monitorear", "watch_entry",  "watch_folder",
             "Ej: C:/Users/TuUsuario/Downloads",            self._browse_watch),
            ("Carpeta de destino",   "output_entry", "output_folder",
             "Ej: C:/Users/TuUsuario/Documents/Organizado", self._browse_output),
        ]
        for ri, (label, attr, cfg_key, ph, cmd) in enumerate(_rows):
            top_pad = 14 if ri == 0 else 6
            ctk.CTkLabel(
                card, text=label,
                font=("Segoe UI", 11, "bold"), text_color=TEXT_DIM,
            ).grid(row=ri * 2, column=0, columnspan=2, sticky="w",
                   padx=16, pady=(top_pad, 3))
            entry = ctk.CTkEntry(
                card, height=36, corner_radius=8,
                fg_color=BG_DEEP, border_color=BORDER_B, border_width=1,
                placeholder_text=ph, text_color=TEXT_MAIN,
            )
            entry.grid(row=ri * 2 + 1, column=0, sticky="ew",
                       padx=(16, 8), pady=(0, 4))
            entry.insert(0, cfg.get(cfg_key, ""))
            setattr(self, attr, entry)
            ctk.CTkButton(
                card, text="Buscar", width=84, height=36, corner_radius=8,
                fg_color=BTN_GHOST, hover_color=BTN_GHOST_HV, text_color=TEXT_DIM,
                command=cmd,
            ).grid(row=ri * 2 + 1, column=1, padx=(0, 16), pady=(0, 4))

        # Separator
        ctk.CTkFrame(card, fg_color=BORDER, height=1).grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=16, pady=(8, 0),
        )

        # Options row 1: delay + organize existing
        opts1 = ctk.CTkFrame(card, fg_color="transparent")
        opts1.grid(row=5, column=0, columnspan=2, sticky="w", padx=16, pady=(10, 4))
        ctk.CTkLabel(opts1, text="Delay:", text_color=TEXT_DIM,
                     font=("Segoe UI", 11)).pack(side="left")
        self.delay_entry = ctk.CTkEntry(
            opts1, width=44, height=30, corner_radius=6,
            fg_color=BG_DEEP, border_color=BORDER_B, border_width=1,
            text_color=TEXT_MAIN,
        )
        self.delay_entry.pack(side="left", padx=(6, 4))
        self.delay_entry.insert(0, cfg.get("delay", "3"))
        ctk.CTkLabel(opts1, text="seg", text_color=TEXT_MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=(0, 22))
        self.existing_var = ctk.BooleanVar(value=cfg.get("organize_existing", True))
        ctk.CTkCheckBox(
            opts1, text="Organizar archivos existentes",
            variable=self.existing_var, font=("Segoe UI", 11),
            text_color=TEXT_DIM, checkmark_color="white",
            fg_color=ACCENT, hover_color=ACCENT_HV, border_color=BORDER_B,
        ).pack(side="left")

        # Options row 2: autostart
        opts2 = ctk.CTkFrame(card, fg_color="transparent")
        opts2.grid(row=6, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 14))
        self.autostart_var = ctk.BooleanVar(value=self._is_autostart_enabled())
        ctk.CTkCheckBox(
            opts2, text="Iniciar con Windows",
            variable=self.autostart_var, command=self._toggle_autostart,
            font=("Segoe UI", 11), text_color=TEXT_DIM,
            fg_color=ACCENT, hover_color=ACCENT_HV, border_color=BORDER_B,
        ).pack(side="left")

        # Button row
        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 10))
        btn_row.columnconfigure(0, weight=1)

        self.start_btn = ctk.CTkButton(
            btn_row, text="▶   Iniciar organizador",
            font=("Segoe UI", 14, "bold"), height=46, corner_radius=10,
            fg_color=BTN_START, hover_color=BTN_START_HV,
            command=self._toggle,
        )
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.undo_btn = ctk.CTkButton(
            btn_row, text="↩  Deshacer",
            font=("Segoe UI", 12), height=46, width=130, corner_radius=10,
            fg_color=BTN_GHOST, hover_color=BTN_GHOST_HV, text_color=TEXT_DIM,
            command=self._undo,
        )
        self.undo_btn.grid(row=0, column=1)

        # Activity log
        ctk.CTkLabel(
            body, text="ACTIVIDAD",
            font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 6))

        log_card = ctk.CTkFrame(
            body, fg_color=BG_DEEP, corner_radius=12,
            border_width=1, border_color=BORDER,
        )
        log_card.pack(fill="both", expand=True, pady=(0, 8))

        self.log_box = ctk.CTkTextbox(
            log_card, font=("Consolas", 11), state="disabled",
            corner_radius=0, fg_color=BG_DEEP, text_color=LOG_TEXT,
        )
        self.log_box.pack(fill="both", expand=True, padx=2, pady=2)

        # Stats + footer
        self.stats_label = ctk.CTkLabel(
            body,
            text="Movidos: 0   |   Saltados: 0   |   Errores: 0",
            font=("Segoe UI", 11), text_color=TEXT_MUTED,
        )
        self.stats_label.pack(pady=(0, 4))
        ctk.CTkLabel(
            body,
            text="Cerrar ventana minimiza al área de notificaciones",
            font=("Segoe UI", 9), text_color=TEXT_MUTED,
        ).pack(pady=(0, 10))

    def _attach_logger(self):
        self._log_handler = _GUILogHandler(self._append_log)
        logging.getLogger("FileOrganizer").addHandler(self._log_handler)

    # ── Actualizaciones ───────────────────────────────────────────────────────

    def _check_for_updates(self):
        result = get_latest_release()
        if result and is_newer(result[0]):
            tag, url = result
            self.after(0, self._show_update_dialog, tag, url)

    def _show_update_dialog(self, tag: str, url: str):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Actualización disponible")
        dialog.geometry("440x200")
        dialog.resizable(False, False)
        dialog.configure(fg_color=BG_CARD)
        dialog.grab_set()
        dialog.lift()

        ctk.CTkLabel(
            dialog, text=f"🚀  Nueva versión: {tag}",
            font=("Segoe UI", 15, "bold"), text_color=TEXT_MAIN,
        ).pack(pady=(24, 6))
        ctk.CTkLabel(
            dialog,
            text="La app se cerrará, se actualizará y se volverá a abrir.",
            font=("Segoe UI", 12), text_color=TEXT_DIM,
        ).pack(pady=(0, 20))

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack()
        ctk.CTkButton(
            btn_row, text="Actualizar ahora", width=150, corner_radius=8,
            fg_color=BTN_ACCENT, hover_color=BTN_ACCENT_HV,
            command=lambda: self._do_update(dialog, url),
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            btn_row, text="Ahora no", width=110, corner_radius=8,
            fg_color=BTN_GHOST, hover_color=BTN_GHOST_HV, text_color=TEXT_DIM,
            command=dialog.destroy,
        ).pack(side="left", padx=8)

    def _do_update(self, dialog: ctk.CTkToplevel, url: str):
        dialog.destroy()
        self._append_log("Descargando actualización...")

        def run():
            def progress(pct):
                self._append_log(f"  Descargando... {int(pct * 100)}%")
            ok = download_and_apply(url, on_progress=progress)
            if ok:
                self._append_log("Descarga completa. Cerrando para aplicar actualización...")
                self.after(1500, self._do_quit)
            else:
                self._append_log("Error al descargar. Intentá de nuevo más tarde.")

        threading.Thread(target=run, daemon=True).start()

    # ── System Tray ───────────────────────────────────────────────────────────

    def _setup_tray(self):
        image = _create_tray_icon()
        menu  = pystray.Menu(
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
        self.start_btn.configure(
            text="■   Detener organizador",
            fg_color=BTN_STOP, hover_color=BTN_STOP_HV,
        )
        self.status_label.configure(text="● Activo", text_color=SUCCESS)
        self._poll_stats()

    def _stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        self.running = False
        self.start_btn.configure(
            text="▶   Iniciar organizador",
            fg_color=BTN_START, hover_color=BTN_START_HV,
        )
        self.status_label.configure(text="● Detenido", text_color=DANGER)
        if self.organizer:
            s = self.organizer.stats
            self._append_log(
                f"Sesión terminada — Movidos: {s['movidos']} | "
                f"Saltados: {s['saltados']} | Errores: {s['errores']}"
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
