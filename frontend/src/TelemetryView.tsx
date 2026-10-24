import { Detail } from './ui';
import { date } from './api';
import type { Telemetry } from './types';

export type SensorQuality = {
  movement_state?: 'unknown' | 'rest' | 'moving'; activity_method?: string;
  acceleration_g?: { x: number | null; y: number | null; z: number | null };
  battery_pct_est?: number | null; battery_present?: boolean | null;
  battery_charging?: boolean | null; usb_present?: boolean | null;
  gps_satellites?: number | null; gps_hdop?: number | null; gps_age_ms?: number | null;
  gps_diagnostics?: { bytes: number; valid_sentences: number; failed_checksums: number };
  observed_at_estimated?: boolean; period_ms?: number; uptime_ms?: number;
  tx_reason?: string; flags?: number; wire_protocol_version?: number;
  radio?: { rssi_dbm: number; snr_db: number }; receiver_label?: string;
  capture_received_at?: string; time_basis?: string;
};
export const quality = (s: Telemetry): SensorQuality => s.quality as SensorQuality;
export const number = (n: number | null | undefined, digits = 3) => n == null || !Number.isFinite(n) ? 'Sin lectura' : n.toLocaleString('es-CL', { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const movement = (s: Telemetry) => ({ rest: 'En reposo', moving: 'En movimiento', unknown: 'Sin clasificar' }[quality(s).movement_state ?? 'unknown']);
export const reason = (s: Telemetry) => ({ boot: 'Inicio del collar', periodic: 'Envío periódico', movement_start: 'Inicio de movimiento' }[quality(s).tx_reason ?? ''] ?? 'No informado');
export function battery(s: Telemetry) {
  const q = quality(s);
  if (q.battery_present === false) return 'Sin batería';
  return `${q.battery_pct_est == null ? '' : `~${q.battery_pct_est}% · `}${s.battery_mv == null ? 'Sin lectura' : `${number(s.battery_mv / 1000, 3)} V`}`;
}
const yes = (v: boolean | null | undefined) => v == null ? 'No informado' : v ? 'Sí' : 'No';
export function TelemetryDetails({ sample }: { sample: Telemetry }) {
  const q = quality(sample);
  const failures = q.flags == null ? 'No informados' : [q.flags & 1 ? 'GPS sin posición válida' : '', q.flags & 2 ? 'Temperatura ausente' : '', q.flags & 4 ? 'Acelerómetro ausente' : ''].filter(Boolean).join(' · ') || 'Sin ausencias informadas';
  return <div className="telemetry-details">
    <dl className="details-grid">
      <Detail label="Temperatura del sensor" value={`${number(sample.surface_temperature_c, 2)}${sample.surface_temperature_c == null ? '' : ' °C'}`} />
      <Detail label="Movimiento" value={movement(sample)} />
      <Detail label="Actividad RMS" value={`${number(sample.activity_index)} g`} />
      <Detail label="Aceleración X / Y / Z" value={`${number(q.acceleration_g?.x)} / ${number(q.acceleration_g?.y)} / ${number(q.acceleration_g?.z)} g`} />
      <Detail label="Batería estimada" value={battery(sample)} />
      <Detail label="Batería presente / cargando" value={`${yes(q.battery_present)} / ${yes(q.battery_charging)}`} />
      <Detail label="Alimentación USB" value={yes(q.usb_present)} />
      <Detail label="Posición GPS" value={sample.gnss_valid && sample.latitude != null && sample.longitude != null ? `${number(sample.latitude, 6)}, ${number(sample.longitude, 6)}` : 'Sin posición válida en este paquete'} />
      <Detail label="Satélites usados en solución" value={q.gps_satellites ?? 'No informado'} />
      <Detail label="HDOP" value={number(q.gps_hdop, 2)} />
      <Detail label="Edad de posición al transmitir" value={q.gps_age_ms == null ? 'No informada' : `${q.gps_age_ms} ms`} />
      <Detail label="Radio RSSI / SNR" value={q.radio ? `${q.radio.rssi_dbm} dBm / ${q.radio.snr_db} dB` : 'No informado'} />
      <Detail label="Motivo del envío" value={reason(sample)} />
      <Detail label="Intervalo anunciado" value={q.period_ms == null ? 'No informado' : `${number(q.period_ms / 1000, 1)} s`} />
      <Detail label="Tiempo encendido" value={q.uptime_ms == null ? 'No informado' : `${number(q.uptime_ms / 1000, 1)} s`} />
      <Detail label="NMEA: bytes / válidas / errores" value={q.gps_diagnostics ? `${q.gps_diagnostics.bytes} / ${q.gps_diagnostics.valid_sentences} / ${q.gps_diagnostics.failed_checksums}` : 'No transmitido'} />
      <Detail label="Estado de sensores" value={failures} />
      <Detail label="Receptor" value={q.receiver_label ?? 'No informado'} />
      <Detail label="Hora observada" value={`${date(sample.observed_at)}${q.observed_at_estimated ? ' · aproximada, reloj del PC' : ''}`} />
      <Detail label="Recepción USB / guardado servidor" value={`${date(q.capture_received_at)} / ${date(sample.received_at)}`} />
      <Detail label="Sesión / secuencia" value={`${sample.session_id} / ${sample.seq}`} />
      <Detail label="Protocolo / origen" value={`V${q.wire_protocol_version ?? '?'} · ${sample.source}`} />
    </dl>
    <p className="sensor-caption">El movimiento se clasifica con el acelerómetro. La temperatura del sensor no equivale a temperatura corporal. La batería es una estimación. Satélites visibles y C/N₀ no se incluyen en los paquetes actuales.</p>
    <details className="telemetry-json"><summary>Ver registro JSON almacenado completo</summary><pre>{JSON.stringify(sample, null, 2)}</pre></details>
  </div>;
}
