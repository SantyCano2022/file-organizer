import fnmatch
import re
import shutil
import time
from collections import deque
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

import yaml

from fileorganizer.history import append_move as _hist_append
from fileorganizer.logger import setup_logger

logger = setup_logger()


class FileOrganizer:
    def __init__(self, config_path: str, output_folder: str, move_delay: int = 3,
                 on_file_moved: Optional[Callable[[str, str], None]] = None,
                 exclusion_patterns: list = None):
        self.output_folder = Path(output_folder)
        self.move_delay = move_delay
        self.config = self._load_config(config_path)
        self.extension_map = self._build_extension_map()
        self.stats = {"movidos": 0, "saltados": 0, "errores": 0}
        self.on_file_moved = on_file_moved
        self.move_history: deque = deque(maxlen=20)
        self._batch_mode = False
        self.exclusion_patterns: list = exclusion_patterns or []

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

    # Patrones de fecha soportados en nombres de archivo
    _DATE_PATTERNS = [
        (r"(\d{4})[-_/\.](\d{2})[-_/\.](\d{2})", "ymd"),  # 2024-08-20, 2024_08_20
        (r"(\d{2})[-_/\.](\d{2})[-_/\.](\d{4})", "dmy"),  # 20-08-2024, 20/08/2024
        (r"(\d{4})(\d{2})(\d{2})",                 "ymd"),  # 20240820
    ]

    def _extract_date_from_name(self, filename: str) -> Optional[datetime]:
        """Intenta extraer una fecha del nombre del archivo."""
        for pattern, order in self._DATE_PATTERNS:
            match = re.search(pattern, filename)
            if match:
                a, b, c = match.group(1), match.group(2), match.group(3)
                try:
                    if order == "ymd":
                        year, month, day = int(a), int(b), int(c)
                    else:
                        day, month, year = int(a), int(b), int(c)
                    if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
                        return datetime(year, month, day)
                except ValueError:
                    continue
        return None

    def _get_fecha(self, file_path: Path) -> datetime:
        """Devuelve la fecha a usar: primero busca en el nombre, luego usa modificacion."""
        fecha = self._extract_date_from_name(file_path.stem)
        if fecha:
            logger.debug(f"Fecha extraida del nombre: {file_path.name} → {fecha.date()}")
            return fecha
        return datetime.fromtimestamp(file_path.stat().st_mtime)

    def classify(self, file_path: Path) -> Optional[Path]:
        """Determina la carpeta destino de un archivo segun su extension."""
        ext = file_path.suffix.lower()
        info = self.ext_map_get(ext)

        if info:
            destino = self.output_folder / info["destino"]
            if info["subcarpeta_por_año"]:
                fecha = self._get_fecha(file_path)
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

        for pat in self.exclusion_patterns:
            if fnmatch.fnmatch(file_path.name.lower(), pat.lower()):
                logger.debug(f"Excluido por patron '{pat}': {file_path.name}")
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
            self.move_history.append((file_path, destino_final))
            _hist_append(file_path.name, str(file_path), str(destino_final), cat_name)
            if not self._batch_mode and self.on_file_moved:
                try:
                    self.on_file_moved(file_path.name, str(destino_final.parent))
                except Exception:
                    pass
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
        self._batch_mode = True
        logger.info(f"Organizando {len(files)} archivos existentes...")
        try:
            for file_path in files:
                self.move_file(file_path)
        finally:
            self._batch_mode = False

    def organize_folder(self, folder: Path):
        """Organiza todos los archivos de una carpeta caída recursivamente."""
        files = [f for f in folder.rglob("*") if f.is_file()]
        if not files:
            return
        self._batch_mode = True
        logger.info(f"Organizando carpeta '{folder.name}': {len(files)} archivos...")
        count = 0
        try:
            for file_path in files:
                if self.move_file(file_path):
                    count += 1
        finally:
            self._batch_mode = False
        for d in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass
        try:
            folder.rmdir()
        except OSError:
            pass
        if self.on_file_moved:
            try:
                self.on_file_moved(f"[Carpeta] {folder.name}",
                                   f"{count} archivos organizados")
            except Exception:
                pass

    def undo_last(self) -> bool:
        """Revierte el último movimiento registrado."""
        if not self.move_history:
            return False
        original, moved_to = self.move_history.pop()
        if not moved_to.exists():
            logger.warning(f"No se puede deshacer: {moved_to.name} ya no existe en destino")
            return False
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            dest = original
            if dest.exists():
                stem, suffix, counter = dest.stem, dest.suffix, 1
                while dest.exists():
                    dest = dest.parent / f"{stem}_{counter}{suffix}"
                    counter += 1
            shutil.move(str(moved_to), str(dest))
            logger.info(f"[Deshacer] {moved_to.name}  →  {dest.parent}")
            self.stats["movidos"] = max(0, self.stats["movidos"] - 1)
            return True
        except Exception as e:
            logger.error(f"Error al deshacer: {e}")
            return False

    def print_stats(self):
        logger.info(
            f"Resumen — Movidos: {self.stats['movidos']} | "
            f"Saltados: {self.stats['saltados']} | "
            f"Errores: {self.stats['errores']}"
        )
