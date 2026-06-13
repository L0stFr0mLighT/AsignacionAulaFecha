import ast
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from pathlib import Path



# CONFIGURACION
# =============
RESULTADO_PATH = "Resultado_Asignacion.xlsx"
OUTPUT_PATH = "Calendario_Examenes.xlsx"


# AUXILIARES
# ==========

def extraer_fecha_hora(slot_texto):

    """
    Extrae de un slot (fecha, hora, Timestamp fecha-hora)
    """
    texto = str(slot_texto).strip()

    #NOTA: Nuestras fechas estan escritas en formato "01/06/2026 10:00"
    try:
        dt = pd.to_datetime(texto, dayfirst=True)
        fecha = dt.strftime("%d/%m/%Y")
        hora = dt.strftime("%H:%M")
        return fecha, hora, dt # p.e. ("01/06/2026", "10:00", Timestamp("2026-06-01 10:00:00"))
    except Exception:
        return texto, "", pd.NaT # p.e. (texto original, "", fecha inválida)

def semestre_a_curso(semestre):
    """
    Transforma semestre en curso (Sem. 2 -> Primero)
    """
    nombres = ["Primero", "Segundo", "Tercero", "Cuarto", "Quinto"]
    return nombres[int(semestre) // 2 - 1] # NOTA: nuestro modelo solo trabaja en semestre pares por ser convocatoria de junio

def parsear_lista(valor):
    """
    Convierte strings tipo "[(6, 'GII'), (6, 'GII+ADE')]" -> lista real de Python [(6, 'GII'), (6, 'GII+ADE')]
    """

    if pd.isna(valor):
        return []

    return ast.literal_eval(str(valor))

# LECTURA DEL RESULTADO
# =====================

def leer_resultado():
    df = pd.read_excel(RESULTADO_PATH, sheet_name="Asignacion")
    df.columns = [str(c).strip() for c in df.columns]

    columnas_necesarias = {"Examen", "Slot asignado", "Alumnos", "Semestres_titulaciones"}
    faltan = columnas_necesarias - set(df.columns)
    if faltan:
        raise ValueError(f"No se pudo generar el calendario porque faltan las columnas: {faltan}")

    df["Semestres_titulaciones"] = df["Semestres_titulaciones"].apply(parsear_lista)

    parsed = df["Slot asignado"].apply(extraer_fecha_hora)
    # Se añaden nuevas columnas
    df["Fecha"] = parsed.apply(lambda x: x[0])
    df["Hora"] = parsed.apply(lambda x: x[1])
    df["Fecha_dt"] = parsed.apply(lambda x: x[2])
    df["Dia_dt"] = parsed.apply(lambda x: x[2].normalize() if pd.notna(x[2]) else pd.NaT) # Lo usare despues para ordenar segun dias

    return df

def construir_formato_largo(df):
    """
    Dado la tabla de examenes, se contruye su formato largo.
    Si un examen pertenece a varias titulaciones, p.e. [(6, 'GII'), (6, 'GII+ADE')]
    entonces aparecerá una fila para GII y otra para GII+ADE.
    """

    filas = []

    for _, row in df.iterrows():
        examen = row["Examen"]
        alumnos = row["Alumnos"]
        slot = row["Slot asignado"]
        fecha = row["Fecha"]
        hora = row["Hora"]
        sem_tit = row["Semestres_titulaciones"]
        fecha_dt = row["Fecha_dt"]
        dia_dt = row["Dia_dt"]

        for semestre, titulacion in sem_tit:
            filas.append({
                "Titulacion": str(titulacion),
                "Semestre": int(semestre),
                "Curso": semestre_a_curso(int(semestre)),
                "Examen": examen,
                "Alumnos": alumnos,
                "Slot": slot,
                "Fecha": fecha,
                "Hora": hora,
                "Fecha_dt": fecha_dt,
                "Dia_dt": dia_dt,
            })

    return pd.DataFrame(filas)

def obtener_orden_fechas(df_largo):

    """
    Saca la lista de fechas únicas ordenadas cronológicamente para las columnas
    en el calendario Excel.
    """

    df_fechas = (
        df_largo[["Fecha", "Dia_dt"]]
        .drop_duplicates(subset=["Fecha"])
        .sort_values("Dia_dt")
    )
    return df_fechas["Fecha"].tolist()

# DETECCIÓN DE CONFLICTOS
# =======================

def detectar_conflictos(df_largo):
    """
    Crea la tabla que detecta conflictos: GRAVE (mismo slot) ó LEVE (mismo dia)
    """

    conflictos = []

    # Conflictos GRAVES: mismo slot
    grupos_slot = df_largo.groupby(["Titulacion", "Curso", "Semestre", "Slot"])

    for (titulacion, curso, semestre, slot), g in grupos_slot:
        if len(g) > 1:
            examenes_lista = sorted(g["Examen"].tolist())

            conflictos.append({
                "Tipo": "MISMO SLOT (grave)",
                "Titulacion": titulacion,
                "Curso": curso,
                "Semestre": semestre,
                "Fecha": g["Fecha"].iloc[0],
                "Hora": g["Hora"].iloc[0],
                "Nº examenes": len(g),
                "Examenes": " | ".join(examenes_lista),
            })

    # Conflictos LEVES: mismo dia distintas horas
    grupos_dia = df_largo.groupby(["Titulacion", "Curso", "Semestre", "Fecha"])

    for (titulacion, curso, semestre, fecha), g in grupos_dia:
        if len(g) > 1 and g["Slot"].nunique() == len(g): # Tengo que mirar que sean distintos slots pq sino seria GRAVE y no LEVE
            examenes_lista = [] # Aqui guardo los examenes que coinciden por dia

            # Para que quede bonito la columna de Examenes en conflicto lo ordeno por Hora
            for _, row in g.sort_values("Hora").iterrows():
                examenes_lista.append(f"{row['Hora']} - {row['Examen']}")

            conflictos.append({
                "Tipo": "MISMO DIA (leve)",
                "Titulacion": titulacion,
                "Curso": curso,
                "Semestre": semestre,
                "Fecha": fecha,
                "Hora": "-", # No importa la hora
                "Num. examenes": len(g),
                "Examenes": " | ".join(examenes_lista),
            })

    df_conf = pd.DataFrame(conflictos)

    if not df_conf.empty:
        # Ordeno la dataFrame por Tipos y despues Fecha para mas bonito 
        df_conf = df_conf.sort_values(["Tipo","Fecha"]).reset_index(drop=True)

    return df_conf

def calcular_metricas(df_largo, df_asignacion, df_conflictos):
    """
    Calcula las metricas del resultado. 
    Devuelve una lista de tuplas (categoria, nombre_metrica, valor) para luego imprimir en Excel.
    """

    # Calendario
    examenes_unicos = df_largo["Examen"].nunique()
    dias_usados = df_largo["Fecha"].nunique()
    carga_por_dia = df_largo.groupby("Fecha")["Examen"].nunique() # En tabla larga se repite filas de examen-fecha por cada titulacion

    # Conflictos
    if not df_conflictos.empty:
        graves = (df_conflictos["Tipo"] == "MISMO SLOT (grave)").sum()
        leves = (df_conflictos["Tipo"] == "MISMO DIA (leve)").sum()
    else:
        graves = 0
        leves = 0

    # Aulas
    exceso_total = int(df_asignacion["Exceso"].sum())
    exceso_medio = float(df_asignacion["Exceso"].mean())
    exceso_max = int(df_asignacion["Exceso"].max())
    num_aulas_medio = float(df_asignacion["Num aulas"].mean())
    num_aulas_max = int(df_asignacion["Num aulas"].max())

    una_sola_aula = 100.0 * (df_asignacion["Num aulas"] == 1).sum() / len(df_asignacion)
    mal_usadas = 100.0 *((df_asignacion["Capacidad asignada"] > 2 * df_asignacion["Alumnos"]).sum()) / len(df_asignacion)

    metricas = [
        ("CALENDARIO", "Examenes unicos", examenes_unicos),
        ("CALENDARIO", "Dias con examenes", dias_usados),
        ("CALENDARIO", "Carga maxima en un dia", int(carga_por_dia.max())),
        ("CALENDARIO", "Carga minima en un dia", int(carga_por_dia.min())),
        ("CALENDARIO", "Carga media por dia", f"{carga_por_dia.mean():.2f}"),
        ("CALIDAD", "Conflictos GRAVES (mismo slot)", graves),
        ("CALIDAD", "Conflictos LEVES (mismo dia)", leves),
        ("AULAS", "Exceso total (capacidad)", exceso_total),
        ("AULAS", "Exceso medio por examen", f"{exceso_medio:.1f}"),
        ("AULAS", "Exceso maximo", exceso_max),
        ("AULAS", "Num aulas medio por examen", f"{num_aulas_medio:.2f}"),
        ("AULAS", "Num aulas maximo", num_aulas_max),
        ("AULAS", "Examenes con 1 sola aula (%)", f"{una_sola_aula:.1f}%"),
        ("AULAS", "Examenes en aula > 2x alumnos (%)", f"{mal_usadas:.1f}%"),
    ]

    return metricas

# ESCRITURA DEL EXCEL
# ===================

def escribir_calendario_excel(df_largo, df_asignacion, output_path):
    fechas = obtener_orden_fechas(df_largo)
    titulaciones = sorted(df_largo["Titulacion"].unique())

    # Creo el nuevo Excel y borro la hoja por defecto que viene
    wb = Workbook()
    ws_default = wb.active
    wb.remove(ws_default)

    # Preparo los estilos
    fill_titulo = PatternFill("solid", fgColor="1F4E78") # Color azul oscuro
    fill_header = PatternFill("solid", fgColor="D9EAF7") # Color azul claro
    fill_curso = PatternFill("solid", fgColor="E2F0D9") # Color verde claro
    fill_conflicto_leve = PatternFill("solid", fgColor="FFF2CC") # Color amarillo claro
    fill_conflicto_grave = PatternFill("solid", fgColor="F4CCCC") # Color rojo claro
    fill_normal = PatternFill("solid", fgColor="FFFFFF") # Color blanco
    fill_categoria = PatternFill("solid", fgColor="DDEBF7") # Color azul muy claro

    font_titulo = Font(bold=True, size=14, color="FFFFFF") # Color blanco
    font_header = Font(bold=True)
    font_curso = Font(bold=True)
    font_categoria = Font(bold=True, size=11)

    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True) # wrap_text para ocupar varias lineas en la celda
    align_left = Alignment(horizontal="left", vertical="top", wrap_text=True)

    orden_cursos = ["Primero", "Segundo", "Tercero", "Cuarto", "Quinto"]

    # Hoja por titulación
    # ===================

    for titulacion in titulaciones:
        ws = wb.create_sheet(title=str(titulacion))

        df_tit = df_largo[df_largo["Titulacion"] == titulacion].copy() # Las filas de esa titu

        # Título: Calendario de exámenes
        ws.merge_cells(
            start_row=1, start_column=1,
            end_row=1, end_column=len(fechas) + 1
        )

        c = ws.cell(row=1, column=1)
        c.value = f"Calendario de exámenes - {titulacion}"
        c.fill = fill_titulo
        c.font = font_titulo
        c.alignment = align_center

        # Cabecera: Curso y Fechas
        ws.cell(row=2, column=1).value = "Curso"
        ws.cell(row=2, column=1).fill = fill_header
        ws.cell(row=2, column=1).font = font_header
        ws.cell(row=2, column=1).alignment = align_center

        for j, fecha in enumerate(fechas, start=2):
            cell = ws.cell(row=2, column=j)
            cell.value = fecha
            cell.fill = fill_header
            cell.font = font_header
            cell.alignment = align_center

        # Filas por curso
        fila_actual = 3

        for curso in orden_cursos:
            df_curso = df_tit[df_tit["Curso"] == curso]

            if df_curso.empty: continue # Para los que no tienen quinto año

            ws.cell(row=fila_actual, column=1).value = curso
            ws.cell(row=fila_actual, column=1).fill = fill_curso
            ws.cell(row=fila_actual, column=1).font = font_curso
            ws.cell(row=fila_actual, column=1).alignment = align_center

            for j, fecha in enumerate(fechas, start=2):
                df_dia = df_curso[df_curso["Fecha"] == fecha].copy()
                df_dia = df_dia.sort_values("Hora")

                examenes = []
                slots_unicos = set() # Para detectar conflicto grave ya que set no guarda repes

                for _, row in df_dia.iterrows():
                    examenes.append(f"{row['Hora']} - {row['Examen']}")
                    slots_unicos.add(row["Slot"])

                cell = ws.cell(row=fila_actual, column=j) # Celda donde toca escribir

                if examenes: # Si hay examenes lo escribo con salto de linea al final
                    cell.value = "\n".join(examenes)
                else:
                    cell.value = ""

                cell.alignment = align_left

                if len(examenes) > 1: # Si hay mas de un examen en el mismo dia, miro si es grave o leve
                    if len(slots_unicos) < len(examenes): # Si hay menos slots unicos que examenes, entonces hay conflicto grave
                        cell.fill = fill_conflicto_grave
                    else:
                        cell.fill = fill_conflicto_leve
                else:
                    cell.fill = fill_normal

            fila_actual += 1

        # Formato general

        # Miro cual es la ultima fila y columna para poner bordes y ajustar tamaños
        max_row = ws.max_row
        max_col = ws.max_column

        for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
            for cell in row: 
                cell.border = border

        ws.column_dimensions["A"].width = 14 # Columna de cursos

        for col in range(2, max_col + 1):
            ws.column_dimensions[get_column_letter(col)].width = 24 # Columna de fechas

        for row in range(3, max_row + 1):
            ws.row_dimensions[row].height = 90 # Hago mas alta la fila para que quepa los dist examenes con salto de linea

        # Ajuste de altura de las dos primeras filas (titulo y cabecera)
        ws.row_dimensions[1].height = 25
        ws.row_dimensions[2].height = 30

        # Para que se vea siempre los cursos al deslizar
        ws.freeze_panes = "B3"

    # Hoja de conflictos
    # ===================

    df_conflictos = detectar_conflictos(df_largo)

    ws_conf = wb.create_sheet(title="Conflictos", index=0)

    ws_conf.cell(row=1, column=1).value = "Conflictos detectados"

    ws_conf.merge_cells(
            start_row=1, start_column=1,
            end_row=1, end_column=len(df_conflictos.columns)
        )
    ws_conf.cell(row=1, column=1).font = font_titulo
    ws_conf.cell(row=1, column=1).fill = fill_titulo
    ws_conf.cell(row=1, column=1).alignment = align_center

    if df_conflictos.empty:
        ws_conf.cell(row=3, column=1).value = (
            "No se han detectado conflictos. "
            "Ningún curso tiene dos exámenes el mismo día."
        )
    else:
        columnas = list(df_conflictos.columns)

        # Escribo la cabecera de la tabla de conflictos
        for j, col in enumerate(columnas, start=1):
            cell = ws_conf.cell(row=2, column=j)
            cell.value = col
            cell.fill = fill_header
            cell.font = font_header
            cell.alignment = align_center
            cell.border = border

        # Escribo los conflictos detectados
        for i, (_, row) in enumerate(df_conflictos.iterrows(), start=3):
            es_grave = row["Tipo"] == "MISMO SLOT (grave)"

            for j, col in enumerate(columnas, start=1):
                cell = ws_conf.cell(row=i, column=j)
                cell.value = row[col]
                cell.alignment = align_left
                cell.border = border

                if es_grave:
                    cell.fill = fill_conflicto_grave
                else:
                    cell.fill = fill_conflicto_leve

    # Ajuste de tamaños de columnas manualmente para que se vea bien el contenido
    widths = {
        "A": 22,
        "B": 15,
        "C": 12,
        "D": 10,
        "E": 14,
        "F": 8,
        "G": 12,
        "H": 80,
    }

    for col, width in widths.items():
        ws_conf.column_dimensions[col].width = width

    # Hoja de métricas
    # ================

    metricas = calcular_metricas(df_largo, df_asignacion, df_conflictos)

    ws_met = wb.create_sheet(title="Metricas", index=0)

    ws_met.merge_cells(start_row=1, start_column=1, end_row=1, end_column=3)

    # Escribo el título de la hoja de métricas
    c = ws_met.cell(row=1, column=1)
    c.value = "Métricas de calidad del calendario"
    c.fill = fill_titulo
    c.font = font_titulo
    c.alignment = align_center
    ws_met.row_dimensions[1].height = 25

    # Escribo la cabecera de la tabla de métricas
    for j, label in enumerate(["Categoría", "Métrica", "Valor"], start=1):
        cell = ws_met.cell(row=2, column=j)
        cell.value = label
        cell.fill = fill_header
        cell.font = font_header
        cell.alignment = align_center
        cell.border = border

    fila = 3
    categoria_actual = None

    for categoria, label, valor in metricas:
        # Si la categoria cambia, escribo la nueva categoria en la primera columna y le doy formato especial
        if categoria != categoria_actual:
            cell_cat = ws_met.cell(row=fila, column=1)
            cell_cat.value = categoria
            cell_cat.fill = fill_categoria
            cell_cat.font = font_categoria
            categoria_actual = categoria
        else:
            ws_met.cell(row=fila, column=1).value = ""

        ws_met.cell(row=fila, column=2).value = label
        ws_met.cell(row=fila, column=3).value = valor

        for j in range(1, 4): # Pongo bordes y alineacion a todas las celdas de la fila
            ws_met.cell(row=fila, column=j).border = border
            ws_met.cell(row=fila, column=j).alignment = align_left

        fila += 1

    ws_met.column_dimensions["A"].width = 14
    ws_met.column_dimensions["B"].width = 38
    ws_met.column_dimensions["C"].width = 18

    # Para ver siempre la cabecera de la tabla de métricas al deslizar
    ws_met.freeze_panes = "A3"

    # Hoja resumen largo
    # ==================

    ws_res = wb.create_sheet(title="Resumen", index=2)

    columnas_resumen = [
        "Titulacion",
        "Curso",
        "Semestre",
        "Fecha",
        "Hora",
        "Examen",
        "Alumnos",
        "Slot",
    ]

    for j, col in enumerate(columnas_resumen, start=1):
        cell = ws_res.cell(row=1, column=j)
        cell.value = col
        cell.fill = fill_header
        cell.font = font_header
        cell.alignment = align_center
        cell.border = border

    # Ordeno el DataFrame por Titulacion, Semestre, Fecha y Hora para que quede bonito en la hoja de resumen
    df_res = df_largo[columnas_resumen].sort_values(
        ["Titulacion", "Semestre", "Fecha", "Hora"]
    )

    for i, (_, row) in enumerate(df_res.iterrows(), start=2):
        for j, col in enumerate(columnas_resumen, start=1):
            cell = ws_res.cell(row=i, column=j)
            cell.value = row[col]
            cell.alignment = align_left
            cell.border = border

    # Ajuste de tamaños de columnas manualmente para que se vea bien el contenido
    widths = {
        "A": 14,
        "B": 12,
        "C": 10,
        "D": 14,
        "E": 10,
        "F": 45,
        "G": 10,
        "H": 18,
    }

    for col, width in widths.items():
        ws_res.column_dimensions[col].width = width

    ws_res.freeze_panes = "A2"

    wb.save(output_path)


# MAIN
# =====

def generar_calendario():
    df_resultado = leer_resultado()
    df_largo = construir_formato_largo(df_resultado)

    if df_largo.empty:
        raise RuntimeError(
            "No se ha podido construir el calendario. "
            "Revisa que en {RESULTADO_PATH} este la columna 'Semestres_titulaciones'."
        )

    escribir_calendario_excel(df_largo, df_resultado, OUTPUT_PATH)

    print(f"Calendario guardado en: {OUTPUT_PATH}")

if __name__ == "__main__":
    generar_calendario()