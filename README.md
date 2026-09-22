# Simulador de Procesos

Proyecto Final — Sistemas Operativos I
Bachillerato en Ingenieria de Sistemas — UACA

Simulador de los procesos de un sistema operativo: planificacion, gestion y
visualizacion de recursos (CPU, memoria y E/S), modificacion de parametros en
tiempo real y registro de actividad.

**Sin dependencias externas.** Solo requiere Python 3.10 o superior.

---

## Puesta en marcha

```bash
python main.py
```

Abre el panel en <http://127.0.0.1:8765/> con los procesos de
`data/procesos_ejemplo.csv`. Para el tablero de terminal:

```bash
python main.py --interfaz consola
```

Otros ejemplos:

```bash
python main.py --generar 12 --semilla 7 --algoritmo srtf --nucleos 4

# Memoria escasa: obliga al sistema a intercambiar procesos con el disco
python main.py --memoria 256 --intercambio activado --politica-intercambio fifo

# La misma carga sin intercambio, para comparar
python main.py --memoria 256 --intercambio desactivado
```

`python main.py --help` lista todas las opciones y sus rangos validos.

---

## Que hace

**Entrada de datos.** Carga desde CSV, generador de carga sintetica reproducible
por semilla y alta manual de procesos con la simulacion en marcha. Toda entrada
pasa por la misma validacion, con mensajes en espanol que indican archivo, linea
y campo.

**Recursos visibles en tiempo real.**

- *CPU multinucleo* con costo de cambio de contexto configurable. Cada tick de
  nucleo se clasifica en trabajo util, sobrecarga u ocioso.
- *Memoria* por particiones dinamicas contiguas con primer, mejor y peor ajuste,
  fusion de huecos y medicion de fragmentacion externa.
- *Area de intercambio* en disco, con su propia ocupacion, sus imagenes
  suspendidas y el costo en ticks de cada traslado.
- *Dispositivos de E/S* con cola de peticiones.

**Seis politicas de planificacion:** FCFS, SJF, SRTF, Round Robin, Prioridad y
Prioridad apropiativa, esta ultima con envejecimiento contra la inanicion.

**Intercambio (swapping).** Cuando la memoria se llena y hay procesos esperando,
el planificador a mediano plazo expulsa a disco la imagen de un proceso
residente y lo trae de vuelta cuando hay espacio. Tres politicas para elegir la
victima —menor prioridad, mayor memoria y el mas antiguo en memoria— y un costo
de traslado configurable que se cobra como latencia de disco. Se puede
desactivar en caliente para comparar las dos situaciones sobre la misma carga.

**Parametros modificables en caliente:** algoritmo, quantum, nucleos, memoria
total, politica de memoria, intercambio (activado o no), tamano del area de
intercambio, politica de intercambio, costo de intercambio, dispositivos de E/S,
costo de cambio de contexto, envejecimiento y velocidad del reloj. Ninguno
requiere reiniciar la simulacion.

**Saturacion de memoria.** El sistema distingue tres situaciones y ninguna lo
deja colgado: si el proceso cabe pero no hay hueco *ahora*, espera en la cola de
admision; si no hay hueco y el intercambio esta activo, se expulsa una victima
para hacerle sitio; y si pide mas memoria que la memoria fisica total —caso en
que no cabria ni con el sistema vacio— se **rechaza** con el motivo en la
bitacora, en lugar de esperar para siempre por algo imposible.

**Registro y reportes.** Bitacora de eventos clasificada por categoria y
exportacion a `reportes_generados/`: reporte de la corrida, detalle de procesos
en CSV y bitacora completa en CSV.

**Dos interfaces.** Panel web (retícula bento, tema oscuro, diagrama de Gantt,
mapa de memoria, area de intercambio, series de uso) y tablero de consola con
ANSI. Ambas consumen la misma instantanea del simulador.

---

## Ciclo de vida de un proceso

Modelo de siete estados: a los cinco clasicos se suman los dos que introduce el
intercambio, mas `RECHAZADO` para los procesos que no pueden admitirse nunca.

```
                        admision            despacho
        NUEVO ────────────────────► LISTO ──────────► EJECUCION
          │                          ▲   ▲                │
          │ no cabe jamas            │   │ fin de quantum │ fin de rafaga
          ▼                          │   └────────────────┤
      RECHAZADO                      │                    ▼
                                     │              TERMINADO
                          swap-in    │
                                     │        solicitud de E/S
              SUSPENDIDO_LISTO ──────┘   BLOQUEADO ◄───────┘
                     ▲   │                  │  ▲
            fin de   │   │ swap-in          │  │ swap-in
            la E/S   │   └──────────────────│──┘
                     │                      │ swap-out
              SUSPENDIDO_BLOQUEADO ◄────────┘
```

Un proceso suspendido perdio su memoria principal pero conserva su PCB intacto:
al volver retoma la rafaga de CPU y el progreso de E/S donde los dejo.

---

## Estructura

```
Simulador-de-Procesos/
├── main.py                     # Punto de entrada y linea de comandos
├── requirements.txt            # (sin dependencias)
├── data/
│   └── procesos_ejemplo.csv    # Entrada de datos de ejemplo
└── src/
    ├── config.py               # Parametros y su validacion
    ├── modelos/                # PCB y maquina de estados
    │   ├── proceso.py
    │   └── estados.py
    ├── nucleo/                 # Entrada de datos, planificador y reloj
    │   ├── entrada.py
    │   ├── planificador.py
    │   └── simulador.py
    ├── algoritmos/             # Politicas de planificacion
    │   ├── base.py
    │   ├── fcfs.py
    │   ├── sjf.py
    │   ├── round_robin.py
    │   └── prioridad.py
    ├── recursos/               # CPU, memoria, intercambio y dispositivos de E/S
    │   ├── cpu.py
    │   ├── memoria.py
    │   ├── area_intercambio.py
    │   └── dispositivos_es.py
    ├── reportes/               # Bitacora y metricas
    │   ├── registro.py
    │   └── metricas.py
    └── interfaz/               # Panel web (+ web/) y consola
        ├── grafica.py
        ├── consola.py
        └── web/
```

---

## Arquitectura

Patron **Modelo - Vista - Controlador**, con una regla que se cumple sin
excepciones: **las vistas no calculan nada**. Consumen una instantanea
(`Simulador.instantanea()`) y envian ordenes; toda la logica vive en el nucleo.

| Capa | Modulos |
|---|---|
| Vistas | `interfaz/grafica.py` (panel web), `interfaz/consola.py` (terminal) |
| Controladores | `nucleo/simulador.py`, `nucleo/planificador.py`, `nucleo/entrada.py`, `algoritmos/` |
| Modelos | `modelos/`, `recursos/`, `reportes/`, `config.py` |

Las dependencias apuntan siempre hacia adentro: `interfaz` conoce a `nucleo`;
`nucleo` conoce a `modelos`, `recursos` y `algoritmos`; los modelos no conocen a
nadie.

### Decisiones tecnicas

**Las colas se derivan del estado.** `Planificador` guarda una sola lista de
procesos y expone `listos`, `bloqueados`, etc. como propiedades que filtran por
estado. Mantener listas paralelas es la fuente clasica de desincronizacion entre
la cola y el PCB. El orden FIFO se conserva con `secuencia_listos`.

**Los algoritmos solo definen un criterio de orden.** La seleccion y la
expropiacion se implementan una sola vez en `AlgoritmoPlanificacion`; cada
politica sobrescribe `clave_orden()`. FCFS y Round Robin heredan el orden FIFO
por defecto.

**Un solo descriptor por parametro.** `PARAMETROS` define etiqueta, tipo,
limites, unidad y ayuda. El mismo diccionario valida los cambios, genera las
opciones de la linea de comandos y construye los controles de las dos interfaces.

**Un unico cerrojo reentrante.** El reloj corre en un hilo aparte mientras el
panel web atiende peticiones; todas las mutaciones pasan por `Simulador._bloqueo`.
La espera entre ticks ocurre fuera del cerrojo para no bloquear a la interfaz.

**Cambios de parametros con reversion.** Si un recurso rechaza el cambio (por
ejemplo, reducir la memoria por debajo de lo que ocupan los procesos cargados),
la configuracion vuelve a su valor anterior.

**El intercambio no expulsa a cualquiera.** Un proceso en ejecucion nunca es
victima: quitarle la memoria obligaria a deshacer el despacho y a tirar el
cambio de contexto ya pagado. Tampoco lo es quien acaba de entrar en el mismo
tick, porque eso abriria un ciclo de expulsar y traer el mismo proceso sin que
avance nunca. Entre los candidatos van primero los bloqueados: estan esperando
E/S y no van a pedir CPU pronto, asi que su memoria es la que menos duele.

**El swap-in tiene prioridad sobre la admision.** Los procesos suspendidos
vuelven a memoria antes de que entren los nuevos. Ya consumieron CPU y
recursos; dejarlos en disco mientras entra trabajo fresco alargaria su tiempo
de retorno sin ganancia para el sistema.

**Liberar memoria no es lo mismo que tener hueco.** Con particiones contiguas,
dos bloques liberados solo sirven si quedan pegados. Por eso el planificador
vuelve a consultar `hay_hueco()` despues de cada expulsion en lugar de sumar los
KB liberados.

---

## Cumplimiento de los requisitos

| Requisito del enunciado | Donde vive |
|---|---|
| Simulacion de la entrada de datos | [entrada.py](src/nucleo/entrada.py), [procesos_ejemplo.csv](data/procesos_ejemplo.csv) |
| Consumo de CPU, memoria y E/S | [cpu.py](src/recursos/cpu.py), [memoria.py](src/recursos/memoria.py), [dispositivos_es.py](src/recursos/dispositivos_es.py) |
| Intercambio con memoria secundaria | [area_intercambio.py](src/recursos/area_intercambio.py), [planificador.py](src/nucleo/planificador.py) |
| Parametros modificables en tiempo real | [config.py](src/config.py), [simulador.py](src/nucleo/simulador.py) |
| Registro y reporte de actividades | [registro.py](src/reportes/registro.py), [metricas.py](src/reportes/metricas.py) |
| Interfaz grafica o de consola | [grafica.py](src/interfaz/grafica.py), [consola.py](src/interfaz/consola.py) |
