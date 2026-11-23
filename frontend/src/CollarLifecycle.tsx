import { useLayoutEffect, useState, type ComponentProps, type FormEvent } from 'react';
import { Archive, ArchiveRestore, Link2, Radio, Settings2, Trash2, Unlink2, type LucideIcon } from 'lucide-react';
import { age, ApiError, api, message, write } from './api';
import type { Animal, Device } from './types';
import { Badge, ErrorNotice, Modal, Submit } from './ui';

export type CollarAction = {
  kind: 'close' | 'retire' | 'reactivate' | 'delete';
  id: string;
  name: string;
};

const actions = {
  close: {
    title: 'Desvincular del bovino',
    description: 'Se cierra la asociación vigente y se resuelven sus alertas activas. El historial se conserva y las nuevas lecturas quedarán sin bovino hasta que el collar se asigne de nuevo.',
    success: 'Collar desvinculado. El historial se conserva.',
  },
  retire: {
    title: 'Retirar collar',
    description: 'El collar seguirá en el inventario con su historial. Dejará de recibir lecturas y de generar alertas por falta de comunicación. Podrás reactivarlo más adelante.',
    success: 'Collar retirado. El historial se conserva.',
  },
  reactivate: {
    title: 'Reactivar collar',
    description: 'El collar podrá recibir lecturas y volver a asignarse. Se conserva su historial, pero no se reabren sus asociaciones anteriores.',
    success: 'Collar reactivado.',
  },
  delete: {
    title: 'Eliminar del inventario',
    description: 'Se eliminará el registro del collar si no tiene historial operativo. La auditoría se conserva y, si el alta venía de una detección, esta quedará descartada. Una nueva recepción física podrá detectarlo otra vez.',
    success: 'Collar eliminado del inventario.',
  },
};

const exactTime = new Intl.DateTimeFormat('es-CL', {
  dateStyle: 'long', timeStyle: 'long', timeZone: 'America/Santiago',
});

export function collarTimestamp(value: string | null | undefined, now: number) {
  const millis = value ? Date.parse(value) : NaN;
  if (!value || !Number.isFinite(millis)) return null;
  const seconds = Math.max(0, (now - millis) / 1000);
  return { value, seconds, relative: age(seconds).toLowerCase(), exact: exactTime.format(millis) };
}

const configLabels: Record<string, string> = { requested: 'Solicitada', sent: 'Enviada', pending: 'Pendiente' };

export function CollarInventoryTable({ devices, animals, canWrite, onAssign, onConfigure, onLifecycle, now = Date.now() }: {
  devices: Device[];
  animals: Animal[];
  canWrite: boolean;
  onAssign: (device: Device) => void;
  onConfigure: (device: Device) => void;
  onLifecycle: (action: CollarAction) => void;
  now?: number;
}) {
  return <div className="table-scroll">
    <table className="card-table collar-table" aria-label="Inventario de dispositivos">
      <thead><tr>
        <th scope="col">Dispositivo</th>
        <th scope="col">Estado</th>
        <th scope="col">Bovino asociado</th>
        <th scope="col">Intervalo</th>
        <th scope="col">Última recepción</th>
        {canWrite && <th scope="col">Acciones</th>}
      </tr></thead>
      <tbody>{devices.map(device => {
        const animal = device.animal_id === undefined ? animals.find(item => item.device_id === device.id)
          : animals.find(item => item.id === device.animal_id);
        const assigned = Boolean(device.assignment_id || device.animal_id || animal);
        const last = collarTimestamp(device.last_received_at, now);
        const freshness = last ? (last.seconds <= 3 * device.interval_seconds + 30 ? 'recent' : 'stale') : 'unknown';
        const state = !device.enabled ? { label: 'Retirado', tone: 'unknown' }
          : !assigned ? { label: 'Sin asignar', tone: 'unknown' }
          : freshness === 'stale' ? { label: 'Sin comunicación', tone: 'warning' }
          : { label: 'Activo', tone: 'normal' };
        const pending = device.pending_config;
        return <tr key={device.id}>
          <td data-label="Dispositivo">
            <div className="animal-cell">
              <span className="animal-avatar" aria-hidden="true"><Radio size={18} /></span>
              <div>
                <strong>{device.name}</strong><small>{device.hardware_id}</small>
                <small>{device.transport === 'academic' ? 'Académico' : 'LoRaWAN'}{device.dev_eui && <> · {device.dev_eui}</>}</small>
              </div>
            </div>
          </td>
          <td data-label="Estado"><Badge status={state.tone}>{state.label}</Badge></td>
          <td data-label="Bovino asociado">
            {animal ? <>{animal.name}<small>DIIO {animal.diio}</small></> : assigned ? 'Bovino asociado' : <span className="muted">—</span>}
          </td>
          <td data-label="Intervalo">
            <strong>{device.interval_seconds} s</strong><small>Versión {device.config_version}</small>
            {pending && <small className="collar-pending-config">
              <Badge status="warning">{configLabels[pending.status] ?? pending.status}</Badge> {pending.interval_seconds} s · v{pending.version}
            </small>}
          </td>
          <td data-label="Última recepción">
            {last ? <time className={`collar-reception collar-reception-${freshness}`} dateTime={last.value} title={last.exact}>{last.relative}</time>
              : <span className="collar-reception collar-reception-unknown">Sin datos</span>}
          </td>
          {canWrite && <td data-label="Acciones" className="card-table-action">
            <CollarRowActions device={device} assigned={assigned} onAssign={onAssign} onConfigure={onConfigure} onLifecycle={onLifecycle} />
          </td>}
        </tr>;
      })}</tbody>
    </table>
  </div>;
}

function CollarRowActions({ device, assigned, onAssign, onConfigure, onLifecycle }: {
  device: Device;
  assigned: boolean;
  onAssign: (device: Device) => void;
  onConfigure: (device: Device) => void;
  onLifecycle: (action: CollarAction) => void;
}) {
  const assignLabel = assigned ? 'Cambiar bovino' : 'Asignar a un bovino';
  function lifecycleButton(kind: CollarAction['kind'], id: string, Icon: LucideIcon, variant = '') {
    const label = actions[kind].title;
    return <button type="button" className={`icon-button ${variant}`} aria-label={`${label}: ${device.name}`} title={label}
      onClick={() => onLifecycle({ kind, id, name: device.name })}><Icon size={17} aria-hidden="true" /></button>;
  }
  return <div className="row-actions collar-row-actions" role="group" aria-label={`Acciones de ${device.name}`}>
    {device.enabled && <>
      <button type="button" className="icon-button collar-primary-action" aria-label={`${assignLabel}: ${device.name}`} title={assignLabel}
        onClick={() => onAssign(device)}><Link2 size={17} aria-hidden="true" /></button>
      <button type="button" className="icon-button" aria-label={`Configurar intervalo: ${device.name}`}
        title={device.pending_config ? 'Ya hay una configuración pendiente' : 'Configurar intervalo'}
        onClick={() => onConfigure(device)} disabled={!!device.pending_config}><Settings2 size={17} aria-hidden="true" /></button>
    </>}
    {device.assignment_id && lifecycleButton('close', device.assignment_id, Unlink2)}
    {!device.enabled ? lifecycleButton('reactivate', device.id, ArchiveRestore, 'collar-primary-action')
      : !assigned && lifecycleButton('retire', device.id, Archive)}
    {device.can_delete && lifecycleButton('delete', device.id, Trash2, 'collar-danger-action')}
  </div>;
}

export function CollarDialog({ returnFocusTo, ...props }: ComponentProps<typeof Modal> & { returnFocusTo?: HTMLElement | null }) {
  useLayoutEffect(() => {
    const trigger = returnFocusTo ?? document.activeElement;
    return () => queueMicrotask(() => {
      if (trigger instanceof HTMLElement && trigger.isConnected && !document.querySelector('dialog[open]')) {
        trigger.focus({ preventScroll: true });
      }
    });
  }, [returnFocusTo]);
  return <Modal {...props} />;
}

export function CollarLifecycleDialog({ action, onCancel, onSaved, onRefresh }: {
  action: CollarAction;
  onCancel: () => void;
  onSaved: (notice: string) => void;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const { kind, id, name } = action;
  const copy = actions[kind];

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || conflict) return;
    setBusy(true);
    setError('');
    try {
      if (kind === 'close') await write(`/assignments/${id}/close`, {});
      else if (kind === 'delete') await api(`/devices/${id}`, { method: 'DELETE' });
      else await write(`/devices/${id}`, { enabled: kind === 'reactivate' }, 'PATCH');
      onSaved(copy.success);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 403) {
        setError(`No tienes permiso para cambiar este collar en el predio activo. ${failure.message}`);
      } else if (failure instanceof ApiError && failure.status === 409) {
        setError(failure.message);
        setConflict(true);
      } else if (failure instanceof ApiError && failure.status === 422) {
        setError(`No se pudo validar la operación. ${failure.message}`);
      } else setError(message(failure));
    } finally {
      setBusy(false);
    }
  }

  return <CollarDialog title={copy.title} onClose={() => { if (!busy) onCancel(); }}>
    <form className="form-body" onSubmit={submit} aria-busy={busy}>
      <p><strong>{name}</strong>. {copy.description}</p>
      <ErrorNotice error={error} />
      <div className="form-actions">
        <button type="button" className="button secondary" onClick={onCancel} disabled={busy}>Cancelar</button>
        {conflict ? <button type="button" className="button primary" onClick={onRefresh}>Actualizar datos</button>
          : kind === 'delete' ? <button type="submit" className="button collar-danger-submit" disabled={busy}>
            <Trash2 size={17} aria-hidden="true" />{busy ? 'Eliminando…' : copy.title}
          </button> : <Submit busy={busy}>{copy.title}</Submit>}
      </div>
    </form>
  </CollarDialog>;
}
