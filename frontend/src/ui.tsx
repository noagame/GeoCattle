import { useEffect, useRef, type ReactNode } from 'react';
import { AlertCircle, Check, ChevronRight, LoaderCircle, X } from 'lucide-react';
import type { AnimalStatus } from './types';

export const statusLabels: Record<AnimalStatus, string> = { normal: 'Normal', warning: 'Precaución', critical: 'Crítico', unknown: 'Sin información' };
export const eventLabels: Record<string, string> = {
  escape: 'Fuera de geocerca', geofence_exit: 'Fuera de geocerca', outside_geofence: 'Fuera de geocerca',
  communication_loss: 'Sin comunicación', communication_timeout: 'Sin comunicación', config_timeout: 'Configuración sin confirmar', timeout: 'Sin comunicación', low_battery: 'Batería baja',
  no_fix: 'Sin posición GNSS', high_surface_temperature: 'Temperatura superficial elevada', temperature_high: 'Temperatura elevada', high_temperature: 'Temperatura elevada',
  low_activity: 'Actividad reducida', activity_low: 'Actividad reducida', proximity: 'Cerca del límite de geocerca', proximity_alert: 'Cerca del límite de geocerca',
};
export const attentionLabels: Record<string, string> = { pending: 'Pendiente', acknowledged: 'Reconocido', in_review: 'En revisión', concluded: 'Concluido' };
export const actionLabels: Record<string, string> = { acknowledge: 'Reconocer', review: 'Iniciar revisión', conclude: 'Concluir atención', reopen: 'Reabrir atención' };
export function Badge({ status, children }: { status: string; children?: ReactNode }) { return <span className={`badge badge-${status}`}><span />{children ?? statusLabels[status as AnimalStatus] ?? status}</span>; }
export function ErrorNotice({ error, retry }: { error: string; retry?: () => void }) {
  if (!error) return null;
  return <div className="notice notice-error" role="alert"><AlertCircle size={18} /><span>{error}</span>{retry && <button type="button" className="text-button" onClick={retry}>Reintentar</button>}</div>;
}
export function Loading({ label = 'Cargando información del predio…' }: { label?: string }) { return <div className="loading" role="status"><LoaderCircle size={24} className="spin" />{label}</div>; }
export function Empty({ title, description, action }: { title: string; description?: string; action?: ReactNode }) { return <div className="empty"><div className="empty-symbol">↗</div><h3>{title}</h3>{description && <p>{description}</p>}{action}</div>; }
export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) { return <section className={`panel ${className}`}>{children}</section>; }
export function PageTitle({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) { return <div className="page-title"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</div>; }
export function PanelTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) { return <div className="panel-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>; }
export function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog className={`modal ${wide ? 'modal-wide' : ''}`} ref={ref} onCancel={onClose} aria-labelledby="modal-title" onClick={event => { if (event.target === event.currentTarget) { const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose(); } }}><div className="modal-heading"><h2 id="modal-title">{title}</h2><button className="icon-button" aria-label="Cerrar" onClick={onClose}><X size={20} /></button></div>{children}</dialog>;
}
export function Submit({ busy, children = 'Guardar cambios' }: { busy: boolean; children?: ReactNode }) { return <button type="submit" className="button primary" disabled={busy}>{busy ? <LoaderCircle size={17} className="spin" /> : <Check size={17} />}{busy ? 'Guardando…' : children}</button>; }
export function Detail({ label, value }: { label: string; value: ReactNode }) { return <div className="detail"><dt>{label}</dt><dd>{value}</dd></div>; }
export function Forward({ children, onClick }: { children: ReactNode; onClick: () => void }) { return <button className="text-button" onClick={onClick}>{children}<ChevronRight size={16} /></button>; }
export function pretty(value: unknown): string { return typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? '—'; }
