"""Metricas de desempeno y generacion de reportes."""

import csv
from collections import deque
from datetime import datetime
from pathlib import Path

from ..modelos.estados import EstadoProceso
from ..modelos.proceso import Proceso

MUESTRAS_SERIE = 180


def _promedio(valores: list[int]) -> float:
    return round(sum(valores) / len(valores), 2) if valores else 0.0


class CalculadoraMetricas:
    """
    Calcula los indicadores clasicos de planificacion y mantiene series de
    tiempo cortas del uso de CPU, memoria y E/S para las graficas en vivo.

    Los promedios se calculan solo sobre procesos terminados: incluir los que
    aun estan en curso daria un tiempo de retorno artificialmente bajo.
    """

    def __init__(self, cpu, memoria, intercambio, dispositivos_es):
        self.cpu = cpu
        self.memoria = memoria
        self.intercambio = intercambio
        self.dispositivos_es = dispositivos_es
        self.series: dict[str, deque] = {
            clave: deque(maxlen=MUESTRAS_SERIE)
            for clave in ("tick", "cpu", "memoria", "intercambio", "es", "listos", "suspendidos")
        }

    def muestrear(self, tick: int, procesos: list[Proceso]) -> None:
        listos = sum(1 for p in procesos if p.estado is EstadoProceso.LISTO)
        suspendidos = sum(1 for p in procesos if p.estado.suspendido)
        self.series["tick"].append(tick)
        self.series["cpu"].append(self.cpu.porcentaje_uso)
        self.series["memoria"].append(self.memoria.porcentaje_uso)
        self.series["intercambio"].append(self.intercambio.porcentaje_uso)
        self.series["es"].append(self.dispositivos_es.porcentaje_uso)
        self.series["listos"].append(listos)
        self.series["suspendidos"].append(suspendidos)

    def reiniciar(self) -> None:
        for serie in self.series.values():
            serie.clear()

    def resumen(self, procesos: list[Proceso], reloj: int) -> dict:
        # Los rechazados nunca llegaron a ejecutarse: promediarlos con los
        # terminados hundiria el tiempo de retorno y mentiria sobre el
        # desempeno del algoritmo.
        terminados = [p for p in procesos if p.estado is EstadoProceso.TERMINADO]
        rechazados = [p for p in procesos if p.estado is EstadoProceso.RECHAZADO]
        conteo_estados = {
            estado.value: sum(1 for p in procesos if p.estado is estado)
            for estado in EstadoProceso
        }

        return {
            "reloj": reloj,
            "procesos_totales": len(procesos),
            "procesos_terminados": len(terminados),
            "procesos_rechazados": len(rechazados),
            "estados": conteo_estados,
            "promedio_espera": _promedio([p.ticks_espera for p in terminados]),
            "promedio_retorno": _promedio([p.tiempo_retorno for p in terminados]),
            "promedio_respuesta": _promedio([p.tiempo_respuesta for p in terminados]),
            "promedio_bloqueo": _promedio([p.ticks_bloqueado for p in terminados]),
            "promedio_suspendido": _promedio([p.ticks_suspendido for p in terminados]),
            "rendimiento": round(len(terminados) / reloj, 3) if reloj else 0.0,
            "cambios_contexto": sum(p.cambios_contexto for p in procesos),
            "uso_cpu": self.cpu.porcentaje_uso,
            "rendimiento_util_cpu": self.cpu.rendimiento_util,
            "ticks_sobrecarga": self.cpu.ticks_sobrecarga,
            "ticks_ocioso_cpu": self.cpu.ticks_ocioso,
            "uso_memoria": self.memoria.porcentaje_uso,
            "fragmentacion_externa": self.memoria.fragmentacion_externa,
            "asignaciones_fallidas": self.memoria.asignaciones_fallidas,
            "uso_intercambio": self.intercambio.porcentaje_uso,
            "intercambios_salida": self.intercambio.intercambios_salida,
            "intercambios_entrada": self.intercambio.intercambios_entrada,
            "ticks_intercambio": self.intercambio.ticks_transferencia,
            "procesos_suspendidos": self.intercambio.procesos_suspendidos,
            "uso_es": self.dispositivos_es.porcentaje_uso,
            "operaciones_es": self.dispositivos_es.operaciones_atendidas,
        }

    def series_como_diccionario(self) -> dict[str, list]:
        return {clave: list(valores) for clave, valores in self.series.items()}

    def exportar_procesos_csv(self, ruta: str | Path, procesos: list[Proceso]) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        columnas = [
            "pid", "nombre", "estado", "tiempo_llegada", "rafaga_cpu", "rafaga_es",
            "prioridad", "memoria_kb", "espera", "bloqueado", "suspendido", "retorno",
            "respuesta", "cambios_contexto", "intercambios_salida", "intercambios_entrada",
            "motivo_rechazo",
        ]
        with ruta.open("w", newline="", encoding="utf-8") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=columnas, extrasaction="ignore")
            escritor.writeheader()
            for proceso in procesos:
                escritor.writerow(proceso.como_diccionario())
        return ruta

    def exportar_reporte(
        self, ruta: str | Path, procesos: list[Proceso], reloj: int, configuracion: dict,
        resumen_bitacora: dict,
    ) -> Path:
        """Reporte legible con la configuracion usada, los indicadores y el detalle."""
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        datos = self.resumen(procesos, reloj)

        lineas = [
            "REPORTE DE SIMULACION DE PROCESOS",
            f"Generado: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "=" * 78,
            "",
            "CONFIGURACION",
            "-" * 78,
        ]
        lineas += [f"  {clave:<28} {valor}" for clave, valor in configuracion.items()]

        lineas += [
            "",
            "INDICADORES GLOBALES",
            "-" * 78,
            f"  {'Ticks simulados':<28} {datos['reloj']}",
            f"  {'Procesos totales':<28} {datos['procesos_totales']}",
            f"  {'Procesos terminados':<28} {datos['procesos_terminados']}",
            f"  {'Procesos rechazados':<28} {datos['procesos_rechazados']}",
            f"  {'Tiempo de espera promedio':<28} {datos['promedio_espera']} ticks",
            f"  {'Tiempo de retorno promedio':<28} {datos['promedio_retorno']} ticks",
            f"  {'Tiempo de respuesta promedio':<28} {datos['promedio_respuesta']} ticks",
            f"  {'Tiempo bloqueado promedio':<28} {datos['promedio_bloqueo']} ticks",
            f"  {'Tiempo suspendido promedio':<28} {datos['promedio_suspendido']} ticks",
            f"  {'Rendimiento (throughput)':<28} {datos['rendimiento']} procesos/tick",
            f"  {'Cambios de contexto':<28} {datos['cambios_contexto']}",
            "",
            "USO DE RECURSOS",
            "-" * 78,
            f"  {'CPU: trabajo util':<28} {datos['rendimiento_util_cpu']}%",
            f"  {'CPU: ticks de sobrecarga':<28} {datos['ticks_sobrecarga']}",
            f"  {'CPU: ticks ociosos':<28} {datos['ticks_ocioso_cpu']}",
            f"  {'Memoria en uso':<28} {datos['uso_memoria']}%",
            f"  {'Fragmentacion externa':<28} {datos['fragmentacion_externa']}%",
            f"  {'Asignaciones fallidas':<28} {datos['asignaciones_fallidas']}",
            f"  {'Operaciones de E/S atendidas':<28} {datos['operaciones_es']}",
            "",
            "INTERCAMBIO (SWAPPING)",
            "-" * 78,
            f"  {'Estado':<28} {configuracion['intercambio']}",
            f"  {'Politica':<28} {configuracion['politica_intercambio']}",
            f"  {'Area en uso':<28} {datos['uso_intercambio']}%",
            f"  {'Salidas a disco (swap-out)':<28} {datos['intercambios_salida']}",
            f"  {'Regresos a memoria (swap-in)':<28} {datos['intercambios_entrada']}",
            f"  {'Ticks gastados en traslados':<28} {datos['ticks_intercambio']}",
            f"  {'Suspendidos ahora mismo':<28} {datos['procesos_suspendidos']}",
            "",
            "DETALLE POR PROCESO",
            "-" * 78,
            f"  {'PID':>4} {'NOMBRE':<12} {'ESTADO':<20} {'ESPERA':>7} {'SUSPEND':>8} "
            f"{'RETORNO':>8} {'RESPUESTA':>10} {'CAMBIOS':>8} {'SWAPS':>6}",
        ]
        for proceso in sorted(procesos, key=lambda p: p.pid):
            swaps = proceso.intercambios_salida + proceso.intercambios_entrada
            lineas.append(
                f"  {proceso.pid:>4} {proceso.nombre[:12]:<12} {proceso.estado.etiqueta[:20]:<20} "
                f"{proceso.ticks_espera:>7} {proceso.ticks_suspendido:>8} "
                f"{proceso.tiempo_retorno if proceso.tiempo_retorno is not None else '-':>8} "
                f"{proceso.tiempo_respuesta if proceso.tiempo_respuesta is not None else '-':>10} "
                f"{proceso.cambios_contexto:>8} {swaps:>6}"
            )

        rechazados = [p for p in procesos if p.motivo_rechazo]
        if rechazados:
            lineas += ["", "PROCESOS RECHAZADOS", "-" * 78]
            lineas += [
                f"  {p.pid:>4} {p.nombre[:12]:<12} {p.motivo_rechazo}"
                for p in sorted(rechazados, key=lambda p: p.pid)
            ]

        lineas += ["", "EVENTOS REGISTRADOS", "-" * 78]
        lineas += [f"  {clave:<28} {total}" for clave, total in resumen_bitacora.items()]

        ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        return ruta
