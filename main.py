"""
File Organizer — Punto de entrada principal
Uso: python main.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Agrega src/ al path para que Python encuentre el paquete fileorganizer
sys.path.insert(0, str(Path(__file__).parent / "src"))

from fileorganizer.organizer import FileOrganizer
from fileorganizer.watcher import FolderWatcher
from fileorganizer.logger import setup_logger

load_dotenv()
logger = setup_logger()

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config" / "rules.yaml"


def main():
    watch_folder = os.getenv("WATCH_FOLDER", str(Path.home() / "Downloads"))
    output_folder = os.getenv("OUTPUT_FOLDER", str(Path.home() / "Documents" / "Organizado"))
    move_delay = int(os.getenv("MOVE_DELAY", "3"))
    organize_existing = os.getenv("ORGANIZE_EXISTING", "true").lower() == "true"

    logger.info("=" * 55)
    logger.info("  FILE ORGANIZER  |  Automatizacion de archivos")
    logger.info("=" * 55)
    logger.info(f"Carpeta monitoreada : {watch_folder}")
    logger.info(f"Carpeta de salida   : {output_folder}")
    logger.info(f"Delay antes de mover: {move_delay}s")
    logger.info("=" * 55)

    if not CONFIG_PATH.exists():
        logger.error(f"No se encontro rules.yaml en {CONFIG_PATH}")
        sys.exit(1)

    try:
        organizer = FileOrganizer(
            config_path=str(CONFIG_PATH),
            output_folder=output_folder,
            move_delay=move_delay,
        )
    except Exception as e:
        logger.error(f"Error al cargar la configuracion: {e}")
        sys.exit(1)

    if organize_existing:
        organizer.organize_existing(Path(watch_folder))

    watcher = FolderWatcher(watch_folder=watch_folder, organizer=organizer)

    logger.info("Esperando archivos nuevos... (Ctrl+C para detener)")
    watcher.run_forever()


if __name__ == "__main__":
    main()
