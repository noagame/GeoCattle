import React, { useState, type FormEvent } from 'react';
import { Plus, Radio, RefreshCw, Trash2 } from 'lucide-react';
import type { DeviceCandidate, DeviceCandidateApprove, DeviceCandidateApproveResult } from './v3types';
import { ApiError, date, write } from './api';
import { Empty, ErrorNotice, Loading, Modal, Panel, PanelTitle, Submit } from './ui';
import type { Notify } from './App';

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

export function DeviceCandidatesPanel({
  canWrite,
  notify,
  candidates,
  onApproved,
  onDismissed,
}: {
  canWrite: boolean;
  notify: Notify;
  candidates: {
    data: { items: DeviceCandidate[] } | null;
    loading: boolean;
    error: string;
    reload: () => void;
  };
  onApproved: () => void;
  onDismissed: () => void;
}) {
  const [approving, setApproving] = useState<DeviceCandidate | null>(null);
  const [dismissing, setDismissing] = useState<DeviceCandidate | null>(null);

  const pendingItems = candidates.data?.items ?? [];

  return (
    <Panel className="candidates-panel">
      <PanelTitle
        title="Collares detectados"
        subtitle="Módulos reconocidos por USB o tramas de radio pendientes de incorporación al inventario del predio."
        action={
          <button
            className="button secondary small"
            type="button"
            onClick={candidates.reload}
            disabled={candidates.loading}
          >
            <RefreshCw size={15} className={candidates.loading ? 'spin' : ''} />
            Actualizar
          </button>
        }
      />
      <ErrorNotice error={candidates.error} retry={candidates.reload} />
      {candidates.loading && !candidates.data && <Loading label="Consultando collares detectados…" />}
      {!candidates.loading && candidates.data && (
        pendingItems.length > 0 ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Collar detectado</th>
                  <th>Origen</th>
                  <th>Transporte</th>
                  <th>Intervalo</th>
                  <th>Firmware</th>
                  <th>Detección</th>
                  <th>Veces visto</th>
                  {canWrite && <th>Acciones</th>}
                </tr>
              </thead>
              <tbody>
                {pendingItems.map(candidate => (
                  <tr key={candidate.id}>
                    <td>
                      <div className="animal-cell">
                        <span className="animal-avatar">
                          <Radio size={18} />
                        </span>
                        <div>
                          <strong>{candidate.suggested_name}</strong>
                          <small>{candidate.hardware_id}</small>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className="neutral-tag">
                        {candidate.source === 'usb' ? 'USB' : 'Radio'}
                      </span>
                    </td>
                    <td>
                      {candidate.transport === 'academic' ? 'Académico' : 'LoRaWAN'}
                      {candidate.dev_eui && <small>{candidate.dev_eui}</small>}
                    </td>
                    <td>
                      <strong>{candidate.interval_seconds} s</strong>
                    </td>
                    <td>
                      {candidate.firmware_version || <span className="muted">—</span>}
                    </td>
                    <td>
                      <div>
                        <strong>{date(candidate.last_seen_at)}</strong>
                        <small>Primera: {date(candidate.first_seen_at)}</small>
                      </div>
                    </td>
                    <td>
                      <span>{candidate.seen_count} {candidate.seen_count === 1 ? 'vez' : 'veces'}</span>
                    </td>
                    {canWrite && (
                      <td>
                        <div className="row-actions">
                          <button
                            className="button primary small"
                            type="button"
                            onClick={() => setApproving(candidate)}
                          >
                            <Plus size={14} />
                            Agregar al sistema
                          </button>
                          <button
                            className="button secondary small"
                            type="button"
                            onClick={() => setDismissing(candidate)}
                          >
                            <Trash2 size={14} />
                            Descartar
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            compact
            icon={<Radio size={18} />}
            title="Sin collares detectados pendientes"
            description="Los collares conectados por USB o reconocidos mediante radio aparecerán automáticamente aquí para su incorporación."
          />
        )
      )}

      {approving && (
        <ApproveCandidateModal
          candidate={approving}
          onClose={() => setApproving(null)}
          onApproved={() => {
            setApproving(null);
            onApproved();
          }}
          notify={notify}
        />
      )}

      {dismissing && (
        <DismissCandidateModal
          candidate={dismissing}
          onClose={() => setDismissing(null)}
          onDismissed={() => {
            setDismissing(null);
            onDismissed();
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
    <Modal title={`Agregar collar ${candidate.hardware_id} al sistema`} onClose={onClose}>
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
    </Modal>
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
    <Modal title={`Descartar collar detectado`} onClose={onClose}>
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
    </Modal>
  );
}
