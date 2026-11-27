import { useEffect, useLayoutEffect, useRef, useId, type ReactNode } from 'react';
import { AlertCircle, Check, ChevronRight, Inbox, LoaderCircle, X } from 'lucide-react';
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
  return <div className="notice notice-error" role="alert"><AlertCircle size={18} aria-hidden="true" /><span>{error}</span>{retry && <button type="button" className="text-button" onClick={retry}>Reintentar</button>}</div>;
}
export function Loading({ label = 'Cargando información del predio…' }: { label?: string }) { return <div className="loading" role="status"><LoaderCircle size={24} className="spin" aria-hidden="true" />{label}</div>; }
export function Empty({ title, description, action, icon, compact = false }: { title: string; description?: string; action?: ReactNode; icon?: ReactNode; compact?: boolean }) { return <div className={`empty${compact ? ' empty-compact' : ''}`}><div className="empty-symbol" aria-hidden="true">{icon ?? <Inbox size={19} />}</div><h3>{title}</h3>{description && <p>{description}</p>}{action}</div>; }
export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) { return <section className={`panel ${className}`}>{children}</section>; }
export function PageTitle({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) { return <div className="page-title"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</div>; }
export function PanelTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) { return <div className="panel-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>; }

export function SectionTabs<T extends string>({ label, active, onChange, sections }: {
  label: string;
  active: T;
  onChange: (id: T) => void;
  sections: { id: T; label: string; content: ReactNode }[];
}) {
  const id = useId();
  const tabs = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const focus = document.activeElement;
    const panel = focus?.closest('[role="tabpanel"][hidden]');
    if (panel?.parentElement === container.current) tabs.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus();
  }, [active]);
  return <div className="section-tabs" ref={container}>
    <div className="section-tablist" ref={tabs} role="tablist" aria-label={label}>
      {sections.map((section, index) => <button key={section.id} type="button" role="tab"
        id={`${id}-tab-${section.id}`} aria-controls={`${id}-panel-${section.id}`}
        aria-selected={active === section.id} tabIndex={active === section.id ? 0 : -1}
        onClick={() => onChange(section.id)} onKeyDown={event => {
          const last = sections.length - 1;
          let next: number;
          switch (event.key) {
            case 'ArrowLeft': next = index ? index - 1 : last; break;
            case 'ArrowRight': next = index === last ? 0 : index + 1; break;
            case 'Home': next = 0; break;
            case 'End': next = last; break;
            default: return;
          }
          event.preventDefault();
          onChange(sections[next].id);
          tabs.current?.querySelectorAll('button')[next]?.focus();
        }}>{section.label}</button>)}
    </div>
    {sections.map(section => <div key={section.id} role="tabpanel" id={`${id}-panel-${section.id}`}
      aria-labelledby={`${id}-tab-${section.id}`} hidden={active !== section.id} tabIndex={0}>{section.content}</div>)}
  </div>;
}

export function ScrollRegion({ label, children, className = '' }: { label: string; children: ReactNode; className?: string }) {
  return <div className={`table-scroll scroll-region ${className}`} role="region" aria-label={label} tabIndex={0}>{children}</div>;
}

export function dateInputValue(value = new Date(), timeZone?: string) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(value);
  const part = (type: string) => parts.find(entry => entry.type === type)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

export type DatePeriod = { preset: string; start: string; end: string };
export const defaultDatePeriod: DatePeriod = { preset: 'default', start: '', end: '' };

export function PeriodFields({ value, onChange, timeZone, defaultLabel, endLabel = 'Hasta' }: {
  value: DatePeriod;
  onChange: (value: DatePeriod) => void;
  timeZone?: string;
  defaultLabel: string;
  endLabel?: string;
}) {
  const { preset, start, end } = value;
  function selectPeriod(next: string) {
    if (next === 'custom') { onChange({ ...value, preset: next }); return; }
    if (next === 'default') { onChange(defaultDatePeriod); return; }
    const today = dateInputValue(new Date(), timeZone);
    const first = new Date(`${today}T00:00:00Z`);
    first.setUTCDate(first.getUTCDate() - Number(next) + 1);
    onChange({ preset: next, start: first.toISOString().slice(0, 10), end: today });
  }
  return <div className="period-fields">
    <label>Período<select value={preset} onChange={event => selectPeriod(event.target.value)}>
      <option value="default">{defaultLabel}</option><option value="1">Hoy</option>
      <option value="7">Últimos 7 días</option><option value="30">Últimos 30 días</option>
      <option value="custom">Rango personalizado</option>
    </select></label>
    {preset === 'custom' && <div className="period-dates">
      <label>Desde<input type="date" value={start} max={end || undefined} onChange={event => onChange({ ...value, start: event.target.value })} /></label>
      <label>{endLabel}<input type="date" value={end} min={start || undefined} onChange={event => onChange({ ...value, end: event.target.value })} /></label>
    </div>}
  </div>;
}
export function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null); const titleId = useId();
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog className={`modal ${wide ? 'modal-wide' : ''}`} ref={ref} onCancel={event => { event.preventDefault(); onClose(); }} aria-labelledby={titleId} onClick={event => { if (event.target === event.currentTarget) { const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose(); } }}><div className="modal-heading"><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label="Cerrar" onClick={onClose}><X size={20} /></button></div>{children}</dialog>;
}
export function Submit({ busy, disabled = false, children = 'Guardar cambios' }: { busy: boolean; disabled?: boolean; children?: ReactNode }) { return <button type="submit" className="button primary" disabled={busy || disabled}>{busy ? <LoaderCircle size={17} className="spin" /> : <Check size={17} />}{busy ? 'Guardando…' : children}</button>; }
export function Detail({ label, value }: { label: string; value: ReactNode }) { return <div className="detail"><dt>{label}</dt><dd>{value}</dd></div>; }
export function Forward({ children, onClick }: { children: ReactNode; onClick: () => void }) { return <button className="text-button" onClick={onClick}>{children}<ChevronRight size={16} /></button>; }
export function pretty(value: unknown): string { return typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? '—'; }
