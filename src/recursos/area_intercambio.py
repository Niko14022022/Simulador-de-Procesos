"""
Area de intercambio (swapping): la memoria secundaria donde el sistema guarda
la imagen de los procesos que expulsa de la memoria principal.

Es el respaldo del planificador a mediano plazo. Cuando la memoria fisica se
llena y hay procesos esperando para entrar, el sistema elige una victima entre
los procesos residentes, copia su imagen aqui y libera su particion. Mas tarde,
cuando vuelve a haber espacio, la imagen se lee de vuelta (swap-in) y el proceso
retoma exactamente donde iba: no pierde su rafaga de CPU ni su progreso de E/S.

A diferencia de la memoria principal, el area de intercambio no se modela por
particiones contiguas: en disco la imagen puede fragmentarse sin costo de
busqueda apreciable en este nivel de simulacion, asi que basta con llevar la
cuenta de cuanto ocupa cada proceso.
"""

from ..modelos.proceso import Proceso

POLITICAS_INTERCAMBIO = {
    "menor_prioridad": "Menor prioridad",
    "mayor_memoria": "Mayor memoria",
    "fifo": "Mas antiguo en memoria",
}


class AreaIntercambio:
    """
    Almacen de imagenes de procesos suspendidos, con la politica que decide a
    quien expulsar de la memoria principal cuando hace falta espacio.
    """

    def __init__(
        self,
        total_kb: int,
        politica: str = "menor_prioridad",
        habilitado: bool = True,
        costo_transferencia: int = 1,
    ):
        self.total_kb = total_kb
        self.politica = self._validar_politica(politica)
        self.habilitado = habilitado
        self.costo_transferencia = costo_transferencia

        self.residentes: dict[int, int] = {}
        self.intercambios_salida = 0
        self.intercambios_entrada = 0
        self.ticks_transferencia = 0

    @staticmethod
    def _validar_politica(politica: str) -> str:
        if politica not in POLITICAS_INTERCAMBIO:
            validas = ", ".join(POLITICAS_INTERCAMBIO)
            raise ValueError(
                f"Politica de intercambio invalida: '{politica}'. Validas: {validas}."
            )
        return politica

    # --------------------------------------------------------------- consultas

    @property
    def usados_kb(self) -> int:
        return sum(self.residentes.values())

    @property
    def libres_kb(self) -> int:
        return self.total_kb - self.usados_kb

    @property
    def porcentaje_uso(self) -> float:
        if self.total_kb == 0:
            return 0.0
        return round(self.usados_kb / self.total_kb * 100, 1)

    @property
    def procesos_suspendidos(self) -> int:
        return len(self.residentes)

    def contiene(self, pid: int) -> bool:
        return pid in self.residentes

    def cabe(self, kilobytes: int) -> bool:
        return self.habilitado and kilobytes <= self.libres_kb

    # -------------------------------------------------------------- operaciones

    def almacenar(self, proceso: Proceso) -> bool:
        """
        Copia la imagen del proceso al area de intercambio (swap-out). Devuelve
        False si el area no tiene espacio, en cuyo caso el proceso debe seguir
        en memoria principal.
        """
        if not self.cabe(proceso.memoria_kb):
            return False

        self.residentes[proceso.pid] = proceso.memoria_kb
        self.intercambios_salida += 1
        proceso.intercambios_salida += 1
        proceso.transferencia_restante = self.costo_transferencia
        self.ticks_transferencia += self.costo_transferencia
        return True

    def recuperar(self, proceso: Proceso) -> None:
        """Lee la imagen de vuelta a memoria principal (swap-in)."""
        if self.residentes.pop(proceso.pid, None) is None:
            return
        self.intercambios_entrada += 1
        proceso.intercambios_entrada += 1
        proceso.transferencia_restante = self.costo_transferencia
        self.ticks_transferencia += self.costo_transferencia

    def descartar(self, proceso: Proceso) -> None:
        """Libera la imagen sin traerla de vuelta (proceso terminado o rechazado)."""
        self.residentes.pop(proceso.pid, None)

    # ---------------------------------------------------------------- politica

    def clave_victima(self, proceso: Proceso) -> tuple:
        """
        Orden de expulsion segun la politica activa: la clave mas baja es la
        primera victima. El PID cierra la clave para que los empates se
        resuelvan siempre igual y la simulacion sea reproducible.
        """
        if self.politica == "mayor_memoria":
            # Expulsar al mas grande libera espacio para varios procesos chicos.
            return (-proceso.memoria_kb, proceso.pid)
        if self.politica == "fifo":
            # El que lleva mas tiempo en memoria ya tuvo su oportunidad.
            return (proceso.tick_residente_desde or 0, proceso.pid)
        # Menor prioridad: en este simulador el numero mas alto es el menos urgente.
        return (-proceso.prioridad, proceso.pid)

    def cambiar_politica(self, politica: str) -> None:
        self.politica = self._validar_politica(politica)

    def cambiar_habilitado(self, habilitado: bool) -> None:
        self.habilitado = habilitado

    def redimensionar(self, total_kb: int) -> None:
        """
        Cambia el tamano del area en caliente. No se puede reducir por debajo de
        lo que ya ocupan las imagenes suspendidas: esos procesos existen y su
        imagen no puede desaparecer.
        """
        if total_kb < self.usados_kb:
            raise ValueError(
                f"Area de intercambio: no se puede reducir a {total_kb} KB, las "
                f"imagenes suspendidas ocupan {self.usados_kb} KB."
            )
        self.total_kb = total_kb

    # -------------------------------------------------------------- proyeccion

    def como_diccionario(self) -> dict:
        return {
            "habilitado": self.habilitado,
            "total_kb": self.total_kb,
            "usados_kb": self.usados_kb,
            "libres_kb": self.libres_kb,
            "porcentaje_uso": self.porcentaje_uso,
            "politica": self.politica,
            "politica_etiqueta": POLITICAS_INTERCAMBIO[self.politica],
            "costo_transferencia": self.costo_transferencia,
            "procesos_suspendidos": self.procesos_suspendidos,
            "intercambios_salida": self.intercambios_salida,
            "intercambios_entrada": self.intercambios_entrada,
            "ticks_transferencia": self.ticks_transferencia,
            "imagenes": [
                {"pid": pid, "memoria_kb": kilobytes}
                for pid, kilobytes in sorted(self.residentes.items())
            ],
        }
