"""
Planificador: coordina el ciclo de vida de los procesos en cada tick.

El estado de cada proceso es la unica fuente de verdad; las colas se derivan de
`self.procesos` filtrando por estado. Asi es imposible que una cola quede
desincronizada del PCB, que es el error clasico al mantener listas paralelas.

Conviven aqui los tres niveles clasicos de planificacion:

- *Largo plazo* (`_admitir`): decide que procesos nuevos entran al sistema, es
  decir a quien se le concede memoria principal.
- *Mediano plazo* (`_reactivar` y `_liberar_memoria_para`): decide quien sale de
  memoria hacia el area de intercambio y quien vuelve. Es el que permite que el
  sistema siga aceptando trabajo aunque la memoria este llena.
- *Corto plazo* (`_expropiar` y `_despachar`): decide que proceso listo ocupa
  cada nucleo de CPU, delegando el criterio en el algoritmo activo.
"""

from ..algoritmos import crear_algoritmo
from ..modelos.estados import EstadoProceso
from ..modelos.proceso import Proceso


class Planificador:
    def __init__(self, configuracion, cpu, memoria, intercambio, dispositivos_es, registro):
        self.configuracion = configuracion
        self.cpu = cpu
        self.memoria = memoria
        self.intercambio = intercambio
        self.dispositivos_es = dispositivos_es
        self.registro = registro

        self.procesos: list[Proceso] = []
        self.reloj = 0
        self.algoritmo = crear_algoritmo(configuracion.algoritmo, configuracion)
        self._secuencia = 0
        self._sin_memoria: set[int] = set()
        self._completados_es: list[Proceso] = []
        self._estancamiento_avisado = False

    # ------------------------------------------------------------------ colas

    def _por_estado(self, estado: EstadoProceso) -> list[Proceso]:
        return [proceso for proceso in self.procesos if proceso.estado is estado]

    @property
    def programados(self) -> list[Proceso]:
        """Procesos definidos que todavia no han llegado al sistema."""
        return [p for p in self._por_estado(EstadoProceso.NUEVO) if p.tiempo_llegada > self.reloj]

    @property
    def nuevos(self) -> list[Proceso]:
        """Llegaron, pero esperan memoria para ser admitidos."""
        return [p for p in self._por_estado(EstadoProceso.NUEVO) if p.tiempo_llegada <= self.reloj]

    @property
    def listos(self) -> list[Proceso]:
        return sorted(self._por_estado(EstadoProceso.LISTO), key=lambda p: p.secuencia_listos)

    @property
    def despachables(self) -> list[Proceso]:
        """
        Listos que ademas pueden ocupar la CPU ahora mismo. Un proceso recien
        traido del area de intercambio esta en la cola de listos pero su imagen
        todavia se esta leyendo del disco, asi que no es despachable.
        """
        return [p for p in self.listos if not p.transferencia_en_curso]

    @property
    def en_ejecucion(self) -> list[Proceso]:
        return self._por_estado(EstadoProceso.EJECUCION)

    @property
    def bloqueados(self) -> list[Proceso]:
        return self._por_estado(EstadoProceso.BLOQUEADO)

    @property
    def suspendidos_listos(self) -> list[Proceso]:
        return self._por_estado(EstadoProceso.SUSPENDIDO_LISTO)

    @property
    def suspendidos_bloqueados(self) -> list[Proceso]:
        return self._por_estado(EstadoProceso.SUSPENDIDO_BLOQUEADO)

    @property
    def suspendidos(self) -> list[Proceso]:
        return [p for p in self.procesos if p.estado.suspendido]

    @property
    def residentes(self) -> list[Proceso]:
        """Procesos que ocupan memoria principal en este momento."""
        return [p for p in self.procesos if p.estado.residente]

    @property
    def terminados(self) -> list[Proceso]:
        return self._por_estado(EstadoProceso.TERMINADO)

    @property
    def rechazados(self) -> list[Proceso]:
        return self._por_estado(EstadoProceso.RECHAZADO)

    @property
    def finalizada(self) -> bool:
        return bool(self.procesos) and all(p.estado.terminal for p in self.procesos)

    # ------------------------------------------------------------- operaciones

    def agregar(self, proceso: Proceso) -> None:
        self.procesos.append(proceso)
        # Un proceso con llegada futura lo anuncia el tick correspondiente; solo
        # se avisa aqui si se incorpora con la llegada ya vencida.
        if proceso.tiempo_llegada < self.reloj:
            self._anunciar_llegada(proceso)

    def sincronizar_algoritmo(self) -> None:
        if self.algoritmo.nombre != self.configuracion.algoritmo:
            self.algoritmo = crear_algoritmo(self.configuracion.algoritmo, self.configuracion)

    def reencolar(self, proceso: Proceso) -> None:
        """Devuelve un proceso al final de la cola de listos."""
        self._secuencia += 1
        proceso.secuencia_listos = self._secuencia
        proceso.cambiar_estado(EstadoProceso.LISTO, self.reloj)

    def tick(self, reloj: int) -> None:
        self.reloj = reloj
        self.sincronizar_algoritmo()

        self._anunciar_llegadas()
        self._avanzar_transferencias()
        self._rechazar_imposibles()
        self._reactivar()
        self._admitir()
        self._expropiar()
        self._despachar()
        self._ejecutar()
        self._contabilizar_espera()
        self._resolver_salidas()
        self._vigilar_estancamiento()

    # --------------------------------------------------------------- etapas

    def _anunciar_llegada(self, proceso: Proceso) -> None:
        self.registro.registrar(
            self.reloj,
            "llegada",
            f"Llego {proceso.nombre} (rafaga CPU {proceso.rafaga_cpu}, "
            f"E/S {proceso.rafaga_es}, {proceso.memoria_kb} KB)",
            proceso.pid,
        )

    def _anunciar_llegadas(self) -> None:
        for proceso in self.procesos:
            if proceso.estado is EstadoProceso.NUEVO and proceso.tiempo_llegada == self.reloj:
                self._anunciar_llegada(proceso)

    def _avanzar_transferencias(self) -> None:
        """Descuenta la latencia del disco de los traslados en curso."""
        for proceso in self.procesos:
            if proceso.transferencia_en_curso:
                proceso.avanzar_transferencia()

    def _rechazar_imposibles(self) -> None:
        """
        Un proceso que pide mas memoria que la memoria fisica total no cabe ni
        con el sistema vacio: la asignacion contigua no puede partirlo y el
        intercambio tampoco ayuda, porque el area de intercambio solo sirve para
        guardar imagenes de procesos que si caben. Sin este rechazo el proceso
        esperaria en NUEVO para siempre y la simulacion nunca terminaria.
        """
        for proceso in list(self.nuevos):
            if proceso.memoria_kb <= self.memoria.total_kb:
                continue
            proceso.motivo_rechazo = (
                f"requiere {proceso.memoria_kb} KB y la memoria fisica total es de "
                f"{self.memoria.total_kb} KB"
            )
            proceso.cambiar_estado(EstadoProceso.RECHAZADO, self.reloj)
            proceso.tick_finalizacion = self.reloj
            self._sin_memoria.discard(proceso.pid)
            self.registro.registrar(
                self.reloj,
                "rechazo",
                f"{proceso.nombre} rechazado por el sistema: {proceso.motivo_rechazo}",
                proceso.pid,
            )

    # -------------------------------------------------- planificador a mediano

    def _reactivar(self) -> None:
        """
        Swap-in: devuelve a memoria los procesos suspendidos que ya pueden
        seguir ejecutandose. Tienen prioridad sobre los procesos nuevos porque
        ya consumieron CPU y recursos; dejarlos en disco mientras entra trabajo
        nuevo alargaria su retorno sin ganar nada.

        Se intenta con todos los candidatos y no se corta en el primer fallo:
        un proceso pequeno puede caber en un hueco donde uno grande no.
        """
        candidatos = sorted(
            (p for p in self.suspendidos_listos if not p.transferencia_en_curso),
            key=lambda p: (p.prioridad, p.pid),
        )
        for proceso in candidatos:
            if not self.memoria.hay_hueco(proceso.memoria_kb):
                continue
            self.memoria.asignar(proceso)
            self.intercambio.recuperar(proceso)
            proceso.tick_residente_desde = self.reloj
            self.reencolar(proceso)
            self.registro.registrar(
                self.reloj,
                "intercambio",
                f"{proceso.nombre} vuelve a memoria (swap-in): {proceso.memoria_kb} KB "
                f"en la direccion {proceso.direccion_memoria}",
                proceso.pid,
            )

    def _candidatos_victima(self) -> list[Proceso]:
        """
        Procesos que pueden ser expulsados de memoria, del mejor candidato al
        peor.

        Nunca se expulsa a un proceso en ejecucion: quitarle la memoria a quien
        esta usando la CPU obligaria a deshacer el despacho y desperdiciaria el
        cambio de contexto que ya se pago. Tampoco se expulsa a quien acaba de
        entrar en este mismo tick, porque eso abriria un ciclo de expulsar y
        traer al mismo proceso una y otra vez (hiperpaginacion).

        Los bloqueados van primero: estan esperando E/S y no van a necesitar la
        CPU en el corto plazo, asi que su memoria es la que menos duele. Entre
        iguales decide la politica de intercambio configurada.
        """
        candidatos = [
            p for p in self.residentes
            if p.estado is not EstadoProceso.EJECUCION
            and not p.transferencia_en_curso
            and p.tick_residente_desde != self.reloj
        ]
        return sorted(
            candidatos,
            key=lambda p: (
                0 if p.estado is EstadoProceso.BLOQUEADO else 1,
                self.intercambio.clave_victima(p),
            ),
        )

    def _suspender(self, proceso: Proceso) -> bool:
        """
        Swap-out: copia la imagen del proceso al area de intercambio y libera su
        particion de memoria principal. El PCB conserva la rafaga pendiente, de
        modo que al volver el proceso continua donde iba.
        """
        if not self.intercambio.almacenar(proceso):
            return False

        origen = proceso.estado
        liberados = proceso.memoria_kb
        self.memoria.liberar(proceso)
        proceso.cambiar_estado(
            EstadoProceso.SUSPENDIDO_BLOQUEADO if origen is EstadoProceso.BLOQUEADO
            else EstadoProceso.SUSPENDIDO_LISTO,
            self.reloj,
        )
        proceso.tick_residente_desde = None
        self.registro.registrar(
            self.reloj,
            "intercambio",
            f"{proceso.nombre} sale de memoria (swap-out) desde {origen.etiqueta}: "
            f"libera {liberados} KB",
            proceso.pid,
        )
        return True

    def _liberar_memoria_para(self, solicitante: Proceso) -> bool:
        """
        Expulsa procesos hasta abrir un hueco contiguo para el solicitante.

        La expulsion es todo o nada: primero se calcula que victimas hacen falta
        y se comprueba que la operacion completa es viable, y solo entonces se
        ejecuta. Expulsar sin esa garantia es lo que produce hiperpaginacion: se
        manda gente a disco, el hueco nunca llega a abrirse, el planificador a
        mediano plazo los trae de vuelta al tick siguiente y vuelve a expulsarlos.
        El sistema se pasa la vida moviendo imagenes entre memoria y disco sin
        que ningun proceso llegue a usar la CPU.
        """
        if not self.configuracion.intercambio_activo:
            return False

        victimas = {p.pid: p for p in self._candidatos_victima()}
        plan = self.memoria.victimas_necesarias(list(victimas), solicitante.memoria_kb)
        if plan is None:
            # Ni expulsando a todos los candidatos se abre el hueco: no se
            # expulsa a nadie y el solicitante espera a que alguien termine.
            return False

        # El area de intercambio tiene que poder con todas las imagenes del plan.
        # Si se llenara a mitad de camino, las expulsiones ya hechas serian
        # perdida pura, que es el mismo problema por otro lado.
        requerido = sum(victimas[pid].memoria_kb for pid in plan)
        if requerido > self.intercambio.libres_kb:
            if solicitante.pid not in self._sin_memoria:
                self.registro.registrar(
                    self.reloj,
                    "error",
                    f"Area de intercambio llena ({self.intercambio.usados_kb}/"
                    f"{self.intercambio.total_kb} KB): hacen falta {requerido} KB "
                    f"libres para abrir memoria a {solicitante.nombre}",
                    solicitante.pid,
                )
            return False

        for pid in plan:
            self._suspender(victimas[pid])
        return True

    # ---------------------------------------------------- planificador a largo

    def _admitir(self) -> None:
        """Planificador a largo plazo: NUEVO -> LISTO cuando hay memoria libre."""
        for proceso in sorted(self.nuevos, key=lambda p: (p.tiempo_llegada, p.pid)):
            if self.memoria.hay_hueco(proceso.memoria_kb) or self._liberar_memoria_para(proceso):
                self._cargar(proceso)
            elif proceso.pid not in self._sin_memoria:
                # Se avisa una sola vez por proceso para no inundar la bitacora.
                self._sin_memoria.add(proceso.pid)
                motivo = (
                    "el intercambio no pudo liberar mas"
                    if self.configuracion.intercambio_activo
                    else "el intercambio esta desactivado"
                )
                self.registro.registrar(
                    self.reloj,
                    "error",
                    f"{proceso.nombre} en espera: requiere {proceso.memoria_kb} KB, el "
                    f"mayor hueco libre es de {self.memoria.mayor_hueco_kb} KB y "
                    f"{motivo}",
                    proceso.pid,
                )

    def _cargar(self, proceso: Proceso) -> None:
        self.memoria.asignar(proceso)
        proceso.tick_admision = self.reloj
        proceso.tick_residente_desde = self.reloj
        self._sin_memoria.discard(proceso.pid)
        self.reencolar(proceso)
        self.registro.registrar(
            self.reloj,
            "memoria",
            f"{proceso.nombre} admitido: {proceso.memoria_kb} KB en la "
            f"direccion {proceso.direccion_memoria}",
            proceso.pid,
        )

    # ---------------------------------------------------- planificador a corto

    def _expropiar(self) -> None:
        """
        Libera nucleos cuando el algoritmo lo exige (quantum agotado o candidato
        mas urgente). Se expropian como maximo tantos nucleos como candidatos
        haya en espera, para no provocar cambios de contexto inutiles.
        """
        candidatos = self.despachables
        if not candidatos:
            return

        activos = [n for n in self.cpu.nucleos if not n.libre and not n.conmutando]
        activos.sort(key=lambda n: self.algoritmo.orden_expropiacion(n, self.reloj), reverse=True)

        reservados = 0
        for nucleo in activos:
            if reservados >= len(candidatos):
                break
            candidato = candidatos[reservados]
            proceso = nucleo.proceso
            if not self.algoritmo.debe_expropiar(
                proceso, [candidato], nucleo.ticks_en_proceso, self.reloj
            ):
                continue

            turno = nucleo.ticks_en_proceso
            self.cpu.liberar(nucleo, self.reloj)
            self.reencolar(proceso)
            reservados += 1
            self.registro.registrar(
                self.reloj,
                "expropiacion",
                f"{proceso.nombre} deja el nucleo {nucleo.indice} tras {turno} ticks; "
                f"entra {candidato.nombre}",
                proceso.pid,
            )

    def _despachar(self) -> None:
        for nucleo in self.cpu.nucleos_libres:
            proceso = self.algoritmo.seleccionar(self.despachables, self.reloj)
            if proceso is None:
                return

            proceso.cambiar_estado(EstadoProceso.EJECUCION, self.reloj)
            if proceso.tick_primer_despacho is None:
                proceso.tick_primer_despacho = self.reloj
            self.cpu.asignar(
                nucleo, proceso, self.reloj, self.configuracion.costo_cambio_contexto
            )
            self.registro.registrar(
                self.reloj,
                "despacho",
                f"{proceso.nombre} ocupa el nucleo {nucleo.indice} "
                f"({proceso.cpu_restante} ticks de CPU pendientes)",
                proceso.pid,
            )

    def _ejecutar(self) -> None:
        self.cpu.ejecutar_tick()
        self.dispositivos_es.asignar_pendientes()
        self._completados_es = self.dispositivos_es.ejecutar_tick()

    def _contabilizar_espera(self) -> None:
        """La espera se mide sobre el estado que el proceso tuvo durante el tick."""
        for proceso in self.procesos:
            if proceso.estado is EstadoProceso.LISTO:
                proceso.ticks_espera += 1
            elif proceso.estado is EstadoProceso.BLOQUEADO:
                proceso.ticks_bloqueado += 1
            elif proceso.estado.suspendido:
                # El tiempo fuera de memoria se contabiliza aparte: no es espera
                # por la CPU ni por la E/S, es espera por memoria.
                proceso.ticks_suspendido += 1
                if proceso.estado is EstadoProceso.SUSPENDIDO_BLOQUEADO:
                    proceso.ticks_bloqueado += 1

    def _resolver_salidas(self) -> None:
        for proceso in self._completados_es:
            if proceso.estado is EstadoProceso.SUSPENDIDO_BLOQUEADO:
                # Termino su E/S mientras estaba en disco: pasa a la cola de
                # suspendidos listos y esperara turno para volver a memoria.
                proceso.cambiar_estado(EstadoProceso.SUSPENDIDO_LISTO, self.reloj)
            else:
                self.reencolar(proceso)
            self.registro.registrar(
                self.reloj, "desbloqueo", f"{proceso.nombre} completo su operacion de E/S",
                proceso.pid,
            )
        self._completados_es = []

        for nucleo in list(self.cpu.nucleos):
            proceso = nucleo.proceso
            if proceso is None or nucleo.conmutando:
                continue
            if proceso.finalizo:
                self._finalizar(nucleo, proceso)
            elif proceso.solicita_es:
                self._bloquear(nucleo, proceso)

    def _finalizar(self, nucleo, proceso: Proceso) -> None:
        self.cpu.liberar(nucleo, self.reloj + 1)
        proceso.cambiar_estado(EstadoProceso.TERMINADO, self.reloj + 1)
        proceso.tick_finalizacion = self.reloj + 1
        self.memoria.liberar(proceso)
        self.intercambio.descartar(proceso)
        proceso.tick_residente_desde = None
        self.registro.registrar(
            self.reloj + 1,
            "finalizacion",
            f"{proceso.nombre} termino: retorno {proceso.tiempo_retorno} ticks, "
            f"espera {proceso.ticks_espera} ticks",
            proceso.pid,
        )

    def _bloquear(self, nucleo, proceso: Proceso) -> None:
        self.cpu.liberar(nucleo, self.reloj + 1)
        proceso.cambiar_estado(EstadoProceso.BLOQUEADO, self.reloj + 1)
        proceso.operaciones_es += 1
        proceso.es_restante = proceso.rafaga_es
        self.dispositivos_es.solicitar(proceso)
        self.registro.registrar(
            self.reloj + 1,
            "bloqueo",
            f"{proceso.nombre} solicita E/S por {proceso.rafaga_es} ticks",
            proceso.pid,
        )

    # ----------------------------------------------------------- diagnostico

    def _vigilar_estancamiento(self) -> None:
        """
        Red de seguridad: detecta que el sistema quedo sin ninguna via de
        progreso y lo dice, en lugar de dejar la simulacion girando en vacio.

        Hay progreso posible mientras algun proceso pueda avanzar por su cuenta
        (CPU, E/S o una transferencia de disco en curso) o mientras falte por
        llegar algun proceso programado.
        """
        if self.finalizada:
            return

        puede_avanzar = (
            self.listos
            or self.en_ejecucion
            or self.bloqueados
            or self.suspendidos_bloqueados
            or self.programados
            or any(p.transferencia_en_curso for p in self.procesos)
        )
        detenidos = self.nuevos + self.suspendidos_listos
        # La memoria que se libera al terminar un proceso se reparte en el tick
        # siguiente, no en este. Si alguno de los que esperan ya tiene hueco, el
        # sistema arranca solo y no hay nada que denunciar.
        puede_avanzar = puede_avanzar or any(
            self.memoria.hay_hueco(p.memoria_kb) for p in detenidos
        )
        if puede_avanzar:
            self._estancamiento_avisado = False
            return

        if not detenidos or self._estancamiento_avisado:
            return

        self._estancamiento_avisado = True
        self.registro.registrar(
            self.reloj,
            "error",
            f"El sistema no puede avanzar: {len(detenidos)} proceso(s) esperan memoria "
            f"y ningun otro esta en condiciones de liberarla",
        )

    # ------------------------------------------------- cambios en los recursos

    def aplicar_cambio_nucleos(self, cantidad: int) -> None:
        for proceso in self.cpu.redimensionar(cantidad, self.reloj):
            self.reencolar(proceso)

    def colas_como_diccionario(self) -> dict:
        return {
            "programados": [p.como_diccionario() for p in self.programados],
            "nuevos": [p.como_diccionario() for p in self.nuevos],
            "listos": [p.como_diccionario() for p in self.listos],
            "ejecucion": [p.como_diccionario() for p in self.en_ejecucion],
            "bloqueados": [p.como_diccionario() for p in self.bloqueados],
            "suspendidos_listos": [p.como_diccionario() for p in self.suspendidos_listos],
            "suspendidos_bloqueados": [
                p.como_diccionario() for p in self.suspendidos_bloqueados
            ],
            "terminados": [p.como_diccionario() for p in self.terminados],
            "rechazados": [p.como_diccionario() for p in self.rechazados],
        }
