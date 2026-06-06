
% MODELO 2: ASIGNACIÓN DE AULAS CON SLOTS FIJOS

% Conjuntos principales
%_______________________

int: n_exams;
int: n_aula;
int: n_slots;
int: n_plantas;
int: n_bloques;

int: max_aulas;

set of int: EXAMS = 1..n_exams;
set of int: ROOMS = 1..n_aula;
set of int: SLOTS = 1..n_slots;
set of int: PLANT = 1..n_plantas;
set of int: BLOCK = 1..n_bloques;


% Datos de examenes
%___________________

array[EXAMS] of int: alumnos;
array[EXAMS] of SLOTS: slot_examen;

array[EXAMS] of bool: requiere_pc;
array[EXAMS] of bool: requiere_enchufes;

array[EXAMS] of string: nombre_examen;
array[SLOTS] of string: nombre_slot;


% Datos de aulas
%_________________

array[ROOMS] of int: capacidad;
array[ROOMS] of bool: tiene_enchufes;
array[ROOMS] of bool: es_informatica;

array[ROOMS] of PLANT: planta_aula;
array[ROOMS] of BLOCK: bloque_aula;

array[ROOMS] of string: nombre_aula;

array[ROOMS, SLOTS] of bool: aula_disponible;


% Variable de decisión
%______________________

array[EXAMS, ROOMS] of var 0..1: usa_aula;


% Variables auxiliares
%______________________

array[EXAMS] of var int: capacidadAsig = [sum(r in ROOMS)(usa_aula[e,r] * capacidad[r]) | e in EXAMS];

array[EXAMS] of var int: aulasPorExamen = [sum(r in ROOMS)(usa_aula[e,r]) | e in EXAMS];

array[EXAMS] of var int: excesoPorExamen = [capacidadAsig[e] - alumnos[e] | e in EXAMS];

var int: exceso_total =
    sum(e in EXAMS)(excesoPorExamen[e]);

var int: aulas_usadas =
    sum(e in EXAMS)(aulasPorExamen[e]);


% R1: capacidad suficiente
%==========================

constraint forall(e in EXAMS)(
    capacidadAsig[e] >= alumnos[e]
);


% R2: un aula no puede usarse por dos examenes en un mismo slot
%==============================================================

constraint forall(r in ROOMS, s in SLOTS)(
    sum(e in EXAMS where slot_examen[e] = s)(
        usa_aula[e,r]
    ) <= 1
);


% R3: si requiere PC, solo puede usar aulas informaticas
%========================================================

constraint forall(e in EXAMS, r in ROOMS)(
    requiere_pc[e] /\ not es_informatica[r] -> usa_aula[e,r] = 0
);



% R4: si requiere enchufes, solo puede usar aulas con enchufes
%=============================================================

constraint forall(e in EXAMS, r in ROOMS)(
    requiere_enchufes[e] /\ not tiene_enchufes[r] -> usa_aula[e,r] = 0
);



% R5: todo examen debe usar al menos un aula
%============================================

constraint forall(e in EXAMS)(
    aulasPorExamen[e] >= 1
);


% R6: eliminar el uso de una aula en un slot
%===========================================

constraint forall(e in EXAMS, r in ROOMS)(
    usa_aula[e,r] = 1 -> aula_disponible[r, slot_examen[e]]
);



% R7: maximo de aulas por examen
%================================

constraint forall(e in EXAMS)(
    aulasPorExamen[e] <= max_aulas
);


% P1: usar varias plantas para un mismo examen
%==============================================

array[EXAMS, PLANT] of var 0..1: usa_planta;

constraint forall(e in EXAMS, p in PLANT)(
    usa_planta[e,p] =
        bool2int(sum(r in ROOMS where planta_aula[r] = p)(usa_aula[e,r]) >= 1)
);

array[EXAMS] of var int: num_plantas_examen =[sum(p in PLANT)(usa_planta[e,p]) | e in EXAMS];

var int: plantasDif =
    sum(e in EXAMS)(num_plantas_examen[e] - 1); %Le -1 porque solo penalizo si usa >1


% P2: usar varios bloques para un mismo examen
%==============================================

array[EXAMS, BLOCK] of var 0..1: usa_bloque;

constraint forall(e in EXAMS, b in BLOCK)(
    usa_bloque[e,b] =
        bool2int(sum(r in ROOMS where bloque_aula[r] = b)(usa_aula[e,r]) >= 1)
);

array[EXAMS] of var int: num_bloques_examen = [sum(b in BLOCK)(usa_bloque[e,b]) | e in EXAMS];

var int: bloqueDif =
    sum(e in EXAMS)(num_bloques_examen[e] - 1);


% P3: usar aula informática sin necesitar PC
%===========================================

var int: info_mal =
    sum(e in EXAMS, r in ROOMS)(
        usa_aula[e,r] * bool2int(not requiere_pc[e] /\ es_informatica[r])
    );


% P4: usar aulas grandes para examenes pequeños
%==============================================

var int: aula_grande_mal =
    sum(e in EXAMS, r in ROOMS)(
        usa_aula[e,r] *
        bool2int(capacidad[r] >= 2 * alumnos[e])
    );



% Función objetivo
%==================

% solve satisfy;

solve minimize 60 * exceso_total + 10  * aulas_usadas + 5  * plantasDif + 10  * bloqueDif + 20 * info_mal + 200*aula_grande_mal;


% Output

output[
    nombre_examen[e] ++
    " | Alumnos = " ++ show(alumnos[e]) ++
    " | Slot = " ++ nombre_slot[slot_examen[e]] ++
    " | CapacidadAsignada = " ++ show(capacidadAsig[e]) ++
    " | Exceso = " ++ show(excesoPorExamen[e]) ++
    " | NAulas = " ++ show(aulasPorExamen[e]) ++
    " | Aulas = " ++
        concat([
        if fix(usa_aula[e,r]) = 1 then nombre_aula[r] ++ " " else "" endif
        | r in ROOMS
        ])
    ++ "\n"
    | e in EXAMS
];