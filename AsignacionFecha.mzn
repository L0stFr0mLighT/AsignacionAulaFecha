% MODELO 1: PLANIFICACIÓN DE SLOTS DE EXÁMENES
include "globals.mzn";

% Conjuntos principales
%_______________________

int: n_exams;
int: n_slots;
int: n_titu;
int: n_sem;
int: n_dias;


% Distancia minima entre examenes de misma titulacion y mismo semestre
int: min_dist_mismo_semestre;

% Distancia minima entre semestres cercanos
int: min_dist_semestre_cercano;

% Para reducir la carga y no pensar en solapar lo maximo en un slot
int: max_examenes_por_slot;

% Para separar los examenes de un mismo semestre y titulacion
% NOTA: son dias por slot, p.e. 5 y 8 son dif = 1 si no hay dias de examenes disp entre medio
int: min_dias_mismo_semestre;

% Para saber si el numero de examenes en titulacion-año puede repartirse de esa forma
int: max_examenes_repartibles = ((n_dias - 1) div min_dias_mismo_semestre) + 1; 

set of int: EXAMS = 1..n_exams;
set of int: SLOTS = 1..n_slots;
set of int: TITULACIONES = 1..n_titu;
set of int: SEMESTRES = 0..n_sem;
set of int: DIAS = 1..n_dias;


% Datos de exámenes
%___________________

array[EXAMS] of int: alumnos;
array[EXAMS] of string: nombre_examen;
array[SLOTS] of string: nombre_slot;

% 0 si el examen e no pertenece a la titulación t
% 2,4,6,8... si pertenece a esa titulación en ese semestre
array[EXAMS, TITULACIONES] of int: semestre_examen;


% Guarda num de examenes por titulacion y semestre
array[TITULACIONES, SEMESTRES] of int: n_exam_por_tituSem;

array[EXAMS] of bool: requiere_pc;
array[EXAMS] of bool: requiere_enchufes;



% Capacidades necesaria por slot
%________________________________

% Capacidad total disponible en cada slot
array[SLOTS] of int: capacidad_total_slot;

% Capacidad total de aulas informaticas disponible en cada slot
array[SLOTS] of int: capacidad_pc_slot;

% Capacidad total de aulas con enchufes disponible en cada slot
array[SLOTS] of int: capacidad_enchufes_slot;

% Dia de cada slot
array[SLOTS] of int: dia_slot; %Esto lo usare para hacer que no coincida los examenes de un mismo sem-titu


% Variable de decision
%______________________

array[EXAMS] of var SLOTS: slot_asignado; % slot identificado por su indice 


% Variable auxiliar
%___________________

array[EXAMS] of var DIAS: dia_examen;

constraint forall(e in EXAMS)(
    dia_examen[e] = dia_slot[slot_asignado[e]]
);


% Grupos de exámenes por titulación y semestre (calculado en compilación)
array[TITULACIONES, SEMESTRES] of set of int: exams_por_tituSem =
    array2d(TITULACIONES, SEMESTRES,
        [ { e | e in EXAMS where semestre_examen[e,t] = s }
          | t in TITULACIONES, s in SEMESTRES ]
    );

% R1: capacidad maxima de alumnos en una fecha-hora
%==================================================

constraint forall(s in SLOTS)(
    sum(e in EXAMS)(
        alumnos[e] * bool2int(slot_asignado[e] = s)) <= capacidad_total_slot[s]
);


% R2: capacidad maxima de pc en una fecha-hora
%=============================================

constraint forall(s in SLOTS)(
    sum(e in EXAMS where requiere_pc[e])(
        alumnos[e] * bool2int(slot_asignado[e] = s)) <= capacidad_pc_slot[s]
);


% R3: capacidad maxima de enchufes en una fecha-slot
%===================================================

constraint forall(s in SLOTS)(
    sum(e in EXAMS where requiere_enchufes[e])(
        alumnos[e] * bool2int(slot_asignado[e] = s)) <= capacidad_enchufes_slot[s]
);


% R4: capacidad maxima de examenes en una fecha-slot
%===================================================

constraint forall(s in SLOTS)(
    sum(e in EXAMS)(bool2int(slot_asignado[e] = s)) <= max_examenes_por_slot
);


% R5: no permitir examenes del mismo semestre y titulación en el mismo dia
%==========================================================================

constraint forall(
    e1, e2 in EXAMS, t in TITULACIONES
    where e1 < e2 
        /\ semestre_examen[e1,t] > 0 
        /\ semestre_examen[e2,t] > 0 
        /\ semestre_examen[e1,t] = semestre_examen[e2,t]
        % Solo pongo distancia de dias si num exam < num dias (por las optativas de cuarto de GII) 
        %Parte derecha: resto 1 pq primero no necesita dist previa y despues lo añado
        /\ n_exam_por_tituSem[t, semestre_examen[e1,t]] <= max_examenes_repartibles 
    )(
    (dia_examen[e1] - dia_examen[e2]) >= min_dias_mismo_semestre
    \/ (dia_examen[e2] - dia_examen[e1]) >= min_dias_mismo_semestre
);


% R7: no permitir examenes del mismo semestre y titulación en el mismo slot
%==========================================================================

constraint forall(t in TITULACIONES, s in SEMESTRES where s > 0)(
    alldifferent([slot_asignado[e] | e in EXAMS where semestre_examen[e,t] = s])
);


% P1: examenes de misma titulación y semestre demasiado cerca en slots
%======================================================================

var int: mismo_semestre =
    sum(t in TITULACIONES, s in SEMESTRES where s > 0
        /\ card(exams_por_tituSem[t,s]) >= 2)(
        sum(e1, e2 in exams_por_tituSem[t,s] where e1 < e2)(
            max(0, min_dist_mismo_semestre
                   - abs(slot_asignado[e1] - slot_asignado[e2]))
        )
    );


% P2: penalizar semestres cercanos de la misma titulacion
%========================================================

var int: semestre_cercano =
    sum(t in TITULACIONES,
        s1 in SEMESTRES, s2 in SEMESTRES
        where s1 > 0 /\ s2 > 0 /\ s2 - s1 = 2
        /\ card(exams_por_tituSem[t,s1]) > 0
        /\ card(exams_por_tituSem[t,s2]) > 0)(
        sum(e1 in exams_por_tituSem[t,s1],
            e2 in exams_por_tituSem[t,s2])(
            max(0, min_dist_semestre_cercano
                   - abs(slot_asignado[e1] - slot_asignado[e2]))
        )
    );


% P3: examenes del mismo semestre y titulación en dias consecutivos
%==================================================================

var int: dias_consecutivos =
    sum(t in TITULACIONES, s in SEMESTRES where s > 0
        /\ card(exams_por_tituSem[t,s]) >= 2)(
        sum(e1, e2 in exams_por_tituSem[t,s] where e1 < e2)(
            bool2int(abs(dia_examen[e1] - dia_examen[e2]) = 1)
        )
    );

% P4: examenes del mismo semestre y titulación en el mismo dia
%==============================================================
% Esto es por si R6 no se aplica por el num de exam repartibles
var int: mismo_dia =
    sum(t in TITULACIONES, s in SEMESTRES where s > 0
        /\ card(exams_por_tituSem[t,s]) >= 2)(
        sum(e1, e2 in exams_por_tituSem[t,s] where e1 < e2)(
            bool2int(dia_examen[e1] = dia_examen[e2])
        )
    );
    
% Función objetivo
%=================


solve :: int_search(slot_asignado, first_fail, indomain_median)
      :: restart_luby(100) 
    minimize 1000 * mismo_semestre + 200  * semestre_cercano + 500 * dias_consecutivos + 2000 * mismo_dia <= 134000;
% constraint 1000 * mismo_semestre + 200  * semestre_cercano + 500 * dias_consecutivos + 2000 * mismo_dia <= 134000;
% solve satisfy;


% Output

output[
    nombre_examen[e] ++
    " | Alumnos = " ++ show(alumnos[e]) ++
    " | Slot asignado = " ++ nombre_slot[fix(slot_asignado[e])] ++
    "\n"
    | e in EXAMS
];