# File Organizer

Automatización de archivos que monitorea una carpeta en tiempo real y clasifica cada archivo nuevo según su tipo, moviéndolo a la carpeta correspondiente sin intervención manual.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-12%20passed-brightgreen?logo=pytest)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## Descarga directa (Windows)

No necesitás instalar Python ni nada. Descargá el ejecutable desde la sección [Releases](../../releases/latest) y ejecutalo directamente.

La primera vez te pide que elijas la carpeta a monitorear y la carpeta de destino. Esa configuración queda guardada para las próximas veces.

---

## Cómo funciona

El programa observa la carpeta configurada (por defecto `Downloads`) y en el momento que detecta un archivo nuevo lo clasifica por extensión y lo mueve al destino correspondiente:

```
Downloads/
    factura.pdf      →   Documentos/PDF/2026/Abril/
    foto_viaje.jpg   →   Imagenes/2026/Abril/
    presupuesto.xlsx →   Documentos/HojasDeCalculo/2026/
    cancion.mp3      →   Musica/
```

Los archivos que todavía se están descargando (`.crdownload`, `.part`, `.tmp`) se ignoran hasta que la descarga termina.

---

## Características

- Interfaz gráfica para configurar y controlar el organizador sin tocar código
- Detección en tiempo real usando eventos del sistema de archivos (`watchdog`)
- 11 categorías predefinidas: Imágenes, Videos, Música, PDF, Word, Excel, Código, Comprimidos, Instaladores y más
- Subcarpetas por año y mes: `Imagenes/2026/Abril/`, `Documentos/PDF/2025/Junio/`
- Manejo de archivos duplicados: renombra, reemplaza o ignora según configuración
- Reglas completamente editables en `config/rules.yaml` sin tocar el código
- Logs en consola con colores y registro mensual en archivo

---

## Estructura del proyecto

```
file-organizer/
│
├── src/
│   └── fileorganizer/
│       ├── organizer.py        # Motor de clasificación y movimiento de archivos
│       ├── watcher.py          # Monitor del sistema de archivos en tiempo real
│       ├── gui.py              # Interfaz gráfica
│       └── logger.py           # Configuración de logs
│
├── config/
│   └── rules.yaml              # Reglas de clasificación por extensión
│
├── tests/
│   └── test_organizer.py       # Tests automatizados con pytest
│
├── scripts/
│   └── setup_autostart.py      # Configura el arranque automático en Windows
│
├── main.py                     # Entrada por línea de comandos
└── main_gui.py                 # Entrada con interfaz gráfica
```

---

## Instalación desde código fuente

### Requisitos

- Python 3.10 o superior

### Pasos

```bash
git clone https://github.com/SantyCano2022/file-organizer.git
cd file-organizer

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

### Interfaz gráfica

```bash
python main_gui.py
```

### Línea de comandos

Copiá el archivo `.env.example` a `.env` y editá las rutas:

```env
WATCH_FOLDER=C:/Users/TuUsuario/Downloads
OUTPUT_FOLDER=C:/Users/TuUsuario/Documents/Organizado
MOVE_DELAY=3
ORGANIZE_EXISTING=true
```

```bash
python main.py
```

---

## Configuración de reglas

Las reglas de clasificación están en `config/rules.yaml`. Se pueden agregar categorías nuevas o modificar las existentes sin tocar el código:

```yaml
categorias:
  Facturas:
    destino: Trabajo/Facturas
    subcarpeta_por_año: true
    subcarpeta_por_mes: true
    extensiones:
      - .pdf
      - .xml
```

Comportamiento ante archivos duplicados:

| Valor | Resultado |
|---|---|
| `renombrar` | Agrega un número al nombre: `factura_1.pdf` (por defecto) |
| `saltar` | Ignora el archivo si ya existe en destino |
| `reemplazar` | Sobreescribe el archivo existente |

---

## Arranque automático con Windows

```bash
python scripts/setup_autostart.py

# Para desinstalarlo
python scripts/setup_autostart.py --remove
```

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

```
tests/test_organizer.py::TestClassification::test_pdf_goes_to_documentos        PASSED
tests/test_organizer.py::TestClassification::test_jpg_goes_to_imagenes          PASSED
tests/test_organizer.py::TestClassification::test_jpg_creates_year_subfolder    PASSED
tests/test_organizer.py::TestClassification::test_xlsx_goes_to_hojas_de_calculo PASSED
tests/test_organizer.py::TestClassification::test_mp4_goes_to_videos            PASSED
tests/test_organizer.py::TestClassification::test_unknown_extension_goes_to_otros PASSED
tests/test_organizer.py::TestClassification::test_case_insensitive_extension    PASSED
tests/test_organizer.py::TestMoveFile::test_moves_file_successfully             PASSED
tests/test_organizer.py::TestMoveFile::test_skips_temp_files                    PASSED
tests/test_organizer.py::TestMoveFile::test_skips_nonexistent_file              PASSED
tests/test_organizer.py::TestMoveFile::test_rename_on_conflict                  PASSED
tests/test_organizer.py::TestMoveFile::test_stats_are_updated                   PASSED

12 passed in 0.22s
```

---

## Dependencias

| Paquete | Versión | Descripción |
|---|---|---|
| `watchdog` | 6.0.0 | Monitoreo del sistema de archivos con eventos nativos del SO |
| `pyyaml` | 6.0.2 | Lectura y validación del archivo de reglas |
| `colorlog` | 6.8.2 | Formato de logs con colores en la consola |
| `python-dotenv` | 1.0.1 | Carga de variables de entorno desde `.env` |
| `customtkinter` | 5.2.2 | Interfaz gráfica moderna |

---

## Licencia

MIT
