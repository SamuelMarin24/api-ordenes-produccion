SamuelMarin24
api-ordenes-produccion
Repository navigation
Code
Issues
Pull requests
Actions
Projects
Wiki
Security and quality
Insights
Settings
Files
Go to file
t
T
README.md
config.py
iniciar_api.bat
main.py
requirements.txt
api-ordenes-produccion/pruebas
/
prueba_conexion.py
in
main

Edit

Preview
Indent mode

Spaces
Indent size

2
Line wrap mode

No wrap
Editing prueba_conexion.py file contents
  1
  2
  3
  4
  5
  6
  7
  8
  9
 10
 11
 12
 13
 14
 15
 16
 17
 18
 19
 20
 21
 22
 23
 24
 25
 26
 27
 28
 29
 30
 31
 32
 33
 34
 35
 36
 37
 38
 39
"""
Verifica que la conexión a la base funcione y que la consulta traiga datos.
Útil al instalar la API en un equipo nuevo, antes de levantar el servicio.

Uso:  python pruebas/prueba_conexion.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyodbc
from config import CONEXION, TABLA_ORDENES, CENTRO_OPERACION, DESDE_BASE

try:
    cn = pyodbc.connect(CONEXION, timeout=10)
    cur = cn.cursor()

    cur.execute(f"""
        SELECT COUNT(*) FROM {TABLA_ORDENES}
        WHERE centro_operacion = ? AND fecha_creacion >= ?
    """, CENTRO_OPERACION, DESDE_BASE)
    print("Filas crudas:", cur.fetchone()[0])

    cur.execute(f"""
        SELECT COUNT(DISTINCT op) FROM {TABLA_ORDENES}
        WHERE centro_operacion = ? AND fecha_creacion >= ?
    """, CENTRO_OPERACION, DESDE_BASE)
    print("OPs unicas:", cur.fetchone()[0])

    cur.execute(f"SELECT MAX(fecha_carga) FROM {TABLA_ORDENES}")
    print("Ultima carga:", cur.fetchone()[0])

    cn.close()
    print("Conexion correcta")

except Exception as e:
    print("Fallo:", e)
Use Control + Shift + m to toggle the tab key moving focus. Alternatively, use esc then tab to move to the next interactive element on the page.
