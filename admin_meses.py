# -*- coding: utf-8 -*-
"""Módulo de histórico mensual para los administradores (CEDULAS_ADMIN).

Permite consultar la información de meses anteriores con un filtro de mes:
resumen por tipo de transacción, ventas por asesor, metas del periodo, dinero
recibido por método de pago, tendencia de los últimos meses, detalle de
registros (con exportación a CSV) y las ventas pendientes por facturar.

Módulo independiente de app.py (patrón similar a admin_correcciones.py): recibe
el cliente de Supabase y renderiza con Streamlit. Las reglas de cálculo del
avance contra metas NO se duplican aquí: se reciben de app.py las funciones
`calcular_avance` y `calcular_avance_por_asesor` (que filtran por el año/mes de
la fecha que reciben), por eso se les entrega una fecha cualquiera del mes
elegido y las ventas ya filtradas por ese mes.
"""

import datetime

import pandas as pd
import streamlit as st

from facturacion import (
    cargar_facturas_csv,
    cargar_facturas_postpago,
    calcular_estado_facturacion,
)

ES_MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# PostgREST (Supabase) limita a 1000 filas por respuesta: se pagina.
FILAS_PAGINA = 1000
MAX_PAGINAS = 50
MESES_TENDENCIA = 6

# Columnas mostradas en el detalle de registros (mismas que el historial de app.py)
COLUMNAS_DETALLE = [
    "fecha_venta", "nombre_vendedor", "tipo_venta", "punto_venta", "nombre_cliente",
    "tipo_documento", "nro_documento", "contacto_cliente",
    "referencia", "imei", "iccid", "min", "plan",
    "valor_equipo", "valor_pagado_cliente", "financiera", "recibido_en",
]


# ================= UTILIDADES =================
def _nombre_mes(anio, mes):
    """'2026-08' -> 'Agosto 2026'."""
    return f"{ES_MESES.get(mes, mes)} {anio}"


def _etiqueta_periodo(periodo):
    """'2026-08' -> 'Agosto 2026' (acepta 'YYYY-MM' o 'YYYY-MM-DD')."""
    try:
        partes = str(periodo).split("-")
        return _nombre_mes(int(partes[0]), int(partes[1]))
    except (IndexError, ValueError):
        return str(periodo)


def _dinero(valor):
    return f"${int(round(valor or 0)):,}".replace(",", ".")


def _etiqueta_asesor(venta, dict_asesores):
    """Nombre del asesor de la venta; si no viene, se resuelve por cédula."""
    nombre = str(venta.get("nombre_vendedor") or "").strip()
    if nombre:
        return nombre
    cedula = str(venta.get("cedula_vendedor") or "").strip()
    if cedula:
        return dict_asesores.get(cedula, cedula)
    return "SIN ASESOR"


def _normalizar_fecha(venta):
    """Convierte fecha_venta (ISO str) a datetime.date. Modifica la venta."""
    fv = venta.get("fecha_venta")
    if isinstance(fv, str):
        try:
            venta["fecha_venta"] = datetime.date.fromisoformat(fv[:10])
        except ValueError:
            pass


# ================= CONSULTAS A SUPABASE =================
def cargar_ventas_historicas(cliente, tabla_ventas):
    """Descarga todas las ventas (paginadas) y normaliza fecha_venta.
    Retorna (lista de ventas, error)."""
    ventas = []
    for pagina in range(MAX_PAGINAS):
        desde = pagina * FILAS_PAGINA
        try:
            respuesta = (
                cliente.table(tabla_ventas)
                .select("*")
                .order("fecha_venta", desc=True)
                .range(desde, desde + FILAS_PAGINA - 1)
                .execute()
            )
        except Exception as e:
            if pagina == 0:
                return [], str(e)
            break
        lote = respuesta.data or []
        ventas.extend(lote)
        if len(lote) < FILAS_PAGINA:
            break

    for venta in ventas:
        _normalizar_fecha(venta)
    return ventas, None


def cargar_metas_periodo(cliente, periodo):
    """Consulta todas las metas de un periodo ('YYYY-MM'). Retorna (lista, error)."""
    try:
        respuesta = cliente.table("metas").select("*").eq("periodo", periodo).execute()
        return (respuesta.data or []), None
    except Exception as e:
        return [], str(e)


def meses_con_ventas(ventas):
    """Lista de (anio, mes) con ventas registradas, del más reciente al más antiguo."""
    vistos = set()
    for venta in ventas:
        fv = venta.get("fecha_venta")
        if isinstance(fv, datetime.date):
            vistos.add((fv.year, fv.month))
    return sorted(vistos, reverse=True)


# ================= SECCIONES DE LA PESTAÑA =================
def _resumen_por_tipo(ventas_mes):
    """DataFrame: ventas, valor de equipo y valor pagado por tipo de transacción."""
    if not ventas_mes:
        return pd.DataFrame()
    df = pd.DataFrame(ventas_mes)
    df["valor_equipo"] = pd.to_numeric(df.get("valor_equipo"), errors="coerce").fillna(0)
    df["valor_pagado_cliente"] = pd.to_numeric(df.get("valor_pagado_cliente"), errors="coerce").fillna(0)
    df["tipo_venta"] = df["tipo_venta"].fillna("SIN TIPO")
    df = (
        df.groupby("tipo_venta", dropna=False)
        .agg(
            Ventas=("tipo_venta", "size"),
            **{"Equipo ($)": ("valor_equipo", "sum"), "Pagado ($)": ("valor_pagado_cliente", "sum")},
        )
        .reset_index()
        .rename(columns={"tipo_venta": "Tipo de Transacción"})
        .sort_values("Ventas", ascending=False, ignore_index=True)
    )
    fila_total = pd.DataFrame([{
        "Tipo de Transacción": "TOTAL",
        "Ventas": int(df["Ventas"].sum()),
        "Equipo ($)": float(df["Equipo ($)"].sum()),
        "Pagado ($)": float(df["Pagado ($)"].sum()),
    }])
    return pd.concat([df, fila_total], ignore_index=True)


def _crosstab_por_asesor(ventas_mes, campo, titulo):
    """Crosstab ventas por asesor x valor de `campo`, con totales."""
    datos = [
        v for v in ventas_mes
        if v.get(campo) and str(v.get(campo)).strip()
    ]
    if not datos:
        return
    st.markdown(f"**{titulo}**")
    df_pivot = pd.crosstab(
        index=pd.Series([_etiqueta_asesor(v, {}) for v in datos]),
        columns=pd.Series([v[campo] for v in datos]),
        margins=True,
        margins_name="TOTAL",
    )
    df_pivot.index.name = "Asesor"
    df_pivot.columns.name = None
    st.dataframe(df_pivot, use_container_width=True)


def _tabla_metas(ventas_mes, anio, mes, dict_asesores, cliente,
                 calcular_avance_por_asesor, period_label):
    """Metas del periodo vs avance real de cada asesor."""
    metas, error = cargar_metas_periodo(cliente, period_label)
    if error:
        st.error(f"❌ Error al consultar las metas: {error}")
        return
    if not metas:
        st.info(f"📭 No hay metas cargadas para {_nombre_mes(anio, mes)}.")
        return

    # Se pasa una fecha del mes elegido: las funciones de app.py filtran por año/mes
    fecha_ref = datetime.date(anio, mes, 1)
    avance_por_asesor = calcular_avance_por_asesor(ventas_mes, fecha_ref)

    def celda(avance_val, meta_val, es_dinero=False):
        if meta_val <= 0:
            return "—"
        pct = (avance_val / meta_val * 100) if meta_val else 0
        fmt = (lambda x: _dinero(x)) if es_dinero else (lambda x: f"{int(x)}")
        return f"{fmt(avance_val)}/{fmt(meta_val)} ({pct:.0f}%)"

    filas = []
    for m in metas:
        cedula = str(m.get("cedula_vendedor") or "").strip()
        nombre = dict_asesores.get(cedula, cedula)
        av = avance_por_asesor.get(
            cedula, {"pospago": 0, "accesos": 0, "hogar": 0, "terminales": 0, "claro_up": 0}
        )
        filas.append({
            "Asesor": nombre,
            "Cédula": cedula,
            "Postpago": celda(av["pospago"], float(m.get("pospago") or 0)),
            "Hogar": celda(av["hogar"], float(m.get("hogar") or 0)),
            "Accesos": celda(av["accesos"], float(m.get("accesos") or 0)),
            "Terminales": celda(av["terminales"], float(m.get("terminales") or 0), es_dinero=True),
            "Claro Up": celda(av["claro_up"], float(m.get("claro_up") or 0)),
        })

    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
    st.download_button(
        label="📥 Exportar Metas del Mes (CSV)",
        data=pd.DataFrame(filas).to_csv(index=False).encode("utf-8"),
        file_name=f"metas_{anio}-{mes:02d}.csv",
        mime="text/csv",
    )


def _tablas_dinero(ventas_mes):
    """Dinero recibido por método de pago, desagregado por asesor y por PDV."""
    ventas_pago = [
        v for v in ventas_mes
        if v.get("valor_pagado_cliente") and float(v["valor_pagado_cliente"] or 0) > 0
        and v.get("recibido_en")
    ]
    if not ventas_pago:
        return

    def pivot(indice, nombre_indice, etiqueta):
        datos = [v for v in ventas_pago if v.get(indice)]
        if not datos:
            return None
        df = pd.DataFrame(datos)
        df[indice] = df[indice].map(etiqueta)
        df = df.pivot_table(
            index=indice,
            columns="recibido_en",
            values="valor_pagado_cliente",
            aggfunc="sum",
            fill_value=0,
            margins=True,
            margins_name="TOTAL",
        )
        df.index.name = nombre_indice
        df.columns.name = None
        return df

    df_asesor = pivot("nombre_vendedor", "Asesor", lambda val: _etiqueta_asesor({"nombre_vendedor": val}, {}))
    df_pdv = pivot("punto_venta", "PDV", lambda val: val)
    if df_asesor is None and df_pdv is None:
        return

    st.subheader("💵 Dinero Recibido por Método de Pago")
    c_asesor, c_pdv = st.columns(2)
    with c_asesor:
        if df_asesor is not None:
            st.markdown("**Por Asesor**")
            st.dataframe(df_asesor, use_container_width=True)
    with c_pdv:
        if df_pdv is not None:
            st.markdown("**Por PDV**")
            st.dataframe(df_pdv, use_container_width=True)


def _tendencia(ventas, meses):
    """Gráfico de ventas de los últimos meses con datos (sin aplicar filtros)."""
    ultimos = meses[:MESES_TENDENCIA]
    if len(ultimos) < 2:
        return
    filas = []
    for anio, mes in ultimos:
        ventas_mes = [
            v for v in ventas
            if isinstance(v.get("fecha_venta"), datetime.date)
            and v["fecha_venta"].year == anio and v["fecha_venta"].month == mes
        ]
        equipo = sum(float(v.get("valor_equipo") or 0) for v in ventas_mes)
        pagado = sum(float(v.get("valor_pagado_cliente") or 0) for v in ventas_mes)
        filas.append({
            "Mes": _nombre_mes(anio, mes),
            "Ventas": len(ventas_mes),
            "Equipo ($)": int(equipo),
            "Pagado ($)": int(pagado),
        })
    df = pd.DataFrame(filas)
    with st.expander(f"📈 Tendencia de los últimos {len(ultimos)} meses"):
        st.caption("Vista rápida sin filtros de asesor/PDV. Use la tabla para el detalle monetario.")
        st.bar_chart(df.set_index("Mes")[["Ventas"]], y="Ventas", color="#DA291C")
        st.dataframe(
            df.set_index("Mes"),
            use_container_width=True,
            column_config={
                "Equipo ($)": st.column_config.NumberColumn("Equipo ($)", format="$ %.0f"),
                "Pagado ($)": st.column_config.NumberColumn("Pagado ($)", format="$ %.0f"),
            },
        )


def _estado_facturacion_pendiente(ventas_mes, anio, mes):
    """Cruza las ventas del mes contra los CSV de facturación y lista solo las
    que quedaron PENDIENTES por facturar (columna 'Facturado' == 'NO')."""
    df_fact = cargar_facturas_csv()
    df_post = cargar_facturas_postpago()

    st.subheader("🧾 Estado de Facturación del Mes - Pendientes")
    if df_fact is None and df_post is None:
        st.info("📁 No se encontraron 'FacturadoParaCruce.csv' ni 'Facturado_Postpago.csv' en el proyecto.")
        return

    fecha_ref = datetime.date(anio, mes, 1)
    df_facturacion = calcular_estado_facturacion(ventas_mes, fecha_ref, df_fact, df_post)
    st.caption(
        "Solo ventas sin facturar según los CSV de facturación del proyecto. "
        "Sim card, Tecnología y Hogar se excluyen."
    )

    pendientes = df_facturacion[df_facturacion["Facturado"] == "NO"] if not df_facturacion.empty else df_facturacion
    if pendientes.empty:
        st.success("✅ No hay ventas pendientes por facturar en el mes seleccionado.")
        return

    st.markdown(f"**Ventas pendientes por facturar: {len(pendientes)}**")
    st.dataframe(pendientes, use_container_width=True, hide_index=True, height=420)
    st.download_button(
        label="📥 Exportar Pendientes por Facturar (CSV)",
        data=pendientes.to_csv(index=False).encode("utf-8"),
        file_name=f"pendientes_facturar_{anio}-{mes:02d}.csv",
        mime="text/csv",
    )


# ================= PESTAÑA =================
def render_admin_meses(cliente, dict_asesores, tabla_ventas, calcular_avance_por_asesor):
    """Renderiza la pestaña de histórico mensual (solo administradores).

    - `cliente`: cliente de Supabase.
    - `dict_asesores`: dict {cedula: nombre} para resolver nombres.
    - `tabla_ventas`: nombre de la tabla de ventas.
    - `calcular_avance_por_asesor`: función de app.py (recibe las ventas del
      mes y una fecha de referencia de ese mes).
    """
    st.subheader("📅 Histórico por Mes")

    ventas, error = cargar_ventas_historicas(cliente, tabla_ventas)
    if error:
        st.error(f"❌ Error al consultar las ventas en Supabase: {error}")
        return
    if not ventas:
        st.info("📭 No hay ventas registradas en la base de datos.")
        return

    meses = meses_con_ventas(ventas)
    if not meses:
        st.info("📭 No hay ventas con fecha válida para mostrar.")
        return

    # ================= FILTROS =================
    opciones_mes = [_nombre_mes(a, m) for a, m in meses]
    f1, f2 = st.columns(2)
    with f1:
        mes_sel = st.selectbox("📅 Mes a consultar", options=opciones_mes, index=0)
    idx_mes = opciones_mes.index(mes_sel)
    anio, mes = meses[idx_mes]

    ventas_periodo = [
        v for v in ventas
        if isinstance(v.get("fecha_venta"), datetime.date)
        and v["fecha_venta"].year == anio and v["fecha_venta"].month == mes
    ]

    etiquetas_asesor = sorted({_etiqueta_asesor(v, dict_asesores) for v in ventas_periodo})
    etiquetas_tipo = sorted({
        str(v.get("tipo_venta")).strip()
        for v in ventas_periodo if v.get("tipo_venta")
    })
    etiquetas_pdv = sorted({
        str(v.get("punto_venta")).strip()
        for v in ventas_periodo if v.get("punto_venta")
    })
    with f2:
        filtro_asesor = st.multiselect("👤 Filtrar por Asesor", options=etiquetas_asesor)
    f3, f4 = st.columns(2)
    with f3:
        filtro_pdv = st.multiselect("📍 Filtrar por PDV", options=etiquetas_pdv)
    with f4:
        filtro_tipo = st.multiselect("🏷️ Filtrar por Tipo de Transacción", options=etiquetas_tipo)

    ventas_mes = ventas_periodo
    if filtro_asesor:
        ventas_mes = [
            v for v in ventas_mes
            if _etiqueta_asesor(v, dict_asesores) in filtro_asesor
        ]
    if filtro_pdv:
        ventas_mes = [v for v in ventas_mes if str(v.get("punto_venta") or "").strip() in filtro_pdv]
    if filtro_tipo:
        ventas_mes = [v for v in ventas_mes if str(v.get("tipo_venta") or "").strip() in filtro_tipo]

    st.caption(
        f"👑 Modo Administrador: mostrando las ventas de **{mes_sel}**"
        + (f" · {len(ventas_mes)} de {len(ventas_periodo)} registros luego de los filtros" if (filtro_asesor or filtro_pdv or filtro_tipo) else "")
    )

    # ================= MÉTRICAS DEL MES =================
    total_equipo = sum(float(v.get("valor_equipo") or 0) for v in ventas_mes)
    total_pagado = sum(float(v.get("valor_pagado_cliente") or 0) for v in ventas_mes)
    n_asesores = len({str(v.get("cedula_vendedor") or "") for v in ventas_mes if v.get("cedula_vendedor")})

    # Comparación contra el mes inmediatamente anterior que tenga datos
    idx_previo = idx_mes + 1
    tiene_previo = idx_previo < len(meses)
    if tiene_previo:
        a_prev, m_prev = meses[idx_previo]
        ventas_previas = [
            v for v in ventas
            if isinstance(v.get("fecha_venta"), datetime.date)
            and v["fecha_venta"].year == a_prev and v["fecha_venta"].month == m_prev
        ]
        previo_ventas = len(ventas_previas)
        previo_equipo = sum(float(v.get("valor_equipo") or 0) for v in ventas_previas)
        previo_pagado = sum(float(v.get("valor_pagado_cliente") or 0) for v in ventas_previas)
        etq_previo = _nombre_mes(a_prev, m_prev)
    else:
        previo_ventas = previo_equipo = previo_pagado = 0
        etq_previo = None

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "📦 Ventas del Mes",
        value=len(ventas_mes),
        delta=f"{len(ventas_mes) - previo_ventas:+d} vs {etq_previo}" if tiene_previo else None,
    )
    m2.metric(
        "💵 Total Equipo",
        value=_dinero(total_equipo),
        delta=f"{_dinero(total_equipo - previo_equipo)} vs {etq_previo}" if tiene_previo else None,
    )
    m3.metric(
        "💰 Total Pagado",
        value=_dinero(total_pagado),
        delta=f"{_dinero(total_pagado - previo_pagado)} vs {etq_previo}" if tiene_previo else None,
    )
    m4.metric("👥 Asesores con ventas", value=n_asesores)

    if not ventas_mes:
        st.info("📭 No hay ventas para el mes seleccionado con los filtros aplicados.")
        return

    # ================= RESUMEN POR TIPO =================
    st.markdown("---")
    st.subheader(f"📊 Resumen de Ventas - {mes_sel}")
    col_tipo, col_asesores = st.columns([3, 7])
    with col_tipo:
        st.markdown("**Resumen por Tipo de Transacción**")
        st.dataframe(
            _resumen_por_tipo(ventas_mes),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Equipo ($)": st.column_config.NumberColumn("Equipo ($)", format="$ %.0f"),
                "Pagado ($)": st.column_config.NumberColumn("Pagado ($)", format="$ %.0f"),
            },
        )
    with col_asesores:
        st.markdown("**Ventas por Asesor y Tipo de Transacción**")
        _crosstab_por_asesor(ventas_mes, "tipo_venta", "")
        st.markdown("**Ventas por Asesor y Financiera**")
        _crosstab_por_asesor(ventas_mes, "financiera", "")

    st.markdown("**Ventas por Punto de Venta**")
    df_pdv = (
        pd.DataFrame([v for v in ventas_mes if v.get("punto_venta")])
        .assign(
            valor_equipo=lambda d: pd.to_numeric(d.get("valor_equipo"), errors="coerce").fillna(0),
            valor_pagado_cliente=lambda d: pd.to_numeric(d.get("valor_pagado_cliente"), errors="coerce").fillna(0),
        )
        .groupby("punto_venta")
        .agg(Ventas=("punto_venta", "size"), **{"Equipo ($)": ("valor_equipo", "sum"), "Pagado ($)": ("valor_pagado_cliente", "sum")})
        .reset_index()
        .rename(columns={"punto_venta": "PDV"})
        .sort_values("Ventas", ascending=False, ignore_index=True)
    )
    if not df_pdv.empty:
        st.dataframe(
            df_pdv,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Equipo ($)": st.column_config.NumberColumn("Equipo ($)", format="$ %.0f"),
                "Pagado ($)": st.column_config.NumberColumn("Pagado ($)", format="$ %.0f"),
            },
        )

    # ================= METAS DEL PERIODO =================
    st.markdown("---")
    st.markdown("### 🎯 Metas del Mes - Todos los Asesores")
    st.caption(f"Avance / Meta ({anio}-{mes:02d})")
    _tabla_metas(
        ventas_mes, anio, mes, dict_asesores, cliente,
        calcular_avance_por_asesor, f"{anio}-{mes:02d}",
    )

    # ================= DINERO RECIBIDO =================
    _tablas_dinero(ventas_mes)

    # ================= TENDENCIA =================
    st.markdown("---")
    _tendencia(ventas, meses)

    # ================= DETALLE DE REGISTROS =================
    st.markdown("---")
    st.subheader(f"📋 Detalle de Ventas - {mes_sel}")
    df_detalle = pd.DataFrame(ventas_mes).sort_values("fecha_venta", ascending=False)
    columnas = [c for c in COLUMNAS_DETALLE if c in df_detalle.columns]
    st.markdown(f"**Registros encontrados: {len(df_detalle)}**")
    st.dataframe(
        df_detalle[columnas],
        use_container_width=True,
        hide_index=True,
        height=420,
        column_config={
            "fecha_venta": st.column_config.DateColumn("Fecha Venta", format="DD/MM/YYYY"),
            "valor_equipo": st.column_config.NumberColumn("Valor Equipo ($)", format="$ %.0f"),
            "valor_pagado_cliente": st.column_config.NumberColumn("Pagado Cliente ($)", format="$ %.0f"),
        },
    )
    st.download_button(
        label="📥 Exportar Reporte del Mes (CSV)",
        data=df_detalle.to_csv(index=False).encode("utf-8"),
        file_name=f"reporte_ventas_{anio}-{mes:02d}.csv",
        mime="text/csv",
    )

    # ================= ESTADO DE FACTURACIÓN (SOLO PENDIENTES) =================
    st.markdown("---")
    _estado_facturacion_pendiente(ventas_mes, anio, mes)
