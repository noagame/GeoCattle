import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Archive, Eye, LocateFixed, MousePointer2, Pencil, Plus, Radio } from 'lucide-react';
import type { Notify } from './App';
import type { Geofence, List } from './types';
import type { Gateway, GatewayReception } from './v3types';
import { ApiError, date, message, useData, write } from './api';
import { Badge, Detail, Empty, ErrorNotice, Loading, Modal, PageTitle, Panel, PanelTitle, Submit } from './ui';
import { CattleMap, type Point } from './Map';
import { Pagination } from './PagesAnimals';
import { gatewayPoint, gatewayStatus, hasGatewayPosition } from './gatewayCoordinates';

export function GatewaysPage({ notify }: { notify: Notify }) {
  const [archived,setArchived]=useState(false);
  const gateways=useData<List<Gateway>>(`/v3/gateways${archived?'?include_archived=true':''}`);
  const fences=useData<List<Geofence>>('/geofences');
  const [editing,setEditing]=useState<Gateway|'new'|null>(null),[detail,setDetail]=useState<string|null>(null),[archiving,setArchiving]=useState<Gateway|null>(null);
  const [focus,setFocus]=useState<Point[]>([]),[fitRequest,setFitRequest]=useState(0),[selected,setSelected]=useState<string|null>(null);
  const activeFences=fences.data?.items.filter(f=>f.active) ?? [];
  const items=gateways.data?.items ?? [];
  function view(g: Gateway) {setSelected(g.id);setFocus(hasGatewayPosition(g)?[[g.latitude!,g.longitude!]]:[]);setFitRequest(n=>n+1);}
  function saved() {setEditing(null);gateways.reload();notify('Gateway guardado. Ubicación y mapa actualizados.');}
  function archivedSaved() {setArchiving(null);setDetail(null);setSelected(null);setFocus([]);gateways.reload();notify('Gateway archivado. Su historial de recepciones se conserva.');}
  return <><PageTitle eyebrow="INFRAESTRUCTURA DEL PREDIO" title="Gateways del predio" description="Administra el inventario, su ubicación y sus recepciones registradas." actions={<button className="button primary" onClick={()=>setEditing('new')}><Plus size={17}/>Agregar gateway</button>}/>
    <div className="notice"><Radio size={18}/><span>Registrar o mover un gateway en el mapa no configura el equipo físico. El estado Instalado describe el inventario; la última recepción indica la evidencia disponible de comunicación.</span></div>
    <Panel><PanelTitle title="Ubicación de gateways" subtitle="Marcadores azules G: gateways. Polígonos verdes: geocercas del predio."/><ErrorNotice error={fences.error} retry={fences.reload}/><CattleMap gateways={items} geofences={activeFences} focusPoints={focus} fitRequest={fitRequest} selectedGatewayId={selected} onGateway={g=>setDetail(g.id)}/></Panel>
    <Panel><PanelTitle title="Inventario de gateways" subtitle={`${items.length} registros en esta vista`}/><label className="checkbox-field gateway-archive-toggle"><input type="checkbox" checked={archived} onChange={e=>{setArchived(e.target.checked);setFocus([]);setSelected(null);}}/>Incluir archivados para consultar su historial</label><ErrorNotice error={gateways.error} retry={gateways.reload}/>
      {gateways.loading?<Loading/>:items.length?<div className="table-scroll"><table><thead><tr><th>Gateway / EUI físico</th><th>Ubicación WGS84</th><th>Estado administrativo</th><th>Última recepción del servidor</th><th>Acciones</th></tr></thead><tbody>{items.map(g=><tr key={g.id}><td><strong>{g.name}</strong><small>{g.gateway_eui}</small>{g.archived_at&&<Badge status="unknown">Archivado</Badge>}</td><td>{hasGatewayPosition(g)?<>{g.latitude!.toFixed(6)}<small>{g.longitude!.toFixed(6)}</small></>:'Sin ubicación registrada'}</td><td>{gatewayStatus[g.status] ?? g.status}</td><td>{date(g.last_seen_at)}</td><td><div className="gateway-row-actions"><button className="button secondary small" onClick={()=>setDetail(g.id)} aria-label={`Ver detalle de ${g.name}`}><Eye size={14}/>Detalle e historial</button><button className="button secondary small" disabled={!hasGatewayPosition(g)} onClick={()=>view(g)} aria-label={`Ver ${g.name} en mapa`}><LocateFixed size={14}/>Ver en mapa</button>{!g.archived_at&&<><button className="button secondary small" onClick={()=>setEditing(g)} aria-label={`Editar ${g.name}`}><Pencil size={14}/>Editar</button><button className="button secondary small" onClick={()=>setArchiving(g)} aria-label={`Archivar ${g.name}`}><Archive size={14}/>Archivar</button></>}</div></td></tr>)}</tbody></table></div>:<Empty title="Sin gateways en esta vista" description="Registra uno nuevo o incluye los archivados para consultar su historial."/>}
    </Panel>
    {editing&&<GatewayForm gateway={editing==='new'?undefined:editing} geofences={activeFences} gateways={items.filter(g=>!g.archived_at)} onClose={()=>setEditing(null)} onSaved={saved}/>}
    {detail&&<GatewayDetail ident={detail} onClose={()=>setDetail(null)} onEdit={g=>{setDetail(null);setEditing(g);}} onArchive={g=>setArchiving(g)}/>}
    {archiving&&<ArchiveGateway gateway={archiving} onClose={()=>setArchiving(null)} onSaved={archivedSaved}/>}
  </>;
}

function GatewayForm({gateway,geofences,gateways,onClose,onSaved}:{gateway?:Gateway;geofences:Geofence[];gateways:Gateway[];onClose:()=>void;onSaved:()=>void}) {
  const [name,setName]=useState(gateway?.name ?? ''),[eui,setEui]=useState(gateway?.gateway_eui ?? ''),[status,setStatus]=useState(gateway?.status ?? 'installed');
  const [latitude,setLatitude]=useState(gateway?.latitude==null?'':String(gateway.latitude)),[longitude,setLongitude]=useState(gateway?.longitude==null?'':String(gateway.longitude));
  const [selecting,setSelecting]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[conflict,setConflict]=useState(false),[discard,setDiscard]=useState(false);
  const [fitRequest,setFitRequest]=useState(0),[focus,setFocus]=useState<Point[]>(hasGatewayPosition(gateway ?? {})?[[gateway!.latitude!,gateway!.longitude!]]:[]);
  const signature=JSON.stringify([name,eui,status,latitude,longitude]);const initial=useRef(signature);const dirty=signature!==initial.current;
  const point=gatewayPoint(latitude,longitude);const missingBoth=!latitude.trim()&&!longitude.trim();
  const locationValid=!!point || (!!gateway && gateway.latitude==null && gateway.longitude==null && missingBoth);
  useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[dirty]);
  function close(){if(busy)return;if(dirty)setDiscard(true);else onClose();}
  function move(p:Point){setLatitude(String(p[0]));setLongitude(String(p[1]));setFocus([]);}
  function center(){if(point){setFocus([point]);setFitRequest(n=>n+1);}}
  async function submit(event:FormEvent){
    event.preventDefault();if(!locationValid||!name.trim()||conflict||busy)return;
    setBusy(true);setError('');
    const body=gateway?{name:name.trim(),status,expected_version:gateway.version,...(point?{latitude:point[0],longitude:point[1]}:{})}:{name:name.trim(),gateway_eui:eui.trim(),latitude:point![0],longitude:point![1]};
    try{await write(`/v3/gateways${gateway?`/${gateway.id}`:''}`,body,gateway?'PATCH':'POST');onSaved();}
    catch(problem){setError(message(problem));setConflict(problem instanceof ApiError&&problem.status===409&&!!gateway);}finally{setBusy(false);}
  }
  return <><Modal title={gateway?`Editar gateway: ${gateway.name}`:'Registrar gateway'} wide onClose={close}><form className="form-body" onSubmit={submit}>
    {gateway&&<p className="form-intro">UUID interno: {gateway.id} · Versión {gateway.version}. El EUI físico y las recepciones históricas se conservan.</p>}
    <div className="form-grid"><label>Nombre del gateway<input required maxLength={150} value={name} onChange={e=>setName(e.target.value)}/></label><label>Gateway EUI físico<input required pattern="[0-9a-fA-F]{16}" maxLength={16} value={eui} readOnly={!!gateway} onChange={e=>setEui(e.target.value)}/><small>16 caracteres hexadecimales; identifica el equipo físico, no el UUID interno.</small></label>{gateway&&<label>Estado administrativo<select value={status} onChange={e=>setStatus(e.target.value as Gateway['status'])}>{Object.entries(gatewayStatus).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>}</div>
    <div className="geofence-drawing-toolbar"><button type="button" className={`button ${selecting?'primary':'secondary'} small`} aria-pressed={selecting} onClick={()=>setSelecting(v=>!v)}><MousePointer2 size={15}/>{selecting?'Pausar selección':'Elegir ubicación en mapa'}</button><button type="button" className="button secondary small" disabled={!point} onClick={center}><LocateFixed size={15}/>Centrar ubicación</button></div>
    <CattleMap geofences={geofences} gateways={gateways.filter(g=>g.id!==gateway?.id)} gatewayDraft={point?{...gateway,id:gateway?.id ?? 'draft',name:name.trim()||'Nuevo gateway',gateway_eui:eui.trim(),status,version:gateway?.version ?? 1,latitude:point[0],longitude:point[1]}:undefined} onGatewayMove={move} onPoint={selecting?move:undefined} focusPoints={focus} fitRequest={fitRequest} height="editor"/>
    <p role="status" className="form-intro">{selecting?'Un clic en el mapa elige o reemplaza la ubicación del único marcador G.':'Activa la selección para ubicarlo con un clic. Puedes arrastrar el marcador G o editar sus coordenadas.'} Los cambios se guardan solo al confirmar.</p>
    <div className="form-grid"><label>Latitud del gateway<input type="number" step="any" min={-90} max={90} required={!gateway||!missingBoth} value={latitude} onChange={e=>setLatitude(e.target.value)}/></label><label>Longitud del gateway<input type="number" step="any" min={-180} max={180} required={!gateway||!missingBoth} value={longitude} onChange={e=>setLongitude(e.target.value)}/></label></div>
    {!locationValid&&<p className="notice notice-warning" role="status">Indica latitud y longitud válidas, o elige una ubicación en el mapa.</p>}{gateway&&missingBoth&&<p className="notice">Este registro antiguo no tiene ubicación. Puedes completarla en el mapa o conservarla sin inventar coordenadas.</p>}
    <ErrorNotice error={error}/>{conflict&&<p className="form-intro">Cierra y vuelve a abrir el gateway para consultar su versión vigente. Tus cambios todavía no se guardaron.</p>}<div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={close}>Cancelar</button><Submit busy={busy} disabled={!dirty||!locationValid||!name.trim()||conflict}>Guardar gateway</Submit></div>
  </form></Modal>{discard&&<Modal title="Descartar cambios del gateway" onClose={()=>setDiscard(false)}><div className="form-body"><p>Hay cambios sin guardar. ¿Cerrar y descartarlos? La ubicación y los datos guardados se conservarán.</p><div className="form-actions"><button type="button" className="button secondary" onClick={()=>setDiscard(false)}>Continuar editando</button><button type="button" className="button primary" onClick={onClose}>Descartar cambios</button></div></div></Modal>}</>;
}

function ArchiveGateway({gateway,onClose,onSaved}:{gateway:Gateway;onClose:()=>void;onSaved:()=>void}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function archive(){setBusy(true);setError('');try{await write(`/v3/gateways/${gateway.id}`,{expected_version:gateway.version,confirm:true},'DELETE');onSaved();}catch(problem){setError(message(problem));}finally{setBusy(false);}}
  return <Modal title="Confirmar archivado del gateway" onClose={()=>{if(!busy)onClose();}}><div className="form-body"><p>¿Archivar <strong>{gateway.name}</strong>, EUI <strong>{gateway.gateway_eui}</strong>?</p><p>Se ocultará de la vista operativa. Su estado administrativo, ubicación, auditoría y recepciones históricas se conservarán. Esto no apaga ni reconfigura el equipo físico.</p><ErrorNotice error={error}/><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cancelar</button><button type="button" className="button primary" disabled={busy||!!error} onClick={archive}>{busy?'Archivando…':'Confirmar archivado'}</button></div></div></Modal>;
}

function GatewayDetail({ident,onClose,onEdit,onArchive}:{ident:string;onClose:()=>void;onEdit:(g:Gateway)=>void;onArchive:(g:Gateway)=>void}){
  const gateway=useData<Gateway>(`/v3/gateways/${ident}`),[offset,setOffset]=useState(0);
  const history=useData<List<GatewayReception>>(`/v3/gateways/${ident}/receptions?limit=50&offset=${offset}`);
  const g=gateway.data;
  return <Modal title={g?`Gateway: ${g.name}`:'Detalle del gateway'} wide onClose={onClose}><div className="form-body"><ErrorNotice error={gateway.error} retry={gateway.reload}/>{gateway.loading?<Loading/>:g&&<><div className="detail-badges"><Badge status={g.archived_at?'unknown':'normal'}>{g.archived_at?'Archivado':'En inventario operativo'}</Badge><span className="neutral-tag">{gatewayStatus[g.status]}</span></div><dl className="details-grid"><Detail label="UUID interno" value={g.id}/><Detail label="Gateway EUI físico" value={g.gateway_eui}/><Detail label="Latitud" value={g.latitude==null?'Sin ubicación':g.latitude.toFixed(6)}/><Detail label="Longitud" value={g.longitude==null?'Sin ubicación':g.longitude.toFixed(6)}/><Detail label="Instalación registrada" value={date(g.installed_at)}/><Detail label="Última recepción del servidor" value={date(g.last_seen_at)}/><Detail label="Recepciones conservadas" value={g.reception_count ?? 0}/>{g.archived_at&&<><Detail label="Fecha de archivado" value={date(g.archived_at)}/><Detail label="Usuario que archivó" value={g.archived_by ?? 'Sin registro'}/></>}</dl><p className="notice">Instalado, Mantenimiento y Retirado son estados administrativos. Una recepción pasada no confirma conexión actual.</p>{hasGatewayPosition(g)?<CattleMap gateways={[g]} height="small"/>:<Empty title="Sin ubicación registrada" description="El registro se conserva y puede completarse mediante Editar."/>}{!g.archived_at&&<div className="gateway-row-actions"><button className="button secondary" onClick={()=>onEdit(g)}><Pencil size={15}/>Editar gateway</button><button className="button secondary" onClick={()=>onArchive(g)}><Archive size={15}/>Archivar gateway</button></div>}</>}
    <h3>Historial de recepciones</h3><p className="form-intro">La hora informada corresponde a los metadatos del receptor; la fecha del servidor identifica cuándo se recibió la lectura. Mover o archivar este gateway no reescribe esos registros.</p><ErrorNotice error={history.error} retry={history.reload}/>{history.loading?<Loading/>:history.data?.items.length?<><div className="table-scroll"><table><thead><tr><th>Collar / lectura</th><th>Captura</th><th>Recepción informada</th><th>Recepción del servidor</th><th>RSSI / SNR</th></tr></thead><tbody>{history.data.items.map(r=><tr key={r.telemetry_id}><td>{r.hardware_id}<small>{r.telemetry_id}</small></td><td>{date(r.observed_at)}</td><td>{date(r.reception_at)}</td><td>{date(r.server_received_at)}</td><td>{r.rssi_dbm==null?'Sin RSSI':`${r.rssi_dbm} dBm`}<small>{r.snr_db==null?'Sin SNR':`${r.snr_db} dB`}</small></td></tr>)}</tbody></table></div><Pagination offset={offset} limit={50} total={history.data.total} count={history.data.items.length} onChange={setOffset}/></>:<Empty title="Sin recepciones registradas" description="Registrar el gateway no genera lecturas ni demuestra conectividad."/>}
  </div></Modal>;
}
