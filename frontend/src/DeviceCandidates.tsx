import React, { useEffect, useRef, useState, type FormEvent } from 'react';
import { Info, Plus, Radio, RefreshCw, Trash2, Usb } from 'lucide-react';
import type { DeviceCandidate, DeviceCandidateApprove, DeviceCandidateApproveResult } from './v3types';
import { ApiError, date, write } from './api';
import { detectUsbCollar } from './collarSerial';
import { CollarDialog, collarTimestamp } from './CollarLifecycle';
import { Empty, ErrorNotice, Loading, Panel, PanelTitle, Submit } from './ui';
import type { Notify } from './App';

const usbProgress = {
  selecting: 'Selecciona el puerto USB del collar, no el de la receptora.',
  identifying: 'Esperando identificación…',
  legacy: 'Firmware anterior: esperando el próximo envío (hasta 55 s)…',
  saving: 'Guardando la detección en el predio activo…',
};

export type CandidateApprovalInput = {
  name: string;
  hardware_id: string;
  transport: 'academic' | 'lorawan';
  interval_seconds: number | string;
  dev_eui?: string | null;
  installed_at?: string | null;
  enabled?: boolean;
};

export type CandidateValidationResult =
  | { ok: true; payload: DeviceCandidateApprove }
  | { ok: false; error: string };

export function validateCandidateApproval(input: CandidateApprovalInput): CandidateValidationResult {
  const trimmedName = (input.name ?? '').trim();
  if (!trimmedName) {
    return { ok: false, error: 'Ingresa un nombre para el collar.' };
  }
  const intervalNum = typeof input.interval_seconds === 'number'
    ? input.interval_seconds
    : Number(input.interval_seconds);
  if (!Number.isInteger(intervalNum) || intervalNum < 30 || intervalNum > 86400) {
    return { ok: false, error: 'El intervalo debe estar entre 30 y 86400 segundos.' };
  }
  const rawDevEui = (input.dev_eui ?? '').trim().toLowerCase();
  if (input.transport === 'lorawan' && !rawDevEui) {
    return { ok: false, error: 'El DevEUI es obligatorio para transporte LoRaWAN.' };
  }
  if (rawDevEui && !/^[0-9a-f]{16}$/.test(rawDevEui)) {
    return { ok: false, error: 'El DevEUI debe contener exactamente 16 caracteres hexadecimales.' };
  }

  let installedAtIso: string;
  if (input.installed_at && input.installed_at.trim()) {
    const parsed = new Date(input.installed_at);
    if (!Number.isNaN(parsed.getTime())) {
      installedAtIso = parsed.toISOString();
    } else {
      installedAtIso = new Date().toISOString();
    }
  } else {
    installedAtIso = new Date().toISOString();
  }

  return {
    ok: true,
    payload: {
      name: trimmedName,
      interval_seconds: intervalNum,
      installed_at: installedAtIso,
      dev_eui: rawDevEui || null,
      enabled: input.enabled !== false,
    },
  };
}

export function UsbCollarDetection({ onDetected, onCandidatesChange }: {
  onDetected: (candidate: DeviceCandidate) => void;
  onCandidatesChange: () => void;
}) {
  const [usbStage, setUsbStage] = useState<keyof typeof usbProgress | null>(null);
  const [usbBusy, setUsbBusy] = useState(false);
  const [usbError, setUsbError] = useState('');
  const usbRun = useRef<AbortController | null>(null);
  const detectButton = useRef<HTMLButtonElement>(null);

  useEffect(() => () => {
    usbRun.current?.abort();
    usbRun.current = null;
  }, []);

  async function detectCollar() {
    if (usbRun.current) return;
    const run = new AbortController();
    usbRun.current = run;
    setUsbBusy(true);
    setUsbError('');
    try {
      const descriptor = await detectUsbCollar({ signal: run.signal, onProgress: setUsbStage });
      run.signal.throwIfAborted();
      setUsbStage('saving');
      const candidate = await write<DeviceCandidate>('/v3/device-candidates', { ...descriptor, source: 'usb' });
      if (usbRun.current !== run) return;
      if (!candidate.id || candidate.status !== 'pending') throw new Error('El servidor no confirmó la detección USB. Actualiza la bandeja y vuelve a intentarlo.');
      onCandidatesChange();
      if (!run.signal.aborted) onDetected(candidate);
    } catch (error) {
      if (!run.signal.aborted) {
        setUsbError(error instanceof ApiError && error.status === 409
          ? 'Ese collar ya está registrado. Busca su identificador en el inventario de dispositivos.'
          : error instanceof Error ? error.message : 'No se pudo detectar el collar. Reconéctalo y vuelve a intentarlo.');
      }
    } finally {
      if (usbRun.current === run) {
        usbRun.current = null;
        setUsbStage(null);
        setUsbBusy(false);
      }
    }
  }

  function closeDetection() {
    usbRun.current?.abort();
    setUsbStage(null);
    setUsbError('');
  }

  return <>
    <button className="button primary" type="button" onClick={detectCollar} disabled={usbBusy} ref={detectButton}>
      <Usb size={17} aria-hidden="true" />Detectar collar por USB
    </button>
    {(usbStage || usbError) && <CollarDialog title="Detectar collar por USB" onClose={closeDetection} returnFocusTo={detectButton.current}>
      <div className="form-body">
        <p className="collar-usb-note"><Info size={16} aria-hidden="true" />Conecta el collar por USB al equipo donde está abierto este navegador.</p>
        {usbStage && <p role="status">{usbProgress[usbStage]}</p>}
        <ErrorNotice error={usbError} />
        <div className="form-actions">
          <button className="button secondary" type="button" onClick={closeDetection}>{usbError ? 'Cerrar' : 'Cancelar'}</button>
        </div>
      </div>
    </CollarDialog>}
  </>;
}

export function DeviceCandidatesPanel({
  canWrite, notify, candidates, approving, onApprove, onApproved, onCandidatesChange, now = Date.now(),
}: {
  canWrite: boolean;
  notify: Notify;
  candidates: {
    data: { items: DeviceCandidate[] } | null;
    loading: boolean;
    error: string;
    reload: () => void;
  };
  approving: DeviceCandidate | null;
  onApprove: (candidate: DeviceCandidate | null) => void;
  onApproved: () => void;
  onCandidatesChange: () => void;
  now?: number;
}) {
  const [dismissing, setDismissing] = useState<DeviceCandidate | null>(null);
  const pendingItems = candidates.data?.items ?? [];
  const hasPending = pendingItems.length > 0;
  const refresh = <button className="icon-button collar-candidate-refresh" type="button" onClick={candidates.reload}
    disabled={candidates.loading} title="Actualizar collares detectados" aria-label="Actualizar collares detectados">
    <RefreshCw size={16} aria-hidden="true" className={candidates.loading ? 'spin' : ''} />
  </button>;

  return (
    <Panel className={'candidates-panel' + (hasPending ? ' collar-candidates-pending' : '')}>
      {(!candidates.data || hasPending) && <PanelTitle
        title="Collares detectados"
        subtitle="Revisa los collares detectados por USB o radio antes de agregarlos al inventario."
        action={<div className="collar-candidate-tools">
          {hasPending && <span className="collar-pending-count">{pendingItems.length} {pendingItems.length === 1 ? 'pendiente' : 'pendientes'}</span>}
          {refresh}
        </div>}
      />}
      <ErrorNotice error={candidates.error} retry={candidates.reload} />
      {candidates.loading && !candidates.data && <Loading label="Consultando collares detectados…" />}
      {candidates.data && (
        hasPending ? (
          <div className="table-scroll">
            <table className="card-table collar-table" aria-label="Collares detectados">
              <thead>
                <tr>
                  <th scope="col">Collar detectado</th>
                  <th scope="col">Origen</th>
                  <th scope="col">Detalles</th>
                  <th scope="col">Detección</th>
                  {canWrite && <th scope="col">Acciones</th>}
                </tr>
              </thead>
              <tbody>
                {pendingItems.map(candidate => {
                  const last = collarTimestamp(candidate.last_seen_at, now);
                  const first = collarTimestamp(candidate.first_seen_at, now);
                  const detectionTitle = [last && 'Última detección: ' + last.exact, first && 'Primera detección: ' + first.exact].filter(Boolean).join(' · ');
                  return <tr key={candidate.id}>
                    <td data-label="Collar detectado">
                      <div className="animal-cell">
                        <span className="animal-avatar" aria-hidden="true"><Radio size={18} /></span>
                        <div><strong>{candidate.suggested_name}</strong><small>{candidate.hardware_id}</small></div>
                      </div>
                    </td>
                    <td data-label="Origen"><span className="neutral-tag">{candidate.source === 'usb' ? 'USB' : 'Radio'}</span></td>
                    <td data-label="Detalles">
                      {candidate.transport === 'academic' ? 'Académico' : 'LoRaWAN'} · {candidate.interval_seconds} s · firmware {candidate.firmware_version || '—'}
                      {candidate.dev_eui && <small>{candidate.dev_eui}</small>}
                    </td>
                    <td data-label="Detección">
                      {last ? <time dateTime={last.value} title={detectionTitle}>{last.relative}</time> : 'Sin datos'}
                      {' · '}{candidate.seen_count} {candidate.seen_count === 1 ? 'vez' : 'veces'}
                    </td>
                    {canWrite && <td data-label="Acciones" className="card-table-action">
                      <div className="row-actions collar-row-actions" role="group" aria-label={'Acciones de ' + candidate.suggested_name}>
                        <button className="button primary small" type="button" aria-label={'Agregar al sistema: ' + candidate.suggested_name}
                          onClick={() => onApprove(candidate)}><Plus size={15} aria-hidden="true" />Agregar</button>
                        <button className="icon-button collar-danger-action" type="button" aria-label={'Descartar: ' + candidate.suggested_name}
                          title="Descartar" onClick={() => setDismissing(candidate)}><Trash2 size={17} aria-hidden="true" /></button>
                      </div>
                    </td>}
                  </tr>;
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            compact
            icon={<Radio size={18} />}
            title="Sin collares detectados pendientes"
            action={refresh}
          />
        )
      )}

      {canWrite && approving && (
        <ApproveCandidateModal
          candidate={approving}
          onClose={() => onApprove(null)}
          onApproved={() => {
            onApprove(null);
            onApproved();
          }}
          notify={notify}
        />
      )}

      {canWrite && dismissing && (
        <DismissCandidateModal
          candidate={dismissing}
          onClose={() => setDismissing(null)}
          onDismissed={() => {
            setDismissing(null);
            onCandidatesChange();
          }}
          notify={notify}
        />
      )}
    </Panel>
  );
}

function ApproveCandidateModal({
  candidate,
  onClose,
  onApproved,
  notify,
}: {
  candidate: DeviceCandidate;
  onClose: () => void;
  onApproved: () => void;
  notify: Notify;
}) {
  const [name, setName] = useState(candidate.suggested_name || '');
  const transport = candidate.transport;
  const [devEui, setDevEui] = useState(candidate.dev_eui || '');
  const [interval, setInterval] = useState(String(candidate.interval_seconds ?? 300));
  const [installedAt, setInstalledAt] = useState(() => {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  });
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault();
    const validation = validateCandidateApproval({
      name,
      hardware_id: candidate.hardware_id,
      transport,
      interval_seconds: interval,
      dev_eui: devEui,
      installed_at: installedAt,
      enabled,
    });

    if (!validation.ok) {
      setError(validation.error);
      return;
    }

    setBusy(true);
    setError('');
    try {
      await write<DeviceCandidateApproveResult>(
        `/v3/device-candidates/${candidate.id}/approve`,
        validation.payload
      );
      notify(`Collar ${validation.payload.name} (${candidate.hardware_id}) agregado al sistema.`);
      onApproved();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError('El identificador de hardware ya está registrado en este predio.');
          return;
        }
        if (err.status === 403) {
          setError('No tienes permisos para agregar dispositivos a este predio.');
          return;
        }
      }
      setError(err instanceof Error ? err.message : 'No se pudo agregar el collar al sistema.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <CollarDialog title={`Agregar collar ${candidate.hardware_id} al sistema`} onClose={onClose}>
      <form className="form-body" onSubmit={submit}>
        <p className="form-intro">
          Revisa y confirma la configuración del collar detectado por {candidate.source === 'usb' ? 'USB' : 'radio'} antes de incorporarlo al inventario activo.
        </p>
        <label>
          Nombre
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            required
            maxLength={100}
            placeholder="Collar / módulo"
          />
        </label>
        <label>
          Identificador de hardware
          <input value={candidate.hardware_id} readOnly disabled />
        </label>
        <label>
          Transporte
          <input value={transport === 'academic' ? 'Prototipo · LoRa punto a punto' : 'Cliente · LoRaWAN'} readOnly disabled />
        </label>
        <label>
          DevEUI {transport === 'academic' && '(opcional)'}
          <input
            value={devEui}
            onChange={e => setDevEui(e.target.value)}
            required={transport === 'lorawan'}
            pattern="[0-9a-fA-F]{16}"
            placeholder="16 caracteres hexadecimales"
          />
          <small>16 dígitos hexadecimales (0-9, a-f).</small>
        </label>
        <label>
          Intervalo inicial (segundos)
          <input
            type="number"
            min="30"
            max="86400"
            step="1"
            value={interval}
            onChange={e => setInterval(e.target.value)}
            required
          />
          <small>Rango permitido: 30 a 86400 segundos.</small>
        </label>
        <label>
          Fecha de instalación
          <input
            type="datetime-local"
            value={installedAt}
            onChange={e => setInstalledAt(e.target.value)}
            required
          />
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={enabled}
            onChange={e => setEnabled(e.target.checked)}
          />
          <span>Habilitar dispositivo de inmediato para recepción</span>
        </label>
        <ErrorNotice error={error} />
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <Submit busy={busy}>Agregar al sistema</Submit>
        </div>
      </form>
    </CollarDialog>
  );
}

function DismissCandidateModal({
  candidate,
  onClose,
  onDismissed,
  notify,
}: {
  candidate: DeviceCandidate;
  onClose: () => void;
  onDismissed: () => void;
  notify: Notify;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submitDismiss() {
    setBusy(true);
    setError('');
    try {
      await write(`/v3/device-candidates/${candidate.id}/dismiss`, {});
      notify(`Collar detectado ${candidate.hardware_id} descartado.`);
      onDismissed();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('No tienes permisos para descartar collares en este predio.');
        return;
      }
      setError(err instanceof Error ? err.message : 'No se pudo descartar el collar detectado.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <CollarDialog title="Descartar collar detectado" onClose={onClose}>
      <div className="form-body">
        <p className="form-intro">
          ¿Confirmas que deseas descartar el collar <strong>{candidate.suggested_name}</strong> con identificador <code>{candidate.hardware_id}</code>?
          Se eliminará de la bandeja de collares pendientes.
        </p>
        <ErrorNotice error={error} />
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button
            type="button"
            className="button primary"
            onClick={submitDismiss}
            disabled={busy}
          >
            {busy ? 'Descartando…' : 'Descartar collar'}
          </button>
        </div>
      </div>
    </CollarDialog>
  );
}
