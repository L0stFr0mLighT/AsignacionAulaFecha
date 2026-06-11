
% MODELO 1: PLANIFICACIÓN DE SLOTS DE EXÁMENES
include "globals.mzn";

% Conjuntos principales
%_______________________

int: n_exams;
int: n_slots;
int: n_titu;
int: n_sem;
int: n_dias;

set of int: EXAMS = 1..n_exams;
set of int: SLOTS = 1..n_slots;
set of int: TITULACIONES = 1..n_titu;
set of int: SEMESTRES = 0..n_sem;
set of int: SEMESTRES_REALES = 1..n_sem;
set of int: DIAS = 1..n_dias;


% Para reducir la carga y no pensar en solapar lo maximo en un slot/dia
int: max_examenes_por_slot;
int: max_examenes_por_dia;


array[EXAMS] of string: nombre_examen;
array[SLOTS] of string: nombre_slot;

% Datos de exámenes
%___________________

array[EXAMS] of int: alumnos;

array[EXAMS] of bool: requiere_pc;
array[EXAMS] of bool: requiere_enchufes;


% 0 si el examen e no pertenece a la titulación t
% 2,4,6,8... si pertenece a esa titulación en ese semestre
array[EXAMS, TITULACIONES] of SEMESTRES: semestre_examen;

% Guarda num de examenes por titulacion y semestre
array[TITULACIONES, SEMESTRES] of 0..n_exams: n_exam_por_tituSem;


% Datos de slots
%________________________________

% Capacidad total disponible en cada slot
array[SLOTS] of int: capacidad_total_slot;

% Capacidad total de aulas informaticas disponible en cada slot
array[SLOTS] of int: capacidad_pc_slot;

% Capacidad total de aulas con enchufes disponible en cada slot
array[SLOTS] of int: capacidad_enchufes_slot;

% Dia de cada slot
array[SLOTS] of DIAS: dia_slot;


% Variable de decision
%______________________

array[EXAMS] of var SLOTS: slot_asignado; % slot identificado por su indice 


array[EXAMS] of var DIAS: dia_examen;

constraint forall(e in EXAMS)(
    dia_examen[e] =
        sum(s in SLOTS)(
            dia_slot[s] * bool2int(slot_asignado[e] = s)
        )
);

% Si una (titu, sem) tiene N examenes y hay D dias, la separacion natural
% entre examenes consecutivos es (D-1)/(N-1)
array[TITULACIONES, SEMESTRES_REALES] of int: separacion_ideal =
    array2d(TITULACIONES, SEMESTRES_REALES,
        [ if n_exam_por_tituSem[t,s] >= 2
            then (n_dias - 1) div (n_exam_por_tituSem[t,s] - 1)
            else 0
            endif
        | t in TITULACIONES, s in SEMESTRES_REALES ]
    );



% Restricciones
%===============

% R1: capacidad total de alumnos por slot
constraint forall(s in SLOTS)(
    sum(e in EXAMS)(
        alumnos[e] * bool2int(slot_asignado[e] = s)) <= capacidad_total_slot[s]
);


% R2: capacidad de aulas de informatica por slot (examenes que requieren PC)
constraint forall(s in SLOTS)(
    sum(e in EXAMS where requiere_pc[e])(
        alumnos[e] * bool2int(slot_asignado[e] = s)) <= capacidad_pc_slot[s]
);


% R3: capacidad de aulas con enchufes por slot
constraint forall(s in SLOTS)(
    sum(e in EXAMS where requiere_enchufes[e])(
        alumnos[e] * bool2int(slot_asignado[e] = s)) <= capacidad_enchufes_slot[s]
);


% R4: maximo de examenes por slot - dispersa horizontalmente
constraint forall(s in SLOTS)(
    sum(e in EXAMS)(bool2int(slot_asignado[e] = s)) <= max_examenes_por_slot
);


% R5: mismo slot prohibido para examenes de la misma (titulacion, semestre)
constraint forall(e1, e2 in EXAMS, t in TITULACIONES
    where e1 < e2
        /\ semestre_examen[e1,t] > 0
        /\ semestre_examen[e1,t] = semestre_examen[e2,t]
)(
    slot_asignado[e1] != slot_asignado[e2]
);

% R6: Si hay menos examenes de la misma (titulacion,semestre) que dias, mismo dia prohibido para examenes 
constraint forall(e1, e2 in EXAMS, t in TITULACIONES
    where e1 < e2
        /\ semestre_examen[e1,t] > 0
        /\ semestre_examen[e1,t] = semestre_examen[e2,t]
        /\ n_exam_por_tituSem[t, semestre_examen[e1,t]] <= n_dias
)(
    dia_examen[e1] != dia_examen[e2]
);

% R7: tope maximo de examenes por dia
array[DIAS] of var 0..n_exams: examenes_por_dia;

constraint forall(d in DIAS)(
    examenes_por_dia[d] = sum(e in EXAMS)(bool2int(dia_examen[e] = d))
);

constraint forall(d in DIAS)(
    examenes_por_dia[d] <= max_examenes_por_dia
);

% Penalizaciones 
%===============

% P1: SEPARACION IDEAL
var int: mal_repartidos =
    sum(e1, e2 in EXAMS, t in TITULACIONES
        where e1 < e2
        /\ semestre_examen[e1,t] > 0
        /\ semestre_examen[e1,t] = semestre_examen[e2,t]
    )(
        max([0,
            separacion_ideal[t, semestre_examen[e1,t]] - abs(dia_examen[e1] - dia_examen[e2])
            ])
    );


% P2: Penalizar examenes en el mismo slot de cursos contiguos
% Importante para repetidores
var int: colision_slot_titu =
    sum(e1, e2 in EXAMS, t in TITULACIONES
        where e1 < e2
        /\ semestre_examen[e1,t] > 0
        /\ semestre_examen[e2,t] > 0
        /\ abs(semestre_examen[e1,t] - semestre_examen[e2,t]) == 2
    )(
        bool2int(slot_asignado[e1] = slot_asignado[e2])
    );


% P3: REPARTO GLOBAL (evita asimetrias raras)

%Se multiplica *100 para intentar operar con numeros enteros cuando se pueda
int: media_examenes_dia_x10 = (n_exams * 100) div n_dias;

var int: mal_reparto =
    sum(d in DIAS)(
        abs(100 * examenes_por_dia[d] - media_examenes_dia_x10)
    );

% Función objetivo
%=================

var int: objetivo =
    3000 * colision_slot_titu
    + 1500 * mal_repartidos
    + 100 * mal_reparto;

solve :: int_search(slot_asignado, dom_w_deg, indomain_split, complete)
    :: restart_luby(150)
    minimize objetivo;

% Output

output[
    nombre_examen[e] ++
    " | Alumnos = " ++ show(alumnos[e]) ++
    " | Slot asignado = " ++ nombre_slot[fix(slot_asignado[e])] ++
    "\n"
    | e in EXAMS
];