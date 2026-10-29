import { useEffect, useMemo, useReducer, useRef, useState, type FormEvent } from 'react';
import { LocateFixed, MousePointer2, Plus, Trash2, Undo2, Upload } from 'lucide-react';
import type { Geofence, Sector } from './types';
import { write } from './api';
import { ErrorNotice, Modal, Submit } from './ui';
import { CattleMap, type CollarLocation, type Point } from './Map';
import { draftReducer, importVertices, polygonFromVertices, position, vertex, type Vertex } from './geofenceDraft';

export function GeofenceForm({ fence, sectors, existing, collars, onClose, onSaved }: { fence?: Geofence; sectors: Sector[]; existing: Geofence[]; collars: CollarLocation[]; onClose: () => void; onSaved: () => void }) {
  const [name,setName] = useState(fence?.name ?? '');
  const [sectorIds,setSectorIds] = useState<string[]>(fence?.sector_ids ?? (fence ? [fence.sector_id] : []));
  const [primary,setPrimary] = useState(fence?.sector_id ?? '');
  const [draft,dispatch] = useReducer(draftReducer, undefined, () => ({ vertices: fence?.geometry.coordinates[0].slice(0,-1).map(([lon,lat]) => vertex(lat,lon)) ?? [], selected: null, history: [] }));
  const [drawing,setDrawing] = useState(false), [busy,setBusy] = useState(false), [error,setError] = useState('');
  const [focusPoints,setFocusPoints] = useState<Point[]>(fence?.geometry.coordinates[0].map(([lon,lat]) => [lat,lon]) ?? []);
  const [fitRequest,setFitRequest] = useState(0), [raw,setRaw] = useState(''), [confirmed,setConfirmed] = useState(false);
  const [latitude,setLatitude] = useState(''), [longitude,setLongitude] = useState('');
  const [pending,setPending] = useState<{ message: string; label: string; run: () => void } | null>(null);
  const signature = JSON.stringify({ name, sectorIds, primary, vertices: draft.vertices });
  const initial = useRef(signature); const dirty = signature !== initial.current;
  useEffect(() => { setConfirmed(false); },[signature]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload',warn); return () => window.removeEventListener('beforeunload',warn);
  },[dirty]);
  const geometry = useMemo(() => { try { return { value: polygonFromVertices(draft.vertices), error: '' }; } catch(problem) { return { value: null, error: (problem as Error).message }; } },[draft.vertices]);
  const mapVertices = draft.vertices.flatMap((v,index) => { const point=position(v); return point ? [{ id:v.id, point, label:index+1 }] : []; });
  function close() { if (busy) return; if (dirty) setPending({ message:'Hay cambios sin guardar. ¿Descartar este borrador y cerrar? La geocerca guardada se conservará.', label:'Descartar cambios', run:onClose }); else onClose(); }
  function replace(vertices: Vertex[]) { dispatch({ type:'replace',vertices }); setConfirmed(false); }
  function add(point: Point) { replace([...draft.vertices,vertex(...point)]); setFocusPoints([]); }
  function select(id: string) { dispatch({ type:'select',id }); }
  function addCoordinates(centerOnly=false) {
    const point=position({ id:'input',latitude,longitude });
    if (!point) { setError('Ingresa latitud y longitud WGS84 válidas.'); return; }
    if (centerOnly) { setFocusPoints([point]); setFitRequest(v=>v+1); } else { add(point); setLatitude('');setLongitude(''); }
    setError('');
  }
  function load(text: string) {
    try {
      const vertices=importVertices(JSON.parse(text));
      const apply=() => { replace(vertices); setDrawing(false); setFocusPoints(vertices.map(v=>position(v)!));setFitRequest(v=>v+1);setError(''); };
      if (draft.vertices.length) setPending({ message:'Importar reemplazará todos los puntos del borrador. La versión guardada se conservará.',label:'Reemplazar borrador',run:apply }); else apply();
    } catch(problem) { setError((problem as Error).message); }
  }
  function remove(v: Vertex, index: number) { setPending({ message:`¿Eliminar solo el punto ${index+1} (${v.latitude}, ${v.longitude})? Los demás puntos se conservarán.`,label:`Eliminar punto ${index+1}`,run:()=>replace(draft.vertices.filter(p=>p.id!==v.id)) }); }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!geometry.value || !sectorIds.length || !confirmed) return;
    setBusy(true);setError('');
    try { await write('/geofences',{ name,sector_ids:sectorIds,sector_id:primary || sectorIds[0],geofence_key:fence?.geofence_key ?? null,geometry:geometry.value,expected_version:fence?.version ?? 0,confirm_impact:confirmed });onSaved(); }
    catch(problem) { setError((problem as Error).message); } finally { setBusy(false); }
  }
  return <><Modal title={fence ? `Editar ${fence.name} · nueva versión` : 'Nueva geocerca'} onClose={close} wide><form className="form-body" onSubmit={submit}>
    <div className="form-grid"><label>Nombre de la geocerca<input value={name} required maxLength={100} onChange={e=>setName(e.target.value)} /></label><label>Sector principal de pastoreo<select required value={primary} onChange={e=>setPrimary(e.target.value)}><option value="">Selecciona un sector asociado</option>{sectors.filter(s=>sectorIds.includes(s.id)).map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label></div>
    <fieldset className="geofence-sectors"><legend>Sectores asociados</legend>{sectors.map(s=><label className="checkbox-field" key={s.id}><input type="checkbox" checked={sectorIds.includes(s.id)} onChange={e=>{ const next=e.target.checked ? [...sectorIds,s.id] : sectorIds.filter(id=>id!==s.id);setSectorIds(next);if (!next.includes(primary)) setPrimary(next[0] ?? '');setConfirmed(false); }} />{s.name}</label>)}<p className="form-intro">Puedes asociar varios sectores. El sector principal se utiliza al asignar pastoreo. Cada animal se evalúa contra su geocerca asignada, incluso si otras zonas se superponen.</p></fieldset>
    <div className="editor-instructions"><p>Añade cuatro o más puntos en orden. Selecciona un marcador o una fila para editarlo. Arrastra el marcador para mover solo ese punto.</p><span className="neutral-tag">{draft.vertices.length} vértices</span></div>
    <div className="geofence-drawing-toolbar"><button type="button" className={`button ${drawing?'primary':'secondary'} small`} aria-pressed={drawing} onClick={()=>setDrawing(v=>!v)}><MousePointer2 size={15}/>{drawing?'Pausar dibujo':'Activar dibujo'}</button><button type="button" className="button secondary small" disabled={!draft.history.length} onClick={()=>{dispatch({type:'undo'});setConfirmed(false);}}><Undo2 size={15}/>Deshacer última edición</button><button type="button" className="button secondary small" disabled={!draft.vertices.length} onClick={()=>setPending({ message:`¿Limpiar los ${draft.vertices.length} puntos del borrador? La geocerca guardada y su historial se conservarán.`,label:'Limpiar borrador',run:()=>{replace([]);setDrawing(false);} })}><Trash2 size={15}/>Limpiar borrador</button></div>
    <CattleMap geofences={existing.filter(f=>f.geofence_key!==fence?.geofence_key && (!sectorIds.length || f.sector_ids.some(id=>sectorIds.includes(id))))} collars={collars} drawPoints={mapVertices.length===draft.vertices.length ? mapVertices.map(v=>v.point) : []} drawVertices={mapVertices} selectedVertex={draft.selected} onVertexSelect={select} onVertexDragStart={()=>dispatch({type:'checkpoint'})} onVertexMove={(id,point)=>{ dispatch({type:'edit',id,latitude:String(point[0]),longitude:String(point[1]),record:false});setConfirmed(false); }} focusPoints={focusPoints} fitRequest={fitRequest} onPoint={drawing?add:undefined} height="editor" />
    <p role="status" className="form-intro">{drawing?'Dibujo activo: un clic en el terreno agrega un punto.':'Dibujo pausado: puedes mover puntos y explorar el mapa.'}</p>
    <div className="coordinate-entry"><label>Latitud para nuevo punto<input type="number" step="any" min="-90" max="90" value={latitude} onChange={e=>setLatitude(e.target.value)} /></label><label>Longitud para nuevo punto<input type="number" step="any" min="-180" max="180" value={longitude} onChange={e=>setLongitude(e.target.value)} /></label><button type="button" className="button secondary" onClick={()=>addCoordinates()}><Plus size={16}/>Añadir vértice</button><button type="button" className="button secondary" onClick={()=>addCoordinates(true)}><LocateFixed size={16}/>Centrar mapa</button></div>
    <h3>Puntos de la geocerca</h3><div className="v3-vertices vertex-list">{draft.vertices.map((v,index)=><div id={`vertex-row-${v.id}`} key={v.id} className={v.id===draft.selected?'vertex-selected':''} onFocus={()=>select(v.id)}><button type="button" className="vertex-select" aria-label={`Seleccionar punto ${index+1}`} aria-pressed={v.id===draft.selected} onClick={()=>{select(v.id);const point=position(v);if(point){setFocusPoints([point]);setFitRequest(n=>n+1);}}}>{index+1}</button><label>Latitud del punto {index+1}<input type="number" step="any" min="-90" max="90" value={v.latitude} onChange={e=>{dispatch({type:'edit',id:v.id,latitude:e.target.value,longitude:v.longitude});setConfirmed(false);}} /></label><label>Longitud del punto {index+1}<input type="number" step="any" min="-180" max="180" value={v.longitude} onChange={e=>{dispatch({type:'edit',id:v.id,latitude:v.latitude,longitude:e.target.value});setConfirmed(false);}} /></label><button type="button" className="button secondary small" aria-label={`Eliminar punto ${index+1}`} onClick={()=>remove(v,index)}>Eliminar punto</button></div>)}</div>
    {geometry.error && <p className="notice notice-warning" role="status">{geometry.error}</p>}
    <details className="import-details"><summary><Upload size={16}/>Importar GeoJSON Polygon</summary><label>Archivo GeoJSON<input type="file" accept=".json,.geojson,application/json" onChange={async e=>{const file=e.target.files?.[0];if(!file)return;if(file.size>2000000){setError('El archivo excede 2 MB.');return;}load(await file.text());}} /></label><label>Pegar GeoJSON<textarea value={raw} onChange={e=>setRaw(e.target.value)} rows={4}/></label><button type="button" className="button secondary small" disabled={!raw} onClick={()=>load(raw)}>Aplicar geometría</button></details>
    <div className="notice notice-warning">{fence?`Se creará la versión ${fence.version+1} de esta geocerca. Su versión anterior se conservará.`:'Se creará una geocerca independiente. Las demás zonas del sector se conservarán.'}</div>
    <label className="checkbox-field"><input type="checkbox" required checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>Revisé la zona y confirmo el impacto sobre los animales asignados.</label><ErrorNotice error={error}/><div className="form-actions"><button className="button secondary" type="button" disabled={busy} onClick={close}>Cancelar</button><Submit busy={busy} disabled={!geometry.value || !sectorIds.length || !primary || !confirmed}>Guardar versión</Submit></div>
  </form></Modal>{pending && <Modal title="Confirmar acción sobre el borrador" onClose={()=>setPending(null)}><div className="form-body"><p>{pending.message}</p><div className="form-actions"><button type="button" autoFocus className="button secondary" onClick={()=>setPending(null)}>Cancelar</button><button type="button" className="button primary" onClick={()=>{const action=pending.run;setPending(null);action();}}>{pending.label}</button></div></div></Modal>}</>;
}
