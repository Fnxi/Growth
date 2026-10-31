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

## Pruebas

Con el entorno virtual activado e instalaciones realizadas:

```powershell
pytest
```

## Estado

Se completaron las fases 1 a 6: infraestructura local, medición manual,
analytics, tracking propio, dashboard y motor de experimentos. La evaluación
presenta evidencia disponible y limitaciones; no infiere causalidad.
