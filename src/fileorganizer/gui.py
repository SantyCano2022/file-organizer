import json
import logging
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from watchdog.observers import Observer

from fileorganizer.organizer import FileOrganizer
from fileorganizer.watcher import OrganizeHandler

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SETTINGS_FILE = Path.home() / ".file_organizer_settings.json"

GREEN  = "#22c55e"
RED    = "#ef4444"
MUTED  = "#94a3b8"
BTN_RED       = ("#dc2626", "#dc2626")
BTN_RED_HOVER = ("#b91c1c", "#b91c1c")
BTN_BLUE      = ("#2563eb", "#2563eb")
BTN_BLUE_HOVER= ("#1d4ed8", "#1d4ed8")


def _config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "config" / "rules.yaml"
    return Path(__file__).parent.parent.parent / "config" / "rules.yaml"


class _GUILogHandler(logging.Handler):
    """Redirige mensajes del logger al textbox de la GUI."""
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
        self.geometry("700x590")
        self.resizable(False, False)

        self.observer: Observer | None = None
        self.organizer: FileOrganizer | None = None
        self.running = False
        self._log_handler: _GUILogHandler | None = None

        self._build_ui()
        self._attach_logger()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        ctk.CTkLabel(
            header, text="File Organizer",
            font=("Segoe UI", 22, "bold"), text_color="white",
        ).pack(side="left", padx=24, pady=16)
        self.status_label = ctk.CTkLabel(
            header, text="● Detenido",
            font=("Segoe UI", 12), text_color=RED,
        )
        self.status_label.pack(side="right", padx=24)

        # Settings card
        card = ctk.CTkFrame(self, corner_radius=10)
        card.pack(fill="x", padx=20, pady=(16, 8))
        card.columnconfigure(0, weight=1)

        # Watch folder
        ctk.CTkLabel(card, text="Carpeta a monitorear", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 2),
        )
        self.watch_entry = ctk.CTkEntry(card, height=34, placeholder_text="Ej: C:/Users/TuUsuario/Downloads")
        self.watch_entry.grid(row=1, column=0, sticky="ew", padx=(16, 8), pady=(0, 10))
        self.watch_entry.insert(0, cfg.get("watch_folder", ""))
        ctk.CTkButton(card, text="Buscar", width=88, height=34, command=self._browse_watch).grid(
            row=1, column=1, padx=(0, 16), pady=(0, 10),
        )

        # Output folder
        ctk.CTkLabel(card, text="Carpeta de destino", font=("Segoe UI", 12, "bold")).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 2),
        )
        self.output_entry = ctk.CTkEntry(card, height=34, placeholder_text="Ej: C:/Users/TuUsuario/Documents/Organizado")
        self.output_entry.grid(row=3, column=0, sticky="ew", padx=(16, 8), pady=(0, 10))
        self.output_entry.insert(0, cfg.get("output_folder", ""))
        ctk.CTkButton(card, text="Buscar", width=88, height=34, command=self._browse_output).grid(
            row=3, column=1, padx=(0, 16), pady=(0, 10),
        )

        # Options row
        opts = ctk.CTkFrame(card, fg_color="transparent")
        opts.grid(row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 14))
        ctk.CTkLabel(opts, text="Delay antes de mover:").pack(side="left")
        self.delay_entry = ctk.CTkEntry(opts, width=44, height=30)
        self.delay_entry.pack(side="left", padx=(6, 4))
        self.delay_entry.insert(0, cfg.get("delay", "3"))
        ctk.CTkLabel(opts, text="seg", text_color=MUTED).pack(side="left", padx=(0, 20))
        self.existing_var = ctk.BooleanVar(value=cfg.get("organize_existing", True))
        ctk.CTkCheckBox(opts, text="Organizar archivos existentes al iniciar", variable=self.existing_var).pack(side="left")

        # Start/stop button
        self.start_btn = ctk.CTkButton(
            self, text="▶   Iniciar",
            font=("Segoe UI", 14, "bold"), height=44, corner_radius=8,
            fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER,
            command=self._toggle,
        )
        self.start_btn.pack(fill="x", padx=20, pady=(0, 12))

        # Log area
        log_card = ctk.CTkFrame(self, corner_radius=10)
        log_card.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        ctk.CTkLabel(log_card, text="Actividad en tiempo real", font=("Segoe UI", 12, "bold")).pack(
            anchor="w", padx=14, pady=(10, 4),
        )
        self.log_box = ctk.CTkTextbox(log_card, font=("Consolas", 11), state="disabled", corner_radius=6)
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Stats
        self.stats_label = ctk.CTkLabel(
            self, text="Movidos: 0   |   Saltados: 0   |   Errores: 0",
            font=("Segoe UI", 11), text_color=MUTED,
        )
        self.stats_label.pack(pady=(0, 10))

    def _attach_logger(self):
        self._log_handler = _GUILogHandler(self._append_log)
        logging.getLogger("FileOrganizer").addHandler(self._log_handler)

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

        self.organizer = FileOrganizer(str(_config_path()), output_folder, move_delay=delay)

        if self.existing_var.get():
            threading.Thread(target=self.organizer.organize_existing, args=(watch_folder,), daemon=True).start()

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

    def _on_close(self):
        if self.running:
            self._stop()
        self.destroy()
