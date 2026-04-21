import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent

from fileorganizer.logger import setup_logger

logger = setup_logger()


class OrganizeHandler(FileSystemEventHandler):
    def __init__(self, organizer, watch_folder: Path):
        super().__init__()
        self.organizer = organizer
        self.watch_folder = watch_folder
        self._processing = set()  # evita procesar el mismo archivo dos veces

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        self._handle(Path(event.src_path))

    def on_moved(self, event: FileMovedEvent):
        # Captura archivos que terminan de descargarse (renombrado de .crdownload → .pdf)
        if event.is_directory:
            return
        dest = Path(event.dest_path)
        if dest.parent == self.watch_folder:
            self._handle(dest)

    def _handle(self, file_path: Path):
        if file_path in self._processing:
            return
        if file_path.parent != self.watch_folder:
            return

        self._processing.add(file_path)
        try:
            logger.debug(f"Nuevo archivo detectado: {file_path.name}")
            self.organizer.move_file(file_path)
        finally:
            self._processing.discard(file_path)


class FolderWatcher:
    def __init__(self, watch_folder: str, organizer):
        self.watch_folder = Path(watch_folder)
        self.organizer = organizer
        self._observer = None

    def start(self):
        if not self.watch_folder.exists():
            raise FileNotFoundError(f"La carpeta a monitorear no existe: {self.watch_folder}")

        handler = OrganizeHandler(self.organizer, self.watch_folder)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_folder), recursive=False)
        self._observer.start()
        logger.info(f"Monitoreando: {self.watch_folder}")

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("Monitor detenido.")

    def run_forever(self):
        """Corre hasta que el usuario presione Ctrl+C."""
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Deteniendo organizador...")
            self.stop()
            self.organizer.print_stats()
