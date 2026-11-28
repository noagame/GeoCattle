import type { User } from './types';
import type { DraftAction, MirrorInfo, QueuedWrite, SubmissionStatus } from './v3types';

export const mirrorPollInterval = 15_000;
export const queuedMessage = 'Enviado al campo · se aplicará cuando el PC se conecte';
export const supportRequestsPath = '/auth/support-requests';
export const supportQueuedMessage = 'Solicitud enviada al PC del campo. Aparecerá cuando se sincronice. Sigue su estado en Mis envíos.';
export const fieldOnlyMessage = 'Se gestiona en el PC del campo';
export const supportReplicaMessage = 'Puedes enviar solicitudes desde aquí: se registran en el PC del campo al sincronizar y su estado se sigue en Mis envíos.';

export type WriteFeature = 'farm' | 'hardware' | 'account' | 'admin' | 'change' | 'decision' | 'draft' | 'notice_read' | 'support_request' | DraftAction;

export function isDraftAction(action: string): action is DraftAction {
  return action === 'animal_profile' || action === 'health_record' || action === 'health_schedule';
}

// Intersects with the existing application permissions at each call site.
export function canWrite(mode: MirrorInfo['mode'] | undefined, role: User['role'] | undefined, feature: WriteFeature) {
  if (!mode || !role) return false;
  if (mode !== 'replica' || feature === 'notice_read' || feature === 'support_request') return true;
  if (role === 'admin') return feature === 'admin' || feature === 'change' || feature === 'decision' || isDraftAction(feature);
  return role === 'veterinarian' && (feature === 'draft' || isDraftAction(feature));
}

export function isQueuedWrite(value: unknown): value is QueuedWrite {
  if (!value || typeof value !== 'object') return false;
  const result = value as Partial<QueuedWrite>;
  return result.queued === true && result.status === 'queued' && typeof result.outbox_id === 'string';
}

export const submissionLabels: Record<SubmissionStatus, string> = {
  queued: 'En cola para el campo',
  delivered: 'Recibido por el campo',
  applied: 'Aplicado',
  pending_owner: 'Pendiente del dueño',
  rejected: 'Rechazado',
  conflict: 'Conflicto: revisa tus borradores',
  failed: 'Falló al aplicar',
};

const chileTime = (seconds: boolean) => new Intl.DateTimeFormat('es-CL', {
  timeZone: 'America/Santiago', hourCycle: 'h23', hour: '2-digit', minute: '2-digit',
  ...(seconds ? { second: '2-digit' } : {}),
});
const timeWithSeconds = chileTime(true);
const timeWithMinutes = chileTime(false);

export function freshnessText(info: MirrorInfo, now: number) {
  if (info.mode !== 'replica') return '';
  const heartbeat = info.heartbeat_at ? Date.parse(info.heartbeat_at) : NaN;
  if (!Number.isFinite(heartbeat)) return 'Campo sin conexión · esperando el primer registro';
  if (!info.field_online) return `Campo sin conexión desde ${timeWithMinutes.format(heartbeat)} · mostrando lo último recibido`;
  const elapsed = Math.max(0, Math.floor((now - heartbeat) / 1000));
  return `Datos del campo al ${timeWithSeconds.format(heartbeat)} (hace ${elapsed} s)`;
}
