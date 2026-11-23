import { useEffect, useRef, useState, type FormEvent } from 'react';
import { MousePointer2, Plus, Usb } from 'lucide-react';
import { date, message, useData, write } from './api';
import type { Notify } from './App';
import { gatewayPoint } from './gatewayCoordinates';
import { withUsbGateway, type GatewayNode } from './gatewaySerial';
import { CattleMap, type Point } from './Map';
import type { Geofence, List } from './types';
import { Empty, ErrorNotice, Loading, Modal, Panel, PanelTitle, Submit } from './ui';

const endpoint = '/v3/gateway-candidates';
type Candidate = {
  id: string; source: 'usb' | 'radio'; gateway_eui: string | null; firmware: string | null;
  node_id: GatewayNode | null; reserved_node_id: GatewayNode | null; suggested_name: string | null;
  first_seen_at: string; last_seen_at: string; seen_count: number;
};

export function GatewayCandidates({ geofences, notify, onInstalled, enabled }: {
  geofences: Geofence[]; notify: Notify; onInstalled: () => void; enabled: boolean;
}) {
  const detections = useData<List<Candidate>>(enabled ? endpoint : null, 15000);
  const [approval, setApproval] = useState<Candidate | null>(null);
  const [dismiss, setDismiss] = useState<Candidate | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [progress, setProgress] = useState('');
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  const items = detections.data?.items ?? [];

  async function detect() {
    const controller = new AbortController(); operation.current = controller;
    setBusy(true); setError(''); setProgress('Selecciona el puerto del gateway.');
    try {
      const detection = await withUsbGateway(controller.signal, async descriptor => {
        controller.signal.throwIfAborted();
        return write<Candidate>(endpoint, descriptor);
      }, () => setProgress('Consultando la identidad de la placa…'));
      if (!controller.signal.aborted) {
        detections.reload();
        setApproval(detection);
      }
    } catch (problem) { if (!controller.signal.aborted) setError(message(problem)); }
    finally { setBusy(false); setProgress(''); }
  }

  async function confirmDismiss() {
    if (!dismiss) return;
    setBusy(true); setError('');
    try { await write(`${endpoint}/${dismiss.id}/dismiss`, {}); setDismiss(null); detections.reload(); notify('Detección descartada.'); }
    catch (problem) { setError(message(problem)); }
    finally { setBusy(false); }
  }

  return <Panel><PanelTitle title="Gateways detectados" subtitle={`${items.length} pendientes · bus_v1 admite solo los nodos 01 y 02 por predio`}/>
    <div className="gateway-detection-actions"><button type="button" className="button secondary" disabled={busy || !enabled} onClick={detect}><Usb size={17}/>Detectar gateway por USB</button>
      {progress && <span role="status">{progress}</span>}</div>
    {!enabled && <p className="form-intro">Las detecciones físicas no están disponibles en simulación.</p>}
    <ErrorNotice error={detections.error} retry={detections.reload}/>{!dismiss && <ErrorNotice error={error}/>}
    {detections.loading ? <Loading/> : items.length ? <div className="table-scroll"><table className="card-table gateway-detections-table"><thead><tr><th>Equipo</th><th>Origen</th><th>Última detección</th><th>Acciones</th></tr></thead><tbody>
      {items.map(item => <tr key={item.id}><td data-label="Equipo"><strong>{item.suggested_name ?? 'Nodo por asignar'}</strong><small>{item.gateway_eui ?? 'EUI no informado por radio'}</small></td>
        <td data-label="Origen">{item.source === 'usb' ? 'USB' : 'Radio'}{item.firmware && <small>{item.firmware}</small>}</td>
        <td data-label="Última detección">{date(item.last_seen_at)}<small>{item.seen_count} observaciones</small></td>
        <td data-label="Acciones"><div className="gateway-row-actions"><button type="button" className="button primary small" onClick={() => setApproval(item)}><Plus size={15}/>Agregar al sistema</button>
          <button type="button" className="button secondary small" onClick={() => { setError(''); setDismiss(item); }}>Descartar</button></div></td></tr>)}
    </tbody></table></div> : enabled && <Empty title="Sin detecciones pendientes" description="Conecta el gateway por USB o espera la primera lectura que reenvíe a la base."/>}
    {approval && <ApproveGateway key={approval.id} item={approval} geofences={geofences} onClose={() => { setApproval(null); detections.reload(); }} onSaved={() => {
      setApproval(null); detections.reload(); onInstalled(); notify('Gateway agregado al inventario.');
    }}/>}
    {dismiss && <Modal title="Descartar detección" onClose={() => { if (!busy) setDismiss(null); }}><div className="form-body">
      <p>{dismiss.reserved_node_id ? 'Apaga o desconecta el gateway si su nodo pudo haberse guardado. Descartar libera la reserva en GeoCattle, pero no modifica la placa.' : 'La detección no se incorporará al inventario.'}</p>
      <ErrorNotice error={error}/><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={() => setDismiss(null)}>Cancelar</button>
        <button type="button" className="button primary" disabled={busy} onClick={confirmDismiss}>Descartar</button></div></div></Modal>}
  </Panel>;
}

function ApproveGateway({ item, geofences, onClose, onSaved }: { item: Candidate; geofences: Geofence[]; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(''), [latitude, setLatitude] = useState(''), [longitude, setLongitude] = useState('');
  const [selecting, setSelecting] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [reserved, setReserved] = useState(item.reserved_node_id);
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  const point = gatewayPoint(latitude, longitude);
  const locationValid = !!point || (!latitude.trim() && !longitude.trim());
  const node = reserved ?? item.node_id;
  const suggestion = node ? `Gateway 0${node}` : 'Gateway 01 o 02 según disponibilidad';
  function move(coords: Point) { setLatitude(String(coords[0])); setLongitude(String(coords[1])); setSelecting(false); }

  async function approve(event: FormEvent) {
    event.preventDefault();
    if (!locationValid || busy) return;
    const controller = new AbortController(); operation.current = controller;
    setBusy(true); setError('');
    const path = `${endpoint}/${item.id}`;
    const body = { ...(name.trim() ? { name: name.trim() } : {}), ...(point ? { latitude: point[0], longitude: point[1] } : {}) };
    try {
      if (item.source === 'usb') {
        await withUsbGateway(controller.signal, async (descriptor, setNode) => {
          if (descriptor.gateway_eui !== item.gateway_eui) throw new Error('El puerto no corresponde al gateway de esta detección.');
          const allocation = await write<Candidate>(`${path}/reserve`, {});
          const assigned = allocation.reserved_node_id;
          if (assigned === null) throw new Error('La API no confirmó la reserva del nodo.');
          setReserved(assigned);
          if (descriptor.node_id !== null && descriptor.node_id !== assigned) throw new Error('La placa informa otro nodo. No se modificó el gateway.');
          const confirmed = await setNode(assigned);
          controller.signal.throwIfAborted();
          await write(`${path}/approve`, { ...body, confirmed_node_id: confirmed, confirmed_eui: descriptor.gateway_eui });
        });
      } else {
        await write(`${path}/approve`, body);
      }
      if (!controller.signal.aborted) onSaved();
    } catch (problem) { if (!controller.signal.aborted) setError(message(problem)); }
    finally { setBusy(false); }
  }

  return <Modal title="Agregar al sistema" wide onClose={() => { if (!busy) onClose(); }}><form className="form-body" onSubmit={approve}>
    <p className="form-intro">{item.source === 'usb'
      ? 'Selecciona de nuevo el puerto de esta placa al confirmar. El alta solo termina cuando el gateway confirma su nodo.'
      : 'El nodo proviene del primer receptor del collar. La radio no informa el EUI físico.'}</p>
    <div className="form-grid"><label>Nombre<input maxLength={150} value={name} placeholder={suggestion} onChange={event => setName(event.target.value)}/></label>
      <label>Nodo de radio<input readOnly value={node ? `0${node}${reserved ? ' (reservado)' : ''}` : 'Se asigna al confirmar'}/></label>
      <label>EUI físico<input readOnly value={item.gateway_eui ?? 'No informado'}/></label><label>Estado<input readOnly value="Instalado"/></label></div>
    <h3>Ubicación opcional</h3><button type="button" className="button secondary small" aria-pressed={selecting} onClick={() => setSelecting(value => !value)}><MousePointer2 size={15}/>{selecting ? 'Cancelar selección' : 'Elegir ubicación en mapa'}</button>
    <CattleMap geofences={geofences} gatewayDraft={point ? { id: 'draft', name: name.trim() || suggestion, gateway_eui: item.gateway_eui, status: 'installed', version: 1, latitude: point[0], longitude: point[1] } : undefined} onGatewayMove={move} onPoint={selecting ? move : undefined} height="editor"/>
    <div className="form-grid"><label>Latitud<input type="number" step="any" min={-90} max={90} value={latitude} onChange={event => setLatitude(event.target.value)}/></label>
      <label>Longitud<input type="number" step="any" min={-180} max={180} value={longitude} onChange={event => setLongitude(event.target.value)}/></label></div>
    {!locationValid && <p className="notice notice-warning">Indica latitud y longitud válidas o deja ambas vacías.</p>}
    {reserved && <p className="notice">El nodo 0{reserved} queda reservado hasta completar o descartar el alta. Si el USB se desconectó, reconecta la misma placa y reintenta.</p>}
    <ErrorNotice error={error}/><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cerrar</button>
      <Submit busy={busy} disabled={!locationValid}>{item.source === 'usb' ? 'Configurar por USB y agregar' : 'Agregar gateway'}</Submit></div>
  </form></Modal>;
}
