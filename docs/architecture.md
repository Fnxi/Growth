# Arquitectura y limites del MVP

## Alcance implementado

La fase 1 prepara la ejecucion local. La fase 2 incorpora modelos SQLAlchemy,
migracion Alembic y CRUD de publicaciones, campanas y experimentos. La fase 3
agrega captura manual de métricas públicas, eventos de distribución y cálculos
reproducibles. La fase 4 agrega tracking propio: enlaces UTM, eventos mínimos y
redirecciones solo a dominios HTTPS permitidos. No recoge datos de Instagram
mediante scraping ni implementa automatizacion de interacciones.

## Flujo objetivo posterior

Las observaciones manuales de publicaciones se registraran con fecha, hora y
referencia de evidencia. Los enlaces UTM se asociaran a eventos de distribucion,
canales y experimentos. Los eventos de trafico propios alimentaran agregados de
analytics para comparar canales y experimentos.

## Clasificacion de metricas

Cada metrica incluira una de estas clasificaciones, visibles en API, dashboard y
exportaciones:

- `observed`: valor publico registrado manualmente con evidencia.
- `calculated`: valor derivado de datos almacenados mediante una formula trazable.
- `estimated`: aproximacion identificada con su metodo y supuestos.
- `unavailable`: dato que no se puede conocer con las fuentes autorizadas.

Las metricas publicas observables no se presentaran como alcance, impresiones o
interacciones privadas.

Los snapshots pertenecen a publicaciones y las publicaciones pueden pertenecer a
campañas con varios experimentos. Por ello, la evaluación etiqueta esos valores
como `campaign_shared`: son evidencia de campaña, no atribución exclusiva ni
prueba causal de un experimento. Una futura extensión, si el diseño lo exige,
podría registrar una ventana de observación o una asociación explícita al
experimento; no se implementa para evitar duplicar la evidencia existente.

## Tracking seguro previsto

El endpoint de redireccion acepta destinos HTTPS previamente permitidos por
configuracion; nunca recibe un destino en la solicitud de redireccion. Incluye
codigos opacos, limitacion de tasa por identificador anonimo, registro minimo y
respuesta generica para enlaces inexistentes o desactivados.

El rate limiting es local al proceso: deriva una clave BLAKE2b con una sal
aleatoria en memoria a partir de la direccion del cliente, guarda solo esa clave
y marcas de tiempo, y se reinicia al reiniciar la API. No se comparte entre
workers, procesos o instancias, por lo que no sustituye un limite distribuido en
un despliegue escalado. No almacena IP completas en base de datos ni en logs de
aplicacion.

Todo `GET /r/{code}` valido cuenta como clic registrado, incluidos bots,
previsualizadores y solicitudes automatizadas. El sistema no los clasifica como
clics humanos ni como personas unicas.

No se guardaran direcciones IP completas ni se aplicara fingerprinting. Los
controles de abuso se disenaran para proteger la infraestructura, no para
identificar personas.

## Supervisión y alertas

`GET /system/status` es una sonda de solo lectura. La detección de transiciones
y persistencia se ejecuta únicamente mediante `run_infrastructure_check()`, que
el endpoint interno protegido `POST /system/check` usa hoy y un programador de
tareas podrá reutilizar en una fase posterior. Una alerta puede ser reconocida
por un operador (`is_acknowledged`) sin quedar resuelta; solo la recuperación del
servicio marca `is_resolved` y registra su fecha de resolución.

## Integraciones futuras

`collectors/` alojara interfaces comunes de lectura, por ejemplo una operacion
para obtener snapshots normalizados y metadatos de fuente. Los adaptadores de
API oficial implementaran esas interfaces; los datos simulados llevaran una
marca explicita. No habra scraping ni automatizacion de interacciones.
