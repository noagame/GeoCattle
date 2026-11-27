"""Evalúa los KPI del informe que el sistema calcula con sus propios registros.

K04, K07, K10, K11 y K12 requieren ensayos o registros manuales y no se exportan.
"""
from dataclasses import dataclass
from typing import Literal


Status = Literal['Sí', 'No', 'Sin datos']


@dataclass(frozen=True)
class Evidence:
    packets: int = 0
    expected_packets: int = 0
    position_samples: int = 0
    fresh_positions: int = 0
    event_samples: int = 0
    processing_p50: float | None = None
    processing_p95: float | None = None
    unique_packets: int = 0
    extra_gateway_receptions: int = 0
    requests: int = 0
    errors: int = 0
    request_p95_ms: float | None = None
    battery_devices: int = 0
    battery_delta_mv: float | None = None
    exits: int = 0
    animal_hours: float = 0


@dataclass(frozen=True)
class Metric:
    code: str
    name: str
    value: float | None
    unit: str
    target: str
    status: Status
    numerator: int | float | None
    denominator: int | float | None
    window: str
    method: str
    observation: str
    secondary_value: float | None = None
    secondary_label: str | None = None


def ratio(numerator, denominator):
    return 100 * numerator / denominator if denominator else None


def display(number):
    return round(float(number), 4) if number is not None else None


def calculate_metrics(evidence: Evidence, window: str) -> list[Metric]:
    def metric(code, name, unit, target, method, observation, *, value=None, passed=None,
               numerator=None, denominator=None, secondary=None, secondary_label=None):
        return Metric(code, name, display(value), unit, target,
                      'Sin datos' if passed is None else 'Sí' if passed else 'No',
                      numerator, denominator, window, method, observation, display(secondary), secondary_label)

    delivery = ratio(evidence.unique_packets, evidence.expected_packets)
    fresh = ratio(evidence.fresh_positions, evidence.position_samples)
    persisted_unique = ratio(evidence.unique_packets, evidence.packets)
    errors = ratio(evidence.errors, evidence.requests)
    request_p95 = evidence.request_p95_ms / 1_000 if evidence.request_p95_ms is not None else None
    exit_rate = ratio(evidence.exits, evidence.animal_hours)
    return [
        metric('K01', 'Entrega útil', '%', '≥95 %',
               'Telemetría: únicos / ∑(secuencia máxima − mínima + 1) por collar y sesión.',
               'Estimación: no detecta pérdidas fuera de los extremos ni sesiones sin recepción.',
               value=delivery, passed=delivery >= 95 if delivery is not None else None,
               numerator=evidence.unique_packets, denominator=evidence.expected_packets),
        metric('K02', 'Posición vigente', '%', '≥95 % con edad ≤2T + 30 s',
               'Lecturas asignadas a bovinos: GNSS válido y 0 ≤ recepción − observación ≤ 2T + 30 s / total.',
               'Aproximación por lectura (no por animal-minuto); T usa period_ms, la versión de configuración aplicada o el intervalo actual.',
               value=fresh, passed=fresh >= 95 if fresh is not None else None,
               numerator=evidence.fresh_positions, denominator=evidence.position_samples),
        metric('K03', 'Procesamiento', 's', 'p95 ≤2 s',
               'Eventos enlazados a su lectura desencadenante: percentiles de apertura − recepción.',
               'Excluye aperturas sin lectura desencadenante y diferencias negativas; no mide el envío del aviso.',
               value=evidence.processing_p95, passed=evidence.processing_p95 <= 2 if evidence.processing_p95 is not None else None,
               denominator=evidence.event_samples, secondary=evidence.processing_p50, secondary_label='p50 (s)'),
        metric('K05', 'Integridad', '%', '100 % de lecturas recuperadas, sin duplicados',
               'Únicos por collar, sesión y secuencia / lecturas persistidas.',
               f'No certifica recuperación ni contabiliza reintentos descartados. Recepciones adicionales '
               f'del mismo paquete en otros gateways: {evidence.extra_gateway_receptions}.',
               value=persisted_unique, passed=False if evidence.packets > evidence.unique_packets else None,
               numerator=evidence.unique_packets, denominator=evidence.packets,
               secondary=evidence.packets - evidence.unique_packets, secondary_label='Duplicados persistidos'),
        metric('K06', 'Consulta', 's', 'p95 ≤1 s y errores <1 %',
               'request_metrics: p95 de GET de estado y porcentaje con HTTP ≥400.',
               'Solo solicitudes registradas con predio; no incluye fallos sin respuesta registrada.',
               value=request_p95, passed=request_p95 <= 1 and errors < 1 if request_p95 is not None and errors is not None else None,
               numerator=evidence.errors, denominator=evidence.requests, secondary=errors, secondary_label='Errores (%)'),
        metric('K08', 'Autonomía comercial', 'mV', '≥7 días con T = 300 s',
               'Promedio por collar del último voltaje menos el primero (dos o más lecturas).',
               'Solo variación de batería; no mide días ni controla recargas o reemplazos.',
               value=evidence.battery_delta_mv, denominator=evidence.battery_devices),
        metric('K09', 'Falsos avisos', 'salidas / 100 h-animal', '≤1 falso aviso / 100 h-animal',
               'Todas las alertas de salida / horas de asignación bovino–collar en el predio × 100.',
               'Sin referencia de campo no se clasifican falsos avisos. El valor incluye todas las salidas observadas por el sistema.',
               value=exit_rate, numerator=evidence.exits, denominator=display(evidence.animal_hours)),
    ]
