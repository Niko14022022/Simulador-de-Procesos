"""Estados del ciclo de vida de un proceso."""

from enum import Enum


class EstadoProceso(Enum):
    """
    Ciclo de vida modelado por el simulador (modelo de siete estados):

        NUEVO -> LISTO -> EJECUCION -> TERMINADO
          |        ^          |
          |        |          v
          |        +----- BLOQUEADO          (solicitud de E/S)
          |        |          |
          v        v          v
        RECHAZADO  SUSPENDIDO_LISTO <- SUSPENDIDO_BLOQUEADO

    NUEVO es la cola de admision: el proceso ya llego al sistema pero todavia no
    tiene memoria asignada, asi que el planificador a largo plazo aun no lo deja
    competir por la CPU.

    Los dos estados suspendidos son los que introduce el intercambio (swapping).
    Un proceso suspendido perdio su memoria principal y vive en el area de
    intercambio: SUSPENDIDO_LISTO podria ejecutarse en cuanto vuelva a memoria,
    mientras que SUSPENDIDO_BLOQUEADO todavia espera que termine su E/S. Cuando
    esa E/S concluye, el proceso pasa a SUSPENDIDO_LISTO sin necesidad de
    volver a memoria.

    RECHAZADO es un estado terminal para los procesos que jamas podrian cargarse
    porque piden mas memoria que la memoria fisica total. Sin el, un proceso asi
    esperaria en NUEVO indefinidamente y la simulacion nunca terminaria.
    """

    NUEVO = "nuevo"
    LISTO = "listo"
    EJECUCION = "ejecucion"
    BLOQUEADO = "bloqueado"
    SUSPENDIDO_LISTO = "suspendido_listo"
    SUSPENDIDO_BLOQUEADO = "suspendido_bloqueado"
    TERMINADO = "terminado"
    RECHAZADO = "rechazado"

    @property
    def etiqueta(self) -> str:
        return _ETIQUETAS[self]

    @property
    def suspendido(self) -> bool:
        """El proceso esta fuera de memoria principal, en el area de intercambio."""
        return self in (EstadoProceso.SUSPENDIDO_LISTO, EstadoProceso.SUSPENDIDO_BLOQUEADO)

    @property
    def terminal(self) -> bool:
        """No hay transiciones posibles desde aqui: el proceso salio del sistema."""
        return self in (EstadoProceso.TERMINADO, EstadoProceso.RECHAZADO)

    @property
    def residente(self) -> bool:
        """El proceso ocupa memoria principal en este momento."""
        return self in (
            EstadoProceso.LISTO,
            EstadoProceso.EJECUCION,
            EstadoProceso.BLOQUEADO,
        )


_ETIQUETAS = {
    EstadoProceso.NUEVO: "Nuevo",
    EstadoProceso.LISTO: "Listo",
    EstadoProceso.EJECUCION: "En ejecucion",
    EstadoProceso.BLOQUEADO: "Bloqueado (E/S)",
    EstadoProceso.SUSPENDIDO_LISTO: "Suspendido listo",
    EstadoProceso.SUSPENDIDO_BLOQUEADO: "Suspendido bloqueado",
    EstadoProceso.TERMINADO: "Terminado",
    EstadoProceso.RECHAZADO: "Rechazado",
}

TRANSICIONES_VALIDAS = {
    EstadoProceso.NUEVO: {EstadoProceso.LISTO, EstadoProceso.RECHAZADO},
    EstadoProceso.LISTO: {EstadoProceso.EJECUCION, EstadoProceso.SUSPENDIDO_LISTO},
    EstadoProceso.EJECUCION: {
        EstadoProceso.LISTO,
        EstadoProceso.BLOQUEADO,
        EstadoProceso.TERMINADO,
    },
    EstadoProceso.BLOQUEADO: {EstadoProceso.LISTO, EstadoProceso.SUSPENDIDO_BLOQUEADO},
    # Un proceso suspendido vuelve a memoria (swap-in) o, si su E/S termina
    # mientras esta en disco, cambia de cola sin volver a memoria.
    EstadoProceso.SUSPENDIDO_LISTO: {EstadoProceso.LISTO},
    EstadoProceso.SUSPENDIDO_BLOQUEADO: {
        EstadoProceso.SUSPENDIDO_LISTO,
        EstadoProceso.BLOQUEADO,
    },
    EstadoProceso.TERMINADO: set(),
    EstadoProceso.RECHAZADO: set(),
}


def transicion_permitida(origen: EstadoProceso, destino: EstadoProceso) -> bool:
    return destino in TRANSICIONES_VALIDAS[origen]
