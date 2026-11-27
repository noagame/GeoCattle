import { useCallback, useEffect, useState } from 'react';
import type { Session } from './types';
import { isQueuedWrite, queuedMessage, supportQueuedMessage, supportRequestsPath } from './mirror';

let csrf = '';
export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(message: string, status: number, body?: unknown) { super(message); this.status = status; this.body = body; }
}
export function setSession(session: Session | null) { csrf = session?.csrf_token ?? ''; }
export function formatApiDetail(detail: unknown) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((error: { msg?: string; loc?: (string | number)[] } | null) =>
    `${Array.isArray(error?.loc) ? error.loc.slice(1).join('.') : 'Campo'}: ${error?.msg ?? 'valor inválido'}`).join(' · ');
  return '';
}
async function apiResponse(path: string, init: RequestInit = {}): Promise<Response> {
  const isWrite = init.method && !['GET', 'HEAD'].includes(init.method);
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...init, credentials: 'same-origin', headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(isWrite && csrf ? { 'X-CSRF-Token': csrf } : {}), ...init.headers,
      },
    });
  } catch {
    window.dispatchEvent(new CustomEvent('api-connectivity', { detail: false }));
    throw new ApiError('No se pudo conectar con el servidor local. Comprueba la conexión a la red del predio.', 0);
  }
  window.dispatchEvent(new CustomEvent('api-connectivity', { detail: response.status < 500 }));
  if (!response.ok) {
    let detail = `La solicitud no se pudo completar (${response.status}).`;
    let errorBody: unknown;
    try {
      const body = await response.json();
      errorBody = body;
      detail = formatApiDetail(body.detail) || detail;
    } catch { /* Error de infraestructura sin JSON: se conserva la descripción HTTP. */ }
    if (response.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('session-expired'));
    throw new ApiError(detail, response.status, errorBody);
  }
  return response;
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiResponse(path, init);
  if (response.status === 204) return undefined as T;
  const result = await response.json();
  if (response.status === 202 && isQueuedWrite(result)) {
    const detail = path === supportRequestsPath ? supportQueuedMessage : queuedMessage;
    window.dispatchEvent(new CustomEvent('mirror-queued', { detail }));
  }
  return result as T;
}
export async function downloadFile(path: string, fallbackFilename: string) {
  const response = await apiResponse(path);
  const filename = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] ?? fallbackFilename;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const write = <T,>(path: string, body: unknown, method = 'POST') => api<T>(path, { method, body: JSON.stringify(body) });
export function useData<T>(path: string | null, interval = 0, contextKey = '') {
  const [data, setData] = useState<T | null>(null);
  const [dataKey, setDataKey] = useState('');
  const key = `${contextKey}:${path ?? ''}`;
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion(v => v + 1), []);
  useEffect(() => {
    if (!path) { setData(null); setError(''); setLoading(false); return; }
    let alive = true;
    setLoading(true); setError('');
    api<T>(path).then(result => { if (alive) { setData(result); setDataKey(key); setError(''); } })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : 'Ocurrió un error.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [path, version, contextKey]);
  useEffect(() => {
    if (!interval || !path) return;
    const timer = window.setInterval(reload, interval);
    return () => window.clearInterval(timer);
  }, [interval, path, reload]);
  return { data: dataKey === key ? data : null, error, loading, reload };
}
export function message(error: unknown) { return error instanceof Error ? error.message : 'La operación no se pudo completar.'; }
export function date(value?: string | null) {
  if (!value) return 'Sin registro';
  const instant = new Date(value);
  return Number.isNaN(instant.getTime()) ? value : new Intl.DateTimeFormat('es-CL', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'America/Santiago' }).format(instant);
}
export function age(seconds: number | null | undefined) {
  if (seconds == null) return 'Sin posición';
  if (seconds < 60) return 'Hace menos de 1 min';
  if (seconds < 3600) return `Hace ${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `Hace ${Math.floor(seconds / 3600)} h`;
  return `Hace ${Math.floor(seconds / 86400)} d`;
}
export function query(values: Record<string, string>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
  return params.toString() ? `?${params.toString()}` : '';
}

export type OwnerExportPeriod = { days: '7' | '30' } | { start: string; end: string };
export function ownerExportPath(kind: 'metricas' | 'dispositivos' | 'telemetria' | 'diario' | 'general', period: OwnerExportPeriod,
  format: 'json' | 'csv' | 'xlsx' = 'json') {
  return `/v3/owner-exports/${kind}${query({ ...period, format })}`;
}
