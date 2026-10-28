import datetime
import pandas as pd
import streamlit as st

# ================= CONFIGURACIÓN DE LA CAMPAÑA (Meta Volante) =================
# Este archivo es un módulo independiente de corta duración: al terminar la
# campaña se elimina (detengase con app.py). La configuración está hardcodeada
# aquí para que borrar el archivo elimine todo el tracking.
#
# Campaña vigente: puntos acumulados por asesor, del 26 al 31 de octubre de 2026.
# El premio es el del nivel más alto alcanzado (no acumulativo).

NOMBRE_CAMPANA = "Meta Volante de Puntos"
SUBTITULO_CAMPANA = "¡SUMA PUNTOS Y GANA!"
FECHA_INICIO = datetime.date(2026, 10, 26)
FECHA_FIN = datetime.date(2026, 10, 31)
MES_CAMPANA = "Octubre"

REGLA_CIERRE = (
    "El premio corresponde al nivel más alto alcanzado según los puntos acumulados "
    "(no acumulativo)."
)

# Escala de premios por puntos (de mayor a menor). El premio puede ser un monto
# en pesos (int) o el nombre de un producto (str).
NIVELES = [
    {"puntos": 100, "premio": 1000000},
    {"puntos": 90, "premio": 900000},
    {"puntos": 80, "premio": 800000},
    {"puntos": 70, "premio": 700000},
    {"puntos": 60, "premio": 500000},
    {"puntos": 50, "premio": "Smartwatch Jincase"},
    {"puntos": 45, "premio": "Smartwatch Honor"},
    {"puntos": 40, "premio": "Audífonos Jincase"},
    {"puntos": 30, "premio": "Tarjeta Adidas"},
]

# Reglas de puntos por tipo de venta.
PUNTOS_EQUIPO_BAJO = 1
PUNTOS_EQUIPO_ALTO = 2
UMBRAL_EQUIPO_ALTO = 1501000

PUNTOS_DTH = 2
PUNTOS_POSPAGO = 2
PUNTOS_ACCESO = 3

# Tipos de venta que corresponden a equipos (se puntúan por valor).
TIPOS_EQUIPO = [
    "Kit Contado",
    "Kit a Cuotas",
    "Reposicion a Cuotas",
    "Reposicion cargo a la factura",
    "Reposicion pago Inmediato",
    "Tecnologia",
]

# Desglose de puntos para mostrar en pantalla (clave -> etiqueta).
DESGLOSE_COLUMNAS = {
    "equipos_1pt": "Eq. 1 pto",
    "equipos_2pt": "Eq. 2 ptos",
    "dth": "DTH",
    "pospagos": "Pospagos",
    "accesos": "Accesos",
}


def consultar_ventas_asesor(cliente, cedula):
    """Consulta todas las ventas del asesor dentro del rango de la campaña.

    Si viene fuera de rango o sin conexión, devuelve lista vacía.
    """
    try:
        respuesta = (
            cliente.table("ventas")
            .select(
                "cedula_vendedor, nombre_vendedor, fecha_venta, tipo_venta, "
                "valor_equipo_claro, acceso"
            )
            .eq("cedula_vendedor", str(cedula))
            .gte("fecha_venta", FECHA_INICIO.isoformat())
            .lte("fecha_venta", FECHA_FIN.isoformat())
            .execute()
        )
        ventas = respuesta.data or []
        # Normalizar fechas a datetime.date (vienen como string ISO)
        for v in ventas:
            try:
                fv = v.get("fecha_venta")
                if isinstance(fv, str):
                    v["fecha_venta"] = datetime.date.fromisoformat(fv[:10])
            except (ValueError, TypeError):
                v["fecha_venta"] = None
        return ventas
    except Exception:
        return []


def calcular_puntos(ventas):
    """Calcula los puntos de la campaña para un conjunto de ventas.

    Reglas:
      - Equipos con valor < $1.501.000: 1 punto.
      - Equipos con valor >= $1.501.000: 2 puntos.
      - DTH (Hogar sin acceso): 2 puntos.
      - Pospagos: 2 puntos.
      - Accesos (Hogar con acceso == 'SI'): 3 puntos.

    Devuelve dict con el desglose y el total en la clave ``puntos``.
    """
    desglose = {clave: 0 for clave in DESGLOSE_COLUMNAS}
    for venta in ventas:
        tv = venta.get("tipo_venta")
        if tv == "Postpago":
            desglose["pospagos"] += 1
        elif tv == "Hogar":
            if str(venta.get("acceso") or "").strip().upper() == "SI":
                desglose["accesos"] += 1
            else:
                desglose["dth"] += 1
        elif tv in TIPOS_EQUIPO:
            try:
                valor = float(venta.get("valor_equipo_claro") or 0)
            except (TypeError, ValueError):
                valor = 0
            if valor >= UMBRAL_EQUIPO_ALTO:
                desglose["equipos_2pt"] += 1
            elif valor > 0:
                desglose["equipos_1pt"] += 1

    desglose["puntos"] = (
        desglose["equipos_1pt"] * PUNTOS_EQUIPO_BAJO
        + desglose["equipos_2pt"] * PUNTOS_EQUIPO_ALTO
        + desglose["dth"] * PUNTOS_DTH
        + desglose["pospagos"] * PUNTOS_POSPAGO
        + desglose["accesos"] * PUNTOS_ACCESO
    )
    return desglose


def nivel_alcanzado(puntos):
    """Devuelve el nivel de premio más alto alcanzado (o None)."""
    for nivel in NIVELES:
        if puntos >= nivel["puntos"]:
            return nivel
    return None


def siguiente_nivel(puntos):
    """Devuelve el siguiente nivel por alcanzar (o None si ya es el máximo)."""
    pendientes = [n for n in NIVELES if puntos < n["puntos"]]
    return pendientes[-1] if pendientes else None


def formatear_premio(premio):
    """Formatea un premio: monto en pesos o nombre de producto."""
    if isinstance(premio, (int, float)):
        return f"${int(premio):,}".replace(",", ".")
    return str(premio)


def _encabezado(titulo, subtitulo):
    st.markdown(
        f"""
        <div style="text-align:center; padding:24px; border:2px solid #DA291C;
                    border-radius:12px; background:linear-gradient(135deg,#FFF0EF,#FFFFFF);">
            <div style="font-size:30px; font-weight:bold; color:#DA291C;">
                🏆 {titulo}
            </div>
            <div style="font-size:18px; color:#DA291C; margin-top:4px;">
                {subtitulo}
            </div>
            <div style="font-size:15px; color:#666; margin-top:10px;">
                Del {FECHA_INICIO.day} al {FECHA_FIN.day} de {MES_CAMPANA}
            </div>
            <div style="font-size:13px; color:#888; margin-top:4px; font-style:italic;">
                {REGLA_CIERRE}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _tabla_niveles(puntos):
    """Tabla con la escala de premios y el estado de cada nivel."""
    filas = []
    for nivel in NIVELES:
        cumplido = puntos >= nivel["puntos"]
        filas.append({
            "Puntos": nivel["puntos"],
            "Premio": formatear_premio(nivel["premio"]),
            "Estado": "✓ Alcanzado" if cumplido else "Pendiente",
        })
    st.dataframe(
        pd.DataFrame(filas),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Puntos": st.column_config.NumberColumn("Puntos"),
            "Premio": st.column_config.TextColumn("Premio"),
            "Estado": st.column_config.TextColumn("Estado"),
        },
    )


def render_meta_volante(cliente, cedula, nombre_asesor):
    """Muestra el tracking de la Meta Volante para el asesor logueado.

    Llamada desde app.py tras elegir PDV (pantalla intermedia). Si hoy está
    fuera del rango de la campaña, muestra un aviso y no renderiza.
    """
    hoy = datetime.date.today()

    st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
    _encabezado(NOMBRE_CAMPANA, SUBTITULO_CAMPANA)

    if hoy < FECHA_INICIO or hoy > FECHA_FIN:
        st.info("📅 La campaña Meta Volante no está activa en esta fecha.")
        return

    st.markdown(
        f"""
        <div class="nombre-vendedor" style="margin-top:18px;">
            👤 Asesor: {nombre_asesor} ({cedula})
        </div>
        """,
        unsafe_allow_html=True,
    )

    ventas_asesor = consultar_ventas_asesor(cliente, cedula)
    desglose = calcular_puntos(ventas_asesor)
    puntos = desglose["puntos"]

    st.markdown("---")

    col_puntos, col_premio = st.columns([1, 1])
    with col_puntos:
        st.metric("PUNTOS ACUMULADOS", f"{puntos}")
    with col_premio:
        nivel = nivel_alcanzado(puntos)
        if nivel is not None:
            st.metric("PREMIO ACTUAL", formatear_premio(nivel["premio"]))
        else:
            minimo = NIVELES[-1]["puntos"]
            st.metric("PREMIO ACTUAL", "Sin premio", help=f"Necesitas al menos {minimo} puntos")

    progreso = min(puntos / 100, 1.0)
    st.progress(progreso)

    cercano = siguiente_nivel(puntos)
    if cercano is not None:
        faltan = cercano["puntos"] - puntos
        st.caption(
            f"Te faltan **{faltan} puntos** para alcanzar "
            f"**{formatear_premio(cercano['premio'])}** ({cercano['puntos']} puntos)."
        )
    else:
        st.success("🏁 ¡Nivel máximo alcanzado!")

    st.markdown("### 🎯 Puntos por tipo de venta")
    st.markdown(
        f"""
        - Equipos menores a $1.500.000: **{PUNTOS_EQUIPO_BAJO} punto**
        - Equipos mayores a $1.501.000: **{PUNTOS_EQUIPO_ALTO} puntos**
        - DTH: **{PUNTOS_DTH} puntos**
        - Pospagos: **{PUNTOS_POSPAGO} puntos**
        - Accesos: **{PUNTOS_ACCESO} puntos**
        """
    )

    resumen = pd.DataFrame([{
        DESGLOSE_COLUMNAS[clave]: desglose[clave]
        for clave in DESGLOSE_COLUMNAS
    }])
    st.dataframe(resumen, use_container_width=True, hide_index=True)

    st.markdown("### 🏆 Escala de premios")
    _tabla_niveles(puntos)

    st.markdown("---")
    st.caption(f"Ventas registradas por el asesor durante la campaña: **{len(ventas_asesor)}**")


def resultados_meta_volante(cliente, asesores):
    """Muestra los resultados finales de la campaña para los administradores.

    Tabla con TODOS los asesores (los que no registraron ventas en la campaña
    aparecen con 0 puntos) y bloque de ganadores. Solo se muestra cuando la
    campaña ya terminó (hoy > FECHA_FIN).
    """
    hoy = datetime.date.today()

    st.markdown("---")
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div style="text-align:center; padding:20px; border:2px solid #DA291C;
                    border-radius:12px; background:linear-gradient(135deg,#FFF0EF,#FFFFFF);">
            <div style="font-size:26px; font-weight:bold; color:#DA291C;">
                🏆 Resultados Meta Volante
            </div>
            <div style="font-size:15px; color:#666; margin-top:8px;">
                Campaña del {FECHA_INICIO.day} al {FECHA_FIN.day} de {MES_CAMPANA} {FECHA_INICIO.year} — cierre de resultados
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if hoy <= FECHA_FIN:
        st.info("📅 La campaña aún no ha terminado. Los resultados se publicarán al cierre.")
        return

    respuesta = cliente.table("ventas").select(
        "cedula_vendedor, nombre_vendedor, fecha_venta, tipo_venta, "
        "valor_equipo_claro, acceso"
    ).gte("fecha_venta", FECHA_INICIO.isoformat()).lte("fecha_venta", FECHA_FIN.isoformat()).execute()
    ventas_totales = respuesta.data or []

    ventas_por_asesor = {}
    for v in ventas_totales:
        cedula = str(v.get("cedula_vendedor") or "").strip()
        if not cedula:
            continue
        ventas_por_asesor.setdefault(cedula, []).append(v)

    # Asegurar que aparezcan todos los asesores registrados, aunque no vendan.
    for cedula in asesores:
        ventas_por_asesor.setdefault(str(cedula).strip(), [])

    minimo = NIVELES[-1]["puntos"]

    filas = []
    for cedula, ventas_asesor in ventas_por_asesor.items():
        desglose = calcular_puntos(ventas_asesor)
        puntos = desglose["puntos"]
        nivel = nivel_alcanzado(puntos)
        nombre = asesores.get(cedula)
        if not nombre:
            nombres_venta = [v.get("nombre_vendedor") for v in ventas_asesor if v.get("nombre_vendedor")]
            nombre = nombres_venta[0] if nombres_venta else "Sin nombre"
        fila = {
            "CC": cedula,
            "Asesor": nombre,
            "Ventas": len(ventas_asesor),
        }
        for clave, etiqueta in DESGLOSE_COLUMNAS.items():
            fila[etiqueta] = desglose[clave]
        fila["Puntos"] = puntos
        fila["Premio"] = formatear_premio(nivel["premio"]) if nivel else "Sin premio"
        fila["Ganador"] = "Sí" if nivel else "No"
        filas.append(fila)

    if not filas:
        st.info("No hay asesores ni ventas registradas para esta campaña.")
        return

    df_res = pd.DataFrame(filas)
    df_res = df_res.sort_values(["Puntos", "Ventas"], ascending=False, ignore_index=True)

    # ===== Bloque de ganadores =====
    ganadores = df_res[df_res["Puntos"] >= minimo] if not df_res.empty else df_res
    st.markdown("### 🎖️ Ganadores")
    if ganadores.empty:
        st.info(f"Ningún asesor alcanzó el mínimo de {minimo} puntos.")
    else:
        cols = st.columns(min(len(ganadores), 3))
        for col, (_, fila) in zip(cols, ganadores.head(3).iterrows()):
            with col:
                st.metric(
                    label=f"🏆 {fila['Asesor']}",
                    value=f"{int(fila['Puntos'])} puntos",
                    delta=fila["Premio"],
                    help=f"CC: {fila['CC']}",
                )

    # ===== Tabla resumen general (todos los asesores) =====
    st.markdown("### 📊 Resumen por Asesor")

    def resaltar_ganador(fila):
        return ["background-color: #E8F5E9; font-weight: bold;" if fila["Ganador"] == "Sí" else "" for _ in fila]

    df_estilo = df_res.style.apply(resaltar_ganador, axis=1)
    st.dataframe(df_estilo, use_container_width=True, hide_index=True)

    st.caption(
        f"🏁 Se resaltan en verde los asesores que alcanzaron al menos {minimo} puntos. "
        "El premio corresponde al nivel más alto alcanzado (no acumulativo). "
        "Los asesores sin registro en la campaña aparecen con 0 puntos."
    )
