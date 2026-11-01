import os

import streamlit as st

from services.api import ApiClient, ApiError

st.set_page_config(page_title="Growth Hacking Lab", page_icon="G", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
  :root { --gh-bg:#f6f8fc; --gh-surface:#ffffff; --gh-text:#162238; --gh-muted:#68768d; --gh-border:#dce3ee; --gh-accent:#315eea; --gh-accent-soft:#e9efff; --gh-sidebar:#10192b; --gh-sidebar-text:#c9d4e8; }
  @media (prefers-color-scheme: dark) { :root { --gh-bg:#0d1422; --gh-surface:#172033; --gh-text:#edf2fb; --gh-muted:#aab7ca; --gh-border:#2b3a53; --gh-accent:#82a2ff; --gh-accent-soft:#1d315f; --gh-sidebar:#090f1b; --gh-sidebar-text:#d5deef; } }
  .stApp { background:var(--gh-bg); color:var(--gh-text); }
  .block-container { max-width:1460px; padding-top:2.15rem; padding-bottom:3rem; }
  [data-testid="stSidebar"] { background:var(--gh-sidebar); border-right:1px solid #26344e; }
  [data-testid="stSidebar"] .stButton>button { width:100%; justify-content:flex-start; border:1px solid transparent; border-radius:9px; background:transparent; color:var(--gh-sidebar-text); font-weight:600; min-height:2.65rem; padding:.45rem .7rem; }
  [data-testid="stSidebar"] .stButton>button:hover { background:#1b2943; color:#ffffff; border-color:#304666; }
  [data-testid="stSidebar"] .stButton>button[kind="primary"] { background:#315eea; color:#ffffff; box-shadow:none; }
  [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color:#94a4be; }
  .brand { font-size:1.28rem; font-weight:750; letter-spacing:-.03em; color:#ffffff; margin-top:.35rem; }
  .eyebrow { color:var(--gh-accent); font-size:.75rem; font-weight:750; letter-spacing:.09em; text-transform:uppercase; }
  .section-title { color:var(--gh-text); font-size:1.78rem; font-weight:750; letter-spacing:-.035em; margin:.1rem 0 .25rem; }
  .section-copy { color:var(--gh-muted); margin-bottom:1.35rem; max-width:760px; }
  [data-testid="stMetric"], [data-testid="stDataFrame"] { background:var(--gh-surface); border:1px solid var(--gh-border); border-radius:12px; }
  [data-testid="stMetric"] { padding:1rem 1.1rem; }
  [data-testid="stMetricLabel"], [data-testid="stMetricValue"] { color:var(--gh-text); }
  .notice { border-left:3px solid var(--gh-accent); background:var(--gh-accent-soft); padding:.8rem 1rem; border-radius:7px; color:var(--gh-text); margin:1rem 0; }
  .empty { background:var(--gh-surface); border:1px dashed var(--gh-border); border-radius:12px; padding:1.6rem; color:var(--gh-muted); text-align:center; }
  [data-testid="stForm"] { background:var(--gh-surface); border:1px solid var(--gh-border); border-radius:12px; padding:1.1rem; }
  [data-testid="stTextInput"] label, [data-testid="stTextArea"] label, [data-testid="stSelectbox"] label { color:var(--gh-text) !important; font-weight:650; }
  [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, [data-baseweb="select"] > div { background:var(--gh-surface) !important; color:var(--gh-text) !important; border-color:var(--gh-border) !important; }
  [data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus { border-color:var(--gh-accent) !important; box-shadow:0 0 0 2px var(--gh-accent-soft) !important; }
  .stButton>button, [data-testid="stFormSubmitButton"] button { border-radius:8px; font-weight:650; }
  .stButton>button[kind="primary"], [data-testid="stFormSubmitButton"] button { background:#315eea; color:#fff; border-color:#315eea; }
  .stButton>button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] button:hover { background:#234bc9; border-color:#234bc9; color:#fff; }
  [data-testid="stTabs"] button { color:var(--gh-muted); font-weight:650; }
  [data-testid="stTabs"] button[aria-selected="true"] { color:var(--gh-accent); }
</style>
""", unsafe_allow_html=True)

api = ApiClient()


def get(path: str):
    try:
        with st.spinner("Consultando datos..."):
            return api.get(path)
    except ApiError as error:
        st.error(f"La API no respondió correctamente: {error}")
        return None


def request(method: str, path: str, payload: dict):
    try:
        result = getattr(api, method)(path, payload)
        st.success("Cambios guardados.")
        return result
    except ApiError as error:
        st.error(f"No se pudo guardar: {error}")
        return None


def empty(message: str):
    st.markdown(f'<div class="empty">{message}</div>', unsafe_allow_html=True)


def heading(title: str, copy: str):
    st.markdown(f'<div class="eyebrow">Growth experimentation</div><div class="section-title">{title}</div><div class="section-copy">{copy}</div>', unsafe_allow_html=True)


st.sidebar.markdown('<div class="brand">Growth Hacking Lab</div>', unsafe_allow_html=True)
st.sidebar.caption("Medición externa y experimentación responsable")
navigation = [
    ("Resumen", ":material/space_dashboard:"),
    ("Campañas", ":material/campaign:"),
    ("Experimentos", ":material/science:"),
    ("Métricas", ":material/monitoring:"),
    ("Tracking", ":material/link:"),
    ("Asistente IA", ":material/psychology:"),
]
if "active_page" not in st.session_state:
    st.session_state.active_page = "Resumen"
for label, icon in navigation:
    if st.sidebar.button(f"{icon}  {label}", key=f"nav_{label}", type="primary" if st.session_state.active_page == label else "secondary"):
        st.session_state.active_page = label
page = st.session_state.active_page
st.sidebar.divider()
st.sidebar.caption(f"API conectada: {os.getenv('API_BASE_URL', 'http://127.0.0.1:8000')}")

if page == "Resumen":
    heading("Panorama del laboratorio", "Indicadores disponibles desde FastAPI. No se estima alcance ni usuarios únicos.")
    system = get("/system/status")
    if system:
        st.subheader("Estado del sistema")
        system_columns = st.columns(len(system["components"]) + 1)
        system_columns[0].metric("Estado general", system["status"])
        for column, component in zip(system_columns[1:], system["components"]):
            column.metric(component["name"], component["status"], help=component["message"])
        if system["status"] != "healthy":
            st.warning("Algún componente crítico no está disponible. Revisa los mensajes de estado antes de operar.")
        st.caption(f"Última comprobación: {system['checked_at']}")
        scheduler = get("/system/scheduler")
        if scheduler:
            st.subheader("Programador de infraestructura")
            scheduler_columns = st.columns(4)
            scheduler_columns[0].metric("Estado", scheduler["status"])
            scheduler_columns[1].metric("Intervalo", f"{scheduler['interval_seconds']} s")
            scheduler_columns[2].metric("Última ejecución", scheduler["last_check"]["started_at"] if scheduler["last_check"] else "Sin ejecuciones")
            scheduler_columns[3].metric("Duración", f"{scheduler['last_check']['duration_ms']} ms" if scheduler["last_check"] and scheduler["last_check"]["duration_ms"] is not None else "No disponible")
            if scheduler["status"] == "not_started":
                st.info("El programador está habilitado, pero todavía no hay evidencia de que haya iniciado.")
            if scheduler["last_heartbeat_at"]:
                st.caption(f"Último heartbeat UTC: {scheduler['last_heartbeat_at']}")
            if scheduler["last_check"]:
                st.caption(f"Resultado: {scheduler['last_check']['status']} · {scheduler['last_check']['message']}")
            if scheduler["next_execution_at"]:
                st.caption(f"Próxima ejecución prevista: {scheduler['next_execution_at']}")
            if scheduler["recent_errors"]:
                st.warning("Hay errores recientes del programador.")
                st.dataframe(scheduler["recent_errors"], use_container_width=True, hide_index=True)
        alerts = get("/system/alerts")
        events = get("/system/events?limit=8")
        if alerts:
            st.subheader("Alertas pendientes")
            for alert in alerts:
                left, right = st.columns([5, 1])
                left.warning(f"{alert['event']['service']} · {alert['event']['severity']} · {alert['event']['description']}")
                if not alert["is_acknowledged"] and right.button("Reconocer", key=f"alert_{alert['id']}"):
                    request("patch", f"/system/alerts/{alert['id']}/acknowledge", {})
                elif alert["is_acknowledged"]:
                    right.caption("Reconocida")
        if events:
            st.subheader("Historial de infraestructura")
            st.dataframe(events, use_container_width=True, hide_index=True)
        else:
            empty("No hay cambios de disponibilidad registrados.")
    summary = get("/dashboard/summary")
    if summary is not None:
        labels = [("Campañas", "campaigns"), ("Experimentos", "experiments"), ("Publicaciones", "posts"), ("Clics propios", "clicks_registered")]
        for column, (label, key) in zip(st.columns(4), labels):
            column.metric(label, summary[key])
        st.markdown('<div class="notice">Clics propios: eventos registrados por infraestructura propia, no alcance, impresiones ni personas únicas.</div>', unsafe_allow_html=True)
        st.subheader("Actividad reciente")
        st.dataframe(summary["recent_experiments"], use_container_width=True, hide_index=True) if summary["recent_experiments"] else empty("Aún no hay experimentos. Crea una campaña y define el primer experimento.")
        attribution = get("/tracking/attribution?group_by=utm_source")
        st.subheader("Distribución de clics por fuente")
        if attribution and attribution["results"]:
            st.bar_chart(attribution["results"], x="dimension", y="clicks_registered")
        else:
            empty("No existen clics propios registrados por fuente.")

elif page == "Campañas":
    heading("Campañas", "Agrupa publicaciones y experimentos bajo un contexto de medición común.")
    left, right = st.columns([1, 1.8])
    with left:
        with st.form("create_campaign", clear_on_submit=True):
            st.subheader("Nueva campaña")
            name = st.text_input("Nombre", placeholder="Ej. Distribución informativa")
            description = st.text_area("Descripción", placeholder="Contexto y alcance del experimento")
            if st.form_submit_button("Crear campaña", use_container_width=True):
                if not name.strip(): st.warning("El nombre es obligatorio.")
                else: request("post", "/campaigns", {"name": name, "description": description or None})
    with right:
        campaigns = get("/campaigns")
        st.subheader("Campañas registradas")
        if campaigns:
            st.dataframe(campaigns, use_container_width=True, hide_index=True)
            selected = st.selectbox("Editar campaña", campaigns, format_func=lambda item: item["name"])
            with st.form("edit_campaign"):
                description = st.text_area("Descripción", value=selected.get("description") or "")
                if st.form_submit_button("Guardar cambios"): request("patch", f"/campaigns/{selected['id']}", {"description": description or None})
        else: empty("No hay campañas registradas.")

elif page == "Experimentos":
    heading("Experimentos", "Diseña, ejecuta y evalúa hipótesis sin inferir causalidad automática.")
    campaigns = get("/campaigns") or []
    if campaigns:
        with st.expander("Diseñar experimento", expanded=False):
            with st.form("create_experiment", clear_on_submit=True):
                campaign = st.selectbox("Campaña", campaigns, format_func=lambda item: item["name"])
                name = st.text_input("Nombre")
                objective = st.text_input("Objetivo")
                hypothesis = st.text_area("Hipótesis")
                variable, channel = st.text_input("Variable"), st.text_input("Canal")
                method = st.text_area("Método")
                criteria = st.text_area("Criterio de éxito")
                starts_at = st.text_input("Inicio ISO 8601", "2026-01-01T00:00:00Z")
                if st.form_submit_button("Crear experimento"):
                    request("post", "/experiments", {"campaign_id": campaign["id"], "name": name, "objective": objective or None, "hypothesis": hypothesis, "variable": variable, "channel": channel or None, "method": method, "success_criteria": criteria or None, "starts_at": starts_at})
    else: empty("Crea una campaña antes de diseñar experimentos.")
    experiments = get("/experiments")
    if experiments:
        st.subheader("Portafolio de experimentos")
        st.dataframe(experiments, use_container_width=True, hide_index=True)
        selected = st.selectbox("Abrir experimento", experiments, format_func=lambda item: f"{item['name']} · {item.get('status', 'draft')}")
        overview, design, execution, evaluation = st.tabs(["Resumen", "Diseño", "Ejecución", "Evaluación"])
        with overview:
            cols = st.columns(3)
            cols[0].metric("Estado", selected.get("status", "draft"))
            cols[1].metric("Canal", selected.get("channel") or "No definido")
            cols[2].metric("Inicio", selected.get("starts_at") or "No definido")
            st.markdown(f"**Objetivo:** {selected.get('objective') or 'No definido'}")
        with design:
            st.markdown(f"**Hipótesis:** {selected['hypothesis']}")
            st.markdown(f"**Variable:** {selected['variable']}")
            st.markdown(f"**Método:** {selected['method']}")
            st.markdown(f"**Criterio de éxito:** {selected.get('success_criteria') or 'No definido'}")
        with execution:
            actions = get(f"/experiments/{selected['id']}/distribution-events")
            st.dataframe(actions, use_container_width=True, hide_index=True) if actions else empty("No hay acciones de distribución registradas.")
            state = st.selectbox("Nuevo estado", ["draft", "planned", "running", "completed", "cancelled"], key="status_update")
            if st.button("Confirmar cambio de estado"): request("patch", f"/experiments/{selected['id']}/status", {"status": state})
        with evaluation:
            result = get(f"/experiments/{selected['id']}/evaluation")
            if result:
                st.metric("Clics propios registrados", result["clicks_registered"])
                st.markdown('<div class="notice">Las métricas observadas pertenecen a publicaciones de campaña y pueden estar compartidas entre experimentos. No son resultados exclusivos.</div>', unsafe_allow_html=True)
                st.dataframe(result["metrics"], use_container_width=True, hide_index=True) if result["metrics"] else empty("No hay suficientes snapshots para una comparación.")
    else: empty("No hay experimentos registrados.")

elif page == "Métricas":
    heading("Métricas observadas", "Likes y comentarios visibles capturados manualmente; no representan alcance ni impresiones.")
    posts = get("/posts") or []
    if posts:
        post = st.selectbox("Publicación", posts, format_func=lambda item: item["canonical_url"])
        for metric in ("visible_likes", "visible_comments"):
            series = get(f"/analytics/observed-metrics?metric_name={metric}&post_id={post['id']}")
            st.subheader(metric.replace("_", " ").title())
            if series and series["points"]:
                st.line_chart(series["points"], x="captured_at", y="value")
                st.caption("Unidad: conteo público observado. Fuente: captura manual.")
            else: empty("No hay observaciones disponibles para esta publicación.")
    else: empty("Registra una publicación y snapshots para ver evolución.")

elif page == "Tracking":
    heading("Tracking propio", "Gestiona enlaces UTM y atribución de eventos propios con límites explícitos.")
    experiments = get("/experiments") or []
    with st.expander("Crear enlace UTM", expanded=False):
        if experiments:
            with st.form("create_tracking", clear_on_submit=True):
                experiment = st.selectbox("Experimento", experiments, format_func=lambda item: item["name"])
                destination = st.text_input("Destino HTTPS autorizado")
                source, medium, campaign = st.text_input("UTM source"), st.text_input("UTM medium"), st.text_input("UTM campaign")
                if st.form_submit_button("Crear enlace"): request("post", "/tracking-links", {"experiment_id": experiment["id"], "destination_url": destination, "utm_source": source, "utm_medium": medium, "utm_campaign": campaign})
        else: empty("Crea un experimento antes de generar enlaces.")
    links = get("/tracking-links")
    if links:
        st.dataframe(links, use_container_width=True, hide_index=True)
        link = st.selectbox("Gestionar enlace", links, format_func=lambda item: item["tracking_url"])
        label = "Desactivar enlace" if link["is_active"] else "Reactivar enlace"
        if st.button(label): request("patch", f"/tracking-links/{link['id']}", {"is_active": not link["is_active"]})
    else: empty("No hay enlaces de tracking.")
    for group in ("utm_source", "utm_medium", "experiment"):
        data = get(f"/tracking/attribution?group_by={group}")
        if data and data["results"]:
            st.subheader(f"Clics por {group}")
            st.bar_chart(data["results"], x="dimension", y="clicks_registered")
    st.caption("Los clics son eventos propios registrados. No son usuarios únicos, alcance ni evidencia causal.")

else:
    heading("Asistente IA", "Inteligencia operativa basada exclusivamente en datos de la plataforma.")
    assistant_status = get("/assistant/status")
    if not assistant_status or assistant_status["status"] != "available":
        state = assistant_status["status"] if assistant_status else "no disponible"
        st.info(f"El asistente IA está {state}. Configura AI_ENABLED=true y una clave del proveedor solo en el backend.")
    else:
        st.caption(f"Proveedor: {assistant_status['provider']} · Modelo: {assistant_status['model']}")
        if "assistant_history" not in st.session_state:
            st.session_state.assistant_history = []
        for item in st.session_state.assistant_history:
            with st.chat_message(item["role"]):
                st.write(item["content"])
        suggestions = ["Resume el estado de infraestructura.", "¿Hay eventos recurrentes?", "¿Qué mantenimiento recomiendas?"]
        selected = st.selectbox("Preguntas sugeridas", [""] + suggestions)
        with st.form("assistant_chat", clear_on_submit=True):
            question = st.text_area("Pregunta", value=selected, max_chars=1000)
            submitted = st.form_submit_button("Consultar asistente")
        if submitted and question.strip():
            try:
                response = api.post("/assistant/chat", {"question": question.strip(), "history": st.session_state.assistant_history[-6:]})
                st.session_state.assistant_history.extend([
                    {"role": "user", "content": question.strip()},
                    {"role": "assistant", "content": response["answer"]},
                ])
                st.subheader("Respuesta")
                st.write(response["answer"])
                for title, key in [("Hechos observados", "observed_facts"), ("Interpretaciones", "interpretations"), ("Recomendaciones", "recommendations"), ("Información insuficiente", "insufficient_information"), ("Referencias", "references")]:
                    if response[key]:
                        st.markdown(f"**{title}:** " + " · ".join(response[key]))
            except ApiError as error:
                st.error(f"El asistente no pudo responder: {error}")
