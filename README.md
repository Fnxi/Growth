# Growth Hacking Lab - El Hilo MX

MVP local para medir experimentos de distribucion organica con datos publicos
observables, registros manuales y tracking propio minimizado. No realiza
scraping de Instagram ni automatiza interacciones.

## Requisitos

- Python 3.11 o superior
- Docker Desktop con Docker Compose

## Ejecucion local

En PowerShell, desde la raiz del proyecto:

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
docker compose --env-file .env up -d postgres
alembic upgrade head
uvicorn app.main:app --app-dir backend --reload
```

En otra terminal, con el mismo entorno virtual:

```powershell
streamlit run frontend/app.py
```

El dashboard usa `API_BASE_URL` si se necesita un backend distinto de
`http://127.0.0.1:8000`. No requiere secretos del navegador.

La API quedara disponible en `http://127.0.0.1:8000`; la comprobacion de vida
es `GET /health` y la documentacion interactiva es `http://127.0.0.1:8000/docs`.

Los endpoints CRUD y medicion de fases 2 y 3 estan documentados en `docs/backend.md`. Si el
puerto `5432` esta ocupado en el equipo, actualiza en `.env` tanto
`POSTGRES_PORT` como el puerto de `DATABASE_URL` al mismo valor disponible.

El valor de `POSTGRES_PASSWORD` en `.env.example` es exclusivamente local y se
debe sustituir antes de cualquier uso fuera del equipo.

## Supervisión programada

El planificador es un proceso independiente de FastAPI. Reutiliza la misma
comprobación interna y adquiere un advisory lock de PostgreSQL por ejecución,
por lo que varias instancias no ejecutan la misma comprobación a la vez. Sus
ejecuciones se conservan en `infrastructure_check_runs`; las transiciones y
alertas siguen conservándose en las tablas existentes.

Configura estas variables en `.env`:

```dotenv
MONITORING_SCHEDULER_ENABLED=true
MONITORING_CHECK_INTERVAL_SECONDS=60
```

El intervalo acepta valores entre 10 y 86400 segundos. Inicia el proceso local
en otra terminal después de aplicar las migraciones:

```powershell
python -m app.monitor_scheduler
```

En Docker Compose, inicia PostgreSQL y el servicio independiente con:

```powershell
docker compose --env-file .env --profile monitoring up -d
```

Detén solo el planificador con `docker compose --profile monitoring stop
monitor`, o usa `Ctrl+C` para el proceso local. Docker lo reinicia si el proceso
falla (`restart: on-failure`); iniciar el perfil no activa el planificador si la
variable sigue en `false`. Antes del primer arranque ejecuta `alembic upgrade
head`.

El proceso persiste un heartbeat UTC al comienzo de cada ciclo y registra un
cierre limpio. El dashboard muestra `disabled` solo por configuración,
`not_started` si no existe evidencia de un inicio, `running` cuando el heartbeat
sigue vigente, `inactive` si venció, `stopped` si hubo un cierre limpio, y
`failed` cuando el proceso sigue vivo pero la última ejecución falló. La hora de
la última ejecución no representa una transición de infraestructura.

## Asistente IA

El asistente es opcional y está deshabilitado por defecto. Solo usa consultas de
lectura acotadas de infraestructura, alertas, ejecuciones, campañas,
experimentos, métricas y tracking. No recibe una sesión de base de datos, no
ejecuta SQL, comandos ni cambios automáticos. Los textos de la base de datos se
tratan como datos no confiables.

```dotenv
AI_ENABLED=false
AI_PROVIDER=openai
AI_OPENAI_API_KEY=
AI_MODEL=gpt-4.1-mini
AI_TIMEOUT_SECONDS=20
AI_MAX_OUTPUT_TOKENS=700
AI_MAX_CONTEXT_CHARACTERS=12000
AI_RATE_LIMIT=10
AI_RATE_WINDOW_SECONDS=60
AI_MAX_CONCURRENT_REQUESTS=2
```

La clave solo debe estar en el entorno del backend, nunca en Streamlit ni en el
navegador. El proveedor usa Responses API con `store=false`; los logs contienen
solo proveedor, modelo, duración, estado y tokens devueltos, no conversaciones
ni contexto. Los endpoints son `GET /assistant/status`, `POST /assistant/chat`
y `POST /assistant/diagnosis`.

## Inteligencia operativa

Los endpoints `GET /operational-intelligence/*` ejecutan reglas deterministas de
solo lectura. `/trends` significa cambios relevantes detectados por umbral; no
es regresión, estacionalidad ni predicción. Las métricas se comparan solo dentro
de la misma publicación y definición, requieren tres observaciones y no calculan
porcentajes con una referencia no positiva. Los checks usan únicamente estados
`success` o `degraded` terminados y una línea base de checks anteriores.

La recurrencia histórica de eventos se presenta como advertencia. Solo una alerta
no resuelta del mismo servicio permite indicar una condición crítica vigente.
Los resultados en vivo pueden variar entre solicitudes concurrentes y no
demuestran causalidad, causas raíz ni atribución exclusiva a experimentos.

En el entorno local no hay autenticación de API: el comando documentado de
Uvicorn se enlaza a loopback por defecto y Docker Compose no publica FastAPI.
No expongas la aplicación con `--host 0.0.0.0` ni mediante un proxy público sin
autenticación y autorización delante de los endpoints de asistente. `status`
solo informa disponibilidad y modelo; `chat` y `diagnosis` están limitados por
origen a `AI_RATE_LIMIT` por `AI_RATE_WINDOW_SECONDS`, y a
`AI_MAX_CONCURRENT_REQUESTS` simultáneas. El límite es memoria local del proceso:
no se comparte entre procesos, réplicas ni reinicios, y no sustituye controles de
red ni autenticación en un despliegue compartido.

`store=false` evita que la respuesta se almacene mediante la API cuando el
proveedor lo soporta, pero no garantiza retención cero. La retención, controles y
uso de datos siguen sujetos a la configuración de la cuenta y las políticas del
proveedor. No se persisten conversaciones en esta aplicación; Streamlit solo
mantiene un historial limitado en la sesión del navegador.

## Pruebas

Con el entorno virtual activado e instalaciones realizadas:

```powershell
pytest
```

## Estado

Se completaron las fases 1 a 6: infraestructura local, medición manual,
analytics, tracking propio, dashboard y motor de experimentos. La evaluación
presenta evidencia disponible y limitaciones; no infiere causalidad.
