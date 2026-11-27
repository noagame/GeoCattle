import { useEffect, useState } from 'react';
import { Activity, Battery, Radio, RefreshCw, Satellite, Thermometer } from 'lucide-react';
import { useData, date, age, query } from './api';
import { Badge, dateInputValue, Empty, ErrorNotice, Loading, Modal, Panel, PanelTitle, PageTitle, ScrollRegion, SectionTabs } from './ui';
import { CattleMap, type CollarLocation } from './Map';
import type { Telemetry } from './types';
import { battery, movement, number, quality, reason, TelemetryDetails } from './TelemetryView';
import { ReportDownloads } from './ReportDownloads';

type Sample = Telemetry & { hardware_id: string; animal_name: string | null };
type Samples = { items: Sample[]; total: number; timezone: string; devices: { hardware_id: string; name: string }[] };
type Snapshot = { hardware_id: string; name: string; enabled: boolean; latest: Sample | null; last_position: Sample | null; age_seconds: number | null; position_age_seconds: number | null; freshness_seconds: number; communication_status: 'unknown' | 'recent' | 'stale' };
type Overview = { items: Snapshot[]; server_time: string };
type Daily = { items: { day: string; hardware_id: string; samples: number; positions: number; temperatures: number; moving_samples: number; rest_samples: number; temperature_min: number | null; temperature_max: number | null; first_at: string; last_at: string }[] };
type Receiver = {
  available: boolean; connected: boolean; port?: string; error?: string; captured?: number; pending?: number;
  delivered?: number; last_capture?: string; updated_at?: string; receiver_mode?: 'direct' | 'gateways'; bus_version?: number;
  wifi_ssid?: string; wifi_rssi_dbm?: number; firmware?: string; buffer_capacity?: number; dropped?: number;
};

function today() {
  return dateInputValue(new Date(), 'America/Santiago');
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
  const [section, setSection] = useState<'summary' | 'history' | 'daily'>('summary');
  const [offset, setOffset] = useState(0); const [selected, setSelected] = useState<Sample | null>(null);
  const samples = useData<Samples>(`/hardware/telemetry?day=${day}&hardware_id=${encodeURIComponent(collar)}&offset=${offset}`, 5000, farmId);
  const daily = useData<Daily>(`/hardware/daily?hardware_id=${encodeURIComponent(collar)}&days=30`, 15000, farmId);
  const overview = useData<Overview>('/hardware/overview', 5000, farmId);
  const receiver = useData<Receiver>('/hardware/receiver', 5000, farmId);
  const cloudReceiver = Boolean(receiver.data?.firmware);
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
  // Al abrir (por ejemplo tras reiniciar el PC) hoy puede no tener lecturas: se muestra el último día con datos.
  const [dayChosen, setDayChosen] = useState(false);
  const latestDay = daily.data?.items[0]?.day;
  useEffect(() => {
    if (!dayChosen && samples.data?.total === 0 && latestDay && latestDay !== day) { setDay(latestDay); setOffset(0); setDayChosen(true); }
  }, [dayChosen, samples.data?.total, latestDay, day]);
  function selectDay(value: string) {
    setDay(value);
    setOffset(0);
    setDayChosen(true);
  }
  return <>
    <PageTitle title="Recepción de collares" description="Sensores, posición y batería recibidos por LoRa. Actualización cada cinco segundos." actions={<button className="button secondary" onClick={refresh}><RefreshCw size={16} />Actualizar</button>} />
    <Panel><div className="form-body hardware-filter" role="group" aria-label="Filtros de recepción">
      <label>Collar<select value={collar} onChange={e => choose(e.target.value)}><option value="">Todos los collares</option>{(overview.data?.items ?? samples.data?.devices ?? []).map(d => <option key={d.hardware_id} value={d.hardware_id}>{d.hardware_id} · {d.name}</option>)}</select></label>
      <label>Fecha de consulta (Chile)<input type="date" value={day} onChange={e => selectDay(e.target.value || today())} /></label>
    </div></Panel>
    <SectionTabs label="Secciones de recepción" active={section} onChange={setSection} sections={[
    { id: 'summary', label: 'Recepción actual', content: <>
    <Panel><PanelTitle title={cloudReceiver ? 'Receptora T3' : 'Receptor USB'}
      subtitle={receiver.data?.available ? (cloudReceiver ? (receiver.data.connected ? 'WiFi conectado' : 'WiFi desconectado')
        : `${receiver.data.port ?? 'USB'} · ${receiver.data.connected ? 'Puerto abierto' : 'Desconectado'}`) : 'Sin estado reciente del receptor'}
      action={<Badge status={receiver.data?.available && receiver.data.connected ? 'normal' : 'unknown'}>{receiver.data?.available && receiver.data.connected ? 'Captura activa' : 'Captura sin confirmar'}</Badge>} />
      <ErrorNotice error={receiver.error} retry={receiver.reload} />
      {!receiver.data && !receiver.error && <Loading label="Consultando el receptor…" />}
      {cloudReceiver && <div className="hardware-receiver">
        <span>Red WiFi <strong>{receiver.data?.wifi_ssid ?? '—'}{receiver.data?.wifi_rssi_dbm != null ? ` · ${receiver.data.wifi_rssi_dbm} dBm` : ''}</strong></span>
        <span>Búfer <strong>{receiver.data?.pending ?? 0} / {receiver.data?.buffer_capacity ?? 0}</strong></span>
        <span>Descartadas desde el arranque <strong>{receiver.data?.dropped ?? 0}</strong></span>
        <span>Firmware <strong>{receiver.data?.firmware}</strong></span>
      </div>}
      {receiver.data && <div className="hardware-receiver"><span>Método seleccionado <strong>{receiver.data.available ? receiverMode : 'Sin confirmar'}</strong></span>{receiver.data.available && receiver.data.receiver_mode === 'gateways' && receiver.data.bus_version === 1 && <span>Lotes USB <strong>V1</strong></span>}<span><Radio size={18} />Capturadas <strong>{receiver.data.captured ?? '—'}</strong></span><span>Guardadas <strong>{receiver.data.delivered ?? '—'}</strong></span><span>Pendientes <strong>{receiver.data.pending ?? '—'}</strong></span><span>Última captura <strong>{date(receiver.data.last_capture)}</strong></span></div>}
      {receiver.data?.error && <p className="sensor-caption" role="status">{receiver.data.error}</p>}
      {receiver.data && !receiver.data.available && <p className="sensor-caption">El último estado del puente está vencido. Los registros del Historial siguen disponibles, pero no confirman recepción actual.</p>}
    </Panel>
    <ErrorNotice error={overview.error} retry={overview.reload} />
    {!overview.data && !overview.error && <Loading label="Leyendo collares…" />}
    {overview.data && !devices.length && <Panel><Empty title="Sin collares para mostrar" compact /></Panel>}
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
    {section === 'summary' && <Panel><PanelTitle title="Ubicación de los collares" subtitle="Última posición válida de cada collar, incluso sin asignación a bovino. Gris: posición histórica. No se inventan coordenadas cuando el GPS no tiene fix." />
      <CattleMap collars={positions} history={history} height="small" />
      <p className="sensor-caption">{positions.length} collares con posición registrada. {collar ? 'La trayectoria corresponde solo a las lecturas de la página del historial seleccionada.' : 'Selecciona un collar para ver su trayectoria sin unir recorridos de animales distintos.'} La última posición puede ser anterior al último paquete.</p>
    </Panel>}
    </> },
    { id: 'history', label: 'Historial', content: <Panel><PanelTitle title="Historial de telemetría" subtitle="Hora aproximada de observación según recepción del PC. Excel y CSV exportan el día y collar seleccionados (hasta 50.000 lecturas)." action={
      <ReportDownloads key={JSON.stringify([farmId, day, collar])} disabled={!!samples.error || !samples.data?.total}
        path={format => `/reports/telemetry.${format}${query({ day, hardware_id: collar })}`}>
        <button type="button" className="button secondary small" disabled={!rows.length} onClick={() => exportPage(rows, day)}>JSONL de esta página</button>
      </ReportDownloads>} />
      <ErrorNotice error={samples.error} retry={samples.reload} />
      {!samples.data && !samples.error && <Loading />}
      {samples.data?.total === 0 && <Empty title="Sin lecturas para esta fecha" description={latestDay && latestDay !== day ? `El último día con datos es ${latestDay}. Consulta la pestaña Registro diario o usa Exportación para descargar todo el período.` : 'Cambia la fecha o el collar. Las lecturas anteriores se descargan desde Exportación.'} />}
      {!!rows.length && <>
        {collar ? <div className="hardware-trends"><Trend rows={rows} field={s => s.surface_temperature_c} title="Temperatura" unit="°C" color="#b87827" /><Trend rows={rows} field={s => s.activity_index} title="Actividad RMS" unit="g" color="#276e68" /><Trend rows={rows} field={s => quality(s).battery_pct_est} title="Batería estimada" unit="%" color="#558446" /></div> : <p className="sensor-caption">Selecciona un collar para comparar sus sensores en gráficas.</p>}
        {collar && <p className="sensor-caption">Gráficas de esta página ({rows.length} lecturas). Las ausencias, reinicios y pausas largas interrumpen el trazado.</p>}
        <ScrollRegion label="Lecturas del historial"><table className="hardware-table"><thead><tr><th>Hora / collar</th><th>Temperatura</th><th>Movimiento / RMS</th><th>Batería / alimentación</th><th>GPS</th><th>Radio</th><th>Envío</th><th>Detalle</th></tr></thead><tbody>{rows.map(s => {
          const q = quality(s);
          return <tr key={s.id}><td>{date(s.observed_at)}<small>{s.hardware_id} · #{s.seq}{q.observed_at_estimated ? ' · hora PC' : ''}</small></td>
            <td>{number(s.surface_temperature_c, 2)}{s.surface_temperature_c == null ? '' : ' °C'}</td><td>{movement(s)}<small>{number(s.activity_index)} g</small></td>
            <td>{battery(s)}<small>{q.usb_present == null ? 'USB no informado' : q.usb_present ? 'USB' : 'Sin USB'}{q.battery_charging ? ' · cargando' : ''}</small></td>
            <td>{s.gnss_valid ? `${number(s.latitude, 6)}, ${number(s.longitude, 6)}` : 'Sin fix'}<small>Sat. usados: {q.gps_satellites ?? '—'} · HDOP {number(q.gps_hdop, 2)}</small></td>
            <td>{q.radio ? `${q.radio.rssi_dbm} dBm` : 'Sin lectura'}<small>{q.radio ? `SNR ${q.radio.snr_db} dB` : ''}</small></td>
            <td>{reason(s)}<small>{q.period_ms == null ? 'Intervalo no informado' : `${number(q.period_ms / 1000, 1)} s`}</small></td><td><button className="text-button" onClick={() => setSelected(s)} aria-label={`Ver paquete ${s.hardware_id} ${s.seq}`}>Ver datos</button></td></tr>;
        })}</tbody></table></ScrollRegion>
        <div className="hardware-pagination"><button className="button secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>Anterior</button><span>{offset + 1}–{Math.min(offset + rows.length, samples.data?.total ?? 0)} de {samples.data?.total}</span><button className="button secondary" disabled={offset + 100 >= (samples.data?.total ?? 0)} onClick={() => setOffset(offset + 100)}>Siguiente</button></div>
      </>}
    </Panel> },
    { id: 'daily', label: 'Registro diario', content: <Panel>
      <PanelTitle title="Registro diario por collar" subtitle="Últimos 30 días para el filtro de collar. La fecha de consulta se resalta si tiene datos. Reposo y movimiento son cantidades de muestras; no representan horas de actividad." />
      <ErrorNotice error={daily.error} retry={daily.reload} />
      {!daily.data && !daily.error && <Loading label="Consultando el registro diario…" />}
      {daily.data && !daily.data.items.length && <Empty title="Sin lecturas en los últimos 30 días" />}
      {!!daily.data?.items.length && <ScrollRegion label="Registro diario por collar"><table><thead><tr><th>Día / collar</th><th>Lecturas</th><th>Con posición</th><th>Temp. mín. / máx.</th><th>Reposo / movimiento</th><th>Primera / última</th></tr></thead><tbody>{daily.data.items.map(d => <tr key={`${d.day}-${d.hardware_id}`} className={d.day === day ? 'hardware-selected-day' : undefined}><td><button className="text-button" type="button" aria-label={`Ver lecturas del ${d.day}, collar ${d.hardware_id}`} onClick={() => { selectDay(d.day); choose(d.hardware_id); setSection('history'); }}>{d.day} · {d.hardware_id}</button></td><td>{d.samples}</td><td>{d.positions}</td><td>{number(d.temperature_min, 2)} / {number(d.temperature_max, 2)} °C<small>{d.temperatures} lecturas</small></td><td>{d.rest_samples} / {d.moving_samples}<small>{d.samples - d.rest_samples - d.moving_samples} sin clasificar</small></td><td>{date(d.first_at)}<small>{date(d.last_at)}</small></td></tr>)}</tbody></table></ScrollRegion>}
    </Panel> },
    ]} />
    {selected && <Modal title={`${selected.hardware_id} · paquete #${selected.seq}`} wide onClose={() => setSelected(null)}><TelemetryDetails sample={selected} /></Modal>}
  </>;
}
