"""
Configuración de la API.

Todo sale de variables de entorno (.env) para no dejar credenciales,
servidores ni nombres de tablas dentro del código.
Copia .env.example como .env y ajusta los valores a tu entorno.
"""

import os
from pathlib import Path
from datetime import timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # Sin python-dotenv se usan las variables de entorno del sistema

BASE_DIR = Path(__file__).parent

# ── Base de datos ─────────────────────────────────────────────────────────────
DB_DRIVER   = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_SERVER   = os.getenv("DB_SERVER", "")
DB_DATABASE = os.getenv("DB_DATABASE", "")
DB_USER     = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

CONEXION = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE={DB_DATABASE};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
    "Encrypt=yes;TrustServerCertificate=yes;"
)

# Tabla origen de las órdenes de producción (la alimenta el ERP)
TABLA_ORDENES = os.getenv("TABLA_ORDENES", "dbo.ordenes_produccion")

# ── Parámetros de negocio ─────────────────────────────────────────────────────
CENTRO_OPERACION = os.getenv("CENTRO_OPERACION", "PRINCIPAL")
DESDE_BASE       = os.getenv("DESDE_BASE", "2025-01-01")

# ── Operación de la copia en memoria ──────────────────────────────────────────
MINUTOS_REVISION   = int(os.getenv("MINUTOS_REVISION", "15"))
HORA_CARGA_DIARIA  = int(os.getenv("HORA_CARGA_DIARIA", "7"))
RESPALDO           = BASE_DIR / os.getenv("ARCHIVO_RESPALDO", "respaldo_ordenes.json")
ZONA               = timezone(timedelta(hours=int(os.getenv("UTC_OFFSET", "-5"))))

# ── Seguridad y avisos ────────────────────────────────────────────────────────
API_KEY        = os.getenv("API_KEY", "")
CORREO_DESTINO = os.getenv("CORREO_DESTINO", "")
CORREO_ACTIVO  = os.getenv("CORREO_ACTIVO", "false").lower() == "true"
