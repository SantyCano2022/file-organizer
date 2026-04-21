import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import yaml

from fileorganizer.logger import setup_logger

logger = setup_logger()


class FileOrganizer:
    def __init__(self, config_path: str, output_folder: str, move_delay: int = 3):
        self.output_folder = Path(output_folder)
        self.move_delay = move_delay
        self.config = self._load_config(config_path)
        self.extension_map = self._build_extension_map()
        self.stats = {"movidos": 0, "saltados": 0, "errores": 0}

    def _load_config(self, config_path: str) -> dict:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        logger.debug(f"Configuracion cargada: {len(config['categorias'])} categorias")
        return config

    MESES = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }

    def _build_extension_map(self) -> dict[str, dict]:
        ext_map = {}
        for categoria, datos in self.config["categorias"].items():
            for ext in datos["extensiones"]:
                ext_map[ext.lower()] = {
                    "destino": datos["destino"],
                    "categoria": categoria,
                    "subcarpeta_por_año": datos.get("subcarpeta_por_año", False),
                    "subcarpeta_por_mes": datos.get("subcarpeta_por_mes", False),
                }
        return ext_map

    def classify(self, file_path: Path) -> Optional[Path]:
        """Determina la carpeta destino de un archivo segun su extension."""
        ext = file_path.suffix.lower()
        info = self.ext_map_get(ext)

        if info:
            destino = self.output_folder / info["destino"]
            if info["subcarpeta_por_año"]:
                fecha = datetime.fromtimestamp(file_path.stat().st_mtime)
                destino = destino / str(fecha.year)
                if info["subcarpeta_por_mes"]:
                    destino = destino / self.MESES[fecha.month]
        else:
            destino = self.output_folder / self.config["sin_categoria"]["destino"]

        return destino

    def ext_map_get(self, ext: str) -> Optional[dict]:
        return self.extension_map.get(ext)

    def _resolve_conflict(self, destination: Path) -> Optional[Path]:
        """Maneja archivos con el mismo nombre en destino segun la config."""
        conflicto = self.config.get("conflicto", "renombrar")

        if conflicto == "saltar":
            return None
        if conflicto == "reemplazar":
            return destination
        # "renombrar" por defecto
        stem = destination.stem
        suffix = destination.suffix
        parent = destination.parent
        counter = 1
        new_path = destination
        while new_path.exists():
            new_path = parent / f"{stem}_{counter}{suffix}"
            counter += 1
        return new_path

    def _is_file_ready(self, file_path: Path) -> bool:
        """Verifica que el archivo no siga siendo escrito (descarga en curso)."""
        try:
            size_before = file_path.stat().st_size
            time.sleep(self.move_delay)
            size_after = file_path.stat().st_size
            return size_before == size_after
        except FileNotFoundError:
            return False

    def move_file(self, file_path: Path) -> bool:
        """Mueve un archivo a su destino correspondiente. Retorna True si tuvo exito."""
        if not file_path.exists() or not file_path.is_file():
            return False

        # Ignorar archivos temporales de descarga
        if file_path.suffix.lower() in {".tmp", ".crdownload", ".part", ".download"}:
            logger.debug(f"Ignorando archivo temporal: {file_path.name}")
            return False

        if not self._is_file_ready(file_path):
            logger.warning(f"Archivo en uso, se reintentara: {file_path.name}")
            return False

        destino_dir = self.classify(file_path)
        destino_dir.mkdir(parents=True, exist_ok=True)
        destino_final = destino_dir / file_path.name

        if destino_final.exists():
            destino_final = self._resolve_conflict(destino_final)
            if destino_final is None:
                logger.info(f"Saltado (ya existe): {file_path.name}")
                self.stats["saltados"] += 1
                return False

        try:
            shutil.move(str(file_path), str(destino_final))
            categoria = self.ext_map_get(file_path.suffix.lower())
            cat_name = categoria["categoria"] if categoria else "Otros"
            logger.info(f"[{cat_name}] {file_path.name}  →  {destino_final.parent}")
            self.stats["movidos"] += 1
            return True
        except PermissionError:
            logger.error(f"Sin permiso para mover: {file_path.name}")
            self.stats["errores"] += 1
            return False
        except Exception as e:
            logger.error(f"Error moviendo {file_path.name}: {e}")
            self.stats["errores"] += 1
            return False

    def organize_existing(self, watch_folder: Path):
        """Organiza archivos que ya estaban en la carpeta al iniciar."""
        files = [f for f in watch_folder.iterdir() if f.is_file()]
        if not files:
            return
        logger.info(f"Organizando {len(files)} archivos existentes...")
        for file_path in files:
            self.move_file(file_path)

    def print_stats(self):
        logger.info(
            f"Resumen — Movidos: {self.stats['movidos']} | "
            f"Saltados: {self.stats['saltados']} | "
            f"Errores: {self.stats['errores']}"
        )
