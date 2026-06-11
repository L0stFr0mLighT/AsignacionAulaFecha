import re
import pandas as pd
import minizinc
from pathlib import Path
from datetime import timedelta
import math 
from datetime import datetime

EXCEL_PATH = "AsignacionClase.xlsx"
CALENDARIO_MZN_PATH = "AsignacionFecha.mzn"
AULAS_MZN_PATH = "AsignacionAulas.mzn"

SHEET_NAME = "Exámenes Junio"

SOLVER_NAME = "gecode"

TIMEOUT_FECHA = 30 # Tiempo de optimizacion Fecha
TIMEOUT_AULA = 10 # Tiempo de optimizacion Aula

def toBool(x):
    """
    Normaliza valores booleanos desde Excel
    Acepta 1, 1.0, x, true
    """
    if pd.isna(x): return False # Caso celda vacia

    if isinstance(x, bool): return x

    s = str(x).strip().lower()
    return s in {"1", "1.0", "x", "true"} # Nosotros solo usaremos 1.0, pero es una mejora futura

def toDatetime(s) -> datetime:
    """
    Convierte un slot a datetime
    """
    s = str(s).strip()
    return datetime.strptime(s, "%d/%m/%Y %H:%M")

def normalizar_slot(x):
    """
    Normaliza los slots posibles leídos del Excel
    """
    if pd.isna(x): return ""

    if isinstance(x, pd.Timestamp):
        return x.strftime("%d/%m/%Y %H:%M")

    return str(x).strip()

def parse_semestre_grado(texto) -> tuple[int, str]:
    """
    Convierte 2º(GII) -> (2, GII)
    """
    texto = str(texto).strip()

    m = re.match(r"(\d+)", texto) #Raw para no sobreinterpretar \, + para no permitir 0 veces
    semestre = int(m.group(1)) if m else -1

    g = re.search(r"\((.*?)\)", texto)
    titulacion = g.group(1).strip() if g else "FALLO_GRADO"

    return semestre, titulacion

def read_excel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Lee del Excel:
    - columnas A-E: examenes
    - columnas F-K: aulas
    - columna L: slots posibles
    """
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME)
    df.columns = [str(c).strip() for c in df.columns]

    # Examenes: columnas A-E
    #-----------------------
    exam_cols = df.columns[0:5]
    df_exams = df.loc[:, exam_cols].copy()

    df_exams.columns = [ #Renombro
        "examen",
        "semestre_grado",
        "matriculados",
        "requiere_pc",
        "requiere_enchufes",
    ]

    examen_criticas = ["examen","semestre_grado","matriculados",]
    df_exams = df_exams.dropna(subset=examen_criticas) #Si falta algunos de los datos en las col criticas lo elimino

    # Aulas: columnas F-K
    # -------------------
    aula_cols = df.columns[5:11]
    df_aulas = df.loc[:, aula_cols].copy()

    df_aulas.columns = [
        "aula",
        "bloque",
        "planta",
        "capacidad",
        "tiene_enchufes",
        "es_informatica",
    ]

    aulas_criticas = ["aula","bloque","planta","capacidad",]
    df_aulas = df_aulas.dropna(subset=aulas_criticas) #Como las filas son menos que examenes ó slot, tengo que eliminar las vacias

    # Slots posibles: columna L
    # --------------------------
    slot_col = df.columns[11]
    df_slots = df.loc[:, [slot_col]].copy()
    df_slots.columns = ["slot_texto"]
    df_slots = df_slots.dropna(subset=["slot_texto"])

    return df_exams, df_aulas, df_slots

def prepare_data(df_exams, df_aulas, df_slots) -> tuple[dict, dict, dict]:
    """
    Prepara los diccionarios data_fechas y data_aulas; y crea tambien metadata para Excel respuesta
    """
    # Slots posibles ordenados cronologicamente

    slots_raw = list(dict.fromkeys(df_slots["slot_texto"].apply(normalizar_slot)))
    slots_raw = [s for s in slots_raw if s != ""]

    slots = sorted(slots_raw, key=toDatetime)  # Ordena slots por dia-hora
    slot_dt = { s: toDatetime(s) for s in slots}

    dias_ordenados = sorted({ slot_dt[s].date() for s in slots}) #Ordena solo dias sin repes
    dia_to_id = {dia: i + 1 for i, dia in enumerate(dias_ordenados)} # Diccionario de dias
    dia_slot = [dia_to_id[slot_dt[s].date()] for s in slots] #Por cada slot, guarda que dia es

    n_dias = len(dias_ordenados)

    # Examenes sin agrupar

    rows = []

    for _, row in df_exams.iterrows():
        semestre, titulacion = parse_semestre_grado(row["semestre_grado"])

        rows.append({
            "examen": str(row["examen"]).strip(),
            "matriculados": int(row["matriculados"]),
            "requiere_pc": toBool(row["requiere_pc"]),
            "requiere_enchufes": toBool(row["requiere_enchufes"]),
            "semestre": semestre,
            "titulacion": titulacion,
        })

    exams_long = pd.DataFrame(rows)

    # Agrupar examenes
    grouped = []

    for nombre, g in exams_long.groupby("examen",sort=False): #sort=False para ir mas rapido
        
        titulaciones = sorted(set(g["titulacion"])) # todas las titulaciones de ese examen sin repetir
        semestres_titulaciones = sorted(set(zip(g["semestre"], g["titulacion"]))) # guarda parejas (semestre, titulacion)

        grouped.append({
            "examen": nombre,
            "alumnos": int(g["matriculados"].sum()),
            "requiere_pc": bool(g["requiere_pc"].max()), # si uno requiere pc, lo hacen todos por convencion
            "requiere_enchufes": bool(g["requiere_enchufes"].max()),
            "titulaciones": titulaciones,
            "semestres_titulaciones": semestres_titulaciones,
        })

    exams = pd.DataFrame(grouped)

    # Matriz semestre_examen

    # Recorre la lista de titu de cada examen,despues mira cada uno individ. y mira que no se repita
    all_titulaciones = sorted({t for ts in exams["titulaciones"] for t in ts}) # Haciendolo asi en un futuro podria aceptar +titu
    n_titu = len(all_titulaciones)

    semestre_examen = []

    for _, row in exams.iterrows():
        fila = []

        for t in all_titulaciones: # P.e: PPS = [2,2,2,2] resp [GII,GII+ADE,GM,GCDIA]
            semestre_en_titulacion = 0 # Por defecto 0
            for sem, tit in row["semestres_titulaciones"]:
                if tit == t: semestre_en_titulacion = int(sem) #Si coincide titulacion, guardo semestre
            fila.append(semestre_en_titulacion)

        semestre_examen.append(fila)

    # Matriz de numero de examenes por titu-sem
    n_sem = max(max(fila) for fila in semestre_examen) # Podria poner directamente 10 (GII+ADE), pero es una posible mejora futura

    # 5 columnas -> 4 semestres dif + semestre 0 (vacio)
    # 4 filas por num de titulaciones
    n_exam_por_tituSem = [[0 for _ in range(n_sem + 1)] for _ in range(n_titu)]

    for e in range(len(semestre_examen)): #Recorro todos los examenes
        for t in range(n_titu):
            sem = semestre_examen[e][t]
            if sem > 0: n_exam_por_tituSem[t][sem] += 1 


    # Aulas

    aulas = df_aulas.copy()

    aulas["aula"] = aulas["aula"].astype(str).str.strip()
    aulas["bloque"] = aulas["bloque"].astype(int)
    aulas["planta"] = aulas["planta"].astype(int)
    aulas["capacidad"] = aulas["capacidad"].astype(int)

    aulas["tiene_enchufes"] = aulas["tiene_enchufes"].apply(toBool)
    aulas["es_informatica"] = aulas["es_informatica"].apply(toBool)

    aulas["planta_mzn"] = aulas["planta"]
    aulas["bloque_mzn"] = aulas["bloque"]

    # Tamaños

    n_exams = len(exams)
    n_aula = len(aulas)
    n_slots = len(slots)
    n_plantas = int(aulas["planta_mzn"].max()) + 1
    n_bloques = int(aulas["bloque_mzn"].max())

    #Disponibilidad de aulas

    aulas_bloqueadas = {"3102-3103"} #NOTA: por ahora solo bloqueare esta aula pq es bastante oscura

    aula_disponible = []

    for _, row in aulas.iterrows():
        nombre_aula = str(row["aula"]).strip()

        if nombre_aula in aulas_bloqueadas:
            aula_disponible.append([False for _ in range(n_slots)])
        else:
            aula_disponible.append([True for _ in range(n_slots)])

    # Capacidad maxima de PC,Enchufes y capacidad por slot

    capacidad = aulas["capacidad"].tolist()
    tiene_enchufes = aulas["tiene_enchufes"].tolist()
    es_informatica = aulas["es_informatica"].tolist()

    capacidad_total_slot = []
    capacidad_pc_slot = []
    capacidad_enchufes_slot = []

    for s in range(n_slots):
        cap_total = 0
        cap_pc = 0
        cap_enchufes = 0

        for r in range(n_aula):
            if aula_disponible[r][s]: #Si todas estan disponibles sera igual todo
                cap_total += capacidad[r]

            if es_informatica[r]:
                cap_pc += capacidad[r]

            if tiene_enchufes[r]:
                cap_enchufes += capacidad[r]

        capacidad_total_slot.append(cap_total)
        capacidad_pc_slot.append(cap_pc)
        capacidad_enchufes_slot.append(cap_enchufes)

    # Data a pasar al modelo 1

    data_fechas = {
        "n_exams": n_exams,
        "n_slots": n_slots,
        "n_titu": n_titu,

        "max_examenes_por_slot": 3,
        "max_examenes_por_dia" : 7,

        "dia_slot": dia_slot,
        "n_dias": n_dias,
        "n_sem": n_sem,
        "n_exam_por_tituSem": n_exam_por_tituSem,

        "alumnos": exams["alumnos"].tolist(),
        "nombre_examen": exams["examen"].tolist(),
        "nombre_slot": slots,

        "semestre_examen": semestre_examen,

        "requiere_pc": exams["requiere_pc"].tolist(),
        "requiere_enchufes": exams["requiere_enchufes"].tolist(),

        "capacidad_total_slot": capacidad_total_slot,
        "capacidad_pc_slot": capacidad_pc_slot,
        "capacidad_enchufes_slot": capacidad_enchufes_slot,
    }

    # Data a pasar al modelo 2

    data_aulas = {
        "n_exams": n_exams,
        "n_aula": n_aula,
        "n_slots": n_slots,
        "n_plantas": n_plantas,
        "n_bloques": n_bloques,

        "max_aulas": 12,

        "nombre_examen": exams["examen"].tolist(),
        "nombre_aula": aulas["aula"].tolist(),
        "nombre_slot": slots,
        "alumnos": exams["alumnos"].tolist(),

        #slot_examen lo añadira el modelo 1

        "capacidad": capacidad,
        "tiene_enchufes": tiene_enchufes,
        "es_informatica": es_informatica,
        "planta_aula": aulas["planta_mzn"].tolist(),
        "bloque_aula": aulas["bloque_mzn"].tolist(),
        "aula_disponible": aula_disponible,
        "requiere_enchufes": exams["requiere_enchufes"].tolist(),
        "requiere_pc": exams["requiere_pc"].tolist(),
    }

    metadata = {
        "exams": exams,
        "aulas": aulas,
        "slots": slots,
        "titulaciones": all_titulaciones,
        "semestre_examen": semestre_examen,
    }

    return data_fechas, data_aulas, metadata

def run_minizinc_model(model_path, data, timeout_minutes=5) -> minizinc.Result:
    model = minizinc.Model(model_path)
    solver = minizinc.Solver.lookup(SOLVER_NAME)
    instance = minizinc.Instance(solver, model)

    for key, value in data.items(): instance[key] = value

    result = instance.solve(timeout=timedelta(minutes=timeout_minutes))

    return result

def extraer_slots_asignados(result_calendario) -> list[int]:
    """
    Devuelve slot_examen[e] como lista 1..n_slots a partir de slot_asignado
    """

    if result_calendario is None or result_calendario.solution is None:
        raise RuntimeError("El modelo de fechas no encontró solución")

    slot_asignado = result_calendario["slot_asignado"] #NOTA: slot_asignado tiene que estar definido en el mnz
    return [int(s) for s in slot_asignado]

def guardar_resultado_excel(result_aulas,data_aulas,metadata,archivo):
    
    if result_aulas is None or result_aulas.solution is None:
        print("No hay solución de aulas para guardar.")
        return

    exams = metadata["exams"]
    aulas = metadata["aulas"]
    slots = metadata["slots"]

    usa_aula = result_aulas["usa_aula"]

    filas = []

    for e in range(data_aulas["n_exams"]):
        aulas_asignadas = []
        capacidad_asignada = 0

        for r in range(data_aulas["n_aula"]):
            if usa_aula[e][r] == 1:
                nombre_aula = aulas.iloc[r]["aula"]
                aulas_asignadas.append(str(nombre_aula))
                capacidad_asignada += data_aulas["capacidad"][r]

        slot_idx = data_aulas["slot_examen"][e]

        filas.append({
            "Examen": exams.iloc[e]["examen"],
            "Semestres_titulaciones": exams.iloc[e]["semestres_titulaciones"],
            "Slot asignado": slots[slot_idx - 1],
            "Slot_idx": slot_idx, # Lo uso para ordenar y despues lo quito
            "Alumnos": data_aulas["alumnos"][e],
            "Capacidad asignada": capacidad_asignada,
            "Exceso": capacidad_asignada - data_aulas["alumnos"][e],
            "Num aulas": len(aulas_asignadas),
            "Aulas asignadas": ", ".join(aulas_asignadas),
        })

    df_resultado = (pd.DataFrame(filas).sort_values("Slot_idx").drop(columns=["Slot_idx"]))

    with pd.ExcelWriter(archivo, engine="openpyxl") as writer:
        df_resultado.to_excel(writer, sheet_name="Asignacion", index=False)

    print(f"Resultado guardado en {archivo}")

def validar_factibilidad(data_fechas, data_aulas, metadata):

    """
    Comprueba futuros problemas con la configuracion dada: 
    examenes demasiado grandes, dias insuficientes o aulas minimas necesarias
    """

    avisos = []
    exams = metadata["exams"]

    # Colisiones inevitables por num de examenes y  num dias
    for t_idx, t_nom in enumerate(metadata["titulaciones"]):
        for sem in range(1, data_fechas["n_sem"] + 1):
            n = data_fechas["n_exam_por_tituSem"][t_idx][sem]

            if n > data_fechas["n_dias"]:
                avisos.append( f"{t_nom} semestre {sem}: {n} examenes > {data_fechas['n_dias']} dias -> COLISION")

    max_cap_aula = max(data_aulas["capacidad"])

    # Combinacion imposible por num alumnos examen y num maximo de aulas
    for _, ex in exams.iterrows():
        min_aulas_necesarias = math.ceil(ex["alumnos"] / max_cap_aula)

        if min_aulas_necesarias > data_aulas["max_aulas"]:
            avisos.append(
                f"{ex['examen']}: necesita al menos {min_aulas_necesarias} aulas, pero max_aulas = {data_aulas['max_aulas']}."
            )

    if avisos:
        print("\nAVISOS DE FACTIBILIDAD")
        for aviso in avisos: print(" -", aviso)

    return avisos

def main():
    df_exams, df_aulas, df_slots = read_excel()

    data_fechas, data_aulas, metadata = prepare_data(df_exams,df_aulas,df_slots)

    validar_factibilidad(data_fechas, data_aulas, metadata)

    print("Datos leídos:")
    print(f"  Examenes agrupados: {data_fechas['n_exams']}")
    print(f"  Aulas: {data_aulas['n_aula']}")
    print(f"  Slots: {data_fechas['n_slots']}")
    print(f"  Dias: {data_fechas['n_dias']}")
    print(f"  Titulaciones: {metadata['titulaciones']}")

    #Fase 1: asignacion de mejores fechas para examen

    print("\nEjecutando modelo 1: AsignacionFecha...")

    result_calendario = run_minizinc_model(CALENDARIO_MZN_PATH,data_fechas,timeout_minutes=TIMEOUT_FECHA)

    print("Estado calendario:", result_calendario.status)

    if result_calendario.solution is None:
        print("No se encontro fechas validas")
        return

    slot_examen = extraer_slots_asignados(result_calendario)

    print("\nSlots asignados:")
    print(slot_examen)

    data_aulas["slot_examen"] = slot_examen #Pasamos los slots decididos a AsignacionAula

    #Fase 2: asignacion de mejores aulas para examen

    print("\nEjecutando modelo 2: AsignacionAula...")

    result_aulas = run_minizinc_model(AULAS_MZN_PATH,data_aulas,timeout_minutes=TIMEOUT_AULA)

    if result_aulas.solution is None:
        print("No se encontró asignación de aulas.")
        return
    
    print("Estado aulas asignadas:", result_aulas.status)
    guardar_resultado_excel(result_aulas,data_aulas,metadata,archivo="Resultado_Asignacion.xlsx")

    print("\nEjecucion finalizada")

if __name__ == "__main__":
    main()