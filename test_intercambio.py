"""
Comprobacion del planificador a mediano plazo.

El punto delicado del intercambio es que la expulsion sea todo o nada. Si el
sistema manda procesos a disco sin garantizar que el hueco se va a abrir, cae en
hiperpaginacion: los expulsa, no consigue nada, los trae de vuelta al tick
siguiente y vuelve a expulsarlos, para siempre y sin que nadie use la CPU.

Ejecutar:  python test_intercambio.py
"""

import random

from src.config import ConfiguracionSimulacion
from src.modelos.proceso import Proceso
from src.nucleo.simulador import Simulador
from src.recursos.memoria import GestorMemoria

LIMITE_TICKS = 3000


def _carga(semilla: int) -> list[Proceso]:
    rnd = random.Random(semilla)
    return [
        Proceso(
            pid=i + 1,
            nombre=f"P{i + 1}",
            tiempo_llegada=rnd.randint(0, 8),
            rafaga_cpu=rnd.randint(2, 12),
            rafaga_es=rnd.choice([0, 0, 2, 4, 6]),
            prioridad=rnd.randint(1, 5),
            memoria_kb=rnd.choice([64, 128, 192, 256, 384, 512]),
        )
        for i in range(rnd.randint(4, 12))
    ]


def probar_plan_de_expulsion() -> None:
    """El plan solo existe si de verdad abre el hueco, y usa el minimo de victimas."""
    memoria = GestorMemoria(512)
    procesos = [Proceso(i, f"P{i}", 0, 5, memoria_kb=128) for i in (1, 2, 3, 4)]
    for proceso in procesos:
        assert memoria.asignar(proceso)

    assert memoria.victimas_necesarias([1, 2, 3, 4], 128) == [1]
    # 256 KB contiguos: liberar 1 y 3 deja dos huecos sueltos de 128, no sirve.
    assert memoria.victimas_necesarias([1, 3, 2], 256) == [1, 3, 2]
    # Nadie puede ceder lo suficiente: no se expulsa a nadie.
    assert memoria.victimas_necesarias([1, 2], 512) is None
    # Ya hay hueco: cero expulsiones.
    memoria.liberar(procesos[0])
    assert memoria.victimas_necesarias([2, 3, 4], 128) == []


def probar_simulacion_bajo_presion() -> None:
    """Con la memoria justa el sistema sigue avanzando y no gasta disco de mas."""
    for semilla in range(40):
        configuracion = ConfiguracionSimulacion(
            memoria_total_kb=512, intercambio_total_kb=1024, nucleos_cpu=2, dispositivos_es=1
        )
        simulador = Simulador(configuracion, _carga(semilla))
        for _ in range(LIMITE_TICKS):
            simulador.avanzar()
            planificador = simulador.planificador
            suspendidos = {p.pid for p in planificador.procesos if p.estado.suspendido}
            assert suspendidos == set(simulador.intercambio.residentes), (
                f"semilla {semilla}: los suspendidos no cuadran con las imagenes en disco"
            )
            residente = sum(p.memoria_kb for p in planificador.procesos if p.estado.residente)
            assert simulador.memoria.usados_kb == residente, (
                f"semilla {semilla}: la memoria ocupada no cuadra con los residentes"
            )
            if planificador.finalizada:
                break

        assert simulador.planificador.finalizada, (
            f"semilla {semilla}: la simulacion no termino en {LIMITE_TICKS} ticks "
            f"(hiperpaginacion: {simulador.intercambio.intercambios_salida} swap-outs)"
        )
        # Una corrida sana intercambia unas pocas veces por proceso. Cientos de
        # traslados para una decena de procesos solo puede ser hiperpaginacion.
        assert simulador.intercambio.intercambios_salida < 20 * len(simulador.definiciones), (
            f"semilla {semilla}: {simulador.intercambio.intercambios_salida} swap-outs "
            f"para {len(simulador.definiciones)} procesos"
        )


if __name__ == "__main__":
    probar_plan_de_expulsion()
    probar_simulacion_bajo_presion()
    print("intercambio: todo en orden")
