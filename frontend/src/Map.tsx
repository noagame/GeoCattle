import { useEffect, useId, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { CircleMarker, Marker, MapContainer, Pane, Polygon as MapPolygon, Polyline, Popup, ScaleControl, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { ChevronDown, Compass, Fence, Layers, LocateFixed, MapPin, Radio, RotateCw } from 'lucide-react';
import type { Animal, Geofence, Telemetry } from './types';
import { age, date } from './api';
import { Badge } from './ui';
import type { Gateway } from './v3types';
import { gatewayStatus, hasGatewayPosition } from './gatewayCoordinates';

export type CollarLocation = { hardware_id: string; latitude: number; longitude: number; observed_at: string; stale: boolean };
export type Point = [number, number]; // Leaflet [latitud, longitud]; GeoJSON usa el orden inverso.
const statusColors = { normal: '#2c8d65', warning: '#bc821f', critical: '#c1534f', unknown: '#7a8580' };
const staleColor = '#77887c';
const allLayers = { fences: true, gateways: true };
type MapLayer = keyof typeof allLayers;
type MapSelection = { layer: MapLayer; id: string };
type MapLocationGroup = { layer: MapLayer; items: { id: string; label: string; focus: () => void }[] };
const locationLabels = {
  fences: { label: 'Geocercas', icon: Fence, all: 'Todas las geocercas', empty: 'Sin geocercas', hide: 'Ocultar geocercas', hidden: 'Geocercas ocultas' },
  gateways: { label: 'Gateways', icon: Radio, all: 'Todos los gateways', empty: 'Sin ubicación', hide: 'Ocultar gateways', hidden: 'Gateways ocultos' },
};
const locationOrder = new Intl.Collator('es', { numeric: true, sensitivity: 'base' });
type MapFence = { fence: Geofence; rings: Point[][]; bounds: L.LatLngBounds };
const basePreference = 'geocattle.map.base';
type SatelliteBounds = [number, number, number, number];
type SatelliteBasemap = {
  name: string; attribution: string; bounds: SatelliteBounds; minZoom: number; maxZoom: number;
  detail?: { bounds: SatelliteBounds; minZoom: number };
};
type LocalZoomArea = { bounds: SatelliteBounds; minZoom: number; maxZoom: number };
type LocalOsm = SatelliteBasemap & { regional: LocalZoomArea; detail: LocalZoomArea & { minZoom: number } };
type MapBase = 'satellite' | 'osm-local' | 'osm';
const sameNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
function validPosition(t: Telemetry | null): t is Telemetry & { latitude: number; longitude: number } {
  return !!t?.gnss_valid && t.latitude != null && t.longitude != null && Number.isFinite(t.latitude) && Number.isFinite(t.longitude);
}
function savedBase(fallback: MapBase): MapBase {
  try {
    const saved = localStorage.getItem(basePreference);
    if (saved === 'roads') return 'satellite';
    return saved === 'osm' || saved === 'osm-local' || saved === 'satellite' ? saved : fallback;
  }
  catch { return fallback; }
}
function validSatelliteBounds(bounds: SatelliteBounds) {
  if (!Array.isArray(bounds) || bounds.length !== 4 || !bounds.every(sameNumber)) return false;
  const [south, west, north, east] = bounds;
  return -85.05 <= south && south < north && north <= 85.05 && -180 <= west && west < east && east <= 180;
}
function parseSatellite(data: SatelliteBasemap) {
  if (!data || typeof data.name !== 'string' || typeof data.attribution !== 'string' || !validSatelliteBounds(data.bounds)) return null;
  if (!Number.isInteger(data.minZoom) || !Number.isInteger(data.maxZoom) || data.minZoom < 0 || data.minZoom > data.maxZoom || data.maxZoom > 20) return null;
  const detail = data.detail;
  if (detail !== undefined && (!detail || !validSatelliteBounds(detail.bounds) || !Number.isInteger(detail.minZoom) ||
      detail.minZoom <= data.minZoom || detail.minZoom > data.maxZoom)) return null;
  if (detail && (detail.bounds[0] < data.bounds[0] || detail.bounds[1] < data.bounds[1] ||
      detail.bounds[2] > data.bounds[2] || detail.bounds[3] > data.bounds[3])) return null;
  return data;
}
function useSatellite(enabled: boolean, attempt: number) {
  const [asset, setAsset] = useState<SatelliteBasemap | null>();
  useEffect(() => {
    if (!enabled) return;
    setAsset(undefined);
    const controller = new AbortController();
    fetch('/mapa-local/satelite/manifest.json', { signal: controller.signal, cache: 'no-cache' })
      .then(async response => response.ok ? parseSatellite(await response.json()) : null)
      .then(data => { if (!controller.signal.aborted) setAsset(data); })
      .catch(() => { if (!controller.signal.aborted) setAsset(null); });
    return () => controller.abort();
  }, [enabled, attempt]);
  return asset;
}
function validZoomArea(area: LocalZoomArea | undefined, outer: SatelliteBasemap): area is LocalZoomArea {
  return !!area && validSatelliteBounds(area.bounds) && Number.isInteger(area.minZoom) && Number.isInteger(area.maxZoom) &&
    outer.minZoom <= area.minZoom && area.minZoom <= area.maxZoom && area.maxZoom <= outer.maxZoom;
}
function parseLocalOsm(data: LocalOsm | SatelliteBasemap): LocalOsm | null {
  const base = parseSatellite({ ...data, detail: undefined } as SatelliteBasemap);
  const { regional, detail } = data as Partial<LocalOsm>;
  if (!base || !validZoomArea(regional, base) || !validZoomArea(detail, base) || regional.minZoom <= base.minZoom ||
      detail.minZoom <= regional.maxZoom) return null;
  return { ...base, regional, detail };
}
function useLocalOsm(enabled: boolean, attempt: number) {
  const [asset, setAsset] = useState<LocalOsm | null>();
  useEffect(() => {
    if (!enabled) return;
    setAsset(undefined);
    const controller = new AbortController();
    fetch('/mapa-local/osm/manifest.json', { signal: controller.signal, cache: 'no-cache' })
      .then(async response => response.ok ? parseLocalOsm(await response.json()) : null)
      .then(data => { if (!controller.signal.aborted) setAsset(data); })
      .catch(() => { if (!controller.signal.aborted) setAsset(null); });
    return () => controller.abort();
  }, [enabled, attempt]);
  return asset;
}
function LocalOsmTiles({ data, onError }: { data: LocalOsm; onError: (failed: boolean) => void }) {
  const failedTiles = useRef(new Set<HTMLElement>());
  const options = {
    url: '/mapa-local/osm/{z}/{x}/{y}.png', noWrap: true, maxZoom: 20,
    eventHandlers: {
      tileerror: (event: L.TileErrorEvent) => { failedTiles.current.add(event.tile); onError(true); },
      tileunload: (event: L.TileEvent) => { if (failedTiles.current.delete(event.tile)) onError(failedTiles.current.size > 0); },
    },
  };
  const { regional, detail } = data;
  return <>
    <TileLayer {...options} bounds={leafletBounds(data.bounds)} zIndex={1} minNativeZoom={data.minZoom} maxNativeZoom={regional.minZoom - 1} />
    <TileLayer {...options} bounds={leafletBounds(regional.bounds)} zIndex={2} minZoom={regional.minZoom} minNativeZoom={regional.minZoom} maxNativeZoom={regional.maxZoom} />
    <TileLayer {...options} bounds={leafletBounds(detail.bounds)} zIndex={3} minZoom={detail.minZoom} minNativeZoom={detail.minZoom} maxNativeZoom={detail.maxZoom} />
  </>;
}
function leafletBounds([south, west, north, east]: SatelliteBounds) {
  return L.latLngBounds([south, west], [north, east]);
}
function SatelliteTiles({ data, onOutside, onError }: {
  data: SatelliteBasemap; onOutside: (outside: boolean) => void; onError: (failed: boolean) => void;
}) {
  const bounds = useMemo(() => leafletBounds(data.bounds), [data]);
  const failedTiles = useRef(new Set<HTMLElement>());
  const map = useMapEvents({ moveend: () => onOutside(!bounds.contains(map.getCenter())) });
  useEffect(() => { onOutside(!bounds.contains(map.getCenter())); }, [map, bounds, onOutside]);
  const regionalMaxZoom = data.detail ? data.detail.minZoom - 1 : data.maxZoom;
  const options = {
    url: '/mapa-local/satelite/{z}/{x}/{y}.webp', noWrap: true, maxZoom: 20,
    eventHandlers: {
      tileerror: (event: L.TileErrorEvent) => { failedTiles.current.add(event.tile); onError(true); },
      tileunload: (event: L.TileEvent) => { if (failedTiles.current.delete(event.tile)) onError(failedTiles.current.size > 0); },
    },
  };
  return <>
    <TileLayer {...options} bounds={bounds} zIndex={1} minNativeZoom={data.minZoom} maxNativeZoom={regionalMaxZoom} />
    {data.detail && <TileLayer {...options} bounds={leafletBounds(data.detail.bounds)} zIndex={2}
      minZoom={data.detail.minZoom} minNativeZoom={data.detail.minZoom} maxNativeZoom={data.maxZoom} />}
  </>;
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
function fitMap(map: L.Map, bounds: L.LatLngBounds, options?: L.FitBoundsOptions) {
  map.invalidateSize({ pan: false });
  map.fitBounds(bounds, { padding: [35, 35], maxZoom: 17, ...options });
}
function Fit({ points, requestedPoints, request, drawing }: { points: Point[]; requestedPoints: Point[]; request: number; drawing: boolean }) {
  const map = useMap(); const fitted = useRef(false); const lastRequest = useRef(request);
  const signature = points.map(p => p.join(',')).join('|');
  const requestedSignature = requestedPoints.map(p => p.join(',')).join('|');
  useEffect(() => {
    const explicit = lastRequest.current !== request; lastRequest.current = request;
    const target = explicit ? requestedPoints : points;
    if (!target.length || (!explicit && (fitted.current || drawing))) return;
    fitMap(map, L.latLngBounds(target), { animate: false });
    fitted.current = true;
    // La telemetría nueva no debe mover el viewport mientras el usuario dibuja o explora el mapa.
  }, [map, signature, requestedSignature, request, drawing]);
  return null;
}
function FenceLayers({ fences, satellite, selectedId, watchedId, drawing, onSelect }: {
  fences: MapFence[]; satellite: boolean; selectedId?: string; watchedId?: string;
  drawing: boolean; onSelect?: (fence: MapFence) => void;
}) {
  const map = useMap();
  const [zoom, setZoom] = useState(() => map.getZoom());
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) });

  const layers = fences.map(area => {
    const { fence, rings, bounds } = area;
    const selected = fence.id === selectedId;
    const watched = fence.id === watchedId;
    const color = selected ? (satellite ? '#b7f9d0' : '#15533b')
      : watched ? (satellite ? '#fff29c' : '#236b52')
      : satellite ? (fence.active ? '#ffe18d' : '#eee8d8') : (fence.active ? '#55937a' : '#8e9e92');
    const weight = selected ? 5 : watched ? 4 : 2;
    const dashArray = fence.active ? undefined : '6 4';
    const fill = { fillColor: '#9dc4a0', fillOpacity: selected ? .32 : watched ? .24 : fence.active ? .16 : .07 };
    const tooltip = <Tooltip sticky>{fence.name} · v{fence.version}{watched && ' · zona vigilada'}{!fence.active && ' · histórica'}</Tooltip>;
    const handlers = onSelect ? { click: () => onSelect(area) } : undefined;
    const key = `${fence.id}-${fence.version}`;
    const footprint = map.project(bounds.getNorthWest(), zoom).subtract(map.project(bounds.getSouthEast(), zoom));
    // El punto conserva un blanco de clic mientras un marcador de 22 px puede cubrir casi toda la geocerca.
    const small = fence.active && Math.max(Math.abs(footprint.x), Math.abs(footprint.y)) < 26;
    return {
      body: <MapPolygon key={key} positions={rings} interactive={!drawing} bubblingMouseEvents={!onSelect}
        pathOptions={{ ...fill, color, weight, dashArray, stroke: !onSelect }} eventHandlers={handlers}>
        {!drawing && tooltip}
      </MapPolygon>,
      // El contorno puede recibir clics sobre un marcador. El interior deja accesibles los marcadores.
      target: <MapPolygon key={key} positions={rings} bubblingMouseEvents={false}
        pathOptions={{ color, weight, dashArray, fill: false }} eventHandlers={handlers}>{tooltip}</MapPolygon>,
      dot: small && <CircleMarker key={key} center={bounds.getCenter()} radius={selected ? 7 : 6} bubblingMouseEvents={false}
        pathOptions={{ color, weight: selected ? 3 : 2, fillColor: '#9dc4a0', fillOpacity: .9 }} eventHandlers={handlers}>
        <Tooltip direction="top">{fence.name} · clic para acercar</Tooltip>
      </CircleMarker>,
    };
  });
  return <>{layers.map(layer => layer.body)}
    <Pane name="fence-targets" style={{ zIndex: 610 }}>
      {onSelect && layers.map(layer => layer.target)}
      {onSelect && layers.map(layer => layer.dot)}
    </Pane>
  </>;
}
function Drawing({ onPoint }: { onPoint?: (point: Point) => void }) {
  useMapEvents({ click: event => {
    const target = event.originalEvent.target;
    if (target instanceof Element && target.closest('.leaflet-control, .map-controls, .leaflet-popup, .leaflet-marker-icon')) return;
    onPoint?.([event.latlng.lat, event.latlng.lng]);
  } });
  return null;
}
function MapLegend({ groups, visible, selection, onVisibility, onFitAll, canFitAll, hasPositions }: {
  groups: MapLocationGroup[]; visible: typeof allLayers; selection: MapSelection | null;
  onVisibility: (layer: MapLayer, visible: boolean) => void; onFitAll: () => void; canFitAll: boolean; hasPositions: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();
  return <aside className="map-layer-panel" aria-label="Explorar mapa">
    <h3 className="map-legend-heading"><Compass size={17} aria-hidden="true" />Explorar mapa</h3>
    <button type="button" className="map-legend-disclosure" aria-expanded={expanded} aria-controls={contentId} onClick={() => setExpanded(value => !value)}>
      <Compass size={17} aria-hidden="true" />Explorar mapa<ChevronDown size={16} aria-hidden="true" />
    </button>
    <div id={contentId} className={`map-legend-content${expanded ? ' expanded' : ''}`}>
      <div className="map-location-fields">
        {groups.map(({ layer, items }) => {
          const { label, icon: Icon, all, empty, hide, hidden } = locationLabels[layer];
          const selected = selection?.layer === layer && items.find(item => item.id === selection.id);
          const value = !visible[layer] && items.length ? 'hidden' : selected ? selected.id : '';
          return <label key={layer} className={`map-location-field map-location-${layer}`}>
            <span className="map-location-label"><Icon size={15} aria-hidden="true" />{label}<small aria-hidden="true">{items.length}</small></span>
            <span className="map-location-input">
              <select aria-label={`${label} del mapa`} title={selected ? selected.label : undefined} value={value} disabled={!items.length} onChange={event => {
                const id = event.currentTarget.value;
                if (id === '' || id === 'hidden') onVisibility(layer, id !== 'hidden');
                else items.find(item => item.id === id)?.focus();
              }}>
                <option value="">{items.length ? all : empty}</option>
                {!!items.length && <option value="hidden">{visible[layer] ? hide : hidden}</option>}
                {[...items].sort((a, b) => locationOrder.compare(a.label, b.label)).map(item =>
                  <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
              <ChevronDown size={15} aria-hidden="true" />
            </span>
          </label>;
        })}
      </div>
      <button type="button" className="map-legend-fit" disabled={!canFitAll} onClick={onFitAll}><LocateFixed size={16} aria-hidden="true" />Ver todo</button>
      <ul className="map-legend-colors" aria-label="Colores del mapa">
        {hasPositions && [
          ['Normal', statusColors.normal],
          ['Advertencia', statusColors.warning],
          ['Crítico', statusColors.critical],
          ['Posición vencida', staleColor],
        ].map(([label, color]) => <li key={label}>
          <span className="map-legend-swatch" style={{ backgroundColor: color }} aria-hidden="true" />{label}
        </li>)}
        <li><span className="map-legend-fence-line" aria-hidden="true" />Geocerca activa</li>
      </ul>
    </div>
  </aside>;
}
function VertexMarker({ vertex, selected, onSelect, onMove, onDragStart }: { vertex: { id: string; point: Point; label: number }; selected: boolean; onSelect?: (id: string) => void; onMove?: (id: string, point: Point) => void; onDragStart?: () => void }) {
  const ref=useRef<L.Marker>(null);
  const icon=useMemo(() => L.divIcon({ className:'vertex-marker',html:`<span>${vertex.label}</span>`,iconSize:[30,30],iconAnchor:[15,15] }),[vertex.label]);
  useEffect(() => { const element=ref.current?.getElement();if(element){element.classList.toggle('selected',selected);element.title=`Punto ${vertex.label}`;element.setAttribute('aria-label',`Punto ${vertex.label}`);} },[vertex.label,icon,selected]);
  return <Marker ref={ref} position={vertex.point} draggable={!!onMove} bubblingMouseEvents={false} icon={icon} title={`Punto ${vertex.label}`} eventHandlers={{ click:event=>{L.DomEvent.stopPropagation(event.originalEvent);onSelect?.(vertex.id);},dragstart:()=>{onSelect?.(vertex.id);onDragStart?.();},drag:event=>{const p=(event.target as L.Marker).getLatLng();onMove?.(vertex.id,[p.lat,p.lng]);} }}><Tooltip>Punto {vertex.label} · arrastra para mover</Tooltip></Marker>;
}

function GatewayMarker({ gateway, onMove, onDetail, onSelect, selected=false, draft=false }: {
  gateway: Gateway; onMove?: (point: Point) => void; onDetail?: (gateway: Gateway) => void;
  onSelect?: () => void; selected?: boolean; draft?: boolean;
}) {
  const ref=useRef<L.Marker>(null);
  const icon = useMemo(() => {
    const size = draft ? 30 : 22;
    return L.divIcon({
      className: `gateway-map-marker${gateway.archived_at ? ' archived' : ''}${draft ? ' draft' : ''}`,
      html: '<span aria-hidden="true">G</span>', iconSize: [size, size], iconAnchor: [size / 2, size / 2],
    });
  }, [gateway.archived_at, draft]);
  const identity=gateway.gateway_eui ?? (gateway.node_id ? `Nodo 0${gateway.node_id}` : 'EUI no informado');
  const title=draft?'Ubicación del gateway en edición':`Gateway ${gateway.name} · ${identity}`;
  useEffect(()=>{const el=ref.current?.getElement();if(el){el.title=title;el.setAttribute('aria-label',title);el.classList.toggle('selected',selected||draft);}},[icon,title,selected,draft]);
  return <Marker ref={ref} position={[gateway.latitude!,gateway.longitude!]} icon={icon} title={title} draggable={!!onMove} bubblingMouseEvents={false} eventHandlers={{
    drag: event => { const p = (event.target as L.Marker).getLatLng(); onMove?.([p.lat, p.lng]); },
    click: event => { L.DomEvent.stopPropagation(event.originalEvent); onSelect?.(); },
  }}>
    <Tooltip permanent={draft} direction="top">{draft ? 'Ubicación propuesta' : identity}{gateway.archived_at?' · Archivado':''}</Tooltip>
    {!draft&&<Popup><div className="map-popup"><strong>Gateway · {gateway.name}</strong><span>{identity}</span><span>{gateway.latitude!.toFixed(6)}, {gateway.longitude!.toFixed(6)}</span><span>{gateway.archived_at?'Archivado · ':''}{gatewayStatus[gateway.status]??gateway.status}</span><span>Última recepción: {date(gateway.last_seen_at)}</span>{onDetail&&<button type="button" onClick={()=>onDetail(gateway)}>Ver detalle e historial</button>}</div></Popup>}
  </Marker>;
}

export function CattleMap({ animals = [], geofences = [], gateways = [], history = [], collars = [], onAnimal, drawPoints = [], drawHoles = [], onPoint, height = 'main', externalTiles = false, focusPoints = [], fitRequest = 0, drawVertices = [], selectedVertex, onVertexSelect, onVertexMove, onVertexDragStart, gatewayDraft, onGatewayMove, onGateway, selectedGatewayId, watchedFenceId, interactiveLegend = false }: {
  gatewayDraft?: Gateway; onGatewayMove?: (point: Point) => void; onGateway?: (gateway: Gateway) => void; selectedGatewayId?: string | null;
  collars?: CollarLocation[]; animals?: Animal[]; geofences?: Geofence[]; gateways?: Gateway[]; history?: Telemetry[]; onAnimal?: (animal: Animal) => void;
  drawPoints?: Point[]; drawHoles?: Point[][]; onPoint?: (point: Point) => void; height?: 'main' | 'small' | 'editor'; externalTiles?: boolean;
  focusPoints?: Point[]; fitRequest?: number;
  drawVertices?: { id: string; point: Point; label: number }[]; selectedVertex?: string | null;
  onVertexSelect?: (id: string) => void; onVertexMove?: (id: string, point: Point) => void; onVertexDragStart?: () => void;
  watchedFenceId?: string;
  interactiveLegend?: boolean;
}) {
  const [map, setMap] = useState<L.Map | null>(null);
  const [base, setBase] = useState(() => savedBase(externalTiles ? 'osm' : 'satellite'));
  const external = base === 'osm';
  const [tileError, setTileError] = useState(false); const [tileBusy, setTileBusy] = useState(false); const [tileAttempt, setTileAttempt] = useState(0);
  const [visibleLayers, setVisibleLayers] = useState(allLayers);
  const [selection, setSelection] = useState<MapSelection | null>(null);
  const [compactLegendOpen, setCompactLegendOpen] = useState(false);
  const browsing = height !== 'editor' && !onPoint;
  const showLegend = interactiveLegend && height === 'main' && browsing;
  const visible = showLegend ? visibleLayers : allLayers;
  const [satelliteError, setSatelliteError] = useState(false);
  const [localOsmError, setLocalOsmError] = useState(false);
  const [localOsmAttempt, setLocalOsmAttempt] = useState(0);
  const [satelliteAttempt, setSatelliteAttempt] = useState(0);
  const [outsideCoverage, setOutsideCoverage] = useState(false);
  useEffect(() => {
    try { if (localStorage.getItem(basePreference) === 'roads') localStorage.setItem(basePreference, 'satellite'); }
    catch { /* Storage can be unavailable in private mode. */ }
  }, []);
  useEffect(() => {
    if (selectedGatewayId) {
      setSelection({ layer: 'gateways', id: selectedGatewayId });
      setVisibleLayers(current => current.gateways ? current : { ...current, gateways: true });
    } else {
      setSelection(current => current?.layer === 'gateways' ? null : current);
    }
  }, [selectedGatewayId, fitRequest]);
  const satellite = useSatellite(base === 'satellite', satelliteAttempt);
  const showSatellite = base === 'satellite' && !!satellite;
  const localOsm = useLocalOsm(base === 'osm-local', localOsmAttempt);
  const showLocalOsm = base === 'osm-local' && !!localOsm;
  function retryLocalOsm() {
    setLocalOsmError(false);
    setLocalOsmAttempt(attempt => attempt + 1);
  }
  function retrySatellite() {
    setSatelliteError(false);
    setSatelliteAttempt(attempt => attempt + 1);
  }
  function selectBase(value: MapBase) {
    setBase(value); setTileError(false); setTileBusy(false); setSatelliteError(false); setLocalOsmError(false);
    if (base === value && value === 'osm-local' && (localOsm === null || localOsmError)) retryLocalOsm();
    if (base === value && value === 'satellite' && (satellite === null || satelliteError)) retrySatellite();
    try { localStorage.setItem(basePreference, value); } catch { /* El almacenamiento puede no estar disponible en modo privado. */ }
  }
  const mappedFences = useMemo(() => geofences.map(fence => {
    const rings = fence.geometry.coordinates.map(ring => ring.map(c => [c[1], c[0]] as Point));
    return { fence, rings, bounds: L.latLngBounds(rings.flat()) };
  }).filter(area => area.bounds.isValid()), [geofences]);
  const positioned = useMemo(() => animals.flatMap(animal => {
    const telemetry = animal.last_position;
    return validPosition(telemetry) ? [{ animal, telemetry, point: [telemetry.latitude, telemetry.longitude] as Point }] : [];
  }), [animals]);
  const locatedGateways = useMemo(() => gateways.filter(hasGatewayPosition), [gateways]);
  const bounds = useMemo<Point[]>(() => {
    const points: Point[] = [];
    mappedFences.forEach(area => area.rings.forEach(ring => points.push(...ring)));
    positioned.forEach(({ point }) => points.push(point));
    locatedGateways.forEach(g => points.push([g.latitude!, g.longitude!]));
    if (gatewayDraft && hasGatewayPosition(gatewayDraft)) points.push([gatewayDraft.latitude!,gatewayDraft.longitude!]);
    collars.forEach(c => points.push([c.latitude, c.longitude]));
    history.filter(validPosition).forEach(t => points.push([t.latitude, t.longitude]));
    return points;
  }, [mappedFences, positioned, locatedGateways, history, collars, gatewayDraft]);
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
  const basemapPoints: Point[] = showSatellite
    ? [[satellite.bounds[0], satellite.bounds[1]], [satellite.bounds[2], satellite.bounds[3]]]
    : showLocalOsm ? [[localOsm.regional.bounds[0], localOsm.regional.bounds[1]], [localOsm.regional.bounds[2], localOsm.regional.bounds[3]]]
    : [];
  const requestedPoints = focusPoints.length ? focusPoints : drawPoints.length ? drawPoints : bounds;
  const recenterPoints = drawPoints.length ? drawPoints : initialPoints.length ? initialPoints : basemapPoints;
  const allPoints = bounds.length ? bounds : basemapPoints;
  const status = external ? (tileBusy ? 'Cargando mapa…' : tileError ? 'Carga parcial' : 'Cartografía en línea')
    : showLocalOsm ? (localOsmError ? 'Algunas teselas no cargaron' : 'Mapa guardado en el servidor')
    : showSatellite ? (outsideCoverage ? 'Centro fuera de la cobertura satelital' : satelliteError ? 'Algunas teselas no cargaron' : 'Imagen guardada en el servidor')
      : satellite === null ? 'Cuadrícula WGS84' : 'Cargando imagen satelital…';
  const drawColor = showSatellite ? '#ffe18d' : '#236b52';
  function selectFence(area: MapFence) {
    if (!map) return;
    map.closePopup();
    setVisibleLayers(current => current.fences ? current : { ...current, fences: true });
    setSelection({ layer: 'fences', id: area.fence.id });
    fitMap(map, area.bounds, { maxZoom: 18, animate: false });
  }
  function selectGateway(gateway: Gateway) {
    if (!map) return;
    map.closePopup();
    setVisibleLayers(current => current.gateways ? current : { ...current, gateways: true });
    setSelection({ layer: 'gateways', id: gateway.id });
    map.setView([gateway.latitude!, gateway.longitude!], Math.max(17, map.getZoom()), { animate: false });
  }
  function changeLayerVisibility(layer: MapLayer, shown: boolean) {
    setVisibleLayers(current => ({ ...current, [layer]: shown }));
    setSelection(current => shown || current?.layer === layer ? null : current);
    if (shown && map) {
      const area = L.latLngBounds([]);
      if (layer === 'fences') mappedFences.forEach(fence => area.extend(fence.bounds));
      else locatedGateways.forEach(gateway => area.extend([gateway.latitude!, gateway.longitude!]));
      if (area.isValid()) {
        map.closePopup();
        fitMap(map, area, { animate: false });
      }
    }
  }
  function showAll() {
    setVisibleLayers(allLayers);
    setSelection(null);
    if (map && allPoints.length) {
      map.closePopup();
      fitMap(map, L.latLngBounds(allPoints), { animate: false });
    }
  }
  const legendGroups: MapLocationGroup[] = showLegend ? [
    { layer: 'fences', items: mappedFences.map(area => ({
      id: area.fence.id,
      label: area.fence.active ? area.fence.name : `${area.fence.name} · histórica v${area.fence.version}`,
      focus: () => selectFence(area),
    })) },
    { layer: 'gateways', items: locatedGateways.map(gateway => ({
      id: gateway.id,
      label: gateway.archived_at ? `${gateway.name} · archivado` : gateway.name,
      focus: () => selectGateway(gateway),
    })) },
  ] : [];
  return <div className={`map-wrapper map-${height}${showSatellite ? ' map-on-satellite' : ''}${showLegend ? ' map-with-legend' : ''}`}>
    <div className="map-base-toolbar" role="group" aria-label="Base del mapa"><Layers size={16} /><button type="button" aria-pressed={base === 'satellite'} onClick={() => selectBase('satellite')}>Satélite local</button><button type="button" aria-pressed={base === 'osm-local'} onClick={() => selectBase('osm-local')}>OpenStreetMap local</button><button type="button" aria-pressed={external} onClick={() => selectBase('osm')}>OpenStreetMap</button><span role="status">{status}</span></div>
    <div className={showLegend ? 'map-legend-layout' : undefined}>
      <div className="map-viewport">
        <MapContainer ref={setMap} center={[-39, -72.5]} zoom={7} maxZoom={20} scrollWheelZoom className={`cattle-map ${onPoint ? 'map-drawing' : ''}`} aria-label={height === 'editor' ? 'Editor de geocerca' : 'Mapa de animales y geocercas'}>
          <OfflineGrid />
          {showSatellite && <SatelliteTiles data={satellite} onOutside={setOutsideCoverage} onError={setSatelliteError} />}
          {showLocalOsm && <LocalOsmTiles data={localOsm} onError={setLocalOsmError} />}
          {external && <TileLayer key={tileAttempt} url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" zIndex={1} maxNativeZoom={19} maxZoom={20} referrerPolicy="strict-origin-when-cross-origin" attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' eventHandlers={{ loading: () => setTileBusy(true), load: () => setTileBusy(false), tileerror: () => setTileError(true) }} />}
          <MapSize /><Fit points={initialPoints} requestedPoints={requestedPoints} request={fitRequest} drawing={!!onPoint} /><Drawing onPoint={onPoint} /><ScaleControl position="bottomleft" imperial={false} />
          {drawVertices.map(v => <VertexMarker key={v.id} vertex={v} selected={selectedVertex===v.id} onSelect={onVertexSelect} onMove={onVertexMove} onDragStart={onVertexDragStart} />)}
          <FenceLayers fences={visible.fences ? mappedFences : []} satellite={showSatellite} drawing={!!onPoint}
            selectedId={selection?.layer === 'fences' ? selection.id : undefined} watchedId={watchedFenceId}
            onSelect={browsing ? selectFence : undefined} />
          {visible.gateways && locatedGateways.map(g => <GatewayMarker key={g.id} gateway={g} onDetail={onGateway}
            selected={selection?.layer === 'gateways' && selection.id === g.id}
            onSelect={showLegend ? () => setSelection({ layer: 'gateways', id: g.id }) : undefined} />)}
          {gatewayDraft && hasGatewayPosition(gatewayDraft) && <GatewayMarker gateway={gatewayDraft} onMove={onGatewayMove} draft />}
          {tracks.map((track, i) => <Polyline key={i} positions={track} pathOptions={{ color: showSatellite ? '#86f3e2' : '#276e68', weight: 3, opacity: .85 }} />)}
          {fixes.length > 0 && <><CircleMarker center={[fixes[0].latitude, fixes[0].longitude]} radius={5} pathOptions={{ color: '#fff', fillColor: '#276e68', fillOpacity: 1 }}><Tooltip>Inicio · {date(fixes[0].observed_at)}</Tooltip></CircleMarker><CircleMarker center={[fixes[fixes.length - 1].latitude, fixes[fixes.length - 1].longitude]} radius={5} pathOptions={{ color: '#fff', fillColor: '#c68a3c', fillOpacity: 1 }}><Tooltip>Fin · {date(fixes[fixes.length - 1].observed_at)}</Tooltip></CircleMarker></>}
          {collars.map(c => {
            const id = `collar-${c.hardware_id}`;
            const freshness = c.stale ? 'Última posición histórica' : 'Posición reciente';
            return <Marker key={id} position={[c.latitude, c.longitude]} title={`Collar ${c.hardware_id} · ${freshness}`}
              icon={L.divIcon({ className: `collar-location-marker ${c.stale ? 'historical' : 'recent'}`,
                html: '<span aria-hidden="true">●</span>', iconSize: [20, 20], iconAnchor: [10, 10] })}>
              <Tooltip>{c.hardware_id} · {freshness}</Tooltip>
              <Popup><div className="map-popup"><strong>Collar {c.hardware_id}</strong><span>{date(c.observed_at)}</span><span>{c.latitude.toFixed(6)}, {c.longitude.toFixed(6)}</span><span>{c.stale ? 'Posición histórica; no indica ubicación actual.' : 'Última posición válida recibida.'}</span></div></Popup>
            </Marker>;
          })}
          {positioned.map(({ animal, telemetry: t, point }) => {
            const stale = animal.position_status !== 'fresh';
            return <CircleMarker key={animal.id} center={point} radius={6}
              pathOptions={{ color: '#fff', weight: 2, fillColor: stale ? staleColor : statusColors[animal.status], fillOpacity: stale ? .65 : 1, dashArray: stale ? '3 2' : undefined }}>
              <Tooltip direction="top">{animal.name || animal.diio} · {age(animal.position_age_seconds)}{stale && ' · posición vencida'}</Tooltip>
              <Popup><div className="map-popup"><strong>{animal.name || animal.diio}</strong><span>DIIO {animal.diio}</span><Badge status={animal.status} /><span>{age(animal.position_age_seconds)} · {animal.position_status === 'fresh' ? 'Posición vigente' : 'Posición vencida'}</span><span>Origen: {t.source === 'sim' ? 'simulado' : t.source === 'academic' ? 'nodo académico' : 'LoRaWAN'}</span>{onAnimal && <button onClick={() => onAnimal(animal)}>Ver ficha del animal →</button>}</div></Popup>
            </CircleMarker>;
          })}
          {drawPoints.length >= 3 && <MapPolygon positions={[drawPoints, ...drawHoles]} pathOptions={{ color: drawColor, fillColor: '#68b28e', fillOpacity: .25, weight: 2, dashArray: '5 4' }} />}
          {drawPoints.length === 2 && <Polyline positions={drawPoints} pathOptions={{ color: drawColor, weight: 2, dashArray: '5 4' }} />}
          {!drawVertices.length && drawPoints.map((p, i) => <CircleMarker key={i} center={p} radius={5} pathOptions={{ color: '#fff', fillColor: '#236b52', fillOpacity: 1, weight: 2 }}><Tooltip permanent direction="top">{i + 1}</Tooltip></CircleMarker>)}
        </MapContainer>
        <div className="map-controls">
          <button type="button" className="map-button" title="Encuadrar geometrías y posiciones" aria-label="Encuadrar geometrías y posiciones"
            disabled={!map || !(showLegend ? allPoints : recenterPoints).length}
            onClick={showLegend ? showAll : () => { if (map) fitMap(map, L.latLngBounds(recenterPoints)); }}><LocateFixed size={18} /></button>
        </div>
        {!bounds.length && !drawPoints.length && !focusPoints.length && <div className="map-empty-hint"><MapPin size={18} /><span>{height === 'editor' ? 'Acerca el mapa a tu predio o centra unas coordenadas antes de dibujar.' : 'Sin posiciones ni geocercas guardadas. Vista regional de referencia.'}</span></div>}
      </div>
      {showLegend && <MapLegend groups={legendGroups} visible={visible} selection={selection} onVisibility={changeLayerVisibility}
        onFitAll={showAll} canFitAll={!!map && !!allPoints.length} hasPositions={!!(animals.length || collars.length)} />}
    </div>
    <div className="map-caption"><span><span className={`connection-dot ${external && !tileError ? 'green' : ''}`} />{external ? 'OpenStreetMap · requiere Internet' : showLocalOsm ? `${localOsm.name} · © OpenStreetMap contributors` : showSatellite ? `${satellite.name} · ${satellite.attribution}` : 'Cuadrícula WGS84 · disponible sin Internet'}</span>
      {!showLegend && <button type="button" aria-expanded={compactLegendOpen} onClick={() => setCompactLegendOpen(value => !value)} className="text-button">{compactLegendOpen ? 'Ocultar leyenda' : 'Leyenda'}</button>}
    </div>
    {!showLegend && compactLegendOpen && <div className="map-legend"><Badge status="normal" /><Badge status="warning" /><Badge status="critical" /><Badge status="unknown">Posición vencida</Badge><span className="legend-line">Geocerca activa</span></div>}
    {external && tileError && <div className="map-note" role="status">Algunas teselas no cargaron. Puedes elegir Satélite local y seguir trabajando con el mismo dibujo.<button className="text-button" type="button" onClick={() => { setTileError(false); setTileAttempt(v => v + 1); }}><RotateCw size={13} />Reintentar mapa</button></div>}
    {base === 'osm-local' && localOsm === null && <div className="map-note" role="status"><span>Para instalar el mapa OpenStreetMap local, ejecuta <code>python scripts/preparar_mapa_osm.py</code> (descargar, importar y renderizar; requiere Docker).</span><button type="button" className="text-button" onClick={retryLocalOsm}><RotateCw size={13} />Reintentar mapa</button></div>}
    {base === 'satellite' && satellite === null && <div className="map-note" role="status"><span>Para instalar la imagen satelital, ejecuta <code>python scripts/preparar_mapa_satelital.py --araucania</code> desde la raíz con rasterio y Pillow.</span><button type="button" className="text-button" onClick={retrySatellite}><RotateCw size={13} />Reintentar mapa</button></div>}
  </div>;
}
