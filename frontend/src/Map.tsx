import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { CircleMarker, MapContainer, Polygon as MapPolygon, Polyline, Popup, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { Layers, LocateFixed, MapPin, RotateCw } from 'lucide-react';
import type { Animal, Geofence, Telemetry } from './types';
import { age, date } from './api';
import { Badge } from './ui';
import type { Gateway } from './v3types';

export type CollarLocation = { hardware_id: string; latitude: number; longitude: number; observed_at: string; stale: boolean };
export type Point = [number, number]; // Leaflet [latitude, longitude]; GeoJSON uses the reverse order.
const statusColors = { normal: '#2c8d65', warning: '#bc821f', critical: '#c1534f', unknown: '#7a8580' };
const basePreference = 'geocattle.map.base';
function validPosition(t: Telemetry | null): t is Telemetry & { latitude: number; longitude: number } {
  return !!t?.gnss_valid && t.latitude != null && t.longitude != null && Number.isFinite(t.latitude) && Number.isFinite(t.longitude);
}
function savedBase(fallback: boolean) {
  try { const saved = localStorage.getItem(basePreference); return saved === 'osm' ? true : saved === 'local' ? false : fallback; }
  catch { return fallback; }
}
function OfflineGrid() {
  const map = useMap();
  useEffect(() => {
    class LocalGrid extends L.GridLayer {
      createTile(coords: L.Coords) {
        const tile = document.createElement('div'); tile.className = 'offline-map-tile';
        const center = map.unproject(L.point(coords.x * 256 + 128, coords.y * 256 + 128), coords.z);
        const label = document.createElement('span'); label.textContent = `${center.lat.toFixed(3)}°, ${center.lng.toFixed(3)}°`;
        tile.appendChild(label); return tile;
      }
    }
    const grid = new LocalGrid({ tileSize: 256, zIndex: 0, attribution: 'Cuadrícula local · WGS84' });
    grid.addTo(map); return () => { grid.remove(); };
  }, [map]);
  return null;
}
function MapSize() {
  const map = useMap();
  useEffect(() => {
    let frame = 0;
    const resize = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => map.invalidateSize({ pan: false, debounceMoveend: true })); };
    const observer = new ResizeObserver(resize); observer.observe(map.getContainer()); resize();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [map]);
  return null;
}
function Fit({ points, requestedPoints, request, drawing }: { points: Point[]; requestedPoints: Point[]; request: number; drawing: boolean }) {
  const map = useMap(); const fitted = useRef(false); const lastRequest = useRef(request);
  const signature = points.map(p => p.join(',')).join('|');
  const requestedSignature = requestedPoints.map(p => p.join(',')).join('|');
  useEffect(() => {
    const explicit = lastRequest.current !== request; lastRequest.current = request;
    const target = explicit ? requestedPoints : points;
    if (!target.length || (!explicit && (fitted.current || drawing))) return;
    map.invalidateSize({ pan: false });
    map.fitBounds(L.latLngBounds(target), { padding: [35, 35], maxZoom: 17, animate: false }); fitted.current = true;
    // New telemetry must not move the viewport while the user draws or explores.
  }, [map, signature, requestedSignature, request, drawing]);
  return null;
}
function Drawing({ onPoint }: { onPoint?: (point: Point) => void }) {
  useMapEvents({ click: event => {
    const target = event.originalEvent.target;
    if (target instanceof Element && target.closest('.leaflet-control, .map-controls, .leaflet-popup')) return;
    onPoint?.([event.latlng.lat, event.latlng.lng]);
  } });
  return null;
}
function Recenter({ points }: { points: Point[] }) {
  const map = useMap();
  return <button type="button" className="map-button" title="Encuadrar geometrías y posiciones" aria-label="Encuadrar geometrías y posiciones" disabled={!points.length} onClick={() => { map.invalidateSize({ pan: false }); map.fitBounds(L.latLngBounds(points), { padding: [35, 35], maxZoom: 17 }); }}><LocateFixed size={18} /></button>;
}
export function CattleMap({ animals = [], geofences = [], gateways = [], history = [], collars = [], onAnimal, drawPoints = [], drawHoles = [], onPoint, height = 'main', externalTiles = true, focusPoints = [], fitRequest = 0 }: {
  collars?: CollarLocation[]; animals?: Animal[]; geofences?: Geofence[]; gateways?: Gateway[]; history?: Telemetry[]; onAnimal?: (animal: Animal) => void;
  drawPoints?: Point[]; drawHoles?: Point[][]; onPoint?: (point: Point) => void; height?: 'main' | 'small' | 'editor'; externalTiles?: boolean;
  focusPoints?: Point[]; fitRequest?: number;
}) {
  const [external, setExternal] = useState(() => savedBase(externalTiles));
  const [tileError, setTileError] = useState(false); const [tileBusy, setTileBusy] = useState(false); const [tileAttempt, setTileAttempt] = useState(0);
  const [legendOpen, setLegendOpen] = useState(false);
  function selectBase(value: boolean) {
    setExternal(value); setTileError(false); setTileBusy(false);
    try { localStorage.setItem(basePreference, value ? 'osm' : 'local'); } catch { /* Storage can be unavailable in private mode. */ }
  }
  const positioned = animals.filter(animal => validPosition(animal.last_position));
  const bounds = useMemo<Point[]>(() => {
    const points: Point[] = [];
    geofences.forEach(f => f.geometry.coordinates.forEach(r => r.forEach(c => points.push([c[1], c[0]]))));
    positioned.forEach(a => { if (validPosition(a.last_position)) points.push([a.last_position.latitude, a.last_position.longitude]); });
    gateways.filter(g => g.latitude != null && g.longitude != null).forEach(g => points.push([g.latitude!, g.longitude!]));
    collars.forEach(c => points.push([c.latitude, c.longitude]));
    history.filter(validPosition).forEach(t => points.push([t.latitude, t.longitude]));
    return points;
  }, [geofences, animals, gateways, history, collars]);
  const orderedHistory = useMemo(() => [...history].sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at)), [history]);
  const fixes = orderedHistory.filter(validPosition);
  const tracks = useMemo(() => {
    const segments: Point[][] = []; let current: Point[] = []; let previous: Telemetry | null = null;
    orderedHistory.forEach(t => {
      const gap = previous && (previous.device_id !== t.device_id || previous.session_id !== t.session_id || Date.parse(t.observed_at) - Date.parse(previous.observed_at) > Math.max(120000, Number(t.quality.period_ms ?? 40000) * 3));
      if ((!validPosition(t) || gap) && current.length) { segments.push(current); current = []; }
      if (validPosition(t)) current.push([t.latitude, t.longitude]);
      previous = t;
    });
    if (current.length) segments.push(current); return segments;
  }, [orderedHistory]);
  const initialPoints = focusPoints.length ? focusPoints : bounds;
  const requestedPoints = focusPoints.length ? focusPoints : drawPoints.length ? drawPoints : bounds;
  return <div className={`map-wrapper map-${height}`}>
    <div className="map-base-toolbar" role="group" aria-label="Base del mapa"><Layers size={16} /><button type="button" aria-pressed={external} onClick={() => selectBase(true)}>OpenStreetMap</button><button type="button" aria-pressed={!external} onClick={() => selectBase(false)}>Cuadrícula local</button><span role="status">{external ? tileBusy ? 'Cargando mapa…' : tileError ? 'Carga parcial' : 'Cartografía en línea' : 'Sin conexión necesaria'}</span></div>
    <MapContainer center={[-39, -72.5]} zoom={7} maxZoom={20} scrollWheelZoom className={`cattle-map ${onPoint ? 'map-drawing' : ''}`} aria-label={height === 'editor' ? 'Editor de geocerca' : 'Mapa de animales y geocercas'}>
      <OfflineGrid />
      {external && <TileLayer key={tileAttempt} url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" zIndex={1} maxNativeZoom={19} maxZoom={20} referrerPolicy="strict-origin-when-cross-origin" attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' eventHandlers={{ loading: () => setTileBusy(true), load: () => setTileBusy(false), tileerror: () => setTileError(true) }} />}
      <MapSize /><Fit points={initialPoints} requestedPoints={requestedPoints} request={fitRequest} drawing={!!onPoint} /><Drawing onPoint={onPoint} />
      {geofences.map(fence => <MapPolygon key={`${fence.id}-${fence.version}`} positions={fence.geometry.coordinates.map(r => r.map(c => [c[1], c[0]] as Point))} pathOptions={{ color: fence.active ? '#55937a' : '#8e9e92', weight: 2, fillColor: '#9dc4a0', fillOpacity: fence.active ? .16 : .07, dashArray: fence.active ? undefined : '6 4' }}><Tooltip sticky>{fence.name} · v{fence.version}{!fence.active && ' · histórica'}</Tooltip></MapPolygon>)}
      {gateways.filter(g => g.latitude != null && g.longitude != null).map(g => <CircleMarker key={`gateway-${g.id}`} center={[g.latitude!, g.longitude!]} radius={10} pathOptions={{ color: '#fff', weight: 2, fillColor: '#406aaa', fillOpacity: .95 }}><Tooltip>Gateway · {g.name}</Tooltip><Popup><div className="map-popup"><strong>Gateway · {g.name}</strong><span>{g.gateway_eui}</span><span>{g.status ?? 'Sin estado'}</span></div></Popup></CircleMarker>)}
      {tracks.map((track, i) => <Polyline key={i} positions={track} pathOptions={{ color: '#276e68', weight: 3, opacity: .85 }} />)}
      {fixes.length > 0 && <><CircleMarker center={[fixes[0].latitude, fixes[0].longitude]} radius={5} pathOptions={{ color: '#fff', fillColor: '#276e68', fillOpacity: 1 }}><Tooltip>Inicio · {date(fixes[0].observed_at)}</Tooltip></CircleMarker><CircleMarker center={[fixes[fixes.length - 1].latitude, fixes[fixes.length - 1].longitude]} radius={5} pathOptions={{ color: '#fff', fillColor: '#c68a3c', fillOpacity: 1 }}><Tooltip>Fin · {date(fixes[fixes.length - 1].observed_at)}</Tooltip></CircleMarker></>}
      {collars.map(c => <CircleMarker key={`collar-${c.hardware_id}`} center={[c.latitude, c.longitude]} radius={9} pathOptions={{ color: '#fff', weight: 3, fillColor: c.stale ? '#77887c' : '#276e68', fillOpacity: .9, dashArray: c.stale ? '3 2' : undefined }}><Tooltip>{c.hardware_id} · {c.stale ? 'Última posición histórica' : 'Posición reciente'}</Tooltip><Popup><div className="map-popup"><strong>Collar {c.hardware_id}</strong><span>{date(c.observed_at)}</span><span>{c.latitude.toFixed(6)}, {c.longitude.toFixed(6)}</span><span>{c.stale ? 'Posición histórica; no indica ubicación actual.' : 'Última posición válida recibida.'}</span></div></Popup></CircleMarker>)}
      {positioned.map(animal => {
        const t = animal.last_position!; const stale = animal.position_status !== 'fresh';
        return <CircleMarker key={animal.id} center={[t.latitude!, t.longitude!]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: stale ? '#77887c' : statusColors[animal.status], fillOpacity: stale ? .65 : 1, dashArray: stale ? '3 2' : undefined }}>
          <Tooltip direction="top">{animal.name || animal.diio} · {age(animal.position_age_seconds)}{stale && ' · posición vencida'}</Tooltip>
          <Popup><div className="map-popup"><strong>{animal.name || animal.diio}</strong><span>DIIO {animal.diio}</span><Badge status={animal.status} /><span>{age(animal.position_age_seconds)} · {animal.position_status === 'fresh' ? 'Posición vigente' : 'Posición vencida'}</span><span>Origen: {t.source === 'sim' ? 'simulado' : t.source === 'academic' ? 'nodo académico' : 'LoRaWAN'}</span>{onAnimal && <button onClick={() => onAnimal(animal)}>Ver ficha del animal →</button>}</div></Popup>
        </CircleMarker>;
      })}
      {drawPoints.length >= 3 && <MapPolygon positions={[drawPoints, ...drawHoles]} pathOptions={{ color: '#236b52', fillColor: '#68b28e', fillOpacity: .25, weight: 2, dashArray: '5 4' }} />}
      {drawPoints.length === 2 && <Polyline positions={drawPoints} pathOptions={{ color: '#236b52', weight: 2, dashArray: '5 4' }} />}
      {drawPoints.map((p, i) => <CircleMarker key={i} center={p} radius={5} pathOptions={{ color: '#fff', fillColor: '#236b52', fillOpacity: 1, weight: 2 }}><Tooltip permanent direction="top">{i + 1}</Tooltip></CircleMarker>)}
      <div className="map-controls leaflet-control"><Recenter points={drawPoints.length ? drawPoints : initialPoints} /></div>
    </MapContainer>
    <div className="map-caption"><span><span className={`connection-dot ${external && !tileError ? 'green' : ''}`} />{external ? 'OpenStreetMap · requiere Internet' : 'Cuadrícula local · disponible sin Internet'}</span><button type="button" onClick={() => setLegendOpen(!legendOpen)} className="text-button">{legendOpen ? 'Ocultar leyenda' : 'Leyenda'}</button></div>
    {legendOpen && <div className="map-legend"><Badge status="normal" /><Badge status="warning" /><Badge status="critical" /><Badge status="unknown">Posición vencida</Badge><span className="legend-line">Geocerca activa</span></div>}
    {external && tileError && <div className="map-note" role="status">Algunas teselas no cargaron. Puedes reintentar o usar la cuadrícula sin perder el dibujo.<button className="text-button" type="button" onClick={() => { setTileError(false); setTileAttempt(v => v + 1); }}><RotateCw size={13} />Reintentar mapa</button></div>}
    {!bounds.length && !drawPoints.length && !focusPoints.length && <div className="map-empty-hint"><MapPin size={18} /><span>{height === 'editor' ? 'Acerca el mapa a tu predio o centra unas coordenadas antes de dibujar.' : 'Sin posiciones ni geocercas guardadas. Vista regional de referencia.'}</span></div>}
  </div>;
}
