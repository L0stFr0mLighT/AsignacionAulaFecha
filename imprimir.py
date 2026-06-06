import ast
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

RESULTADO_PATH = "resultado_asignacion.xlsx"
OUTPUT_PATH = "calendario_examenes.xlsx"


# ==========================================================
# FUNCIONES AUXILIARES
# ==========================================================

def extraer_fecha_hora(slot_texto):
    texto = str(slot_texto).strip()

    # Caso tipo: "1 Jun 10:00"
    try:
        dt = pd.to_datetime("2026 " + texto, format="%Y %d %b %H:%M", dayfirst=True)
        fecha = dt.strftime("%d/%m/%Y")
        hora = dt.strftime("%H:%M")
        return fecha, hora, dt
    except Exception:
        pass

    # Caso tipo: "01/06/2026 10:00"
    try:
        dt = pd.to_datetime(texto, dayfirst=True)
        fecha = dt.strftime("%d/%m/%Y")
        hora = dt.strftime("%H:%M")
        return fecha, hora, dt
    except Exception:
        return texto, "", pd.NaT


def semestre_a_curso(semestre):
    """
    En junio normalmente trabajas con semestres pares:
        2  -> Primero
        4  -> Segundo
        6  -> Tercero
        8  -> Cuarto
        10 -> Quinto
    """
    nombres = {
        1: "Primero",
        2: "Segundo",
        3: "Tercero",
        4: "Cuarto",
        5: "Quinto",
    }

    curso_num = int(semestre) // 2
    return nombres.get(curso_num, f"Curso {curso_num}")


def parsear_lista(valor):
    """
    Convierte strings tipo:
        "[(6, 'GII'), (6, 'GII+ADE')]"
    en una lista real de Python:
        [(6, 'GII'), (6, 'GII+ADE')]
    """
    if isinstance(valor, list):
        return valor

    if pd.isna(valor):
        return []

    try:
        return ast.literal_eval(str(valor))
    except Exception:
        return []


def limpiar_nombre_hoja(nombre):
    """
    Excel no permite algunos caracteres en nombres de hoja.
    """
    nombre = str(nombre)
    caracteres_prohibidos = ["\\", "/", "*", "[", "]", ":", "?"]

    for c in caracteres_prohibidos:
        nombre = nombre.replace(c, "-")

    return nombre[:31]


# ==========================================================
# LECTURA DEL RESULTADO
# ==========================================================

def leer_resultado():
    """
    Lee:
      - hoja Asignacion
      - hoja Examenes_procesados

    De Asignacion usamos:
      Examen, Slot asignado, Alumnos

    De Examenes_procesados usamos:
      examen, semestres_titulaciones
    """

    df_asig = pd.read_excel(RESULTADO_PATH, sheet_name="Asignacion")
    df_exams = pd.read_excel(RESULTADO_PATH, sheet_name="Examenes_procesados")

    # Normalizo nombres por seguridad
    df_asig.columns = [str(c).strip() for c in df_asig.columns]
    df_exams.columns = [str(c).strip() for c in df_exams.columns]

    # Comprobaciones mínimas
    columnas_asig = {"Examen", "Slot asignado", "Alumnos"}
    columnas_exams = {"examen", "semestres_titulaciones"}

    faltan_asig = columnas_asig - set(df_asig.columns)
    faltan_exams = columnas_exams - set(df_exams.columns)

    if faltan_asig:
        raise ValueError(f"Faltan columnas en hoja Asignacion: {faltan_asig}")

    if faltan_exams:
        raise ValueError(f"Faltan columnas en hoja Examenes_procesados: {faltan_exams}")

    df_asig = df_asig[["Examen", "Slot asignado", "Alumnos"]].copy()

    df_exams = df_exams[["examen", "semestres_titulaciones"]].copy()
    df_exams = df_exams.rename(columns={"examen": "Examen"})

    df = df_asig.merge(df_exams, on="Examen", how="left")

    df["semestres_titulaciones"] = df["semestres_titulaciones"].apply(parsear_lista)

    parsed = df["Slot asignado"].apply(extraer_fecha_hora)
    df["Fecha"] = parsed.apply(lambda x: x[0])
    df["Hora"] = parsed.apply(lambda x: x[1])
    df["Fecha_dt"] = parsed.apply(lambda x: x[2])
    df["Dia_dt"] = parsed.apply(lambda x: x[2].normalize() if pd.notna(x[2]) else pd.NaT)

    return df


# ==========================================================
# TRANSFORMACIÓN A FORMATO LARGO
# ==========================================================

def construir_formato_largo(df):
    """
    Convierte cada examen en una o varias filas.

    Si un examen pertenece a varias titulaciones, por ejemplo:
        [(6, 'GII'), (6, 'GII+ADE')]

    entonces aparecerá una fila para GII y otra para GII+ADE.
    """

    filas = []

    for _, row in df.iterrows():
        examen = row["Examen"]
        alumnos = row["Alumnos"]
        slot = row["Slot asignado"]
        fecha = row["Fecha"]
        hora = row["Hora"]
        sem_tit = row["semestres_titulaciones"]
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
    df_fechas = (
        df_largo[["Fecha", "Dia_dt"]]
        .drop_duplicates(subset=["Fecha"])
        .sort_values("Dia_dt")
    )
    return df_fechas["Fecha"].tolist()


# ==========================================================
# DETECCIÓN DE CONFLICTOS
# ==========================================================

def detectar_conflictos(df_largo):
    """
    Detecta si una misma titulación + semestre tiene más de un examen
    el mismo día.
    """

    conflictos = []

    grupos = df_largo.groupby(["Titulacion", "Semestre", "Curso", "Fecha"])

    for (titulacion, semestre, curso, fecha), g in grupos:
        if len(g) > 1:
            examenes = []

            for _, row in g.sort_values(["Hora", "Examen"]).iterrows():
                examenes.append(f"{row['Hora']} - {row['Examen']}")

            conflictos.append({
                "Titulacion": titulacion,
                "Curso": curso,
                "Semestre": semestre,
                "Fecha": fecha,
                "Nº examenes": len(g),
                "Examenes": " | ".join(examenes),
            })

    return pd.DataFrame(conflictos)


# ==========================================================
# ESCRITURA DEL EXCEL
# ==========================================================

def escribir_calendario_excel(df_largo, output_path):
    fechas = obtener_orden_fechas(df_largo)
    titulaciones = sorted(df_largo["Titulacion"].unique())

    wb = Workbook()
    ws_default = wb.active
    wb.remove(ws_default)

    # --------------------------
    # Estilos
    # --------------------------

    fill_titulo = PatternFill("solid", fgColor="1F4E78")
    fill_header = PatternFill("solid", fgColor="D9EAF7")
    fill_curso = PatternFill("solid", fgColor="E2F0D9")
    fill_conflicto = PatternFill("solid", fgColor="F4CCCC")
    fill_normal = PatternFill("solid", fgColor="FFFFFF")

    font_titulo = Font(bold=True, size=14, color="FFFFFF")
    font_header = Font(bold=True)
    font_curso = Font(bold=True)

    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="top", wrap_text=True)

    orden_cursos = ["Primero", "Segundo", "Tercero", "Cuarto", "Quinto"]

    # ======================================================
    # Hoja por titulación
    # ======================================================

    for titulacion in titulaciones:
        ws = wb.create_sheet(title=limpiar_nombre_hoja(titulacion))

        df_tit = df_largo[df_largo["Titulacion"] == titulacion].copy()

        # Título
        ws.merge_cells(
            start_row=1,
            start_column=1,
            end_row=1,
            end_column=len(fechas) + 1
        )

        c = ws.cell(row=1, column=1)
        c.value = f"Calendario de exámenes - {titulacion}"
        c.fill = fill_titulo
        c.font = font_titulo
        c.alignment = align_center

        # Cabecera
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

            if df_curso.empty:
                continue

            ws.cell(row=fila_actual, column=1).value = curso
            ws.cell(row=fila_actual, column=1).fill = fill_curso
            ws.cell(row=fila_actual, column=1).font = font_curso
            ws.cell(row=fila_actual, column=1).alignment = align_center

            for j, fecha in enumerate(fechas, start=2):
                df_dia = df_curso[df_curso["Fecha"] == fecha].copy()
                df_dia = df_dia.sort_values(["Hora", "Examen"])

                examenes = []

                for _, row in df_dia.iterrows():
                    examenes.append(f"{row['Hora']} - {row['Examen']}")

                cell = ws.cell(row=fila_actual, column=j)

                if examenes:
                    cell.value = "\n".join(examenes)
                else:
                    cell.value = ""

                cell.alignment = align_left
                cell.fill = fill_conflicto if len(examenes) > 1 else fill_normal

            fila_actual += 1

        # Formato general
        max_row = ws.max_row
        max_col = ws.max_column

        for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
            for cell in row:
                cell.border = border

        ws.column_dimensions["A"].width = 14

        for col in range(2, max_col + 1):
            ws.column_dimensions[get_column_letter(col)].width = 24

        for row in range(3, max_row + 1):
            ws.row_dimensions[row].height = 90

        ws.row_dimensions[1].height = 25
        ws.row_dimensions[2].height = 30

        ws.freeze_panes = "B3"

    # ======================================================
    # Hoja de conflictos
    # ======================================================

    df_conflictos = detectar_conflictos(df_largo)

    ws_conf = wb.create_sheet(title="Conflictos", index=0)

    ws_conf.cell(row=1, column=1).value = "Conflictos detectados"
    ws_conf.cell(row=1, column=1).font = font_titulo
    ws_conf.cell(row=1, column=1).fill = fill_titulo
    ws_conf.cell(row=1, column=1).alignment = align_center

    if df_conflictos.empty:
        ws_conf.cell(row=3, column=1).value = (
            "No se han detectado conflictos de varios exámenes "
            "el mismo día para la misma titulación y curso."
        )
    else:
        columnas = list(df_conflictos.columns)

        for j, col in enumerate(columnas, start=1):
            cell = ws_conf.cell(row=3, column=j)
            cell.value = col
            cell.fill = fill_header
            cell.font = font_header
            cell.alignment = align_center
            cell.border = border

        for i, (_, row) in enumerate(df_conflictos.iterrows(), start=4):
            for j, col in enumerate(columnas, start=1):
                cell = ws_conf.cell(row=i, column=j)
                cell.value = row[col]
                cell.alignment = align_left
                cell.border = border

    ws_conf.column_dimensions["A"].width = 15
    ws_conf.column_dimensions["B"].width = 15
    ws_conf.column_dimensions["C"].width = 12
    ws_conf.column_dimensions["D"].width = 14
    ws_conf.column_dimensions["E"].width = 14
    ws_conf.column_dimensions["F"].width = 80

    # ======================================================
    # Hoja resumen largo
    # ======================================================

    ws_res = wb.create_sheet(title="Resumen", index=1)

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

    df_res = df_largo[columnas_resumen].sort_values(
        ["Titulacion", "Semestre", "Fecha", "Hora", "Examen"]
    )

    for i, (_, row) in enumerate(df_res.iterrows(), start=2):
        for j, col in enumerate(columnas_resumen, start=1):
            cell = ws_res.cell(row=i, column=j)
            cell.value = row[col]
            cell.alignment = align_left
            cell.border = border

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


# ==========================================================
# MAIN
# ==========================================================

def main():
    df = leer_resultado()
    df_largo = construir_formato_largo(df)

    if df_largo.empty:
        raise RuntimeError(
            "No se ha podido construir el calendario. "
            "Revisa la columna semestres_titulaciones."
        )

    escribir_calendario_excel(df_largo, OUTPUT_PATH)

    print(f"Calendario guardado en: {OUTPUT_PATH}")
    print("Hojas generadas:")
    print("  - Conflictos")
    print("  - Resumen")
    for tit in sorted(df_largo["Titulacion"].unique()):
        print(f"  - {tit}")


if __name__ == "__main__":
    main()