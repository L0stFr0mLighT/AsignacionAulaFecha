# Asignación de fechas y aulas para exámenes

Genera automáticamente el **calendario de exámenes** de la convocatoria de junio, asignando a cada examen una **fecha/hora** y las **aulas** donde se realiza. Usa programación con restricciones (**MiniZinc**) y **Python**.

## Cómo funciona

Los datos de entrada están en `AsignacionClase.xlsx`: exámenes con sus alumnos y requisitos, aulas con su capacidad, planta, bloque, enchufes y PCs, y los huecos de fecha/hora disponibles. El problema se resuelve en dos fases:

1. **Asignación de fechas** (`AsignacionFecha.mzn`): elige el hueco de cada examen.
   - Evita que coincidan exámenes del mismo curso y titulación.
   - Respeta la capacidad total, de aulas de informática y de aulas con enchufes en cada hueco.
   - Intenta repartir los exámenes de cada curso de forma equilibrada entre los días.
2. **Asignación de aulas** (`AsignacionAulas.mzn`): con las fechas ya fijadas, reparte cada examen en aulas.
   - Garantiza capacidad suficiente y que un aula no tenga dos exámenes a la vez.
   - Respeta los requisitos de PC y de enchufes.
   - Minimiza las plazas sobrantes, el número de aulas y la dispersión entre plantas y bloques.

Al final, `imprimir.py` crea un calendario visual en Excel, con una hoja por titulación y otra que marca los posibles conflictos.

## Requisitos

- Python 3
- [MiniZinc](https://www.minizinc.org/) instalado, con el solver **Gecode** (viene incluido en el instalador)
- Las librerías de Python:
  ```bash
  pip install -r requirements.txt
  ```

## Ejecución

```bash
python run.py
```

Se generan dos ficheros:
- `Resultado_Asignacion.xlsx`: cada examen con su fecha, sus aulas y la capacidad asignada.
- `Calendario_Examenes.xlsx`: el calendario por titulación y curso.

Los límites (número máximo de aulas por examen, exámenes por hueco o por día, tiempo de búsqueda) se configuran al principio de `run.py`.

## Nota

Por problemas de combinatoria del ejemplo expuesto (demasiados casos posibles) no se puede llegar a una solución definitiva, por ello
se impuso un TIMEOUT configurable para mostrar el mejor resultado hasta el momento.

## Autores

- Jia Jie Ye - [L0stFr0mLighT](https://github.com/L0stFr0mLighT)
- Yurong Cheng - [Yurong0q](https://github.com/Yurong0q)
- Yun Chen - [YuuAhhm](https://github.com/YuuAhhm)
