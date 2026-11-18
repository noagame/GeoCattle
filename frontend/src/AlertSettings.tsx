import { useState, type FormEvent } from 'react';
import { Check, FlaskConical, RefreshCw, Settings2, ShieldCheck } from 'lucide-react';
import { ApiError, useData, write } from './api';
import type { Settings } from './types';
import type { Notify } from './App';
import { ErrorNotice, Loading, Panel, PanelTitle } from './ui';

export function AlertSettingsPanel({ canWrite, notify, simulation, farmName, onSaved }: { canWrite: boolean; notify: Notify; simulation: boolean; farmName?: string; onSaved?: () => void }) {
  const settings = useData<Settings>('/settings');
  return <>
    <ErrorNotice error={settings.error} retry={settings.reload} />
    {settings.loading && <Loading label="Consultando parámetros vigentes…" />}
    {settings.data && <AlertSettingsForm key={settings.data.version} initial={settings.data} canWrite={canWrite && !settings.loading && !settings.error && settings.data.capabilities?.can_edit !== false} simulation={simulation} farmName={farmName} reload={settings.reload} onSaved={() => { settings.reload(); onSaved?.(); notify('Parámetros guardados. Se evaluarán con las próximas lecturas.'); }} />}
  </>;
}
function AlertSettingsForm({ initial, canWrite, simulation, farmName, reload, onSaved }: { initial: Settings; canWrite: boolean; simulation: boolean; farmName?: string; reload: () => void; onSaved: () => void }) {
  const [battery, setBattery] = useState(String(initial.battery_low_mv));
  const [temperature, setTemperature] = useState(String(initial.temperature_high_c ?? ''));
  const [activity, setActivity] = useState(String(initial.activity_low_threshold ?? ''));
  const [windowMinutes, setWindowMinutes] = useState(String(initial.activity_window_minutes));
  const [proximity, setProximity] = useState(String(initial.proximity_meters));
  const [temperatureOn, setTemperatureOn] = useState(initial.temperature_enabled);
  const [activityOn, setActivityOn] = useState(initial.activity_enabled);
  const [proximityOn, setProximityOn] = useState(initial.proximity_enabled);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [conflict, setConflict] = useState(false);
  const activationAllowed = initial.capabilities?.preventive_rules_allowed ?? simulation;
  const temperatureActivationAllowed = initial.capabilities?.temperature_rule_allowed ?? activationAllowed;
  const payload = { battery_low_mv: Number(battery), temperature_high_c: temperature === '' ? null : Number(temperature), activity_low_threshold: activity === '' ? null : Number(activity), activity_window_minutes: Number(windowMinutes), proximity_meters: Number(proximity), temperature_enabled: temperatureOn, activity_enabled: activityOn, proximity_enabled: proximityOn };
  const changed = (Object.keys(payload) as (keyof typeof payload)[]).some(key => payload[key] !== initial[key]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!canWrite || busy || conflict || !changed) return;
    setBusy(true); setError('');
    try { await write('/settings', { expected_version: initial.version, ...payload }, 'PUT'); onSaved(); }
    catch (problem) { setError(problem instanceof Error ? problem.message : 'No se pudieron guardar los parámetros.'); setConflict(problem instanceof ApiError && problem.status === 409); }
    finally { setBusy(false); }
  }
  return <><form onSubmit={submit}>
    <Panel><PanelTitle title="Parámetros de alertas" subtitle={`${farmName ? `Predio: ${farmName} · ` : ''}Versión ${initial.version}`} action={<span className="neutral-tag">{simulation ? 'Demostración' : 'Configuración del predio'}</span>} />
      <div className="settings-body">
        <div className="notice"><ShieldCheck size={18} /><span>Solo el dueño y el administrador pueden ajustar estos valores. Los cambios se guardan por predio y conservan su historial.</span></div>
        {!activationAllowed && <div className="notice alert-validation-note" role="status"><Settings2 size={18} /><span>{temperatureActivationAllowed ? 'El prototipo permite probar la alerta de temperatura superficial con las lecturas del collar. La activación de la regla de actividad requiere validación en terreno.' : 'Puedes guardar y simular los umbrales de temperatura y actividad. Su activación en el predio está pendiente de validación en terreno.'}</span></div>}
        <fieldset disabled={!canWrite || busy}>
          <div className="setting-row"><div><h3>Batería baja</h3><p>Alerta cuando la tensión medida está por debajo del umbral. Sin batería detectada no se genera esta alerta.</p></div><label>Umbral de batería (mV)<input type="number" required min="0" max="20000" step="1" value={battery} onChange={event => setBattery(event.target.value)} /><small>{battery !== '' && Number.isFinite(Number(battery)) ? `${(Number(battery) / 1000).toFixed(2)} V` : 'Introduce la tensión mínima.'}</small></label></div>
          <div className="setting-row"><div><label className="switch-label"><input type="checkbox" aria-label="Activar alerta de temperatura" checked={temperatureOn} disabled={!temperatureActivationAllowed && !temperatureOn} onChange={event => setTemperatureOn(event.target.checked)} /><span>Temperatura superficial elevada</span></label><p>Una lectura nueva igual o superior al umbral activa la alerta. Una lectura inferior la resuelve.</p></div><label>Umbral de temperatura (°C)<input type="number" required={temperatureOn} min="-60" max="100" step="any" value={temperature} onChange={event => setTemperature(event.target.value)} /></label></div>
          <div className="setting-row"><div><label className="switch-label"><input type="checkbox" aria-label="Activar alerta de actividad" checked={activityOn} disabled={!activationAllowed && !activityOn} onChange={event => setActivityOn(event.target.checked)} /><span>Actividad reducida</span></label><p>Se evalúa el promedio de actividad en una ventana completa de lecturas. Un promedio inferior al mínimo activa la alerta.</p></div><div className="form-grid"><label>Índice mínimo de actividad<input type="number" required={activityOn} min="0" max="1000000" step="any" value={activity} onChange={event => setActivity(event.target.value)} /></label><label>Ventana de actividad (minutos)<input type="number" required min="1" max="1440" step="1" value={windowMinutes} onChange={event => setWindowMinutes(event.target.value)} /></label></div></div>
          <div className="setting-row"><div><label className="switch-label"><input type="checkbox" aria-label="Activar alerta de cercanía al límite" checked={proximityOn} onChange={event => setProximityOn(event.target.checked)} /><span>Cercanía al límite de la geocerca</span></label><p>Alerta si el animal está dentro de su zona y a esta distancia o menos del borde. Requiere una posición GPS válida y una zona asignada.</p></div><label>Distancia al límite (metros)<input type="number" required min="0" max="1000" step="any" value={proximity} onChange={event => setProximity(event.target.value)} /></label></div>
        </fieldset>
        <ErrorNotice error={error} />
        {conflict && <div className="notice notice-warning"><span>Otra persona cambió los parámetros. Recarga la versión vigente antes de guardar.</span><button type="button" className="button secondary small" onClick={reload}><RefreshCw size={15} />Recargar parámetros</button></div>}
        {canWrite ? <div className="form-actions alert-settings-actions"><span>{changed ? 'Hay cambios sin guardar.' : 'Sin cambios pendientes.'}</span><button type="submit" className="button primary" disabled={busy || !changed || conflict}><Check size={17} />{busy ? 'Guardando…' : 'Guardar parámetros'}</button></div> : <p className="form-intro">Tu perfil permite consultar estos parámetros.</p>}
        <p className="form-intro">Guardar no reescribe los eventos anteriores. Las próximas lecturas se evaluarán con la nueva versión.</p>
      </div>
    </Panel>
  </form>
    {canWrite && <SensorRulePreview temperatureThreshold={payload.temperature_high_c} activityThreshold={payload.activity_low_threshold} windowMinutes={payload.activity_window_minutes} />}
    <Panel className="rules-explainer"><PanelTitle title="Reglas automáticas de posición y comunicación" subtitle="Se mantienen vinculadas al intervalo confirmado del collar; no se modifican con estos umbrales." /><div className="rule-facts"><div><span>POSICIÓN VIGENTE</span><strong>Edad ≤ 2T + 30 s</strong><p>Recibir un paquete sin fix no actualiza la posición anterior.</p></div><div><span>AUSENCIA DE COMUNICACIÓN</span><strong>Recepción &gt; 3T + 30 s</strong><p>Los duplicados y paquetes tardíos no rejuvenecen la comunicación.</p></div><div><span>SALIDA DE GEOCERCA</span><strong>Dos posiciones exteriores</strong><p>Consecutivas y válidas. El borde se considera interior.</p></div></div></Panel>
  </>;
}

type SensorPreview = {
  temperature: 'missing_data' | 'alert' | 'clear';
  activity: 'missing_data' | 'incomplete_window' | 'alert' | 'clear';
  activity_window_minutes: number;
};

function SensorRulePreview({ temperatureThreshold, activityThreshold, windowMinutes }: {
  temperatureThreshold: number | null; activityThreshold: number | null; windowMinutes: number;
}) {
  const [temperature, setTemperature] = useState('');
  const [activity, setActivity] = useState('');
  const [complete, setComplete] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [last, setLast] = useState<{ input: string; result: SensorPreview } | null>(null);
  const payload = {
    temperature_high_c: temperatureThreshold, activity_low_threshold: activityThreshold, activity_window_minutes: windowMinutes,
    surface_temperature_c: temperature === '' ? null : Number(temperature),
    activity_average: activity === '' ? null : Number(activity), activity_window_complete: complete,
  };
  const input = JSON.stringify(payload);
  const result = last?.input === input ? last.result : null;
  const validWindow = Number.isInteger(windowMinutes) && windowMinutes >= 1 && windowMinutes <= 1440;
  async function preview(event: FormEvent) {
    event.preventDefault();
    if (busy || !validWindow) return;
    setBusy(true); setError(''); setLast(null);
    try { setLast({ input, result: await write<SensorPreview>('/settings/preview', payload) }); }
    catch (problem) { setError(problem instanceof Error ? problem.message : 'No se pudo simular la alerta.'); }
    finally { setBusy(false); }
  }

  return <Panel className="rules-explainer">
    <PanelTitle title="Probar alertas de sensores" subtitle="Simula lecturas con los umbrales que tienes en pantalla antes de guardar." />
    <form className="settings-body" onSubmit={preview}>
      <div className="form-grid">
        <label>Temperatura superficial simulada (°C)<input type="number" min="-60" max="100" step="any" value={temperature} onChange={e => setTemperature(e.target.value)} /></label>
        <label>Promedio de actividad simulado<input type="number" min="0" max="1000000" step="any" value={activity} onChange={e => setActivity(e.target.value)} /></label>
      </div>
      <label className="checkbox-field"><input type="checkbox" checked={complete} onChange={e => setComplete(e.target.checked)} />Simular una ventana de actividad completa{validWindow ? ` (${windowMinutes} min)` : ''}</label>
      <ErrorNotice error={error} />
      {result && <div className="notice" role="status">
        <FlaskConical size={18} /><div>
          <p><strong>Temperatura</strong> · {result.temperature === 'alert' ? 'Activaría la alerta' : result.temperature === 'clear' ? 'Por debajo del umbral' : 'Falta el umbral o la temperatura simulada'}</p>
          <p><strong>Actividad</strong> · {result.activity === 'alert' ? 'Activaría la alerta por actividad reducida' : result.activity === 'clear' ? 'Igual o por encima del mínimo' : result.activity === 'incomplete_window' ? `Ventana de ${result.activity_window_minutes} min incompleta` : 'Falta el índice mínimo o el promedio simulado'}</p>
        </div>
      </div>}
      <div className="form-actions alert-settings-actions"><span>{validWindow ? 'Los resultados se muestran solamente en este panel.' : 'Indica una ventana de actividad entre 1 y 1440 minutos.'}</span><button type="submit" className="button secondary" disabled={busy || !validWindow}><FlaskConical size={17} />{busy ? 'Simulando…' : 'Simular alertas'}</button></div>
    </form>
  </Panel>;
}
