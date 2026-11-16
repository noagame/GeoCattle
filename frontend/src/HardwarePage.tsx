import { useState } from 'react';
import { Activity, Battery, Download, Radio, RefreshCw, Satellite, Thermometer } from 'lucide-react';
import { useData, date, age } from './api';
import { Badge, Empty, ErrorNotice, Loading, Modal, Panel, PanelTitle, PageTitle } from './ui';
import { CattleMap, type CollarLocation } from './Map';
import type { Telemetry } from './types';
import { battery, movement, number, quality, reason, TelemetryDetails } from './TelemetryView';

type Sample = Telemetry & { hardware_id: string; animal_name: string | null };
type Samples = { items: Sample[]; total: number; timezone: string; devices: { hardware_id: string; name: string }[] };
type Snapshot = { hardware_id: string; name: string; enabled: boolean; latest: Sample | null; last_position: Sample | null; age_seconds: number | null; position_age_seconds: number | null; freshness_seconds: number; communication_status: 'unknown' | 'recent' | 'stale' };
type Overview = { items: Snapshot[]; server_time: string };
type Daily = { items: { day: string; hardware_id: string; samples: number; positions: number; temperatures: number; moving_samples: number; rest_samples: number; temperature_min: number | null; temperature_max: number | null; first_at: string; last_at: string }[] };
type Receiver = { available: boolean; connected: boolean; port?: string; error?: string; captured?: number; pending?: number; delivered?: number; last_capture?: string; updated_at?: string; receiver_mode?: 'direct' | 'gateways'; bus_version?: number };

function today() {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Santiago', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  const part = (name: string) => parts.find(p => p.type === name)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
function Trend({ rows, field, title, unit, color }: { rows: Sample[]; field: (s: Sample) => number | null | undefined; title: string; unit: string; color: string }) {
  const points = [...rows].sort((a, b) => a.observed_at.localeCompare(b.observed_at));
  const values = points.map(field).filter((v): v is number => v != null && Number.isFinite(v));
  if (!values.length) return <div className="telemetry-trend"><h3>{title}</h3><p>Sin lecturas en esta página.</p></div>;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const start = new Date(points[0].observed_at).getTime(), end = new Date(points[points.length - 1].observed_at).getTime();
  const segments: { x: number; y: number; sample: Sample; value: number }[][] = []; let current: typeof segments[number] = [];
  points.forEach(s => {
    const v = field(s);
    // Missing values and long gaps interrupt the graph; they are not interpolated.
    const previous = current[current.length - 1]?.sample;
    const gap = previous && (s.session_id !== previous.session_id || new Date(s.observed_at).getTime() - new Date(previous.observed_at).getTime() > Math.max(120000, (quality(s).period_ms ?? 40000) * 3));
    if (gap && current.length) { segments.push(current); current = []; }
    if (v == null || !Number.isFinite(v)) { if (current.length) segments.push(current); current = []; return; }
    current.push({ x: 35 + (new Date(s.observed_at).getTime() - start) / (end - start || 1) * 530, y: 120 - (v - min) / span * 92, sample: s, value: v });
  });
  if (current.length) segments.push(current);
  return <div className="telemetry-trend"><div><h3>{title}</h3><span>{number(min, 2)}–{number(max, 2)} {unit}</span></div>
    <svg viewBox="0 0 600 160" role="img" aria-label={`${title}: ${values.length} lecturas, mínimo ${min}, máximo ${max} ${unit}`}>
      <line x1="35" x2="565" y1="120" y2="120" stroke="#dce5da" />
      {segments.map((segment, i) => <g key={i}><polyline fill="none" stroke={color} strokeWidth="2" points={segment.map(p => `${p.x},${p.y}`).join(' ')} />{segment.map(p => <circle key={p.sample.id} cx={p.x} cy={p.y} r="3" fill={color}><title>{date(p.sample.observed_at)} · {number(p.value)} {unit}</title></circle>)}</g>)}
      <text x="35" y="150">{date(points[0].observed_at)}</text><text x="565" y="150" textAnchor="end">{date(points[points.length - 1].observed_at)}</text>
    </svg>
  </div>;
}
function exportPage(rows: Sample[], day: string) {
  const url = URL.createObjectURL(new Blob([rows.map(s => JSON.stringify(s)).join('\n') + '\n'], { type: 'application/x-ndjson' }));
  const link = document.createElement('a'); link.href = url; link.download = `geocattle-${day}-pagina.jsonl`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function HardwarePage({ farmId }: { farmId: string }) {
  const [day, setDay] = useState(today); const [collar, setCollar] = useState('');
  const [offset, setOffset] = useState(0); const [selected, setSelected] = useState<Sample | null>(null);
  const samples = useData<Samples>(`/hardware/telemetry?day=${day}&hardware_id=${encodeURIComponent(collar)}&offset=${offset}`, 5000, farmId);
  const daily = useData<Daily>(`/hardware/daily?hardware_id=${encodeURIComponent(collar)}&days=30`, 15000, farmId);
  const overview = useData<Overview>('/hardware/overview', 5000, farmId);
  const receiver = useData<Receiver>('/hardware/receiver', 5000, farmId);
  const receiverMode = receiver.data?.receiver_mode === 'gateways' ? 'Por gateways' : receiver.data?.receiver_mode === 'direct' ? 'Directo' : 'Sin informar';
  const rows = samples.data?.items ?? [];
  const devices = overview.data?.items.filter(d => !collar || d.hardware_id === collar) ?? [];
  const positions: CollarLocation[] = devices.flatMap(d => {
    const p = d.last_position;
    return p && p.gnss_valid && p.latitude != null && p.longitude != null ? [{ hardware_id: d.hardware_id, latitude: p.latitude, longitude: p.longitude, observed_at: p.observed_at, stale: (d.position_age_seconds ?? Infinity) > d.freshness_seconds }] : [];
  });
  const history = collar ? [...rows].reverse() : [];
  function refresh() { samples.reload(); daily.reload(); overview.reload(); receiver.reload(); }
  function choose(id: string) { setCollar(id); setOffset(0); }
  return <>
    <PageTitle eyebrow="TELEMETRÍA DEL PROTOTIPO" title="Recepción de collares" description="Sensores, posición y batería recibidos por LoRa y guardados en GeoCattle. Actualización cada cinco segundos." actions={<button className="button secondary" onClick={refresh}><RefreshCw size={16} />Actualizar</button>} />
    <Panel><PanelTitle title="Receptor USB" subtitle={receiver.data?.available ? `${receiver.data.port ?? 'USB'} · ${receiver.data.connected ? 'Puerto abierto' : 'Desconectado'}` : 'Sin estado reciente del receptor'} action={<Badge status={receiver.data?.available && receiver.data.connected ? 'normal' : 'unknown'}>{receiver.data?.available && receiver.data.connected ? 'Captura activa' : 'Captura sin confirmar'}</Badge>} />
      <ErrorNotice error={receiver.error} retry={receiver.reload} />
      <div className="hardware-receiver"><span>Método seleccionado <strong>{receiver.data?.available ? receiverMode : 'Sin confirmar'}</strong></span>{receiver.data?.available && receiver.data.receiver_mode === 'gateways' && receiver.data.bus_version === 1 && <span>Lotes USB <strong>V1</strong></span>}<span><Radio size={18} />Capturadas <strong>{receiver.data?.captured ?? '—'}</strong></span><span>Guardadas <strong>{receiver.data?.delivered ?? '—'}</strong></span><span>Pendientes <strong>{receiver.data?.pending ?? '—'}</strong></span><span>Última captura <strong>{date(receiver.data?.last_capture)}</strong></span></div>
      {receiver.data?.error && <p className="sensor-caption" role="status">{receiver.data.error}</p>}
      {!receiver.data?.available && <p className="sensor-caption">El último estado del puente está vencido. Los registros de abajo siguen disponibles, pero no confirman recepción actual.</p>}
    </Panel>
    <div className="hardware-filter"><label>Collar<select value={collar} onChange={e => choose(e.target.value)}><option value="">Todos los collares</option>{(overview.data?.items ?? samples.data?.devices ?? []).map(d => <option key={d.hardware_id} value={d.hardware_id}>{d.hardware_id} · {d.name}</option>)}</select></label><label>Fecha del historial (Chile)<input type="date" value={day} onChange={e => { setDay(e.target.value || today()); setOffset(0); }} /></label><span>El resumen muestra la última lectura de cada collar; el historial usa la fecha seleccionada.</span></div>
    <ErrorNotice error={overview.error} retry={overview.reload} />
    {!overview.data && !overview.error && <Loading label="Leyendo collares…" />}
    <div className="hardware-collars">{devices.map(d => {
      const s = d.latest, q = s ? quality(s) : null;
      return <Panel key={d.hardware_id}><PanelTitle title={d.hardware_id} subtitle={`${d.name}${!d.enabled ? ' · deshabilitado' : ''}`} action={<Badge status={d.communication_status === 'recent' ? 'normal' : 'unknown'}>{d.communication_status === 'recent' ? 'Datos recientes' : d.latest ? 'Datos antiguos' : 'Sin lecturas'}</Badge>} />
        {s ? <><div className="hardware-collar-meta"><span>{s.animal_name ?? 'Sin bovino asociado'}</span><span>{date(s.observed_at)} · {age(d.age_seconds)}</span></div>
          <div className="hardware-metrics">
            <div><Thermometer size={19} /><span>Temperatura<strong>{number(s.surface_temperature_c, 2)}{s.surface_temperature_c == null ? '' : ' °C'}</strong></span></div>
            <div><Activity size={19} /><span>Movimiento<strong>{movement(s)}</strong><small>RMS {number(s.activity_index)} g</small></span></div>
            <div><Battery size={19} /><span>Batería<strong>{battery(s)}</strong><small>{q?.usb_present === true ? 'USB conectado' : q?.usb_present === false ? 'USB desconectado' : 'USB sin informar'}{q?.battery_charging === true ? ' · cargando' : ''}</small></span></div>
            <div><Satellite size={19} /><span>GPS<strong>{s.gnss_valid ? 'Posición válida' : 'Sin posición válida'}</strong><small>{q?.gps_satellites ?? '—'} satélites usados · HDOP {number(q?.gps_hdop, 2)}</small></span></div>
          </div>
          <div className="hardware-collar-meta"><span>#{s.seq} · {reason(s)}</span><button className="text-button" onClick={() => setSelected(s)}>Ver todos los datos →</button></div>
        </> : <Empty title="Esperando primera lectura" />}
      </Panel>;
    })}</div>
    <Panel><PanelTitle title="Ubicación de los collares" subtitle="Última posición válida de cada collar, incluso sin asignación a bovino. Gris: posición histórica. No se inventan coordenadas cuando el GPS no tiene fix." />
      <CattleMap collars={positions} history={history} height="small" />
      <p className="sensor-caption">{positions.length} collares con posición registrada. {collar ? 'La trayectoria corresponde solo a las lecturas de la página del historial seleccionada.' : 'Selecciona un collar para ver su trayectoria sin unir recorridos de animales distintos.'} La última posición puede ser anterior al último paquete.</p>
    </Panel>
    <Panel><PanelTitle title="Historial de telemetría" subtitle="Hora aproximada de observación según recepción del PC. Se conservan los valores ausentes y los paquetes de cada sesión." action={<button className="button secondary small" disabled={!rows.length} onClick={() => exportPage(rows, day)}><Download size={15} />Exportar página JSONL</button>} />
      <ErrorNotice error={samples.error} retry={samples.reload} />
      {!samples.data && !samples.error && <Loading />}
      {samples.data?.total === 0 && <Empty title="Sin lecturas para esta fecha" description="Cambia la fecha o el collar. El resumen superior conserva la última lectura disponible." />}
      {!!rows.length && <>
        {collar ? <div className="hardware-trends"><Trend rows={rows} field={s => s.surface_temperature_c} title="Temperatura" unit="°C" color="#b87827" /><Trend rows={rows} field={s => s.activity_index} title="Actividad RMS" unit="g" color="#276e68" /><Trend rows={rows} field={s => quality(s).battery_pct_est} title="Batería estimada" unit="%" color="#558446" /></div> : <p className="sensor-caption">Selecciona un collar para comparar sus sensores en gráficas.</p>}
        {collar && <p className="sensor-caption">Gráficas de esta página ({rows.length} lecturas). Las ausencias, reinicios y pausas largas interrumpen el trazado.</p>}
        <div className="table-scroll"><table className="hardware-table"><thead><tr><th>Hora / collar</th><th>Temperatura</th><th>Movimiento / RMS</th><th>Batería / alimentación</th><th>GPS</th><th>Radio</th><th>Envío</th><th>Detalle</th></tr></thead><tbody>{rows.map(s => {
          const q = quality(s);
          return <tr key={s.id}><td>{date(s.observed_at)}<small>{s.hardware_id} · #{s.seq}{q.observed_at_estimated ? ' · hora PC' : ''}</small></td>
            <td>{number(s.surface_temperature_c, 2)}{s.surface_temperature_c == null ? '' : ' °C'}</td><td>{movement(s)}<small>{number(s.activity_index)} g</small></td>
            <td>{battery(s)}<small>{q.usb_present == null ? 'USB no informado' : q.usb_present ? 'USB' : 'Sin USB'}{q.battery_charging ? ' · cargando' : ''}</small></td>
            <td>{s.gnss_valid ? `${number(s.latitude, 6)}, ${number(s.longitude, 6)}` : 'Sin fix'}<small>Sat. usados: {q.gps_satellites ?? '—'} · HDOP {number(q.gps_hdop, 2)}</small></td>
            <td>{q.radio ? `${q.radio.rssi_dbm} dBm` : 'Sin lectura'}<small>{q.radio ? `SNR ${q.radio.snr_db} dB` : ''}</small></td>
            <td>{reason(s)}<small>{q.period_ms == null ? 'Intervalo no informado' : `${number(q.period_ms / 1000, 1)} s`}</small></td><td><button className="text-button" onClick={() => setSelected(s)} aria-label={`Ver paquete ${s.hardware_id} ${s.seq}`}>Ver datos</button></td></tr>;
        })}</tbody></table></div>
        <div className="hardware-pagination"><button className="button secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>Anterior</button><span>{offset + 1}–{Math.min(offset + rows.length, samples.data?.total ?? 0)} de {samples.data?.total}</span><button className="button secondary" disabled={offset + 100 >= (samples.data?.total ?? 0)} onClick={() => setOffset(offset + 100)}>Siguiente</button></div>
      </>}
    </Panel>
    <Panel><PanelTitle title="Registro diario por collar" subtitle="Últimos 30 días. Reposo y movimiento son cantidades de muestras; no representan horas de actividad." />
      <ErrorNotice error={daily.error} retry={daily.reload} />
      <div className="table-scroll"><table><thead><tr><th>Día / collar</th><th>Lecturas</th><th>Con posición</th><th>Temp. mín. / máx.</th><th>Reposo / movimiento</th><th>Primera / última</th></tr></thead><tbody>{daily.data?.items.map(d => <tr key={`${d.day}-${d.hardware_id}`}><td><button className="text-button" onClick={() => { setDay(d.day); choose(d.hardware_id); }}>{d.day} · {d.hardware_id}</button></td><td>{d.samples}</td><td>{d.positions}</td><td>{number(d.temperature_min, 2)} / {number(d.temperature_max, 2)} °C<small>{d.temperatures} lecturas</small></td><td>{d.rest_samples} / {d.moving_samples}<small>{d.samples - d.rest_samples - d.moving_samples} sin clasificar</small></td><td>{date(d.first_at)}<small>{date(d.last_at)}</small></td></tr>)}</tbody></table></div>
    </Panel>
    {selected && <Modal title={`${selected.hardware_id} · paquete #${selected.seq}`} wide onClose={() => setSelected(null)}><TelemetryDetails sample={selected} /></Modal>}
  </>;
}
