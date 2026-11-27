import { useState, type FormEvent } from 'react';
import { Building2, Check, Link as LinkIcon, Pencil, Plus, Radio, ShieldCheck, Users } from 'lucide-react';
import { date, message, query, useData, write } from './api';
import { Badge, Empty, ErrorNotice, Loading, Modal, PageTitle, Panel, PanelTitle, Submit } from './ui';
import { StepUpGate } from './V3Account';
import { useVerifiedOperation } from './V3Operation';
import { Pagination } from './PagesAnimals';
import type { Notify } from './App';
import type { List } from './types';
import type { Farm, Invitation, InvitationMailStatus, Member, Trust, UserNotice } from './v3types';
import { changeLabels, roleLabels } from './v3types';
import { useMirror } from './MirrorMode';

export function FarmsPage({ notify, onUpdated, admin = false }: { notify: Notify; admin?: boolean; onUpdated: () => void }) {
  const canWrite = useMirror().canWrite('farm');
  const farms = useData<List<Farm>>('/v3/farms'); const [editing, setEditing] = useState<Farm | 'new' | null>(null);
  return <><PageTitle eyebrow="CUENTA CLIENTE" title={admin ? 'Predios de plataforma' : 'Mis predios'} description="Administra establecimientos y su identificación oficial." actions={canWrite && !admin && <button className="button primary" onClick={() => setEditing('new')}><Plus size={17} />Agregar predio</button>} /><ErrorNotice error={farms.error} retry={farms.reload} />{farms.loading ? <Loading /> : farms.data?.items.length ? <div className="v3-card-grid">{farms.data.items.map(farm => <Panel key={farm.id}><PanelTitle title={farm.name} subtitle={farm.rup ? `RUP ${farm.rup}` : 'RUP sin registrar'} action={<Building2 size={21} />} /><div className="form-body"><p className="form-intro">{farm.address || 'Dirección sin registrar'}</p><div className="v3-card-actions"><Badge status={farm.active === false ? 'unknown' : 'normal'}>{farm.active === false ? 'Inactivo' : 'Activo'}</Badge>{canWrite && <button className="button secondary small" onClick={() => setEditing(farm)}><Pencil size={15} />Editar predio</button>}</div></div></Panel>)}</div> : <Panel><Empty title={canWrite ? 'Agrega tu primer predio' : 'Sin predios para mostrar'} description={canWrite ? 'El cupo disponible lo administra tu cuenta cliente.' : undefined} /></Panel>}{canWrite && editing && <FarmForm farm={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); farms.reload(); onUpdated(); notify('Predio guardado.'); }} />}</>;
}
function FarmForm({ farm, onClose, onSaved }: { farm?: Farm; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(farm?.name ?? ''); const [rup, setRup] = useState(farm?.rup ?? ''); const [address, setAddress] = useState(farm?.address ?? ''); const [active, setActive] = useState(farm?.active !== false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(''); try { await write(`/v3/farms${farm ? `/${farm.id}` : ''}`, { name, rup: rup || null, address: address || null, ...(farm ? { active } : {}) }, farm ? 'PATCH' : 'POST'); onSaved(); } catch (err) { setError(message(err)); } finally { setBusy(false); } }
  return <Modal title={farm ? 'Editar predio' : 'Agregar predio'} onClose={onClose}><form className="form-body" onSubmit={submit}><label>Nombre del predio<input required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></label><label>Rol Único Pecuario (RUP)<input maxLength={30} value={rup} onChange={e => setRup(e.target.value)} /></label><label>Dirección<textarea maxLength={300} rows={3} value={address} onChange={e => setAddress(e.target.value)} /></label>{farm && <label className="checkbox-field"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />Predio activo</label>}<ErrorNotice error={error} /><div className="form-actions"><button className="button secondary" type="button" onClick={onClose}>Cancelar</button><Submit busy={busy}>Guardar predio</Submit></div></form></Modal>;
}
export function TeamPage({ notify, admin }: { notify: Notify; admin: boolean }) {
  return <><PageTitle eyebrow="COLABORACIÓN SEGURA" title="Equipo y permisos" description={admin ? "Administra el acceso de colaboradores ya incorporados al predio." : "Invita trabajadores y veterinarios y define la confianza por acción."} /><StepUpGate admin={admin}><TeamContent notify={notify} admin={admin} /></StepUpGate></>;
}

const invitationStatusLabels = {
  pending: 'Pendiente',
  accepted: 'Aceptada',
  revoked: 'Revocada',
  expired: 'Vencida',
};
type InvitationListEntry = Invitation & { status: keyof typeof invitationStatusLabels };
const invitationMailLabels: Record<InvitationMailStatus, string> = {
  manual: 'Enlace manual',
  pending: 'En cola',
  sent: 'Aceptado por el servidor de correo',
  failed: 'Falló el envío',
  expired: 'Plazo vencido',
  cancelled: 'Cancelado',
};

function TeamContent({ notify, admin }: { notify: Notify; admin: boolean }) {
  const canWrite = useMirror().canWrite('farm');
  const [showExpired, setShowExpired] = useState(false);
  const members = useData<List<Member>>('/v3/memberships');
  const invites = useData<List<InvitationListEntry>>(`/v3/invitations?view=${showExpired ? 'expired' : 'main'}`, 60000);
  const trust = useData<List<Trust>>('/v3/trust');
  const [editing, setEditing] = useState<Member | null>(null); const [inviting, setInviting] = useState(false); const [granting, setGranting] = useState(false); const [revoking, setRevoking] = useState<Trust | null>(null); const [link, setLink] = useState('');
  const refresh = () => { members.reload(); invites.reload(); trust.reload(); };
  function invitationCreated(result: Invitation) {
    setInviting(false);
    setShowExpired(false);
    refresh();
    if (result.invitation_token) setLink(result.invitation_url ?? `${location.origin}${location.pathname}#enrol=${encodeURIComponent(result.invitation_token)}`);
    notify(result.delivery === 'queued' ? 'Invitación creada. El correo está en cola de envío.'
      : 'Invitación creada. Copia el enlace y envíalo al destinatario.');
  }

  const invitationPanel = <Panel>
    <PanelTitle
      title={showExpired ? 'Invitaciones vencidas' : 'Invitaciones'}
      subtitle={showExpired ? undefined : 'Consulta la vigencia, la aceptación y el estado de cada correo.'}
      action={<button className="button secondary small" type="button" onClick={() => setShowExpired(view => !view)}>
        {showExpired ? 'Volver al listado' : 'Ver vencidas'}
      </button>}
    />
    <ErrorNotice error={invites.error} retry={invites.reload} />
    {link && !showExpired && <div className="notice v3-invite-link">
      <LinkIcon size={18} />
      <label>Enlace de enrolamiento<input readOnly value={link} onFocus={e => e.currentTarget.select()} />
        <small>Cópialo y entrégalo únicamente a la persona invitada.</small>
      </label>
    </div>}
    {invites.loading && !invites.data ? <Loading /> : invites.data?.items.length ? (
      <div className="table-scroll">
        <table>
          <thead><tr><th>Correo invitado</th><th>Perfil</th><th>Vencimiento</th><th>Invitación</th><th>Correo al colaborador</th><th>Correo al dueño</th></tr></thead>
          <tbody>{invites.data.items.map(invite => <tr key={invite.id}>
            <td>{invite.email}</td>
            <td>{roleLabels[invite.role_code] ?? invite.role_code}</td>
            <td>{date(invite.expires_at)}</td>
            <td>{invitationStatusLabels[invite.status]}</td>
            <td>{invitationMailLabels[invite.email_status ?? 'manual']}</td>
            <td>{invite.acceptance_email_status ? invitationMailLabels[invite.acceptance_email_status] : '—'}</td>
          </tr>)}</tbody>
        </table>
      </div>
    ) : !invites.error && <Empty title={showExpired ? 'No hay invitaciones vencidas' : 'No hay invitaciones en el listado'} />}
  </Panel>;

  return <>{admin && <div className="notice"><ShieldCheck size={18} /><span>Soporte administra los colaboradores ya incorporados. Las invitaciones de trabajadores y veterinarios las emite el dueño del predio.</span></div>}<Panel><PanelTitle title="Colaboradores del predio" subtitle="La revocación afecta a esta membresía y conserva la autoría histórica." action={canWrite && !admin && <button className="button primary small" onClick={() => setInviting(true)}><Plus size={16} />Invitar usuario</button>} /><ErrorNotice error={members.error} retry={members.reload} />{members.loading ? <Loading /> : members.data?.items.length ? <div className="table-scroll"><table><thead><tr><th>Persona</th><th>Correo</th><th>Perfil</th><th>Acceso</th><th>Acciones</th></tr></thead><tbody>{members.data.items.map(member => <tr key={member.id}><td>{member.full_name || member.username || 'Usuario'}</td><td>{member.email || member.username}</td><td>{roleLabels[member.role_code] ?? member.role_code}</td><td><Badge status={member.active === false ? 'unknown' : 'normal'}>{member.active === false ? 'Revocado' : 'Activo'}</Badge></td><td>{canWrite && member.active !== false && ['worker', 'veterinarian'].includes(member.role_code) ? <button className="button secondary small" onClick={() => setEditing(member)}><Pencil size={14} />Modificar acceso</button> : <span className="neutral-tag">{member.active === false ? 'Histórico' : canWrite ? 'Acceso del titular' : 'Vigente'}</span>}</td></tr>)}</tbody></table></div> : <Empty title="Sin colaboradores" description="Invita al equipo que trabaja en este predio." />}</Panel>{invitationPanel}<Panel><PanelTitle title="Confianza de trabajadores" subtitle="Permite aplicar una acción concreta sin aprobación posterior del dueño." action={canWrite && <button className="button secondary small" onClick={() => setGranting(true)}><ShieldCheck size={16} />Conceder confianza</button>} /><ErrorNotice error={trust.error} retry={trust.reload} />{trust.loading ? <Loading /> : trust.data?.items.filter(t => !t.revoked_at && !t.valid_to).length ? <div className="table-scroll"><table><thead><tr><th>Trabajador</th><th>Acción autorizada</th><th>Acciones</th></tr></thead><tbody>{trust.data.items.filter(t => !t.revoked_at && !t.valid_to).map(t => <tr key={t.id}><td>{members.data?.items.find(m => m.id === t.membership_id)?.full_name || members.data?.items.find(m => m.id === t.membership_id)?.email || t.membership_id}</td><td>{changeLabels[t.action] ?? t.action}</td><td>{canWrite && <button className="button secondary small" onClick={() => setRevoking(t)}>Revocar confianza</button>}</td></tr>)}</tbody></table></div> : <Empty title="Sin confianza directa concedida" description="Los cambios de trabajadores quedan pendientes de tu revisión." />}</Panel>{canWrite && !admin && inviting && <InviteForm onClose={() => setInviting(false)} onSaved={invitationCreated} />}{canWrite && editing && <MemberForm member={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); notify('Acceso del colaborador actualizado.'); }} />}{canWrite && granting && <TrustForm members={members.data?.items ?? []} onClose={() => setGranting(false)} onSaved={() => { setGranting(false); trust.reload(); notify('Confianza por acción guardada.'); }} />}{canWrite && revoking && <RevokeTrustForm trust={revoking} onClose={() => setRevoking(null)} onSaved={() => { setRevoking(null); trust.reload(); notify('Confianza revocada. Las próximas acciones requerirán revisión.'); }} />}</>;
}
function InviteForm({ onClose, onSaved }: { onClose: () => void; onSaved: (result: Invitation) => void }) {
  const [email, setEmail] = useState(''); const [role, setRole] = useState('worker'); const [confirmed, setConfirmed] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const verification = useVerifiedOperation(busy);
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(''); try { onSaved(await verification.perform<Invitation>('/v3/invitations', { email, role_code: role })); } catch (err) { setError(message(err)); } finally { setBusy(false); } }
  return <Modal title="Invitar colaborador" onClose={onClose}><form className="form-body" onSubmit={submit}><label>Correo del destinatario<input type="email" required value={email} onChange={e => setEmail(e.target.value)} /></label><label>Perfil<select value={role} onChange={e => setRole(e.target.value)}><option value="worker">Trabajador</option><option value="veterinarian">Veterinario</option></select></label><p className="form-intro">{role === 'veterinarian' ? 'El veterinario puede modificar fichas técnicas y sanitarias directamente.' : 'El trabajador propone cambios; la confianza se concede por acción después del enrolamiento.'}</p><label className="checkbox-field"><input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Confirmo el correo, el perfil y el predio seleccionado.</label>{verification.fields}<ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose}>Cancelar</button><Submit busy={busy}>Crear invitación</Submit></div></form></Modal>;
}
function MemberForm({ member, onClose, onSaved }: { member: Member; onClose: () => void; onSaved: () => void }) {
  const [role, setRole] = useState(member.role_code); const [active, setActive] = useState(member.active !== false); const [confirmed, setConfirmed] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const verification = useVerifiedOperation(busy);
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(''); try { await verification.perform(`/v3/memberships/${member.id}`, { role_code: role, active }, 'PATCH'); onSaved(); } catch (err) { setError(message(err)); } finally { setBusy(false); } }
  return <Modal title="Modificar acceso al predio" onClose={onClose}><form className="form-body" onSubmit={submit}><p>{member.full_name || member.email}</p><label>Perfil<select value={role} onChange={e => setRole(e.target.value as Member['role_code'])}><option value="worker">Trabajador</option><option value="veterinarian">Veterinario</option></select></label><label className="checkbox-field"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />Membresía activa</label><label className="checkbox-field"><input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Confirmo el cambio de acceso en este predio.</label>{verification.fields}<ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose}>Cancelar</button><Submit busy={busy}>Guardar acceso</Submit></div></form></Modal>;
}
function TrustForm({ members, onClose, onSaved }: { members: Member[]; onClose: () => void; onSaved: () => void }) {
  const [member, setMember] = useState(''); const [action, setAction] = useState('health_record'); const [confirmed, setConfirmed] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const verification = useVerifiedOperation(busy);
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(''); try { await verification.perform('/v3/trust', { membership_id: member, action }); onSaved(); } catch (err) { setError(message(err)); } finally { setBusy(false); } }
  return <Modal title="Conceder confianza por acción" onClose={onClose}><form className="form-body" onSubmit={submit}><label>Trabajador<select required value={member} onChange={e => setMember(e.target.value)}><option value="">Selecciona un trabajador activo</option>{members.filter(m => m.role_code === 'worker' && m.active !== false).map(m => <option key={m.id} value={m.id}>{m.full_name || m.email}</option>)}</select></label><label>Acción<select value={action} onChange={e => setAction(e.target.value)}>{['health_record', 'animal_status', 'animal_report', 'battery_replacement'].map(a => <option key={a} value={a}>{changeLabels[a]}</option>)}</select></label><label className="checkbox-field"><input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Autorizo esta acción directa y acepto que conserve la autoría del trabajador.</label>{verification.fields}<ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose}>Cancelar</button><Submit busy={busy}>Conceder confianza</Submit></div></form></Modal>;
}
function RevokeTrustForm({ trust, onClose, onSaved }: { trust: Trust; onClose: () => void; onSaved: () => void }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const verification = useVerifiedOperation(busy);
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { await verification.perform(`/v3/trust/${trust.id}`, {}, 'DELETE'); onSaved(); } catch (err) { setError(message(err)); } finally { setBusy(false); } }
  return <Modal title="Revocar confianza" onClose={onClose}><form className="form-body" onSubmit={submit}><p>Las próximas acciones de «{changeLabels[trust.action] ?? trust.action}» volverán a requerir aprobación del dueño.</p>{verification.fields}<ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cancelar</button><Submit busy={busy}>Confirmar revocación</Submit></div></form></Modal>;
}
export { GatewaysPage } from './GatewayManagement';
export function UserNotifications({ notify, onChange }: { notify: Notify; onChange: () => void }) {
  const canMarkRead = useMirror().canWrite('notice_read');
  const [unread, setUnread] = useState(false);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const limit = 25;
  const notices = useData<List<UserNotice>>('/v3/notifications' + query({
    unread: unread ? 'true' : '', offset: String(offset), limit: String(limit),
  }));
  function reload() { notices.reload(); onChange(); }
  async function mark(id: string) {
    setBusy(id); setError('');
    try {
      await write(`/v3/notifications/${id}/read`, {});
      if (unread && offset && notices.data?.items.length === 1) setOffset(Math.max(0, offset - limit));
      reload(); notify('Aviso marcado como leído.');
    }
    catch (err) { setError(message(err)); }
    finally { setBusy(''); }
  }
  return <>
    <PageTitle eyebrow="TU ACTIVIDAD" title="Avisos personales" description="Solicitudes, decisiones y novedades dirigidas a tu cuenta."
      actions={<button className="button secondary" onClick={reload}>Actualizar</button>} />
    <Panel>
      <div className="list-toolbar">
        <label>Mostrar<select value={unread ? 'unread' : 'all'} onChange={event => {
          setUnread(event.target.value === 'unread'); setOffset(0); setError('');
        }}><option value="all">Todos los avisos</option><option value="unread">Avisos sin leer</option></select></label>
      </div>
      <ErrorNotice error={error || notices.error} retry={reload} />
      {notices.loading ? <Loading /> : notices.data?.items.length ? <div className="v3-notices">
        {notices.data.items.map(n => {
          const body = n.body || n.message || n.status || 'Actividad registrada';
          const action = body.match(/^(Solicitud pendiente|Cambio aplicado): (\w+)$/);
          return <article key={n.id}>
            <div><strong>{n.title || 'Aviso de GeoCattle'}</strong>
              <p>{action && changeLabels[action[2]] ? `${action[1]} · ${changeLabels[action[2]]}` : body}</p>
              <small>{date(n.created_at)}</small>
            </div>
            <div className="v3-inline-actions">
              {n.request_id && <a className="button secondary small" href={`#changes?request=${encodeURIComponent(n.request_id)}`}>Abrir solicitud</a>}
              {n.read_at ? <span className="neutral-tag"><Check size={14} />Leído</span>
                : canMarkRead && <button className="button secondary small" disabled={busy === n.id} onClick={() => mark(n.id)}>Marcar leído</button>}
            </div>
          </article>;
        })}
      </div> : <Empty title={unread ? 'Sin avisos sin leer' : 'Sin avisos personales'} description="Los cambios y decisiones relevantes aparecerán aquí." />}
      {notices.data && (offset > 0 || notices.data.total > limit) &&
        <Pagination offset={offset} count={notices.data.items.length} total={notices.data.total} limit={limit} onChange={setOffset} />}
    </Panel>
  </>;
}
