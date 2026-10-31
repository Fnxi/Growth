# Backend de fases 2 y 3

## Relaciones

```text
Campaign --< Experiment --< DistributionEvent
    |              |
    |              +--< TrackingLink --< TrackingEvent
    |
    +--< campaign_posts >-- Post --< PublicMetricSnapshot >-- MetricDefinition
```

- Una campana agrupa publicaciones mediante `campaign_posts` y tiene muchos experimentos.
- Un experimento pertenece a una campana y es la unidad de comparacion para canales de distribucion y enlaces UTM.
- Un snapshot registra un valor observado para una publicacion y una definicion de metrica, junto con hora de captura y evidencia opcional.
- `MetricDefinition.classification` usa exclusivamente `observed`, `calculated`, `estimated` o `unavailable`.
- `TrackingEvent` solo almacena tipo de evento, hora y dominio de referencia opcional. No incluye IP ni identificadores personales.

## Endpoints

| Recurso | Operaciones |
| --- | --- |
| `/posts` | `POST`, `GET` |
| `/posts/{post_id}` | `GET`, `PATCH`, `DELETE` |
| `/campaigns` | `POST`, `GET` |
| `/campaigns/{campaign_id}` | `GET`, `PATCH`, `DELETE` |
| `/experiments` | `POST`, `GET` (filtro opcional `campaign_id`) |
| `/experiments/{experiment_id}` | `GET`, `PATCH`, `DELETE` |
| `/metric-definitions` | `POST`, `GET` (filtro `classification`) |
| `/metric-definitions/{id}` | `PATCH`, `DELETE` |
| `/metric-snapshots` | `POST` |
| `/posts/{post_id}/metric-snapshots` | `GET` (filtros de métrica y captura) |
| `/distribution-events` | `POST` |
| `/experiments/{experiment_id}/distribution-events` | `GET` (canal y periodo) |
| `/tracking-links` | `POST`, `GET` |
| `/tracking-links/{id}` | `PATCH` (activar/desactivar) |
| `/tracking-links/{id}/clicks` | `GET` |
| `/tracking/attribution` | `GET` (por `utm_source`, `utm_medium` o experimento) |
| `/dashboard/summary` | `GET` (agregado para dashboard) |
| `/analytics/observed-metrics` | `GET` (serie observada por métrica) |
| `/experiments/{id}/status` | `PATCH` (transición de ciclo de vida) |
| `/experiments/{id}/evaluation` | `GET` (resultados disponibles) |
| `/system/status` | `GET` (sonda de solo lectura) |
| `/system/check` | `POST` (comprobación interna con `X-System-Check-Token`) |
| `/system/events` | `GET` (historial por servicio y severidad) |
| `/system/alerts` | `GET` (alertas pendientes o atendidas) |
| `/system/alerts/{id}/acknowledge` | `PATCH` (marcar alerta atendida) |

Las operaciones de creacion y actualizacion validan URL, campos requeridos, periodos temporales y referencias a publicaciones o campanas existentes. Las restricciones de clave unica y foranea se mantienen tambien en PostgreSQL.

Un snapshot requiere una definicion clasificada como `observed`; las métricas calculadas de infraestructura propia no se presentan como observaciones públicas de Instagram.

Ejemplo de snapshot:

```json
{"post_id":"...","metric_definition_id":"...","value":15,"captured_at":"2026-01-02T10:00:00Z","evidence_reference":"manual-note-1"}
```

## Analytics

`app.analytics.metrics` opera exclusivamente sobre observaciones suministradas y devuelve tanto los valores de entrada como limitaciones.

- Variacion absoluta: `valor_final - valor_inicial`.
- Variacion porcentual: `(valor_final - valor_inicial) / valor_inicial * 100` solo si el inicial no es cero.
- Evolucion: variaciones cronologicas consecutivas.
- Tasa observable: `(likes visibles + comentarios visibles) / denominador explicito * 100`.

La tasa observable no representa alcance ni impresiones. Las comparaciones entre experimentos describen diferencias observadas; no infieren causalidad de un canal.

## Tracking propio

`POST /tracking-links` acepta un destino HTTPS en la lista `TRACKING_ALLOWED_DESTINATION_HOSTS` y genera un código opaco. `GET /r/{code}` registra un clic mínimo y redirige con parámetros UTM. Los enlaces desactivados responden como inexistentes. El endpoint limita solicitudes por identificador efímero derivado de la dirección cliente, sin guardar IP completas, y solo conserva el dominio del referrer.

Ejemplo:

```json
{"experiment_id":"...","destination_url":"https://www.instagram.com/p/publicacion/","utm_source":"newsletter","utm_medium":"email","utm_campaign":"encuesta-neutral"}
```

Los resultados son clics registrados por infraestructura propia, no personas únicas, alcance ni impresiones de Instagram.

## Migraciones

Las revisiones son `49ec8a5f0041` (`initial schema`) y `84f7a11be0a0` (definiciones iniciales). Para aplicar cambios:

```powershell
alembic upgrade head
alembic current
```

Alembic toma `DATABASE_URL` desde las variables de entorno o desde `.env`. La URL no se almacena en archivos versionados.
