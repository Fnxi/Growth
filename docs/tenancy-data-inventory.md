# Inventario De Propiedad Multiempresa

Fecha de inventario: 2026-11-03.

Este documento prepara la incorporación de tenancy a `campaigns`, `posts` y `campaign_posts`. No asigna propiedad a registros históricos y no sustituye la revisión/aprobación del manifiesto de asignación.

## Alcance Y Salvaguardas

- La propiedad directa futura corresponde a `Campaign` y `Post`.
- `Experiment`, `DistributionEvent` y `TrackingLink` heredan por `Campaign`.
- `TrackingEvent` hereda por `TrackingLink`.
- `PublicMetricSnapshot` hereda por `Post`.
- `MetricDefinition` sigue siendo catálogo global.
- La información de infraestructura es global de plataforma; no se tenantiza en esta fase.
- El inventario de datos se ejecutó contra `localhost:5433/growth_lab`, después de comprobar host, puerto y nombre de base, dentro de `BEGIN TRANSACTION READ ONLY` (`transaction_read_only=on`). No se consultó DEMO.
- Solo se obtuvieron conteos y checks agregados. No se consultaron URLs, contenidos, identidades ni valores de configuración.

## Estado Actual De Modelos

Todos los modelos usan UUID como clave primaria. `created_at` y `updated_at` proceden de `TimestampedModel` cuando se indica.

| Entidad | Claves, nulabilidad y restricciones | Relaciones y borrado | Decisión de tenancy |
|---|---|---|---|
| `organizations` | PK `id`; `name`, `slug_normalized`, `status` no nulos; `slug_normalized` único; `deleted_at` nullable. | Tiene memberships y eventos de auditoría. | Raíz de organización existente. |
| `organization_memberships` | PK `id`; FKs no nulas a `users` y `organizations`, ambas `RESTRICT`; `role`, `status`, `joined_at` no nulos; `removed_at` nullable; único `(user_id, organization_id)`; índices `(user_id, status)` y `(organization_id, status)`. | N:1 con usuario y organización. | Fuente de autorización, no dueña de recursos comerciales. |
| `campaigns` | PK `id`; `name` no nulo y único global; `description`, `starts_at`, `ends_at` nullable; check de período. No tiene `organization_id`. | M:N con posts; 1:N con experiments. Borrado ORM de campaña elimina experiments huérfanos; FK de experiment a campaña usa `CASCADE`. | Añadir `organization_id` nullable en fase expansiva. |
| `posts` | PK `id`; `canonical_url` no nula y única global; `platform` no nulo; `title`, `published_at` nullable. No tiene `organization_id`. | M:N con campaigns; 1:N snapshots. Borrado ORM de post elimina snapshots; FK de snapshot a post usa `CASCADE`. | Añadir `organization_id` nullable en fase expansiva. |
| `campaign_posts` | PK compuesta `(campaign_id, post_id)`; ambas columnas no nulas; sin índices adicionales. | FKs a `campaigns.id` y `posts.id`, ambas `CASCADE`. | Añadir `organization_id` nullable como valor de consistencia y FKs compuestas en fase expansiva. |
| `experiments` | PK `id`; `campaign_id`, nombre, hipótesis, variable, método y `starts_at` no nulos; restantes campos de diseño/resultado según modelo; único `(campaign_id, name)` y check de período. | N:1 con campaign; 1:N distribution events y tracking links. FK a campaña `CASCADE`; cascada ORM a hijos. | Hereda por `campaign_id`. |
| `distribution_events` | PK `id`; `experiment_id`, `channel`, `distributed_at` no nulos; `notes` nullable. | N:1 con experiment; FK `CASCADE`. | Hereda por experiment y campaign. |
| `tracking_links` | PK `id`; `experiment_id`, `code`, destino y UTM source/medium/campaign no nulos; `code` único global; UTM content/term nullable. | N:1 con experiment; 1:N tracking events; FK a experiment `CASCADE`; cascada ORM a events. | Hereda por experiment y campaign. Mantener `code` globalmente único para `/r/{code}`. |
| `tracking_events` | PK `id`; `tracking_link_id`, `occurred_at`, `event_type` no nulos; `referrer_domain` nullable. | N:1 con tracking link; FK `CASCADE`. | Hereda por tracking link. |
| `public_metric_snapshots` | PK `id`; `post_id`, `metric_definition_id`, `value`, `captured_at` no nulos; evidence nullable; check `value >= 0`; único `(post_id, metric_definition_id, captured_at)`. | N:1 con post (`CASCADE`) y con definición métrica (`RESTRICT`). | Hereda por post. |

Las referencias fuente son `backend/app/db/models.py:134-408`, la migración inicial `database/migrations/versions/49ec8a5f0041_initial_schema.py` y la migración de identidad `database/migrations/versions/d8f7a1c4e902_add_identity_schema.py`.

## Grafo De Dependencias

```text
Organization
  └─< OrganizationMembership >─ User

Organization (futura propiedad directa)
  ├─< Campaign ─< Experiment
  │                  ├─< DistributionEvent
  │                  └─< TrackingLink ─< TrackingEvent
  └─< Post ─< PublicMetricSnapshot >─ MetricDefinition [global]

Campaign >─< campaign_posts >─< Post
```

Después de la migración contract, toda fila en `campaign_posts` deberá tener la misma organización que ambas raíces. Por tanto, el componente conectado completo formado por campaigns, posts y sus asociaciones deberá recibir un único `organization_id` en el manifiesto.

## Inventario De Datos

Conteos agregados obtenidos de la base principal en transacción read-only:

| Concepto | Conteo |
|---|---:|
| Campaigns | 1 |
| Posts | 1 |
| Experiments | 1 |
| Distribution events | 1 |
| Tracking links | 0 |
| Tracking events | 0 |
| Public metric snapshots | 2 |
| Relaciones `campaign_posts` | 1 |
| Organizations | 0 |
| Organization memberships | 0 |

Checks de integridad agregados:

| Check | Resultado |
|---|---:|
| Campaigns sin posts | 0 |
| Posts sin campaigns | 0 |
| Experiments sin campaign | 0 |
| Distribution events sin experiment | 0 |
| Tracking links sin experiment | 0 |
| Tracking events sin link | 0 |
| Snapshots sin post | 0 |
| `campaign_posts` con padre faltante | 0 |

Las FKs actuales explican por qué los checks de hijos huérfanos deberían permanecer en cero; se ejecutaron para confirmar el estado persistido. No es posible comprobar inconsistencia tenant entre campañas y posts hasta que ambas tablas tengan `organization_id`. No se infirió ownership de nombres, contenido, fechas, URLs ni similitudes.

### Consultas De Inventario Repetibles

Ejecutar solo contra una base confirmada, en una transacción read-only:

```sql
BEGIN TRANSACTION READ ONLY;

SELECT
  (SELECT count(*) FROM campaigns) AS campaigns,
  (SELECT count(*) FROM posts) AS posts,
  (SELECT count(*) FROM experiments) AS experiments,
  (SELECT count(*) FROM distribution_events) AS distribution_events,
  (SELECT count(*) FROM tracking_links) AS tracking_links,
  (SELECT count(*) FROM tracking_events) AS tracking_events,
  (SELECT count(*) FROM public_metric_snapshots) AS snapshots,
  (SELECT count(*) FROM campaign_posts) AS campaign_posts,
  (SELECT count(*) FROM organizations) AS organizations,
  (SELECT count(*) FROM organization_memberships) AS memberships;

SELECT count(*) AS campaigns_without_posts
FROM campaigns c
WHERE NOT EXISTS (
  SELECT 1 FROM campaign_posts cp WHERE cp.campaign_id = c.id
);

ROLLBACK;
```

Los restantes checks usan el mismo patrón `NOT EXISTS` para cada FK indicada en la tabla de integridad.

## Riesgos E Integridad Antes Del Backfill

1. No existe organización ni membership en la base principal. Ningún dato comercial puede exponerse a un tenant hasta que exista una organización aprobada y una asignación explícita.
2. Las FKs actuales preservan padres/hijos, pero no expresan propiedad. El modelo permite hoy asociar cualquier campaign con cualquier post existente.
3. `campaign_posts` es M:N. Un post compartido por varias campañas conecta sus decisiones de asignación: no puede pertenecer a organizaciones diferentes sin romper la regla futura.
4. `campaigns.name` y `posts.canonical_url` son únicos globalmente. Cambiar a unicidad por organización no forma parte de la migración expansiva; requiere una fase contract, inventario de duplicados y política de reversión.
5. Los deletes actuales son cascada: campaign elimina experiments, eventos y links; post elimina snapshots. El backfill no debe usar delete/recreate ni modificar relaciones existentes.
6. Una reversión de esquema puede retirar columnas nuevas antes de asignación. Tras asignaciones reales, la reversión semántica exige backup/manifiesto: el esquema previo no conserva ownership.

## Migración Expansiva Implementada

La revisión Alembic `f1a9c2d5e8b0` implementa y superó la integración PostgreSQL aislada de esta expansión. Añade únicamente columnas nullable, índices, constraints y FKs; no realiza backfill, no crea organizaciones ni asigna registros históricos.

1. Añade `campaigns.organization_id UUID NULL` con FK a `organizations.id` y `ON DELETE RESTRICT`.
2. Añade `posts.organization_id UUID NULL` con FK a `organizations.id` y `ON DELETE RESTRICT`.
3. Añade índices no únicos para los nuevos campos de raíces: `campaigns(organization_id)` y `posts(organization_id)`.
4. Añade `campaign_posts.organization_id UUID NULL` con FK a `organizations.id` y `ON DELETE RESTRICT`, más índice para el scope del bridge.
5. Conserva las FKs individuales existentes de `campaign_posts` hacia campaign y post.
6. Añade `UNIQUE (id, organization_id)` a `campaigns` y `posts`. La PK actual mantiene único cada `id`; estas claves candidatas preparan las FKs compuestas.
7. Crea FKs compuestas nullable en `campaign_posts` durante la fase expansiva:

```text
(campaign_id, organization_id) -> campaigns(id, organization_id)
(post_id, organization_id)     -> posts(id, organization_id)
```

Con `organization_id` nullable, PostgreSQL permite las filas históricas sin assignment. Cuando el manifiesto rellene las tres columnas, ambas FKs obligan a que campaña y post compartan organización. Las FKs compuestas implementadas usan `CASCADE`, igual que las FKs de asociación existentes, que permanecen intactas.

8. No actualiza registros existentes, no introduce `NOT NULL`, no cambia `UNIQUE(name)` ni `UNIQUE(canonical_url)` y no activa rutas comerciales tenant-scoped.
9. La fase siguiente debe validar el manifiesto, todas las filas y constraints antes del backfill; debe existir un backup comprobable antes de esa operación.

La migración expansiva es reversible a nivel de esquema antes del backfill: retira primero las FKs compuestas e índices, luego constraints auxiliares y finalmente las columnas nullable. No infiere ni borra datos.

## Manifiesto De Asignación Histórica

Formato recomendado: JSON o CSV versionado y almacenado fuera del repositorio, con revisión humana. Una fila por raíz comercial.

```json
{
  "manifest_version": 1,
  "generated_at": "2026-11-03T00:00:00Z",
  "assignments": [
    {
      "entity_type": "campaign",
      "entity_id": "<UUID existente>",
      "organization_id": "<UUID de organización aprobada>",
      "decision_source": "<referencia a contrato, ticket o registro operativo>",
      "approved_by": "<identificador de aprobador autorizado>",
      "approved_at": "<RFC 3339 UTC>",
      "notes": "<justificación opcional y no sensible>"
    }
  ]
}
```

Reglas de validación previas a ejecutar el manifiesto:

- `entity_type` solo admite `campaign` o `post`.
- Cada `entity_id` debe existir exactamente una vez en su tabla.
- Cada `organization_id` debe existir, estar activa y tener owner aprobado.
- No se permiten assignments duplicados ni entidades omitidas cuando se vaya a aplicar contract.
- Todos los extremos de cada fila `campaign_posts` deben resolver al mismo `organization_id`.
- No se generan entradas para resources derivados: obtienen scope de su padre.
- La fuente y aprobación son obligatorias; no se aceptan defaults ni inferencias automáticas.

## Decisiones Pendientes Antes Del Backfill Y Contract

1. Quién creará y aprobará la primera organización propietaria de los datos actuales.
2. El manifiesto explícito para la campaign y post existentes, y la evidencia operativa que respalda esa decisión.
3. Política de futuras URLs compartidas: permitir una fila `Post` por organización con la misma `canonical_url`, o conservar deduplicación global y modelar evidencia separada. La recomendación de aislamiento es unicidad `(organization_id, canonical_url)` en fase contract.
4. Política de nombres de campaign: la recomendación es `UNIQUE (organization_id, name)` en fase contract, tras validar posibles duplicados para downgrade.
5. Criterios y ventana aprobada para el backfill explícito, tras validar que no queden roots o bridges sin organización ni inconsistencias tenant.
6. Proceso de backup, restauración y aprobación de ventana antes del backfill y de la fase contract.
7. Criterios de fase contract: cero `organization_id` NULL en roots y bridge, cero asociaciones cross-tenant y decisión aprobada para reemplazar las unicidades globales.
