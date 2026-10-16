# -*- coding: utf-8 -*-
"""Módulo de Contabilidad.

Tercer rol del portal (además de asesor y administrador): acceso de solo
consulta/reportería. Permite descargar el reporte de ventas del mes y el
cumplimiento de presupuesto (metas) por asesor. No registra ventas, no
selecciona PDV y no edita datos.

Reutiliza las utilidades de `admin_meses.py` (paginación de Supabase, meses con
ventas y la tabla de metas) para no duplicar lógica. Las reglas de cálculo de
avance NO se duplican: `calcular_avance_por_asesor` llega desde `app.py`.
"""

import datetime

import pandas as pd
import streamlit as st

from admin_meses import (
    COLUMNAS_DETALLE,
    _nombre_mes,
    _tabla_metas,
    cargar_ventas_historicas,
    meses_con_ventas,
)


def _seccion_reporte_ventas(ventas_mes, anio, mes):
    """Detalle de ventas del mes con métricas y exportación a CSV."""
    st.subheader(f"📥 Reporte de Ventas — {_nombre_mes(anio, mes)}")
    if not ventas_mes:
        st.info(f"📭 No hay ventas registradas en {_nombre_mes(anio, mes)}.")
        return

    total_equipo = sum(float(v.get("valor_equipo") or 0) for v in ventas_mes)
    total_pagado = sum(float(v.get("valor_pagado_cliente") or 0) for v in ventas_mes)
    n_asesores = len({
        str(v.get("cedula_vendedor") or "")
        for v in ventas_mes if v.get("cedula_vendedor")
    })

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📦 Ventas del Mes", value=len(ventas_mes))
    m2.metric("💵 Total Equipo", value=f"${total_equipo:,.0f}")
    m3.metric("💰 Total Pagado", value=f"${total_pagado:,.0f}")
    m4.metric("👥 Asesores con ventas", value=n_asesores)

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
        label="📥 Descargar Reporte de Ventas (CSV)",
        data=df_detalle.to_csv(index=False).encode("utf-8"),
        file_name=f"reporte_ventas_{anio}-{mes:02d}.csv",
        mime="text/csv",
    )


def render_contabilidad(cliente, dict_asesores, tabla_ventas, calcular_avance_por_asesor):
    """Renderiza el módulo de contabilidad (rol de solo consulta).

    - `cliente`: cliente de Supabase.
    - `dict_asesores`: dict {cedula: nombre} para resolver nombres.
    - `tabla_ventas`: nombre de la tabla de ventas.
    - `calcular_avance_por_asesor`: función de app.py (recibe las ventas del
      mes y una fecha de referencia de ese mes).
    """
    st.subheader("🧾 Módulo de Contabilidad")
    st.caption(
        "Acceso de solo consulta: descarga del reporte de ventas y del "
        "cumplimiento de presupuesto por asesor."
    )

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

    opciones_mes = [_nombre_mes(a, m) for a, m in meses]
    mes_sel = st.selectbox("📅 Mes a consultar", options=opciones_mes, index=0)
    anio, mes = meses[opciones_mes.index(mes_sel)]
    periodo = f"{anio}-{mes:02d}"

    ventas_mes = [
        v for v in ventas
        if isinstance(v.get("fecha_venta"), datetime.date)
        and v["fecha_venta"].year == anio and v["fecha_venta"].month == mes
    ]

    tab_ventas, tab_presupuesto = st.tabs(
        ["📥 Reporte de Ventas", "🎯 Cumplimiento de Presupuesto"]
    )
    with tab_ventas:
        _seccion_reporte_ventas(ventas_mes, anio, mes)
    with tab_presupuesto:
        st.markdown(f"### 🎯 Cumplimiento de Presupuesto por Asesor - {mes_sel}")
        st.caption(f"Avance / Meta ({periodo})")
        _tabla_metas(
            ventas_mes, anio, mes, dict_asesores, cliente,
            calcular_avance_por_asesor, periodo,
        )
