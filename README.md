# File Organizer

Automatización de archivos que monitorea una carpeta en tiempo real y clasifica cada archivo nuevo según su tipo, moviéndolo a la carpeta correspondiente sin intervención manual.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-12%20passed-brightgreen?logo=pytest)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)
![Version](https://img.shields.io/badge/Version-1.3.1-blue)

---

## Descarga directa (Windows)

No necesitás instalar Python ni nada. Descargá el ejecutable desde la sección [Releases](../../releases/latest) y ejecutalo directamente.

La primera vez te pide que elijas la carpeta a monitorear y la carpeta de destino. Esa configuración queda guardada para las próximas veces.

> Si Windows muestra una advertencia de SmartScreen, hacé clic en **"Más información"** → **"Ejecutar de todas formas"**.

---

## Cómo funciona

El programa observa la carpeta configurada (por defecto `Downloads`) y en el momento que detecta un archivo nuevo lo clasifica por extensión y lo mueve al destino correspondiente:

```
Downloads/
    factura_2024-08-20.pdf   →   Documentos/PDF/2024/Agosto/
    foto_viaje.jpg           →   Imagenes/2026/Abril/
    presupuesto.xlsx         →   Documentos/HojasDeCalculo/2026/
    cancion.mp3              →   Musica/
```

Si el archivo tiene una fecha en el nombre (`factura_2024-08-20.pdf`, `radicado_20230315.pdf`), la usa para clasificarlo en el año y mes correcto. Si no tiene fecha, usa la fecha de modificación del archivo.

Los archivos que todavía se están descargando (`.crdownload`, `.part`, `.tmp`) se ignoran hasta que la descarga termina.

---

## Características

- **Interfaz gráfica** para configurar y controlar el organizador sin tocar código
- **Detección en tiempo real** usando eventos del sistema de archivos (`watchdog`)
- **Bandeja del sistema** — al cerrar la ventana el programa sigue corriendo en segundo plano (área de notificaciones al lado del reloj)
- **Notificaciones de Windows** — cada archivo movido muestra una notificación con el nombre y la carpeta destino
- **Iniciar con Windows** — checkbox en la app para que arranque automáticamente al encender la PC
- **Deshacer** — revierte el último movimiento desde Inicio, o cualquier movimiento individual desde el Historial
- **Vista previa (dry-run)** — muestra qué archivos se moverían y a dónde, sin mover nada
- **Historial con búsqueda** — registro persistente de hasta 2 000 movimientos con filtro en tiempo real por nombre, categoría o destino
- **Programación automática** — organiza en un horario fijo (día y hora configurables)
- **Perfiles de reglas** — múltiples conjuntos de reglas para distintos flujos de trabajo (trabajo, personal, etc.)
- **Estadísticas visuales** — gráfica de actividad por día y distribución por categoría
- **Manual integrado** — guía de uso completa dentro de la app (pestaña Manual)
- **Wizard de bienvenida** — tour interactivo que aparece en el primer inicio
- **Detección de fecha en el nombre del archivo** — organiza por la fecha del nombre si la tiene, o por fecha de modificación si no
- 11 categorías predefinidas: Imágenes, Videos, Música, PDF, Word, Excel, Código, Comprimidos, Instaladores y más
- Subcarpetas por año y mes: `Imagenes/2026/Abril/`, `Documentos/PDF/2025/Junio/`
- Manejo de archivos duplicados: renombra, reemplaza o ignora según configuración
- Reglas completamente editables sin tocar el código, con editor visual en la pestaña Reglas
- **Auto-actualización** — comprueba nuevas versiones en GitHub al iniciar y se actualiza sola

---

## Estructura del proyecto

```
file-organizer/
│
├── src/
│   └── fileorganizer/
│       ├── organizer.py        # Motor de clasificación y movimiento de archivos
│       ├── watcher.py          # Monitor del sistema de archivos en tiempo real
│       ├── gui.py              # Interfaz gráfica completa
│       ├── history.py          # Persistencia del historial de movimientos
│       ├── scheduler.py        # Programación de organización automática por horario
│       ├── updater.py          # Auto-actualización desde GitHub Releases
│       └── logger.py           # Configuración de logs
│
├── config/
│   └── rules.yaml              # Reglas de clasificación por extensión
│
├── tests/
│   └── test_organizer.py       # Tests automatizados con pytest
│
├── scripts/
│   └── setup_autostart.py      # Configura el arranque automático en Windows (CLI)
│
├── FileOrganizer.spec          # Configuración de empaquetado PyInstaller
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
| `pystray` | 0.19.5 | Icono y menú en la bandeja del sistema |
| `pillow` | 12.2.0 | Generación del icono para la bandeja |
| `plyer` | 2.1.0 | Notificaciones nativas de Windows |

---

## Licencia

MIT
