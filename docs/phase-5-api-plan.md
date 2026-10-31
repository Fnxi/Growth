# Endpoints Justificados Para Fase 5

El frontend reutiliza CRUD, snapshots, distribución y tracking existentes. Se agregan dos lecturas agregadas para evitar trasladar lógica analítica al navegador:

- `GET /dashboard/summary`: conteos de campañas, experimentos, publicaciones y clics propios, más experimentos recientes.
- `GET /analytics/observed-metrics`: serie cronológica de snapshots observados por nombre de métrica y publicación opcional.

Ambos endpoints solo agregan datos existentes. No estiman alcance, usuarios únicos ni causalidad.
