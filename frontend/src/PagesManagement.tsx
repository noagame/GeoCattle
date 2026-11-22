import { useState, type FormEvent } from 'react';
import { ArrowRight, Clock, Fence, Link2, Pencil, Plus, Radio, Settings2, ShieldCheck } from 'lucide-react';
import type { Animal, Device, Geofence, List, Sector, UsbCollar } from './types';
import { ApiError, date, useData, write } from './api';
import { Badge, Empty, ErrorNotice, Loading, Modal, PageTitle, Panel, PanelTitle, Submit } from './ui';
import { CattleMap, type CollarLocation } from './Map';
import type { Notify } from './App';
import { AlertSettingsPanel } from './AlertSettings';
import { GeofenceForm } from './GeofenceForm';
import { DeviceCandidatesPanel } from './DeviceCandidates';
import type { DeviceCandidate } from './v3types';

export function DevicesPage({ canWrite, notify, usbCollar, clearUsbCollar, onCandidatesChange }: {
  canWrite: boolean; notify: Notify; usbCollar?: UsbCollar; clearUsbCollar: () => void; onCandidatesChange?: () => void;
}) {
  const devices = useData<List<Device>>('/devices'); const animals = useData<List<Animal>>('/animals?limit=100'); const candidates = useData<{ items: DeviceCandidate[] }>(canWrite ? '/v3/device-candidates?status=pending' : null, 30000);
  const [adding, setAdding] = useState(false); const [assigning, setAssigning] = useState<Device | null>(null); const [configuring, setConfiguring] = useState<Device | null>(null);
  const existingCollar = usbCollar && devices.data?.items.find(d => d.hardware_id === usbCollar.hardware_id);
  const ready = devices.data?.items.filter(d => d.enabled).length ?? 0;
  return <><PageTitle eyebrow="HARDWARE Y ASOCIACIONES" title="Collares y dispositivos" description="Asocia los módulos y consulta su configuración aplicada." actions={canWrite && <button className="button primary" onClick={() => setAdding(true)}><Plus size={17} />Registrar dispositivo</button>} /><div className="summary-strip"><div><Radio size={19} /><strong>{devices.data?.total ?? '—'}</strong><span>dispositivos registrados</span></div><div><ShieldCheck size={19} /><strong>{ready}</strong><span>habilitados</span></div><div><Clock size={19} /><strong>{devices.data?.items.filter(d => !!d.pending_config).length ?? '—'}</strong><span>configuraciones pendientes</span></div>{canWrite && <div><Radio size={19} /><strong>{candidates.data?.items.length ?? '—'}</strong><span>detectados pendientes</span></div>}</div>{canWrite && <DeviceCandidatesPanel canWrite={canWrite} notify={notify} candidates={candidates} onApproved={() => { devices.reload(); candidates.reload(); onCandidatesChange?.(); }} onDismissed={() => { candidates.reload(); onCandidatesChange?.(); }} />}<Panel><PanelTitle title="Inventario de dispositivos" subtitle="El intervalo activo cambia únicamente al recibir confirmación del nodo." /><ErrorNotice error={devices.error} retry={devices.reload} /><ErrorNotice error={animals.error} retry={animals.reload} />{devices.loading && <Loading />}{!devices.loading && devices.data && (devices.data.items.length ? <div className="table-scroll"><table><thead><tr><th>Dispositivo</th><th>Transporte</th><th>Animal asociado</th><th>Intervalo aplicado</th><th>Configuración pendiente</th><th>Última recepción</th>{canWrite && <th>Acciones</th>}</tr></thead><tbody>{devices.data.items.map(device => { const animal = animals.data?.items.find(a => a.id === device.animal_id || a.device_id === device.id); return <tr key={device.id}><td><div className="animal-cell"><span className="animal-avatar"><Radio size={18} /></span><div><strong>{device.name}</strong><small>{device.hardware_id}</small>{!device.enabled && <small>Deshabilitado</small>}</div></div></td><td>{device.transport === 'academic' ? 'Académico' : 'LoRaWAN'}{device.dev_eui && <small>{device.dev_eui}</small>}</td><td>{animal ? <>{animal.name}<small>DIIO {animal.diio}</small></> : device.animal_id ? 'Animal asociado' : <span className="muted">Sin asignar</span>}</td><td><strong>{device.interval_seconds} s</strong><small>Versión {device.config_version}</small></td><td>{device.pending_config ? <><Badge status="warning">{device.pending_config.status === 'requested' ? 'Solicitada' : device.pending_config.status === 'sent' ? 'Enviada' : device.pending_config.status === 'pending' ? 'Pendiente' : device.pending_config.status}</Badge><small>{device.pending_config.interval_seconds} s · v{device.pending_config.version}</small></> : <span className="muted">Sin cambios pendientes</span>}</td><td>{date(device.last_received_at)}</td>{canWrite && <td><div className="row-actions"><button className="icon-button" aria-label={`Asignar ${device.name}`} title="Asignar o reasignar" onClick={() => setAssigning(device)} disabled={!device.enabled}><Link2 size={17} /></button><button className="icon-button" aria-label={`Configurar ${device.name}`} title="Solicitar configuración" onClick={() => setConfiguring(device)} disabled={!!device.pending_config || !device.enabled}><Settings2 size={17} /></button></div></td>}</tr>; })}</tbody></table></div> : <Empty title="Sin dispositivos registrados" description="Da de alta un módulo e identifica su transporte antes de asociarlo a un animal." />)}</Panel>{canWrite && usbCollar && <Modal title="Alta de collar por USB" onClose={clearUsbCollar}>
      <div className="form-body">
        {!devices.data && (devices.error ? <ErrorNotice error={devices.error} retry={devices.reload} /> : <Loading />)}
        {existingCollar && <>
          <p>El collar <strong>{existingCollar.name}</strong> ({existingCollar.hardware_id}) ya está en el inventario de este predio.</p>
          <div className="form-actions">
            <button className="button secondary" onClick={clearUsbCollar}>Cerrar</button>
            <button className="button primary" disabled={!existingCollar.enabled || !animals.data}
              onClick={() => { clearUsbCollar(); setAssigning(existingCollar); }}>Asignar a un bovino</button>
          </div>
        </>}
        {devices.data && !existingCollar && <DeviceFields key={usbCollar.hardware_id} usbCollar={usbCollar}
          onClose={clearUsbCollar} onSaved={() => { clearUsbCollar(); devices.reload(); notify('Collar registrado. Ya puedes asignarlo a un bovino.'); }} />}
      </div>
    </Modal>}
    {adding && <Modal title="Registrar dispositivo" onClose={() => setAdding(false)}><DeviceFields
      onClose={() => setAdding(false)}
      onSaved={() => { setAdding(false); devices.reload(); notify('Dispositivo registrado.'); }} /></Modal>}{assigning && <AssignmentForm device={assigning} animals={animals.data?.items ?? []} onClose={() => setAssigning(null)} onSaved={() => { setAssigning(null); devices.reload(); animals.reload(); notify('Asignación guardada con vigencia histórica.'); }} />}{configuring && <DeviceConfigForm device={configuring} onClose={() => setConfiguring(null)} onSaved={() => { setConfiguring(null); devices.reload(); notify('Configuración solicitada. Pendiente de confirmación del nodo.'); }} />}</>;
}
function DeviceFields({ usbCollar, onClose, onSaved }: {
  usbCollar?: UsbCollar; onClose: () => void; onSaved: () => void;
}) {
  const [name, setName] = useState('');
  const [hardware, setHardware] = useState(usbCollar?.hardware_id ?? '');
  const [devEui, setDevEui] = useState('');
  const [transport, setTransport] = useState('academic');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const intervalSeconds = usbCollar?.interval_seconds ?? 300;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) { setError('Ingresa un nombre para el collar.'); return; }
    setBusy(true);
    setError('');
    try {
      await write('/devices', { name: name.trim(), hardware_id: hardware.trim(),
        ...(!usbCollar && devEui.trim() ? { dev_eui: devEui.trim() } : {}),
        transport, interval_seconds: intervalSeconds });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo registrar.');
    } finally {
      setBusy(false);
    }
  }

  return <form className="form-body" onSubmit={submit}>
    <label>Nombre<input value={name} onChange={e => setName(e.target.value)} required maxLength={100} placeholder="Collar / módulo" /></label>
    <label>Identificador de hardware<input value={hardware} onChange={e => setHardware(e.target.value)} required
      readOnly={!!usbCollar} maxLength={100} placeholder="Identificador único del nodo" /></label>
    {usbCollar ? <p className="form-intro">Transporte LoRa punto a punto. El collar quedará en inventario, listo para asignarlo a un bovino.</p> :
      <label>Transporte<select value={transport} onChange={e => setTransport(e.target.value)}>
        <option value="academic">Prototipo · LoRa punto a punto</option><option value="lorawan">Cliente · LoRaWAN</option>
      </select></label>}
    {!usbCollar && <label>DevEUI {transport === 'academic' && '(opcional)'}<input value={devEui} onChange={e => setDevEui(e.target.value)} required={transport === 'lorawan'}
      pattern="[0-9a-fA-F]{16}" placeholder="16 caracteres hexadecimales" />
      <small>Las claves de radio se configuran en el servicio LoRaWAN.</small></label>}
    <div className="notice"><Clock size={17} /><span>Intervalo inicial de {intervalSeconds} segundos.</span></div>
    <ErrorNotice error={error} />
    <div className="form-actions">
      <button type="button" className="button secondary" onClick={onClose} disabled={busy}>Cancelar</button>
      <Submit busy={busy}>{usbCollar ? 'Guardar collar' : 'Registrar dispositivo'}</Submit>
    </div>
  </form>;
}
function AssignmentForm({ device, animals, onClose, onSaved }: { device: Device; animals: Animal[]; onClose: () => void; onSaved: () => void }) {
  const [animal, setAnimal] = useState(''); const [replace, setReplace] = useState(false); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const destination = animals.find(a => a.id === animal);
  const replacementRequired = !!device.animal_id || !!destination?.device_id;
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { await write('/assignments', { animal_id: animal, device_id: device.id, replace }); onSaved(); } catch (err) { setError(err instanceof Error ? err.message : 'No se pudo asociar.'); } finally { setBusy(false); } }
  return <Modal title={`Asignar ${device.name}`} onClose={onClose}><form className="form-body" onSubmit={submit}><p className="form-intro">La nueva asociación comienza al guardar. El historial de lecturas mantiene las asociaciones que estaban vigentes al observar cada paquete.</p><label>Animal<select value={animal} onChange={e => setAnimal(e.target.value)} required><option value="">Selecciona un animal</option>{animals.filter(a => a.enabled).map(a => <option key={a.id} value={a.id}>{a.name} · DIIO {a.diio}{a.device_id ? ' · tiene collar' : ''}</option>)}</select></label>{replacementRequired && <div className="notice notice-warning">El collar o el animal ya tiene una asociación. La reasignación cerrará las asociaciones previas afectadas.</div>}<label className="checkbox-field"><input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)} required={replacementRequired} /><span>Confirmo el cierre de las asociaciones anteriores si existen.</span></label><ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>Cancelar</button><Submit busy={busy}>Guardar asignación</Submit></div></form></Modal>;
}
function DeviceConfigForm({ device, onClose, onSaved }: { device: Device; onClose: () => void; onSaved: () => void }) {
  const [interval, setInterval] = useState(String(device.pending_config?.interval_seconds ?? device.interval_seconds)); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { await write(`/devices/${device.id}/config`, { interval_seconds: Number(interval), expected_version: device.config_version }); onSaved(); } catch (err) { setError(err instanceof Error ? err.message : 'No se pudo solicitar.'); } finally { setBusy(false); } }
  return <Modal title={`Configurar ${device.name}`} onClose={onClose}><form className="form-body" onSubmit={submit}><div className="notice"><Clock size={18} /><span>Intervalo aplicado: <strong>{device.interval_seconds} s · v{device.config_version}</strong>. El intervalo solicitado permanece pendiente hasta recibir la versión confirmada por el nodo.</span></div>{device.pending_config && <div className="notice notice-warning">Existe una solicitud pendiente de {device.pending_config.interval_seconds} s (v{device.pending_config.version}). El servidor comprobará si puede emitir una nueva versión.</div>}<label>Nuevo intervalo (segundos)<input type="number" min="30" max="86400" step="1" value={interval} onChange={e => setInterval(e.target.value)} required /></label><p className="form-intro">La pérdida de comunicación y la vigencia de posición siguen usando el intervalo aplicado. En clase A, el envío puede esperar una ventana de recepción.</p><ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>Cancelar</button><Submit busy={busy}>Solicitar configuración</Submit></div></form></Modal>;
}
type MapContext = { items: { hardware_id: string; last_position: { latitude: number | null; longitude: number | null; observed_at: string; gnss_valid: boolean } | null; position_age_seconds: number | null; freshness_seconds: number }[] };
function PastureTransferForm({ devices, collars, selected, onSelect, animal, fences, sectors, watched, notify }: {
  devices: ReturnType<typeof useData<List<Device>>>; collars: Device[]; selected?: Device; onSelect: (id: string) => void;
  animal: ReturnType<typeof useData<Animal>>; fences: ReturnType<typeof useData<List<Geofence>>>;
  sectors: ReturnType<typeof useData<List<Sector>>>; watched?: Animal['pasture_assignment']; notify: Notify;
}) {
  const [destinationId, setDestinationId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const eligible = fences.data?.items.filter(f => f.active && f.id !== watched?.geofence_id &&
    sectors.data?.items.some(s => s.id === f.sector_id && s.active !== false)) ?? [];
  const destination = eligible.find(f => f.id === destinationId) ?? (eligible.length === 1 ? eligible[0] : undefined);
  const ready = !!(selected && animal.data?.enabled && destination && !animal.loading);

  async function transfer(event: FormEvent) {
    event.preventDefault();
    if (!ready || busy || !destination || !animal.data || !selected) return;
    setBusy(true); setError('');
    try {
      await write('/pasture-assignments', {
        animal_id: animal.data.id, geofence_id: destination.id, expected_pasture_id: watched?.id ?? null, expected_device_id: selected.id,
      });
      setDestinationId(''); animal.reload();
      notify(`Collar trasladado a ${destination.name}.`);
    } catch (problem) {
      if (problem instanceof ApiError && problem.status === 409) {
        setDestinationId(''); devices.reload(); animal.reload(); fences.reload(); sectors.reload();
      }
      setError(problem instanceof Error ? problem.message : 'No se pudo trasladar el collar.');
    } finally { setBusy(false); }
  }

  return <Panel className="pasture-transfer">
    <PanelTitle title="Trasladar collar entre geocercas" subtitle="Cambia la zona vigilada del animal asociado y conserva el historial de ambos potreros." />
    <div className="form-body">
      <ErrorNotice error={devices.error || animal.error || error} retry={devices.error ? devices.reload : animal.error ? animal.reload : undefined} />
      {!devices.data && devices.loading && <Loading label="Consultando collares…" />}
      {devices.data && !collars.length && <p className="form-intro">Asocia un collar a un animal desde <a href="#devices">Collares y dispositivos</a> para elegir la geocerca que vigilará.</p>}
      {collars.length > 1 && <label>Collar<select value={selected?.id ?? ''} onChange={e => { onSelect(e.target.value); setDestinationId(''); setError(''); }} disabled={busy}>
        <option value="">Selecciona un collar</option>
        {collars.map(collar => <option key={collar.id} value={collar.id}>{collar.hardware_id} · {collar.name}</option>)}
      </select></label>}
      {selected && <>
        <p className="form-intro"><strong>{selected.hardware_id}</strong>{animal.data && <> · {animal.data.name} · DIIO {animal.data.diio}</>}</p>
        {animal.loading && !animal.data ? <Loading label="Consultando zona vigente…" /> : animal.data && <>
          <p className="form-intro">Zona vigilada <strong>{watched ? `${watched.geofence_name} · ${watched.sector_name}` : 'Sin asignación'}</strong></p>
          {!animal.data.enabled ? <p className="form-intro">El animal debe estar habilitado para trasladarlo.</p> :
            <form className="inline-assignment" onSubmit={transfer}>
              <label>Geocerca de destino<select required value={destination?.id ?? ''} onChange={e => setDestinationId(e.target.value)} disabled={busy || animal.loading || !eligible.length}>
                <option value="">{eligible.length ? 'Selecciona la nueva geocerca' : 'Sin otra geocerca activa disponible'}</option>
                {eligible.map(f => <option key={f.id} value={f.id}>{f.name} · {sectors.data?.items.find(s => s.id === f.sector_id)?.name} · v{f.version}</option>)}
              </select></label>
              <button type="submit" className="button primary" disabled={!ready || busy}><ArrowRight size={16} />{busy ? 'Trasladando…' : watched ? 'Confirmar traslado' : 'Asignar geocerca'}</button>
            </form>}
        </>}
      </>}
    </div>
  </Panel>;
}

export function GeofencesPage({ canWrite, notify }: { canWrite: boolean; notify: Notify }) {
  const fences = useData<List<Geofence>>('/geofences'); const sectors = useData<List<Sector>>('/sectors');
  const devices = useData<List<Device>>(canWrite ? '/devices' : null);
  const [collarId, setCollarId] = useState('');
  const linked = devices.data?.items.filter(d => d.enabled && d.animal_id) ?? [];
  const selected = linked.find(d => d.id === collarId) ?? (linked.length === 1 ? linked[0] : undefined);
  const animal = useData<Animal>(selected?.animal_id ? `/animals/${selected.animal_id}` : null);
  const watched = animal.data?.pasture_assignment;
  const context = useData<MapContext>('/hardware/overview', 15000);
  const collars: CollarLocation[] = context.data?.items.flatMap(d => { const p = d.last_position; return p?.gnss_valid && p.latitude != null && p.longitude != null ? [{ hardware_id: d.hardware_id, latitude: p.latitude, longitude: p.longitude, observed_at: p.observed_at, stale: (d.position_age_seconds ?? Infinity) > d.freshness_seconds }] : []; }) ?? [];
  const [sectorEditing, setSectorEditing] = useState<Sector | null>(null);
  const [showVersions, setShowVersions] = useState(false); const [sector, setSector] = useState('');
  const [creating, setCreating] = useState(false); const [editing, setEditing] = useState<Geofence | null>(null); const [addingSector, setAddingSector] = useState(false);
  const visible = fences.data?.items.filter(f => (showVersions || f.active) && (!sector || f.sector_ids.includes(sector))) ?? [];
  return <><PageTitle eyebrow="LÍMITES Y PASTOREO" title="Sectores y geocercas" description="Delimita zonas del predio y conserva cada versión." actions={canWrite && <><button className="button secondary" onClick={() => setAddingSector(true)}><Plus size={17} />Crear sector</button><button className="button primary" disabled={!sectors.data?.items.some(s => s.active !== false)} title="Necesitas un sector activo para crear una geocerca" onClick={() => setCreating(true)}><Fence size={17} />Nueva geocerca</button></>} />{canWrite && <PastureTransferForm devices={devices} collars={linked} selected={selected} onSelect={setCollarId} animal={animal} fences={fences} sectors={sectors} watched={watched} notify={notify} />}<div className="geofence-grid"><Panel className="map-panel"><PanelTitle title="Zonas del predio" subtitle="Geocercas guardadas y últimas posiciones válidas de los collares del predio" action={<select className="compact-select" aria-label="Filtrar geocercas por sector" value={sector} onChange={e => setSector(e.target.value)}><option value="">Todos los sectores</option>{sectors.data?.items.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>} /><CattleMap key={sector} geofences={visible} collars={collars} watchedFenceId={watched?.geofence_id} /></Panel><Panel><PanelTitle title="Geocercas" subtitle={`${fences.data?.items.filter(f => f.active).length ?? 0} versiones activas`} /><label className="checkbox-field version-toggle"><input type="checkbox" checked={showVersions} onChange={e => setShowVersions(e.target.checked)} />Mostrar versiones anteriores</label><ErrorNotice error={fences.error || sectors.error} retry={() => { fences.reload(); sectors.reload(); }} />{fences.loading && <Loading />}{!fences.loading && (visible.length ? <div className="geofence-cards">{visible.map(f => <div className={`geofence-card ${!f.active ? 'inactive' : ''}`} key={f.id}><div className="geofence-card-top"><span className="animal-avatar"><Fence size={18} /></span><div><h3>{f.name}</h3><small>{sectors.data?.items.filter(s => f.sector_ids.includes(s.id)).map(s => s.name).join(' · ') || 'Sector'}</small></div>{canWrite && f.active && <button className="icon-button" aria-label={`Editar ${f.name}`} onClick={() => setEditing(f)}><Pencil size={16} /></button>}</div><div className="geofence-card-meta"><span>Versión {f.version}</span><Badge status={f.active ? 'normal' : 'unknown'}>{f.id === watched?.geofence_id ? 'Zona vigilada' : f.active ? 'Activa' : 'Histórica'}</Badge></div><p>{date(f.created_at)} · {f.geometry.coordinates[0].length - 1} vértices</p></div>)}</div> : <Empty title="Sin geocercas" description="Crea un sector y dibuja o importa su primera zona." />)}</Panel></div><Panel><PanelTitle title="Sectores del predio" subtitle="Define el uso del suelo y conserva sectores retirados." />{sectors.data?.items.length ? <div className="table-scroll"><table><thead><tr><th>Sector</th><th>Uso</th><th>Descripción</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>{sectors.data.items.map(s => <tr key={s.id}><td>{s.name}</td><td>{landUseLabels[s.land_use ?? 'grazing']}</td><td className="wrap-cell">{s.description || 'Sin descripción'}</td><td>{s.active === false ? 'Inactivo' : 'Activo'}</td><td>{canWrite && <button className="button secondary small" onClick={() => setSectorEditing(s)}><Pencil size={14} />Editar sector</button>}</td></tr>)}</tbody></table></div> : <Empty title="Sin sectores" description="Crea un sector antes de delimitar geocercas." />}</Panel>{(creating || editing) && <GeofenceForm fence={editing ?? undefined} collars={collars} sectors={sectors.data?.items.filter(s => s.active !== false) ?? []} existing={fences.data?.items.filter(f => f.active) ?? []} onClose={() => { setCreating(false); setEditing(null); }} onSaved={() => { setCreating(false); setEditing(null); fences.reload(); animal.reload(); notify('Geocerca guardada. Versión anterior conservada.'); }} />}{sectorEditing && <SectorForm sector={sectorEditing} onClose={() => setSectorEditing(null)} onSaved={() => { setSectorEditing(null); sectors.reload(); notify('Sector actualizado.'); }} />}{addingSector && <SectorForm onClose={() => setAddingSector(false)} onSaved={() => { setAddingSector(false); sectors.reload(); notify('Sector creado.'); }} />}</>;
}
const landUseLabels: Record<string, string> = { grazing: 'Pastoreo', available: 'Disponible / libre', cropped: 'Ocupado por siembra', restricted: 'Restringido', other: 'Otro' };
function SectorForm({ sector, onClose, onSaved }: { sector?: Sector; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(sector?.name ?? ''); const [landUse, setLandUse] = useState(sector?.land_use ?? 'grazing'); const [description, setDescription] = useState(sector?.description ?? ''); const [active, setActive] = useState(sector?.active !== false); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { await write(`/sectors${sector ? `/${sector.id}` : ''}`, { name, land_use: landUse, description: description || null, ...(sector ? { active } : {}) }, sector ? 'PATCH' : 'POST'); onSaved(); } catch (err) { setError(err instanceof Error ? err.message : 'No se pudo guardar el sector.'); } finally { setBusy(false); } }
  return <Modal title={sector ? 'Editar sector' : 'Crear sector'} onClose={onClose}><form className="form-body" onSubmit={submit}><label>Nombre del sector<input value={name} onChange={e => setName(e.target.value)} required maxLength={100} placeholder="Nombre usado en el predio" /></label><label>Uso del suelo<select value={landUse} onChange={e => setLandUse(e.target.value as NonNullable<Sector['land_use']>)}>{Object.entries(landUseLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Descripción<textarea rows={3} maxLength={1000} value={description} onChange={e => setDescription(e.target.value)} /></label>{sector && <label className="checkbox-field"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />Sector activo</label>}<ErrorNotice error={error} /><div className="form-actions"><button className="button secondary" type="button" onClick={onClose}>Cancelar</button><Submit busy={busy}>Guardar sector</Submit></div></form></Modal>;
}
export function SettingsPage({ canWrite, notify, simulation, farmName }: { canWrite: boolean; notify: Notify; simulation: boolean; farmName?: string }) {
  return <><PageTitle eyebrow="CONFIGURACIÓN DE SUPERVISIÓN" title="Reglas del predio" description="Los mismos parámetros de alertas disponibles en Alertas y atención." /><AlertSettingsPanel canWrite={canWrite} notify={notify} simulation={simulation} farmName={farmName} /></>;
}
