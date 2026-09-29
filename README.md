# API de Órdenes de Producción

API REST en FastAPI que expone las órdenes de producción de un ERP, para que otros sistemas las consuman sin conectarse directamente a la base de datos.

## El problema

Las órdenes de producción viven en la base del ERP. Cada sistema que necesitaba consultarlas —tableros, reportes, integraciones— se conectaba por su cuenta a la base, lo que traía tres problemas:

- **Credenciales repartidas:** cada consumidor necesitaba usuario y contraseña de la base.
- **Carga sobre el ERP:** consultas pesadas repetidas contra la misma tabla.
- **Datos sucios:** las observaciones vienen con etiquetas HTML, hay espacios sobrantes, ceros que en realidad significan "sin dato" y varias versiones de la misma orden.

## La solución

Un único servicio que se conecta a la base, normaliza los datos y los entrega como JSON limpio, protegido con una llave de acceso.

```
ERP → base de datos → [ API ] → tableros, reportes, integraciones
```

## Decisiones técnicas

- **Copia en memoria con detección de cambios:** la API mantiene todas las órdenes en memoria. Un hilo en segundo plano consulta cada 15 minutos únicamente `MAX(fecha_carga)`; si ese valor no cambió, no trae nada. Así las consultas responden al instante y la base recibe una consulta liviana en vez de una pesada.
- **Reemplazo atómico:** la copia nueva se arma completa **aparte** y solo entonces se reemplaza dentro de un `Lock`. Ninguna petición ve nunca una lista a medio cargar.
- **Respaldo en disco:** si la base no responde al arrancar, la API levanta igual con el último respaldo y marca la respuesta con `desactualizado: true`. El consumidor sabe que los datos no están frescos, pero no se queda sin servicio.
- **Recarga completa diaria:** además de la detección por versión, una vez al día fuerza la recarga total, por si alguna fila cambió sin actualizar su fecha de carga.
- **Deduplicación en SQL:** el ERP vuelca varias veces la misma orden. Un `ROW_NUMBER() OVER (PARTITION BY op ORDER BY fecha_carga DESC)` se queda solo con la última versión de cada una.
- **Normalización en la capa de datos:** se limpian las etiquetas HTML de las observaciones, se recortan espacios, los textos vacíos pasan a `null` y los ceros que significan "sin dato" también.
- **Avisos opcionales:** puede enviar un correo por cada consulta, con su resultado. Corre en un hilo aparte y está envuelto en `try/except`: un fallo enviando el correo nunca tumba la API. Solo funciona en Windows con Outlook; si la librería no está, la API arranca igual.

## Endpoints

### `GET /api/v1/ordenes`

Requiere el header `X-API-Key`.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `estado` | texto | Filtra por estado de la orden |
| `desde` / `hasta` | AAAA-MM-DD | Rango sobre la fecha de creación |
| `pagina` | entero | Página a devolver (por defecto 1) |
| `tamano` | entero | Registros por página (1–500, por defecto 100) |
| `todo` | booleano | Devuelve todo sin paginar |

```bash
curl -H "X-API-Key: TU_LLAVE" \
  "http://localhost:8000/api/v1/ordenes?estado=ABIERTA&desde=2026-01-01&tamano=50"
```

Respuesta:

```json
{
  "ok": true,
  "mensaje": "Consulta ejecutada correctamente",
  "paginacion": { "pagina": 1, "tamano": 50, "total": 128, "paginas": 3 },
  "filtros": { "centro_operacion": "PRINCIPAL", "desde": "2026-01-01", "estado": "ABIERTA" },
  "datos_actualizados_en": "2026-09-20T06:00:00",
  "desactualizado": false,
  "datos": [ { "op": 101, "cliente": "...", "referencia": "...", "estado": "ABIERTA" } ],
  "consultado_en": "2026-09-20T08:15:00-05:00"
}
```

### `GET /salud`

Sin autenticación. Reporta si hay datos en memoria, de cuándo son y si están desactualizados. Sirve para monitoreo.

### Errores

| Código HTTP | Código | Cuándo |
|---|---|---|
| 401 | `NO_AUTORIZADO` | Llave faltante o inválida |
| 400 | `PARAM_INVALIDO` | Fecha con formato incorrecto o rango invertido |
| 503 | `DB_CONEXION` | Sin datos en memoria y la base no responde |

## Stack

Python 3.10+ · FastAPI · uvicorn · pyodbc · SQL Server

## Estructura

```
api-ordenes-produccion/
├── main.py                     # API: endpoints, copia en memoria y refresco
├── config.py                   # Conexión, parámetros y credenciales por entorno
├── iniciar_api.bat             # Arranque en Windows
├── pruebas/
│   └── prueba_conexion.py      # Verifica la conexión antes de levantar el servicio
├── requirements.txt
├── .env.example
└── .gitignore
```

## Cómo usarlo

1. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
2. Copiar `.env.example` como `.env` y completar la conexión y la llave de acceso. Para generar la llave:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. Verificar la conexión: `python pruebas/prueba_conexion.py`
4. Levantar la API:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

La documentación interactiva queda en `http://localhost:8000/docs`.

## Tabla que espera

Una tabla con una fila por versión de cada orden, con columnas de identificación (`op`, `id_fila`), cliente, referencia, cantidad, estado, fechas de creación y compromiso, datos comerciales y `fecha_carga` (marca de cuándo el ERP volcó esa fila).

> Por confidencialidad, este repositorio no incluye credenciales, nombres de servidores ni datos reales de clientes u órdenes. Los valores de `.env.example` son de ejemplo.
