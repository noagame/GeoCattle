import { useEffect, useMemo, useState } from 'react';
import L from 'leaflet';
import { CircleMarker, MapContainer, Polygon as MapPolygon, Polyline, Popup, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { Layers, LocateFixed, MapPin } from 'lucide-react';
import type { Animal, Geofence, Telemetry } from './types';
import { age, date } from './api';
import { Badge } from './ui';
import type { Gateway } from './v3types';

export type Point = [number, number]; // Leaflet [latitude, longitude]
const statusColors = { normal: '#2c8d65', warning: '#bc821f', critical: '#c1534f', unknown: '#7a8580' };
function validPosition(t: Telemetry | null): t is Telemetry & { latitude: number; longitude: number } {
  return !!t?.gnss_valid && t.latitude != null && t.longitude != null && Number.isFinite(t.latitude) && Number.isFinite(t.longitude);
}
function OfflineGrid() {
  const map = useMap();
  useEffect(() => {
    class LocalGrid extends L.GridLayer {
      createTile(coords: L.Coords) {
      const tile = document.createElement('div');
      tile.className = 'offline-map-tile';
      const center = map.unproject(L.point(coords.x * 256 + 128, coords.y * 256 + 128), coords.z);
      const label = document.createElement('span');
      label.textContent = `${center.lat.toFixed(3)}°, ${center.lng.toFixed(3)}°`;
      tile.appendChild(label);
        return tile;
      }
    }
    const grid = new LocalGrid({ tileSize: 256, className: 'offline-grid', attribution: 'Cuadrícula local · WGS84' });
    grid.addTo(map);
    return () => { grid.remove(); };
  }, [map]);
  return null;
}
function Fit({ points }: { points: Point[] }) {
  const map = useMap();
  const signature = points.map(point => point.join(',')).join('|');
  useEffect(() => {
    if (!points.length) return;
    const bounds = L.latLngBounds(points);
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16, animate: false });
    // Only geometry changes should recenter; a telemetry refresh at the same position should preserve exploration.
  }, [map, signature]);
  return null;
}
function Drawing({ onPoint }: { onPoint?: (point: Point) => void }) {
  useMapEvents({ click: event => onPoint?.([event.latlng.lat, event.latlng.lng]) });
  return null;
}
function Recenter({ points }: { points: Point[] }) {
  const map = useMap();
  return <button type="button" className="map-button" title="Encuadrar geometrías y posiciones" aria-label="Encuadrar geometrías y posiciones" disabled={!points.length} onClick={() => map.fitBounds(L.latLngBounds(points), { padding: [50, 50], maxZoom: 16 })}><LocateFixed size={18} /></button>;
}
export function CattleMap({ animals = [], geofences = [], gateways = [], history = [], onAnimal, drawPoints = [], onPoint, height = 'main', externalTiles: defaultExternal = false }: {
  animals?: Animal[]; geofences?: Geofence[]; gateways?: Gateway[]; history?: Telemetry[]; onAnimal?: (animal: Animal) => void;
  drawPoints?: Point[]; onPoint?: (point: Point) => void; height?: 'main' | 'small' | 'editor'; externalTiles?: boolean;
}) {
  const [external, setExternal] = useState(defaultExternal);
  const [tileError, setTileError] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const positioned = animals.filter(animal => validPosition(animal.last_position));
  const bounds = useMemo<Point[]>(() => {
    const points: Point[] = [];
    geofences.forEach(fence => fence.geometry.coordinates.forEach(ring => ring.forEach(c => points.push([c[1], c[0]]))));
    positioned.forEach(animal => { if (validPosition(animal.last_position)) points.push([animal.last_position.latitude, animal.last_position.longitude]); });
    gateways.filter(g => g.latitude != null && g.longitude != null).forEach(g => points.push([g.latitude!, g.longitude!]));
    history.filter(validPosition).forEach(t => points.push([t.latitude, t.longitude]));
    return points;
  }, [geofences, animals, gateways, history]);
  const tracks = useMemo(() => {
    const segments: Point[][] = []; let current: Point[] = [];
    [...history].sort((a, b) => a.observed_at.localeCompare(b.observed_at)).forEach(t => {
      if (validPosition(t)) current.push([t.latitude, t.longitude]);
      else if (current.length) { segments.push(current); current = []; }
    });
    if (current.length) segments.push(current);
    return segments;
  }, [history]);
  return <div className={`map-wrapper map-${height}`}>
    <MapContainer center={[-39, -72.5]} zoom={7} scrollWheelZoom className="cattle-map" aria-label={onPoint ? 'Editor de geocerca, pulse el mapa para añadir vértices' : 'Mapa de animales y geocercas'}>
      <OfflineGrid />
      {external && !tileError && <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' eventHandlers={{ tileerror: () => { setTileError(true); setExternal(false); } }} />}
      <Fit points={bounds} />
      <Drawing onPoint={onPoint} />
      {geofences.map(fence => <MapPolygon key={`${fence.id}-${fence.version}`} positions={fence.geometry.coordinates.map(ring => ring.map(c => [c[1], c[0]] as Point))} pathOptions={{ color: fence.active ? '#55937a' : '#8e9e92', weight: 2, fillColor: '#9dc4a0', fillOpacity: fence.active ? .22 : .07, dashArray: fence.active ? undefined : '6 4' }}><Tooltip sticky>{fence.name} · v{fence.version}{!fence.active && ' · histórica'}</Tooltip></MapPolygon>)}
      {gateways.filter(g => g.latitude != null && g.longitude != null).map(g => <CircleMarker key={`gateway-${g.id}`} center={[g.latitude!, g.longitude!]} radius={10} pathOptions={{ color: '#fff', weight: 2, fillColor: '#406aaa', fillOpacity: .95 }}><Tooltip>Gateway · {g.name}</Tooltip><Popup><div className="map-popup"><strong>Gateway · {g.name}</strong><span>{g.gateway_eui}</span><span>{g.status ?? 'Sin estado'}</span></div></Popup></CircleMarker>)}
      {tracks.map((track, index) => <Polyline key={index} positions={track} pathOptions={{ color: '#276e68', weight: 3, opacity: .85 }} />)}
      {history.filter(validPosition).length > 0 && (() => { const fixes = history.filter(validPosition); const first = fixes[0]; const last = fixes[fixes.length - 1]; return <><CircleMarker center={[first.latitude, first.longitude]} radius={5} pathOptions={{ color: '#fff', fillColor: '#276e68', fillOpacity: 1 }}><Tooltip>Inicio · {date(first.observed_at)}</Tooltip></CircleMarker><CircleMarker center={[last.latitude, last.longitude]} radius={5} pathOptions={{ color: '#fff', fillColor: '#c68a3c', fillOpacity: 1 }}><Tooltip>Fin · {date(last.observed_at)}</Tooltip></CircleMarker></>; })()}
      {positioned.map(animal => {
        const t = animal.last_position!;
        const stale = animal.position_status !== 'fresh';
        return <CircleMarker key={animal.id} center={[t.latitude!, t.longitude!]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: stale ? '#77887c' : statusColors[animal.status], fillOpacity: stale ? .65 : 1, dashArray: stale ? '3 2' : undefined }}>
          <Tooltip direction="top">{animal.name || animal.diio} · {age(animal.position_age_seconds)}{stale && ' · posición vencida'}</Tooltip>
          <Popup><div className="map-popup"><strong>{animal.name || animal.diio}</strong><span>DIIO {animal.diio}</span><Badge status={animal.status} /><span>{age(animal.position_age_seconds)} · {animal.position_status === 'fresh' ? 'Posición vigente' : 'Posición vencida'}</span><span>Origen: {t.source === 'sim' ? 'simulado' : t.source === 'academic' ? 'nodo académico' : 'LoRaWAN'}</span>{onAnimal && <button onClick={() => onAnimal(animal)}>Ver ficha del animal →</button>}</div></Popup>
        </CircleMarker>;
      })}
      {drawPoints.length >= 3 && <MapPolygon positions={drawPoints} pathOptions={{ color: '#236b52', fillColor: '#68b28e', fillOpacity: .25, weight: 2, dashArray: '5 4' }} />}
      {drawPoints.length === 2 && <Polyline positions={drawPoints} pathOptions={{ color: '#236b52', weight: 2, dashArray: '5 4' }} />}
      {drawPoints.map((point, index) => <CircleMarker key={index} center={point} radius={5} pathOptions={{ color: '#fff', fillColor: '#236b52', fillOpacity: 1, weight: 2 }}><Tooltip permanent direction="top">{index + 1}</Tooltip></CircleMarker>)}
      <div className="map-controls leaflet-control"><button className={`map-button ${external ? 'active' : ''}`} type="button" aria-label="Cambiar base cartográfica" title="Cambiar base cartográfica" onClick={() => { setTileError(false); setExternal(!external); }}><Layers size={18} /></button><Recenter points={bounds} /></div>
    </MapContainer>
    <div className="map-caption"><span><span className={`connection-dot ${external ? 'green' : ''}`} />{external ? 'OpenStreetMap · necesita Internet' : 'Cuadrícula local · disponible sin Internet'}</span><button onClick={() => setLegendOpen(!legendOpen)} className="text-button">{legendOpen ? 'Ocultar leyenda' : 'Leyenda'}</button></div>
    {legendOpen && <div className="map-legend"><Badge status="normal" /><Badge status="warning" /><Badge status="critical" /><Badge status="unknown">Posición vencida</Badge><span className="legend-line">Geocerca activa</span></div>}
    {tileError && <div className="map-note">La cartografía externa no responde. Las geometrías locales siguen disponibles.</div>}
    {!bounds.length && !drawPoints.length && <div className="map-empty-hint"><MapPin size={18} /><span>{onPoint ? 'Vista regional de referencia. Acerque el mapa al predio y marque sus vértices, o importe GeoJSON.' : 'Aún no hay posiciones ni geocercas. Vista regional de referencia.'}</span></div>}
  </div>;
}
