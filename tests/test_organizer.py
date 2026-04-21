"""
Tests del motor de clasificacion y movimiento de archivos.
Ejecutar con: pytest tests/
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fileorganizer.organizer import FileOrganizer

CONFIG_PATH = str(Path(__file__).parent.parent / "config" / "rules.yaml")


@pytest.fixture
def organizer(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    return FileOrganizer(config_path=CONFIG_PATH, output_folder=str(output), move_delay=0)


@pytest.fixture
def watch_dir(tmp_path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    return folder


class TestClassification:
    def test_pdf_goes_to_documentos(self, organizer, watch_dir):
        f = watch_dir / "factura.pdf"
        f.write_text("test")
        destino = organizer.classify(f)
        assert "Documentos" in str(destino)

    def test_jpg_goes_to_imagenes(self, organizer, watch_dir):
        f = watch_dir / "foto.jpg"
        f.write_text("test")
        destino = organizer.classify(f)
        assert "Imagenes" in str(destino)

    def test_jpg_creates_year_subfolder(self, organizer, watch_dir):
        f = watch_dir / "foto.jpg"
        f.write_text("test")
        destino = organizer.classify(f)
        assert "2026" in str(destino)

    def test_xlsx_goes_to_hojas_de_calculo(self, organizer, watch_dir):
        f = watch_dir / "datos.xlsx"
        f.write_text("test")
        destino = organizer.classify(f)
        assert "HojasDeCalculo" in str(destino)

    def test_mp4_goes_to_videos(self, organizer, watch_dir):
        f = watch_dir / "clip.mp4"
        f.write_text("test")
        destino = organizer.classify(f)
        assert "Videos" in str(destino)

    def test_unknown_extension_goes_to_otros(self, organizer, watch_dir):
        f = watch_dir / "archivo.xyz123"
        f.write_text("test")
        destino = organizer.classify(f)
        assert "Otros" in str(destino)

    def test_case_insensitive_extension(self, organizer, watch_dir):
        f = watch_dir / "FOTO.JPG"
        f.write_text("test")
        destino = organizer.classify(f)
        assert "Imagenes" in str(destino)


class TestMoveFile:
    def test_moves_file_successfully(self, organizer, watch_dir):
        f = watch_dir / "documento.pdf"
        f.write_text("contenido")
        result = organizer.move_file(f)
        assert result is True
        assert not f.exists()

    def test_skips_temp_files(self, organizer, watch_dir):
        f = watch_dir / "descargando.crdownload"
        f.write_text("incompleto")
        result = organizer.move_file(f)
        assert result is False
        assert f.exists()

    def test_skips_nonexistent_file(self, organizer, watch_dir):
        f = watch_dir / "no_existe.pdf"
        result = organizer.move_file(f)
        assert result is False

    def test_rename_on_conflict(self, organizer, watch_dir):
        f1 = watch_dir / "reporte.pdf"
        f1.write_text("version 1")
        organizer.move_file(f1)

        f2 = watch_dir / "reporte.pdf"
        f2.write_text("version 2")
        result = organizer.move_file(f2)
        assert result is True

        output_files = list(Path(organizer.output_folder).rglob("reporte*.pdf"))
        assert len(output_files) == 2

    def test_stats_are_updated(self, organizer, watch_dir):
        f = watch_dir / "archivo.mp3"
        f.write_text("musica")
        organizer.move_file(f)
        assert organizer.stats["movidos"] == 1
