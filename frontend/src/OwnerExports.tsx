import { useState, type FormEvent } from 'react';
import { Download } from 'lucide-react';
import { downloadFile, message, ownerExportPath, useData, type OwnerExportPeriod } from './api';
import { ReportDownloads } from './ReportDownloads';
import { dateInputValue, Empty, ErrorNotice, Loading, PageTitle, Panel, PanelTitle, ScrollRegion, SectionTabs } from './ui';
import type { OwnerDevicesExport, OwnerMetric, OwnerMetricsExport, OwnerTelemetryExport } from './v3types';

const number = new Intl.NumberFormat('es-CL', { maximumFractionDigits: 4 });
const statusLabel = { 'Sí': 'Cumple', 'No': 'No cumple', 'Sin datos': 'Sin datos' };
const statusClass = { 'Sí': 'pass', 'No': 'fail', 'Sin datos': 'unknown' };
const telemetryDate = new Intl.DateTimeFormat('es-CL', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Santiago' });

function MetricCard({ metric }: { metric: OwnerMetric }) {
  return <li className="owner-metric">
    <div className="owner-metric-heading">
      <h3>{metric.name}</h3>
      <span className={`owner-metric-state ${statusClass[metric.status]}`}>{statusLabel[metric.status]}</span>
    </div>
    <p className={`owner-metric-value${metric.value == null ? ' is-unmeasured' : ''}`}>
      {metric.value == null ? 'Sin medición' : <>{number.format(metric.value)} <span>{metric.unit}</span></>}
    </p>
    <p className="owner-metric-target"><strong>Meta:</strong> {metric.target}</p>
    <details><summary>Método y muestra</summary>
      <p><strong>{metric.code}</strong> · {metric.observation}</p>
      {metric.secondary_value != null && <p>{metric.secondary_label}: {number.format(metric.secondary_value)}</p>}
      <p>{metric.method}</p>
      {metric.numerator != null && <p>Numerador: {number.format(metric.numerator)}</p>}
      {metric.denominator != null && <p>Denominador o tamaño de muestra: {number.format(metric.denominator)}</p>}
    </details>
  </li>;
}

function DevicePreview({ data }: { data: OwnerDevicesExport }) {
  const { summary, collars, gateways } = data;
  if (!summary.collars && !summary.gateways) return <Empty title="Sin dispositivos registrados"
    description="El predio todavía no tiene collares ni gateways en el inventario." />;
  return <div className="owner-export-inventory">
    <p><strong>{number.format(summary.collars)} collares · {number.format(summary.gateways)} gateways</strong><br />
      Bajas: {number.format(summary.withdrawn_collars)} collares y {number.format(summary.withdrawn_gateways)} gateways.</p>
    <p>Vista previa: hasta cinco registros de cada tipo. Las descargas incluyen también los equipos retirados o archivados.</p>
    {collars.length > 0 && <div className="owner-export-table" tabIndex={0} role="region" aria-label="Vista previa de collares">
      <table>
        <caption>Collares</caption>
        <thead><tr><th scope="col">Collar</th><th scope="col">Estado</th><th scope="col">Bovino vigente</th><th scope="col">Lecturas</th></tr></thead>
        <tbody>{collars.map(collar => <tr key={collar.id}>
          <th scope="row">{collar.name}<small>{collar.hardware_id}</small></th><td>{collar.status}</td>
          <td>{collar.diio ? `${collar.diio} · ${collar.animal_name}` : 'Sin asignación'}</td>
          <td>{number.format(collar.period_readings)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {gateways.length > 0 && <div className="owner-export-table" tabIndex={0} role="region" aria-label="Vista previa de gateways">
      <table>
        <caption>Gateways</caption>
        <thead><tr><th scope="col">Gateway</th><th scope="col">Estado</th><th scope="col">Nodo</th><th scope="col">Recepciones</th></tr></thead>
        <tbody>{gateways.map(gateway => <tr key={gateway.id}>
          <th scope="row">{gateway.name}{gateway.gateway_eui && <small>{gateway.gateway_eui}</small>}</th>
          <td>{gateway.status}</td><td>{gateway.node_id ?? 'Sin nodo'}</td><td>{number.format(gateway.period_receptions)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
  </div>;
}

function TelemetryPreview({ data }: { data: OwnerTelemetryExport }) {
  const { summary, daily } = data;
  if (!summary.readings) return <Empty title="Sin lecturas en este período"
    description="Cambia el período. Las lecturas se conservan en la base aunque el PC se apague." />;
  return <div className="owner-export-inventory">
    <dl className="telemetry-summary">
      <div><dt>Lecturas</dt><dd>{number.format(summary.readings)}</dd></div>
      <div><dt>Collares</dt><dd>{number.format(summary.collars)}</dd></div>
      <div><dt>Días con datos</dt><dd>{number.format(summary.days)}</dd></div>
    </dl>
    <p className="telemetry-date-range">Desde {summary.first_at ? telemetryDate.format(new Date(summary.first_at)) : '—'} hasta {summary.last_at ? telemetryDate.format(new Date(summary.last_at)) : '—'} · Hora de Chile</p>
    <ScrollRegion className="owner-export-table telemetry-daily-table" label="Vista previa del registro diario">
      <table>
        <caption>Registro diario por collar <small>{daily.length} {daily.length === 1 ? 'fila' : 'filas'} en la vista previa · máximo 60</small></caption>
        <thead><tr><th scope="col">Día / collar</th><th scope="col">Lecturas</th><th scope="col">Con posición</th><th scope="col">Temp. mín. / máx.</th><th scope="col">Reposo / movimiento</th></tr></thead>
        <tbody>{daily.map(row => <tr key={`${row.day}-${row.hardware_id}`}>
          <th scope="row">{row.day}<small>{row.hardware_id} · {row.name}</small></th><td>{number.format(row.samples)}</td>
          <td>{number.format(row.positions)}</td>
          <td>{row.temperature_min == null ? '—' : `${number.format(row.temperature_min)} / ${number.format(row.temperature_max ?? row.temperature_min)} °C`}</td>
          <td>{number.format(row.rest_samples)} / {number.format(row.moving_samples)}</td>
        </tr>)}</tbody>
      </table>
    </ScrollRegion>
  </div>;
}

export default function OwnerExports() {
  const [section, setSection] = useState('telemetry');
  const [preset, setPreset] = useState<'today' | '7' | '30' | 'custom'>('7');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [applied, setApplied] = useState<OwnerExportPeriod>({ days: '7' });
  const [combinedBusy, setCombinedBusy] = useState(false);
  const [combinedError, setCombinedError] = useState('');
  const metrics = useData<OwnerMetricsExport>(ownerExportPath('metricas', applied));
  const devices = useData<OwnerDevicesExport>(ownerExportPath('dispositivos', applied));
  const telemetry = useData<OwnerTelemetryExport>(ownerExportPath('telemetria', applied));
  const telemetryResult = telemetry.loading || telemetry.error ? null : telemetry.data;
  const telemetryPeriod = telemetryResult ? { start: telemetryResult.start, end: telemetryResult.end } : applied;
  const metricResult = metrics.loading || metrics.error ? null : metrics.data;
  const deviceResult = devices.loading || devices.error ? null : devices.data;
  const context = telemetryResult ?? metricResult ?? deviceResult;
  const matchingDates = metricResult && deviceResult && metricResult.start === deviceResult.start && metricResult.end === deviceResult.end;

  function generate(event: FormEvent) {
    event.preventDefault();
    const today = dateInputValue(new Date(), context?.timezone ?? 'America/Santiago');
    if (preset === 'today') setApplied({ start: today, end: today });
    else setApplied(preset === 'custom' ? { start, end } : { days: preset });
    setCombinedError('');
    metrics.reload();
    devices.reload();
    telemetry.reload();
  }

  async function combinedDownload() {
    if (!matchingDates || !metricResult) return;
    setCombinedBusy(true);
    setCombinedError('');
    try {
      await downloadFile(ownerExportPath('general', { start: metricResult.start, end: metricResult.end }, 'xlsx'), 'geocattle-general.xlsx');
    } catch (error) {
      setCombinedError(message(error));
    } finally {
      setCombinedBusy(false);
    }
  }

  return <div className="owner-exports">
    <PageTitle title="Exportación" description="Consulta y descarga los registros del predio seleccionado." />
    <Panel>
      <form className="form-body owner-export-filter" onSubmit={generate}>
        <div className="form-grid">
          <label>Período
            <select value={preset} onChange={event => setPreset(event.target.value as typeof preset)}>
              <option value="today">Hoy</option><option value="7">Últimos 7 días</option><option value="30">Últimos 30 días</option>
              <option value="custom">Rango personalizado</option>
            </select>
          </label>
          {preset === 'custom' && <>
            <label>Desde<input type="date" required max={end || undefined} value={start} onChange={event => setStart(event.target.value)} /></label>
            <label>Hasta<input type="date" required min={start || undefined} value={end} onChange={event => setEnd(event.target.value)} /></label>
          </>}
        </div>
        <div className="owner-export-actions">
          <button type="submit" className="button primary">Aplicar período</button>
          <button type="button" className="button secondary" disabled={!matchingDates || combinedBusy} onClick={combinedDownload}>
            <Download size={16} aria-hidden="true" />{combinedBusy ? 'Preparando Excel…' : 'Excel combinado'}
          </button>
        </div>
        {context && <p className="owner-export-context" role="status"><strong>{context.farm_name}</strong> · {context.start} a {context.end} · {context.timezone} · {context.origin}</p>}
        <ErrorNotice error={combinedError} />
      </form>
    </Panel>
    <SectionTabs label="Secciones de exportación" active={section} onChange={setSection} sections={[
      { id: 'metrics', label: 'Métricas', content: <Panel>
      <PanelTitle title="Métricas clave" subtitle="Solo indicadores calculados con los registros del sistema; las aproximaciones se identifican en cada tarjeta."
        action={<div role="group" aria-label="Descargas de métricas">
          <ReportDownloads key={ownerExportPath('metricas', applied)} disabled={!metricResult}
            path={format => ownerExportPath('metricas', metricResult ? { start: metricResult.start, end: metricResult.end } : applied, format)} />
        </div>} />
      <ErrorNotice error={metrics.error} retry={metrics.reload} />
      {metrics.loading && <Loading label="Calculando métricas…" />}
      {metricResult && <div className="owner-export-metrics">
        {metricResult.metrics.every(metric => metric.value == null) && <p role="status">No hay mediciones disponibles en este período. Se muestran las metas y los métodos.</p>}
        <ul>{metricResult.metrics.map(metric => <MetricCard key={metric.code} metric={metric} />)}</ul>
      </div>}
    </Panel> },
      { id: 'telemetry', label: 'Historial de telemetría', content: <Panel>
      <PanelTitle title="Historial de telemetría" subtitle="Una fila por lectura en el historial completo y una por día y collar en el registro diario. Hasta 50.000 filas por descarga."
        action={<ReportDownloads group="Historial completo" key={ownerExportPath('telemetria', applied)}
          disabled={!telemetryResult?.summary.readings} path={format => ownerExportPath('telemetria', telemetryPeriod, format)}
          additional={{ label: 'Registro diario', path: format => ownerExportPath('diario', telemetryPeriod, format) }} />} />
      <ErrorNotice error={telemetry.error} retry={telemetry.reload} />
      {telemetry.loading && <Loading label="Consultando lecturas…" />}
      {telemetryResult && <TelemetryPreview data={telemetryResult} />}
    </Panel> },
      { id: 'devices', label: 'Dispositivos', content: <Panel>
      <PanelTitle title="Dispositivos implementados" subtitle="Las lecturas y recepciones se cuentan por período. Las asignaciones y los estados son actuales."
        action={<div role="group" aria-label="Descargas de dispositivos">
          <ReportDownloads key={ownerExportPath('dispositivos', applied)} disabled={!deviceResult}
            path={format => ownerExportPath('dispositivos', deviceResult ? { start: deviceResult.start, end: deviceResult.end } : applied, format)} />
        </div>} />
      <ErrorNotice error={devices.error} retry={devices.reload} />
      {devices.loading && <Loading label="Consultando el inventario…" />}
      {deviceResult && <DevicePreview data={deviceResult} />}
    </Panel> },
    ]} />
  </div>;
}
