"""
Configura el File Organizer para que arranque automaticamente con Windows.
Crea una tarea en el Programador de Tareas de Windows.

Uso: python scripts/setup_autostart.py [--remove]
"""
import subprocess
import sys
from pathlib import Path

TASK_NAME = "FileOrganizerAutostart"
PROJECT_ROOT = Path(__file__).parent.parent
MAIN_SCRIPT = PROJECT_ROOT / "main.py"


def create_task():
    python_exe = sys.executable
    command = f'"{python_exe}" "{MAIN_SCRIPT}"'

    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>"{MAIN_SCRIPT}"</Arguments>
      <WorkingDirectory>{PROJECT_ROOT}</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
</Task>"""

    xml_path = PROJECT_ROOT / "scripts" / "_task.xml"
    xml_path.write_text(xml, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"],
        capture_output=True, text=True
    )
    xml_path.unlink(missing_ok=True)

    if result.returncode == 0:
        print(f"[OK] Tarea '{TASK_NAME}' creada. El organizador arrancara con Windows.")
    else:
        print(f"[ERROR] {result.stderr}")
        print("Intenta ejecutar este script como Administrador.")


def remove_task():
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"[OK] Tarea '{TASK_NAME}' eliminada.")
    else:
        print(f"[ERROR] {result.stderr}")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove_task()
    else:
        create_task()
