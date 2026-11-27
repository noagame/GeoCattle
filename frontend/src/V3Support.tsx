import { useState, type FormEvent } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { date, message, query, useData, write } from './api';
import type { Notify } from './App';
import { Pagination } from './PagesAnimals';
import type { List } from './types';
import { Badge, Empty, ErrorNotice, Loading, Modal, PageTitle, Panel, Submit } from './ui';
import type { SupportKind, SupportRequest, SupportStatus } from './v3types';
import { useMirror } from './MirrorMode';
import { isQueuedWrite, mirrorPollInterval, supportRequestsPath as path } from './mirror';

const kindLabels: Record<SupportKind, string> = {
  close_account: 'Cierre de cuenta',
  change_email: 'Cambio de correo',
  access_issue: 'Problema de acceso',
};
const statusLabels: Record<SupportStatus, string> = {
  pending: 'Pendiente',
  resolved: 'Resuelta',
  rejected: 'Rechazada',
};
const pageSize = 25;

export function SupportPage({ admin, notify, onChange }: { admin: boolean; notify: Notify; onChange: () => void }) {
  const { replica, canWrite } = useMirror();
  const canCreate = !admin && canWrite('support_request');
  const canReview = admin && canWrite('admin');
  const canMarkRead = !admin && canWrite('account');
  const [status, setStatus] = useState<SupportStatus | ''>(admin ? 'pending' : '');
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(!admin && location.hash === '#support?kind=change_email');
  const [review, setReview] = useState<SupportRequest | null>(null);
  const [reading, setReading] = useState('');
  const [error, setError] = useState('');
  const requests = useData<List<SupportRequest>>(path + query({
    admin: admin ? 'true' : '', status, limit: String(pageSize), offset: String(offset),
  }), replica && !admin ? mirrorPollInterval : 0);
  function reload() { requests.reload(); onChange(); }
  async function markRead(id: string) {
    setReading(id);
    setError('');
    try { await write(`${path}/${id}/read`, {}); reload(); }
    catch (err) { setError(message(err)); }
    finally { setReading(''); }
  }
  const total = requests.data?.total ?? 0;
  return <>
    <PageTitle eyebrow="SOPORTE DE PLATAFORMA" title={admin ? 'Solicitudes de soporte' : 'Mis solicitudes a soporte'}
      description={admin ? 'Revisa los casos y responde a la persona que solicitó ayuda.' : 'Envía una solicitud privada a administración y consulta su respuesta.'}
      actions={<>
        <button className="button secondary" onClick={reload}><RefreshCw size={16} />Actualizar</button>
        {canCreate && <button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />Nueva solicitud</button>}
      </>} />
    <Panel>
      <div className="list-toolbar">
        <label>Estado<select value={status} onChange={event => { setStatus(event.target.value as SupportStatus | ''); setOffset(0); }}>
          <option value="">Todos los estados</option>
          {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <span className="list-count">{total} solicitudes</span>
      </div>
      <ErrorNotice error={error || requests.error} retry={reload} />
      {requests.loading && !requests.data ? <Loading /> : requests.data?.items.length ? <div className="v3-changes">
        {requests.data.items.map(item => <article key={item.id}>
          <div className="v3-change-header">
            <div><strong>{kindLabels[item.kind]}</strong>
              <small>{date(item.created_at)}{admin && ` · ${item.requester_name} · ${item.requester_email}`}</small>
              <small>Folio {item.id}</small>
            </div>
            <Badge status={item.status === 'pending' ? 'warning' : item.status === 'resolved' ? 'normal' : 'critical'}>
              {statusLabels[item.status]}
            </Badge>
          </div>
          <p>{item.description}</p>
          {item.response && <div className="v3-treatment"><strong>Respuesta de administración · {date(item.resolved_at)}</strong><p className="support-response">{item.response}</p></div>}
          <div className="v3-inline-actions">
            {canReview && item.status === 'pending' && <button className="button secondary small" onClick={() => setReview(item)}>Responder solicitud</button>}
            {canMarkRead && item.response && !item.read_at && <button className="button secondary small" disabled={reading === item.id} onClick={() => markRead(item.id)}>Marcar respuesta como leída</button>}
          </div>
        </article>)}
      </div> : <Empty title="Sin solicitudes en esta vista" description="Las solicitudes que coincidan con el filtro aparecerán aquí." />}
      {requests.data && (offset > 0 || total > pageSize) &&
        <Pagination offset={offset} count={requests.data.items.length} total={total} limit={pageSize} onChange={setOffset} />}
    </Panel>
    {canCreate && creating && <SupportForm onClose={() => setCreating(false)} onSaved={queued => {
      setCreating(false); setStatus(''); setOffset(0); reload();
      if (!queued) notify('Solicitud enviada a administración.');
    }} />}
    {canReview && review && <SupportDecisionForm item={review} onClose={() => setReview(null)} onSaved={() => {
      setReview(null);
      if (status === 'pending' && offset && requests.data?.items.length === 1) setOffset(Math.max(0, offset - pageSize));
      reload(); notify('Respuesta guardada y disponible para el solicitante.');
    }} />}
  </>;
}

function SupportForm({ onClose, onSaved }: { onClose: () => void; onSaved: (queued: boolean) => void }) {
  const [kind, setKind] = useState<'change_email' | 'access_issue'>(location.hash === '#support?kind=change_email' ? 'change_email' : 'access_issue');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const result = await write(path, { kind, description }); onSaved(isQueuedWrite(result)); }
    catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }
  return <Modal title="Nueva solicitud de soporte" onClose={onClose}>
    <form className="form-body" onSubmit={submit}>
      <label>Tipo de solicitud<select value={kind} onChange={event => setKind(event.target.value as typeof kind)}>
        <option value="access_issue">Problema de acceso</option>
        <option value="change_email">Cambio de correo</option>
      </select></label>
      <label>Describe tu solicitud<textarea required maxLength={2000} rows={4} value={description} onChange={event => setDescription(event.target.value)} />
        <small>Guarda tus contraseñas y códigos de verificación en privado.</small>
      </label>
      <ErrorNotice error={error} />
      <div className="form-actions"><Submit busy={busy}>Enviar a administración</Submit></div>
    </form>
  </Modal>;
}

function SupportDecisionForm({ item, onClose, onSaved }: { item: SupportRequest; onClose: () => void; onSaved: () => void }) {
  const [status, setStatus] = useState<'resolved' | 'rejected'>('resolved');
  const [response, setResponse] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const result = await write(`${path}/${item.id}/decision`, { status, response });
      if (isQueuedWrite(result)) onClose(); else onSaved(); }
    catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }
  return <Modal title={`Responder · ${kindLabels[item.kind]}`} onClose={onClose}>
    <form className="form-body" onSubmit={submit}>
      <p className="form-intro">Indica al solicitante las acciones realizadas o los pasos siguientes.</p>
      <label>Decisión<select value={status} onChange={event => setStatus(event.target.value as typeof status)}>
        <option value="resolved">Marcar como resuelta</option>
        <option value="rejected">Rechazar solicitud</option>
      </select></label>
      <label>Respuesta<textarea required maxLength={2000} rows={4} value={response} onChange={event => setResponse(event.target.value)} /></label>
      <ErrorNotice error={error} />
      <div className="form-actions"><Submit busy={busy}>Guardar respuesta</Submit></div>
    </form>
  </Modal>;
}
