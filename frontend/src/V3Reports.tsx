import { useState, type FormEvent } from 'react';
import { query, useData } from './api';
import { ReportDownloads } from './ReportDownloads';
import type { Animal, List } from './types';
import { defaultDatePeriod, Empty, ErrorNotice, eventLabels, Loading, PageTitle, Panel, PanelTitle, PeriodFields, ScrollRegion } from './ui';

const records = {
  inventario: 'Inventario actual',
  sanidad: 'Ficha sanitaria',
  agenda: 'Agenda sanitaria',
  mediciones: 'Mediciones',
  observaciones: 'Observaciones del rebaño',
  asignaciones: 'Asignaciones de collares',
  alertas: 'Alertas por bovino',
  actividad: 'Actividad diaria',
};
const indicators = {
  totales: 'Totales del predio',
  'serie-alertas': 'Alertas por período',
  'ranking-movimiento': 'Ranking de movimiento',
  'ranking-salidas': 'Ranking de salidas de geocerca',
};
const reports = { ...records, ...indicators };
const alertTypes = ['escape', 'communication_timeout', 'low_battery', 'high_surface_temperature', 'low_activity', 'proximity', 'config_timeout'];
type ReportKind = keyof typeof reports;
type Filters = { kind: ReportKind; animal_id: string; start: string; end: string; grain: string; alert_type: string };
type Report = { columns: string[]; items: string[][]; total: number; start: string | null; end: string | null; timezone: string };

function hasDates(kind: ReportKind) { return kind !== 'inventario' && kind !== 'totales'; }

function reportPath({ kind, animal_id, start, end, grain, alert_type }: Filters, format = '') {
  return `/v3/animal-reports/${kind}${query({
    animal_id: kind in indicators ? '' : animal_id,
    start: hasDates(kind) ? start : '', end: hasDates(kind) ? end : '', format,
    ...(kind === 'serie-alertas' ? { grain, alert_type } : {}),
  })}`;
}

export function AnimalReportsPage({ initialAnimal, canSeeIndicators }: { initialAnimal: string; canSeeIndicators: boolean }) {
  const [filters, setFilters] = useState<Filters>({
    kind: initialAnimal ? 'sanidad' : canSeeIndicators ? 'totales' : 'inventario',
    animal_id: initialAnimal, start: '', end: '', grain: 'day', alert_type: 'all',
  });
  const [applied, setApplied] = useState(filters);
  const [period, setPeriod] = useState(defaultDatePeriod);
  const [search, setSearch] = useState('');
  const chooseAnimal = !(filters.kind in indicators);
  const animals = useData<List<Animal>>(chooseAnimal ? `/animals${query({ limit: '100', q: search })}` : null);
  const result = useData<Report>(reportPath(applied));
  const data = result.data;
  const maxAlerts = applied.kind === 'serie-alertas' && data ? Math.max(1, ...data.items.map(row => Number(row[3]))) : 1;

  function generate(event: FormEvent) {
    event.preventDefault();
    setApplied({ ...filters, start: period.start, end: period.end });
    result.reload();
  }

  return <>
    <PageTitle eyebrow="TRAZABILIDAD DEL PREDIO" title="Reportes del rebaño"
      description="Consulta y exporta los registros de un bovino o de todo el predio seleccionado." />
    <Panel>
      <form className="form-body" onSubmit={generate}>
        <div className="form-grid">
          <label>Tipo de reporte
            <select value={filters.kind} onChange={event => setFilters({ ...filters, kind: event.target.value as ReportKind })}>
              {canSeeIndicators && <optgroup label="Indicadores del predio">
                {Object.entries(indicators).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
              </optgroup>}
              <optgroup label="Registros del rebaño">
                {Object.entries(records).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
              </optgroup>
            </select>
          </label>
          {chooseAnimal && <><label>Buscar por DIIO o nombre
            <input type="search" maxLength={100} value={search} onChange={event => setSearch(event.target.value)} />
          </label>
          <label>Bovino
            <select value={filters.animal_id} onChange={event => setFilters({ ...filters, animal_id: event.target.value })}>
              <option value="">Todos los bovinos</option>
              {filters.animal_id && !animals.data?.items.some(animal => animal.id === filters.animal_id) &&
                <option value={filters.animal_id}>Bovino seleccionado</option>}
              {animals.data?.items.map(animal => <option key={animal.id} value={animal.id}>{animal.diio} · {animal.name}</option>)}
            </select>
          </label></>}
          {hasDates(filters.kind) && <PeriodFields value={period} onChange={setPeriod}
            timeZone={data?.timezone ?? 'America/Santiago'} defaultLabel="Día actual del predio" />}
          {filters.kind === 'serie-alertas' && <>
            <label>Agrupar por<select value={filters.grain} onChange={event => setFilters({ ...filters, grain: event.target.value })}>
              <option value="day">Día</option><option value="week">Semana</option><option value="month">Mes</option>
            </select></label>
            <label>Tipo de alerta<select value={filters.alert_type} onChange={event => setFilters({ ...filters, alert_type: event.target.value })}>
              <option value="all">Todas las alertas</option>
              {alertTypes.map(type => <option key={type} value={type}>{eventLabels[type]}</option>)}
            </select></label>
          </>}
        </div>
        <ErrorNotice error={animals.error} retry={animals.reload} />
        <div className="form-actions"><button className="button primary" disabled={result.loading}>Generar reporte</button></div>
      </form>
    </Panel>
    <Panel>
      <PanelTitle title={reports[applied.kind]}
        subtitle={data && data.start && data.end ? `${data.start} a ${data.end} · ${data.timezone}` : undefined}
        action={<ReportDownloads key={reportPath(applied)} disabled={result.loading || !!result.error || !data?.total}
          path={format => reportPath({ ...applied, start: data?.start ?? '', end: data?.end ?? '' }, format)} />} />
      <ErrorNotice error={result.error} retry={result.reload} />
      {applied.kind === 'ranking-movimiento' && <p className="form-intro">El porcentaje usa las muestras clasificadas como movimiento o reposo. Para obtener un puesto se requieren 10 muestras clasificadas y datos en al menos la mitad de los días transcurridos del período.</p>}
      {applied.kind === 'ranking-salidas' && <p className="form-intro">Cada alerta de salida se cuenta una vez, al abrirse. Para obtener un puesto se requiere al menos una alerta y 10 posiciones válidas durante una asignación de pastoreo en al menos la mitad de los días transcurridos del período.</p>}
      {applied.kind === 'serie-alertas' && <p className="form-intro">Las alertas se cuentan por fecha de apertura. Los días con lecturas asignadas indican cuánta observación hubo durante cada intervalo.</p>}
      {result.loading ? <Loading /> : data?.total ? <>
        <div className="list-toolbar">
          <span className="list-count">{data.total} filas · Vista previa de {data.items.length}</span>
        </div>
        <ScrollRegion label={`Vista previa · ${reports[applied.kind]}`}>
          <table>
            <thead><tr>{data.columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead>
            <tbody>{data.items.map((row, index) => <tr key={index}>
              {row.map((value, column) => <td key={data.columns[column]}>{
                applied.kind === 'serie-alertas' && column === 3 ? <>
                    <meter min={0} max={maxAlerts} value={Number(value)} aria-label="Alertas del intervalo" />{' '}{value}
                  </> : value || '—'
              }</td>)}
            </tr>)}</tbody>
          </table>
        </ScrollRegion>
      </> : !result.error && <Empty title="Sin registros para estos filtros" description="Selecciona otro día, período o bovino." />}
    </Panel>
  </>;
}
