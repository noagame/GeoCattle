import type { Polygon } from './types';

export type Vertex = { id: string; latitude: string; longitude: string };
export type Draft = { vertices: Vertex[]; selected: string | null; history: Vertex[][] };
export type DraftAction =
  | { type: 'select'; id: string }
  | { type: 'replace'; vertices: Vertex[]; record?: boolean }
  | { type: 'edit'; id: string; latitude: string; longitude: string; record?: boolean }
  | { type: 'checkpoint' }
  | { type: 'undo' };
export function vertex(latitude: number, longitude: number): Vertex {
  return { id: crypto.randomUUID(), latitude: String(latitude), longitude: String(longitude) };
}
export function position(v: Vertex): [number, number] | null {
  if (!v.latitude.trim() || !v.longitude.trim()) return null;
  const lat = Number(v.latitude), lon = Number(v.longitude);
  return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null;
}
export function draftReducer(state: Draft, action: DraftAction): Draft {
  if (action.type === 'select') return { ...state, selected: action.id };
  if (action.type === 'undo') {
    const vertices = state.history.at(-1);
    return vertices ? { vertices, selected: vertices.some(v => v.id === state.selected) ? state.selected : null, history: state.history.slice(0, -1) } : state;
  }
  if (action.type === 'checkpoint') return { ...state, history: [...state.history.slice(-99), state.vertices] };
  const vertices = action.type === 'replace' ? action.vertices : state.vertices.map(v => v.id === action.id ? { ...v, latitude: action.latitude, longitude: action.longitude } : v);
  if (JSON.stringify(vertices) === JSON.stringify(state.vertices)) return state;
  return { vertices, selected: vertices.some(v => v.id === state.selected) ? state.selected : null, history: action.record === false ? state.history : [...state.history.slice(-99), state.vertices] };
}
function cross(a: number[], b: number[], c: number[]) { return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]); }
function onSegment(a: number[], b: number[], p: number[]) {
  return cross(a,b,p) === 0 && p[0] >= Math.min(a[0],b[0]) && p[0] <= Math.max(a[0],b[0]) && p[1] >= Math.min(a[1],b[1]) && p[1] <= Math.max(a[1],b[1]);
}
export function polygonFromVertices(vertices: Vertex[]): Polygon {
  if (vertices.length < 4) throw new Error('Se requieren al menos cuatro vértices distintos. Puedes continuar editando.');
  if (vertices.length > 10000) throw new Error('Máximo 10000 vértices.');
  const points = vertices.map(position);
  if (points.some(p => !p)) throw new Error('Completa latitud y longitud válidas en todos los vértices.');
  const ring = (points as [number, number][]).map(([lat, lon]) => [lon, lat]);
  if (new Set(ring.map(p => p.join(','))).size !== ring.length) throw new Error('No se permiten vértices repetidos.');
  let area = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i], b = ring[(i+1)%ring.length]; area += a[0]*b[1]-b[0]*a[1];
    for (let j = i+1; j < ring.length; j++) {
      if (j === i+1 || (i === 0 && j === ring.length-1)) continue;
      const c = ring[j], d = ring[(j+1)%ring.length];
      if ((cross(a,b,c)*cross(a,b,d)<0 && cross(c,d,a)*cross(c,d,b)<0) || onSegment(a,b,c) || onSegment(a,b,d) || onSegment(c,d,a) || onSegment(c,d,b)) throw new Error('El polígono se cruza o toca a sí mismo. Reordena o mueve sus vértices.');
    }
  }
  if (Math.abs(area) < 1e-14) throw new Error('La geocerca debe encerrar un área mayor que cero.');
  return { type: 'Polygon', coordinates: [[...ring, [...ring[0]]]] };
}
export function importVertices(input: unknown): Vertex[] {
  let value = input as { type?: string; geometry?: unknown; features?: unknown[]; coordinates?: unknown };
  if (value?.type === 'FeatureCollection') {
    if (value.features?.length !== 1) throw new Error('Importa exactamente una geocerca Polygon.');
    value = value.features[0] as typeof value;
  }
  if (value?.type === 'Feature') value = value.geometry as typeof value;
  if (value?.type !== 'Polygon' || !Array.isArray(value.coordinates) || value.coordinates.length !== 1) throw new Error('Se requiere un Polygon WGS84 sin huecos interiores.');
  const ring = value.coordinates[0];
  if (!Array.isArray(ring) || ring.some(p => !Array.isArray(p) || p.length !== 2 || p.some(n => typeof n !== 'number' || !Number.isFinite(n)))) throw new Error('Coordenadas GeoJSON inválidas.');
  if (JSON.stringify(ring[0]) !== JSON.stringify(ring.at(-1))) throw new Error('El anillo debe estar cerrado.');
  const vertices = ring.slice(0,-1).map(([lon,lat]: number[]) => vertex(lat,lon));
  polygonFromVertices(vertices); return vertices;
}
