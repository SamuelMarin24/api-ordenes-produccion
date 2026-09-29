"""
API de Órdenes de Producción
============================

Expone las órdenes de producción del ERP como un servicio REST, sin que los
sistemas que las consumen tengan que conectarse directamente a la base.

Cómo funciona:
  - Mantiene una copia completa de las órdenes en memoria.
  - Un hilo en segundo plano revisa cada N minutos si la base cambió
    (comparando MAX(fecha_carga)) y solo recarga cuando hay datos nuevos.
  - Guarda un respaldo en disco: si la base no responde al arrancar,
    la API igual levanta y responde, marcando los datos como desactualizados.
  - Cada consulta exige una llave de acceso en el header X-API-Key.
"""

import html
import json
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pyodbc
from fastapi import FastAPI, Header, Query
from fastapi.responses import JSONResponse

from config import (
    CONEXION, TABLA_ORDENES, CENTRO_OPERACION, DESDE_BASE,
    MINUTOS_REVISION, HORA_CARGA_DIARIA, RESPALDO, ZONA,
    API_KEY, CORREO_DESTINO, CORREO_ACTIVO,
)

# El envío de avisos usa Outlook y solo existe en Windows.
# Si pywin32 no está instalado, la API funciona igual y no envía correos.
try:
    import pythoncom
    import win32com.client
    CORREO_DISPONIBLE = True
except ImportError:
    CORREO_DISPONIBLE = False

CONSULTA = f"""
WITH ultimas AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY op ORDER BY fecha_carga DESC) AS rn
    FROM {TABLA_ORDENES}
    WHERE centro_operacion = ?
      AND fecha_creacion  >= ?
)
SELECT op, id_fila, cliente, id_cliente, cod_cliente, referencia,
       cantidad_unica, estado, elaboro, centro_operacion,
       fecha_creacion, fecha_compromiso, tipo_trabajo, op_repeticion,
       telefonos, contacto, vendedor, oc_cliente, entregar_en,
       num_cotiza, observaciones, fecha_carga
FROM ultimas
WHERE rn = 1
ORDER BY fecha_creacion ASC, op ASC
"""

CEROS_A_NULO = ("num_cotiza", "op_repeticion")

# ---------- la copia en memoria ----------
copia = {
    "registros": [],
    "version": None,          # MAX(fecha_carga) de la base
    "armada_en": None,        # cuándo se armó
    "desactualizado": False,  # true si no se pudo contactar la base
}
candado = threading.Lock()


def ahora():
    return datetime.now(timezone.utc).astimezone(ZONA)


def fecha_valida(texto):
    try:
        datetime.strptime(texto, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def limpiar_observaciones(texto):
    """Las observaciones vienen del ERP con etiquetas HTML y entidades sueltas."""
    if not texto:
        return None
    t = re.sub(r"<\s*BR\s*/?\s*>", " ", texto, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t.replace("&ORDM;", "&ordm;"))
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def convertir(nombre, valor):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.replace(microsecond=0).isoformat()
    if nombre == "observaciones":
        return limpiar_observaciones(valor)
    if isinstance(valor, str):
        return valor.strip() or None
    if nombre in CEROS_A_NULO and valor == 0:
        return None
    return valor


# ---------- avisos por correo ----------
def enviar_correo(asunto, cuerpo):
    """Corre en un hilo aparte. Nunca debe tumbar la API."""
    try:
        pythoncom.CoInitialize()
        outlook = win32com.client.Dispatch("Outlook.Application")
        correo = outlook.CreateItem(0)
        correo.To = CORREO_DESTINO
        correo.Subject = asunto
        correo.Body = cuerpo
        correo.Send()
    except Exception as e:
        print("No se pudo enviar el correo:", e)
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def avisar(exitoso, detalle):
    if not (CORREO_ACTIVO and CORREO_DESTINO and CORREO_DISPONIBLE):
        return
    marca = "OK" if exitoso else "ERROR"
    asunto = f"[{marca}] Consumo API ordenes - {ahora().strftime('%d/%m %H:%M')}"
    cuerpo = (
        f"Fecha y hora: {ahora().isoformat(timespec='seconds')}\n"
        f"Resultado: {'EXITOSO' if exitoso else 'CON ERROR'}\n"
        f"{detalle}\n"
    )
    threading.Thread(target=enviar_correo, args=(asunto, cuerpo), daemon=True).start()


# ---------- base de datos ----------
def version_en_base():
    """MAX(fecha_carga): sirve para saber si hay datos nuevos sin traerlos todos."""
    cn = pyodbc.connect(CONEXION, timeout=5)
    cur = cn.cursor()
    cur.execute(f"SELECT MAX(fecha_carga) FROM {TABLA_ORDENES}")
    v = cur.fetchone()[0]
    cn.close()
    return v.replace(microsecond=0).isoformat() if v else None


def traer_de_base():
    cn = pyodbc.connect(CONEXION, timeout=30)
    cur = cn.cursor()
    cur.execute(CONSULTA, CENTRO_OPERACION, DESDE_BASE)
    columnas = [c[0] for c in cur.description]
    filas = cur.fetchall()
    cn.close()
    return [{n: convertir(n, v) for n, v in zip(columnas, f)} for f in filas]


def guardar_respaldo():
    try:
        RESPALDO.write_text(json.dumps({
            "registros": copia["registros"],
            "version": copia["version"],
            "armada_en": copia["armada_en"],
        }, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print("No se pudo guardar el respaldo:", e)


def cargar_respaldo():
    if not RESPALDO.exists():
        return False
    try:
        d = json.loads(RESPALDO.read_text(encoding="utf-8"))
        with candado:
            copia["registros"] = d["registros"]
            copia["version"] = d["version"]
            copia["armada_en"] = d["armada_en"]
            copia["desactualizado"] = True
        print(f"Copia levantada del respaldo: {len(d['registros'])} registros")
        return True
    except Exception as e:
        print("No se pudo leer el respaldo:", e)
        return False


def refrescar(forzar=False):
    """Arma la copia si cambió la versión. Devuelve True si recargó."""
    try:
        v = version_en_base()
        if not forzar and v == copia["version"] and copia["registros"]:
            with candado:
                copia["desactualizado"] = False
            return False

        nuevos = traer_de_base()                      # se arma completa aparte
        with candado:                                 # y se reemplaza de un golpe
            copia["registros"] = nuevos
            copia["version"] = v
            copia["armada_en"] = ahora().isoformat(timespec="seconds")
            copia["desactualizado"] = False
        guardar_respaldo()
        print(f"Copia actualizada: {len(nuevos)} registros | version {v}")
        return True

    except pyodbc.Error as e:
        print("No se pudo contactar la base:", e)
        with candado:
            if copia["registros"]:
                copia["desactualizado"] = True
        return False


def vigilante():
    """Corre por detrás: revisa cada N minutos y recarga completo una vez al día."""
    ultima_carga_diaria = ahora().date()
    while True:
        threading.Event().wait(MINUTOS_REVISION * 60)
        try:
            hoy = ahora().date()
            if ahora().hour >= HORA_CARGA_DIARIA and ultima_carga_diaria != hoy:
                refrescar(forzar=True)
                ultima_carga_diaria = hoy
            else:
                refrescar()
        except Exception as e:
            print("Error en el vigilante:", e)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    if not refrescar(forzar=True):      # intenta contra la base
        cargar_respaldo()               # si falla, levanta del archivo
    threading.Thread(target=vigilante, daemon=True).start()
    yield


app = FastAPI(title="API Órdenes de Producción", version="1.1", lifespan=ciclo_de_vida)


def error(codigo_http, codigo, mensaje):
    return JSONResponse(
        status_code=codigo_http,
        content={"ok": False, "mensaje": mensaje, "codigo": codigo, "datos": None},
    )


# ---------- endpoints ----------
@app.get("/api/v1/ordenes")
def obtener_ordenes(
    estado: str | None = Query(None),
    desde: str | None = Query(None),
    hasta: str | None = Query(None),
    pagina: int = Query(1, ge=1),
    tamano: int = Query(100, ge=1, le=500),
    todo: bool = Query(False),
    x_api_key: str | None = Header(None),
):
    if not API_KEY or x_api_key != API_KEY:
        avisar(False, "Motivo: llave de acceso faltante o invalida")
        return error(401, "NO_AUTORIZADO", "Llave de acceso faltante o inválida")

    for nombre, valor in (("desde", desde), ("hasta", hasta)):
        if valor and not fecha_valida(valor):
            avisar(False, f"Motivo: parametro {nombre} invalido ({valor})")
            return error(400, "PARAM_INVALIDO",
                         f"El parámetro '{nombre}' debe tener el formato AAAA-MM-DD")

    if desde and hasta and desde > hasta:
        avisar(False, "Motivo: rango de fechas invertido")
        return error(400, "PARAM_INVALIDO",
                     "El parámetro 'desde' no puede ser posterior a 'hasta'")

    with candado:
        registros = copia["registros"]
        version = copia["version"]
        desactualizado = copia["desactualizado"]

    if not registros:
        avisar(False, "Motivo: sin datos en memoria, la base no responde")
        return error(503, "DB_CONEXION", "No fue posible conectar con la base de datos")

    if estado:
        registros = [r for r in registros if r["estado"] == estado.upper()]

    if desde:
        registros = [r for r in registros if r["fecha_creacion"][:10] >= desde]

    if hasta:
        registros = [r for r in registros if r["fecha_creacion"][:10] <= hasta]

    total = len(registros)

    if todo:
        pagina, tamano, paginas = 1, total, 1
        pagina_datos = registros
    else:
        paginas = (total + tamano - 1) // tamano
        inicio = (pagina - 1) * tamano
        pagina_datos = registros[inicio:inicio + tamano]

    avisar(True,
           f"Registros entregados: {len(pagina_datos)} de {total} | "
           f"{'Descarga completa' if todo else f'Pagina {pagina} de {paginas}'} | "
           f"Estado: {estado or 'ninguno'} | "
           f"Rango: {desde or DESDE_BASE} a {hasta or 'hoy'} | "
           f"Datos del: {version}")

    return {
        "ok": True,
        "mensaje": "Consulta ejecutada correctamente" if total else "No se encontraron órdenes con esos filtros",
        "paginacion": {"pagina": pagina, "tamano": tamano, "total": total, "paginas": paginas},
        "filtros": {
            "centro_operacion": CENTRO_OPERACION,
            "desde": desde or DESDE_BASE,
            "hasta": hasta,
            "estado": estado,
            "todo": todo,
        },
        "datos_actualizados_en": version,
        "desactualizado": desactualizado,
        "datos": pagina_datos,
        "consultado_en": ahora().isoformat(timespec="seconds"),
    }


@app.get("/salud")
def salud():
    with candado:
        return {
            "ok": bool(copia["registros"]),
            "mensaje": "API disponible" if copia["registros"] else "Sin datos en memoria",
            "registros_en_memoria": len(copia["registros"]),
            "datos_actualizados_en": copia["version"],
            "copia_armada_en": copia["armada_en"],
            "desactualizado": copia["desactualizado"],
        }
