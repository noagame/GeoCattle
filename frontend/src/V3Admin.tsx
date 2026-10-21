import { useEffect, useState, type FormEvent } from 'react';
import { Activity, BarChart3, Building2, Cpu, KeyRound, Pencil, Plus, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import { date, message, query, useData, write } from './api';
import { Badge, Empty, ErrorNotice, Loading, Modal, PageTitle, Panel, PanelTitle, Submit } from './ui';
import { Pagination } from './PagesAnimals';
import type { List, Audit } from './types';
import type { Notify } from './App';
import type { Farm, Kpis, KpiFarmOption, Owner } from './v3types';
import { roleLabels } from './v3types';

function bytes(value:number|null|undefined) { if(value==null)return 'Sin medición'; const units=['B','KB','MB','GB','TB']; let n=value,i=0; while(n>=1024 && i<units.length-1){n/=1024;i++;} return `${n.toLocaleString('es-CL',{maximumFractionDigits:1})} ${units[i]}`; }
function dateBounds(from: string, through: string) {
  const start = from ? new Date(`${from}T00:00:00`) : null;
  const end = through ? new Date(`${through}T00:00:00`) : null;
  if (start && Number.isNaN(start.getTime()) || end && Number.isNaN(end.getTime())) throw new Error('Ingresa fechas válidas.');
  if (end) end.setDate(end.getDate() + 1);
  if (start && end && start >= end) throw new Error('La fecha inicial debe ser anterior o igual a la fecha final.');
  return { start: start?.toISOString() ?? '', end: end?.toISOString() ?? '' };
}
function fullDate(value: string) {
  return new Intl.DateTimeFormat('es-CL', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'America/Santiago' }).format(new Date(value));
}
export function AdminDashboard() {
  const [account, setAccount] = useState(''); const [farm, setFarm] = useState('');
  const [from, setFrom] = useState(''); const [through, setThrough] = useState(''); const [filterError, setFilterError] = useState('');
  const [filters, setFilters] = useState({ account_id: '', farm_id: '', start: '', end: '' });
  const [options, setOptions] = useState<{ accounts: Kpis['accounts']; farms: KpiFarmOption[] }>({ accounts: [], farms: [] });
  const data = useData<Kpis>(`/v3/admin/kpis${query(filters)}`, 30000);
  const kpis = data.data;
  useEffect(() => { if (kpis) setOptions({ accounts: kpis.accounts, farms: kpis.farm_options ?? [] }); }, [kpis]);
  function apply(event: FormEvent) { event.preventDefault(); try { const bounds = dateBounds(from, through); setFilterError(''); setFilters({ account_id: account, farm_id: farm, ...bounds }); } catch (error) { setFilterError(message(error)); } }
  function clear() { setAccount(''); setFarm(''); setFrom(''); setThrough(''); setFilterError(''); setFilters({ account_id: '', farm_id: '', start: '', end: '' }); }
  const selectedFarms = options.farms.filter(option => !account || option.account_id === account);
  const customPeriod = !!filters.start || !!filters.end;
  const cards = kpis ? [
    { label: 'Usuarios únicos', value: kpis.users, icon: Users }, { label: 'Bovinos registrados', value: kpis.animals, icon: Activity },
    { label: 'Predios', value: kpis.farms, icon: Building2 }, { label: 'Sectores', value: kpis.sectors, icon: Building2 },
    { label: 'Collares inventariados', value: kpis.inventoried_devices, icon: Cpu }, { label: 'Collares instalados', value: kpis.installed_devices, icon: Cpu },
    { label: 'Módulos de software', value: kpis.software_modules, icon: Cpu },
    { label: 'Peticiones registradas', value: kpis.requests, icon: BarChart3 }, { label: 'Peticiones con error', value: kpis.error_requests, icon: ShieldCheck },
  ] : [];
  return <>
    <PageTitle eyebrow="ADMINISTRACIÓN DE PLATAFORMA" title="Visión global de GeoCattle" description="Recursos, actividad y uso registrados en esta instancia." actions={<button className="button secondary" onClick={data.reload}><RefreshCw size={17} />Actualizar</button>} />
    <Panel><PanelTitle title="Filtros del panel" subtitle="El inventario refleja el estado actual; las fechas delimitan las alertas y peticiones." /><form className="form-body" onSubmit={apply}>
      <div className="form-grid">
        <label>Dueño<select value={account} onChange={event => { setAccount(event.target.value); setFarm(''); }}><option value="">Todos los dueños</option>{options.accounts.map(option => <option key={option.id} value={option.id}>{option.display_name}</option>)}</select></label>
        <label>Predio<select value={farm} onChange={event => setFarm(event.target.value)}><option value="">Todos los predios autorizados</option>{selectedFarms.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}</select></label>
        <label>Desde el día<input type="date" value={from} onChange={event => setFrom(event.target.value)} /></label>
        <label>Hasta el día incluido<input type="date" value={through} onChange={event => setThrough(event.target.value)} /></label>
      </div>
      <p className="form-intro">Deja las fechas vacías para consultar alertas de los últimos 30 días y peticiones de las últimas 24 horas. Los límites diarios usan la zona horaria de este equipo: {Intl.DateTimeFormat().resolvedOptions().timeZone}.</p>
      <ErrorNotice error={filterError} /><div className="form-actions"><button type="button" className="button secondary" onClick={clear}>Restablecer</button><button type="submit" className="button primary">Aplicar filtros</button></div>
    </form></Panel>
    <ErrorNotice error={data.error} retry={data.reload} />{data.loading && !kpis && <Loading label="Consultando recursos de plataforma…" />}
    {kpis && <>
      <div className="v3-verification"><RefreshCw size={16} /><span>{kpis.generated_at ? `Corte: ${fullDate(kpis.generated_at)} · Hora de Chile.` : 'Corte temporal sin informar.'} Actualización cada 30 segundos.</span></div>
      {kpis.period && <p className="form-intro">Período {customPeriod ? 'aplicado' : 'de alertas'}: desde {fullDate(kpis.period.start)} hasta {fullDate(kpis.period.end)} (límite final exclusivo). Marcas en hora de Chile.</p>}
      <div className="metrics v3-metrics">{cards.map(card => <div className="metric" key={card.label}><div className="metric-top"><span>{card.label}</span><card.icon size={19} /></div><strong>{card.value == null ? 'Sin medición' : Number(card.value).toLocaleString('es-CL')}</strong></div>)}</div>
      {kpis.usage_24h && <Panel><PanelTitle title="Consumo y respuesta" subtitle={customPeriod ? 'Tamaños HTTP declarados y latencia del período aplicado; no equivalen al tráfico total de la red.' : 'Tamaños HTTP declarados y latencia de las últimas 24 horas; no equivalen al tráfico total de la red.'} />{kpis.usage_period && <p className="form-intro">Desde {fullDate(kpis.usage_period.start)} hasta {fullDate(kpis.usage_period.end)} (límite final exclusivo), hora de Chile.</p>}<dl className="animal-facts"><div><dt>Datos recibidos</dt><dd>{bytes(kpis.usage_24h.request_bytes)}</dd></div><div><dt>Datos enviados</dt><dd>{bytes(kpis.usage_24h.response_bytes)}</dd></div><div><dt>Latencia p95</dt><dd>{kpis.usage_24h.p95_ms==null ? 'Sin medición' : `${Number(kpis.usage_24h.p95_ms).toFixed(1)} ms`}</dd></div></dl></Panel>}
      {kpis.instance_resources && <Panel><PanelTitle title="Recursos de la instancia" subtitle="Lectura actual de esta instancia; no se divide por dueño. La carga corresponde al sistema observado." /><dl className="animal-facts"><div><dt>Base de datos</dt><dd>{bytes(kpis.instance_resources.database_bytes)}</dd></div><div><dt>Memoria del proceso API</dt><dd>{bytes(kpis.instance_resources.api_rss_bytes)}</dd></div><div><dt>Espacio libre del volumen</dt><dd>{bytes(kpis.instance_resources.disk_free_bytes)}</dd></div><div><dt>Carga del sistema (1 min)</dt><dd>{Number(kpis.instance_resources.load_1m).toFixed(2)}</dd></div></dl></Panel>}
      <Panel><PanelTitle title="Alertas generadas por día" subtitle="Conteo de eventos dentro del período y alcance aplicados." />{kpis.alerts_by_day.length ? <div className="v3-chart" role="img" aria-label={kpis.alerts_by_day.map(day => `${day.day}: ${day.count} alertas`).join('. ')}>{kpis.alerts_by_day.map(day => <div className="v3-bar-row" key={day.day}><span>{day.day}</span><div><i style={{ width: `${Math.max(1, day.count / Math.max(1, ...kpis.alerts_by_day.map(value => value.count)) * 100)}%` }} /></div><strong>{day.count}</strong></div>)}</div> : <Empty title="Sin alertas en el período" description="Las alertas generadas aparecerán aquí." />}</Panel>
    </>}
  </>;
}
export function AdminOwners({ notify }: { notify: Notify }) {
  const owners = useData<List<Owner>>('/v3/admin/owners'); const [editing, setEditing] = useState<Owner | 'new' | null>(null);
  return <><PageTitle eyebrow="CLIENTES DE GEOCATTLE" title="Dueños y cuentas cliente" description="Administra acceso, datos del cliente y cupos de predios." actions={<button className="button primary" onClick={() => setEditing('new')}><Plus size={17} />Agregar dueño</button>} /><Panel><PanelTitle title="Cuentas cliente" subtitle={`${owners.data?.total ?? '—'} cuentas registradas`} /><ErrorNotice error={owners.error} retry={owners.reload} />{owners.loading ? <Loading /> : owners.data?.items.length ? <div className="table-scroll"><table><thead><tr><th>Dueño</th><th>Correo</th><th>Cupo de predios</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>{owners.data.items.map(owner => <tr key={owner.id}><td>{owner.full_name || owner.display_name || 'Sin nombre'}</td><td>{owner.email || owner.username || 'Sin correo'}</td><td>{owner.max_farms ?? 'Sin definir'}</td><td><Badge status={owner.active === false ? 'unknown' : 'normal'}>{owner.active === false ? 'Suspendida' : 'Activa'}</Badge></td><td><button className="button secondary small" onClick={() => setEditing(owner)}><Pencil size={15} />Administrar</button></td></tr>)}</tbody></table></div> : <Empty title="Todavía no hay dueños" description="Crea la primera cuenta cliente para habilitar sus predios." />}</Panel>{editing && <OwnerForm owner={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); owners.reload(); notify('Cuenta cliente guardada y acción auditada.'); }} />}</>;
}
function OwnerForm({ owner, onClose, onSaved }: { owner?: Owner; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(owner?.full_name || owner?.display_name || ''); const [email, setEmail] = useState(owner?.email || owner?.username || ''); const [password, setPassword] = useState(''); const [limit, setLimit] = useState(String(owner?.max_farms ?? 1)); const [active, setActive] = useState(owner?.active !== false); const [confirmed, setConfirmed] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(''); try { await write(`/v3/admin/owners${owner ? `/${owner.id}` : ''}`, owner ? { full_name: name, active, max_farms: Number(limit) } : { email, full_name: name, password, max_farms: Number(limit) }, owner ? 'PATCH' : 'POST'); onSaved(); } catch (err) { setError(message(err)); } finally { setBusy(false); } }
  return <Modal title={owner ? 'Administrar dueño' : 'Agregar dueño'} onClose={onClose}><form className="form-body" onSubmit={submit}><label>Nombre completo<input required maxLength={150} value={name} onChange={e => setName(e.target.value)} /></label><label>Correo de acceso<input type="email" required disabled={!!owner} autoComplete="off" value={email} onChange={e => setEmail(e.target.value)} /></label>{!owner && <label>Contraseña inicial<input type="password" required minLength={12} autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} /><small>Entrega la credencial al titular por un canal autorizado.</small></label>}<label>Cupo de predios<input type="number" min={1} max={1000} required value={limit} onChange={e => setLimit(e.target.value)} /></label>{owner && <label className="checkbox-field"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />Cuenta activa</label>}<label className="checkbox-field"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} required />Confirmo los datos y el alcance de este cambio.</label><ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose}>Cancelar</button><Submit busy={busy}>{owner ? 'Guardar cuenta' : 'Crear cuenta'}</Submit></div></form></Modal>;
}
type AdminUser = { id: string; full_name?: string; email?: string; username?: string; active?: boolean; role?: string };
export function AdminUsers({ notify }: { notify: Notify }) {
  const users = useData<List<AdminUser>>('/v3/admin/users'); const [editing, setEditing] = useState<AdminUser | null>(null); const [resetting, setResetting] = useState<AdminUser | null>(null); const [search, setSearch] = useState('');
  const filtered = users.data?.items.filter(u => `${u.full_name} ${u.email} ${u.username}`.toLowerCase().includes(search.toLowerCase())) ?? [];
  return <><PageTitle eyebrow="GOBERNANZA DE PLATAFORMA" title="Usuarios de la plataforma" description="Supervisa identidades y administra accesos de colaboradores ya incorporados." /><Panel><div className="list-toolbar"><label className="search-field"><input aria-label="Buscar usuarios" placeholder="Buscar nombre o correo…" value={search} onChange={e => setSearch(e.target.value)} /></label><span className="list-count">{filtered.length} usuarios visibles</span></div><ErrorNotice error={users.error} retry={users.reload} />{users.loading ? <Loading /> : filtered.length ? <div className="table-scroll"><table><thead><tr><th>Usuario</th><th>Correo</th><th>Perfil</th><th>Acceso</th><th>Acciones</th></tr></thead><tbody>{filtered.map(user => <tr key={user.id}><td>{user.full_name || 'Sin nombre'}</td><td>{user.email || user.username}</td><td>{roleLabels[user.role ?? ''] ?? 'Según membresía predial'}</td><td><Badge status={user.active === false ? 'unknown' : 'normal'}>{user.active === false ? 'Suspendido' : 'Activo'}</Badge></td><td>{user.role === 'admin' ? <span className="neutral-tag">Cuenta protegida</span> : <div className="v3-inline-actions"><button className="button secondary small" onClick={() => setEditing(user)}>Administrar</button><button className="button secondary small" onClick={() => setResetting(user)}><KeyRound size={14} />Restablecer contraseña</button></div>}</td></tr>)}</tbody></table></div> : <Empty title="Sin usuarios para mostrar" description="Prueba otro filtro o incorpora un dueño." />}</Panel>{editing && <AdminUserForm user={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); users.reload(); notify('Usuario actualizado.'); }} />}{resetting && <ResetIssueForm user={resetting} onClose={() => setResetting(null)} />}</>;
}
function AdminUserForm({ user, onClose, onSaved }: { user: AdminUser; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(user.full_name ?? ''); const [active, setActive] = useState(user.active !== false); const [confirmed, setConfirmed] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(''); try { await write(`/v3/admin/users/${user.id}`, { full_name: name, active }, 'PATCH'); onSaved(); } catch (err) { setError(message(err)); } finally { setBusy(false); } }
  return <Modal title="Administrar identidad" onClose={onClose}><form className="form-body" onSubmit={submit}><p className="form-intro">{user.email || user.username}</p><label>Nombre completo<input required maxLength={150} value={name} onChange={e => setName(e.target.value)} /></label><label className="checkbox-field"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />Acceso activo</label><label className="checkbox-field"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} required />Confirmo el cambio sobre esta identidad y sus accesos.</label><ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose}>Cancelar</button><Submit busy={busy}>Actualizar usuario</Submit></div></form></Modal>;
}
export function AuditPage({ global = false }: { global?: boolean }) {
  const [offset, setOffset] = useState(0); const [search, setSearch] = useState('');
  const [actor, setActor] = useState(''); const [action, setAction] = useState(''); const [entity, setEntity] = useState(''); const [farm, setFarm] = useState('');
  const [from, setFrom] = useState(''); const [through, setThrough] = useState(''); const [filterError, setFilterError] = useState('');
  const [filters, setFilters] = useState({ q: '', actor_id: '', action: '', entity: '', farm_id: '', start: '', end: '' });
  const farms = useData<List<Farm>>(global ? '/v3/farms' : null);
  const audit = useData<List<Audit & { username?: string; actor_name?: string; created_at?: string }>>(`/v3/audit${query({ ...filters, limit: '100', offset: String(offset) })}`);
  function apply(event: FormEvent) { event.preventDefault(); try { const bounds = dateBounds(from, through); setFilterError(''); setOffset(0); setFilters({ q: search.trim(), actor_id: actor.trim(), action: action.trim(), entity: entity.trim(), farm_id: global ? farm : '', ...bounds }); } catch (error) { setFilterError(message(error)); } }
  function clear() { setSearch(''); setActor(''); setAction(''); setEntity(''); setFarm(''); setFrom(''); setThrough(''); setOffset(0); setFilterError(''); setFilters({ q: '', actor_id: '', action: '', entity: '', farm_id: '', start: '', end: '' }); }
  return <>
    <PageTitle eyebrow="EVIDENCIA Y RESPONSABILIDAD" title={global ? 'Auditoría de plataforma' : 'Auditoría del predio'} description="Historial de actividad, responsables y cambios conservados." />
    <Panel><PanelTitle title="Buscar en toda la auditoría autorizada" subtitle="La búsqueda y los filtros se ejecutan en el servidor antes de paginar." /><form className="form-body" onSubmit={apply}>
      <label>Buscar por actor, acción o entidad<input type="search" placeholder="Nombre de actor, acción o entidad…" value={search} onChange={event => setSearch(event.target.value)} /></label>
      <div className="form-grid">
        <label>ID exacto del actor (opcional)<input value={actor} onChange={event => setActor(event.target.value)} pattern="[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}" placeholder="UUID del usuario" title="Introduce un UUID completo o deja este campo vacío." /></label>
        <label>Acción exacta (opcional)<input value={action} onChange={event => setAction(event.target.value)} placeholder="Ej.: change_submitted" /></label>
        <label>Entidad exacta (opcional)<input value={entity} onChange={event => setEntity(event.target.value)} placeholder="Ej.: change_request" /></label>
        {global && <label>Predio<select value={farm} onChange={event => setFarm(event.target.value)}><option value="">Todos los predios</option>{farms.data?.items.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}</select></label>}
        <label>Desde el día<input type="date" value={from} onChange={event => setFrom(event.target.value)} /></label>
        <label>Hasta el día incluido<input type="date" value={through} onChange={event => setThrough(event.target.value)} /></label>
      </div>
      <p className="form-intro">Los filtros se combinan. Las fechas incluyen el día final y usan la zona horaria de este equipo: {Intl.DateTimeFormat().resolvedOptions().timeZone}.</p>
      <ErrorNotice error={filterError || farms.error} retry={farms.error ? farms.reload : undefined} />
      <div className="form-actions"><button type="button" className="button secondary" onClick={clear}>Restablecer</button><button type="submit" className="button primary">Buscar en servidor</button></div>
    </form></Panel>
    <Panel><PanelTitle title="Resultados de auditoría" subtitle={`${audit.data?.total ?? '—'} registros coincidentes`} /><ErrorNotice error={audit.error} retry={audit.reload} />
      {audit.loading ? <Loading /> : audit.data?.items.length ? <div className="audit-list">{audit.data.items.map(item => <details key={item.id} className="audit-item"><summary><span className="notification-icon"><ShieldCheck size={17} /></span><div><strong>{item.object_type} · {item.action}</strong><small>{date(item.at || item.created_at)} · {item.username || item.actor_name || item.actor_id || 'Servicio del sistema'}</small></div><span className="neutral-tag">Ver detalle</span></summary><div className="audit-state"><div><h4>Estado anterior</h4><pre>{JSON.stringify(item.before, null, 2) ?? 'Sin estado anterior'}</pre></div><div><h4>Estado posterior</h4><pre>{JSON.stringify(item.after, null, 2) ?? 'Sin estado posterior'}</pre></div></div></details>)}</div> : <Empty title="Sin registros para estos filtros" description="Cambia la búsqueda o amplía el período." />}
      {audit.data && <Pagination offset={offset} count={audit.data.items.length} total={audit.data.total} limit={100} onChange={setOffset} />}
    </Panel>
  </>;
}

function ResetIssueForm({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const [password, setPassword] = useState(''); const [code, setCode] = useState('');
  const [result, setResult] = useState<{ reset_token: string; expires_at: string } | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { const response = await write<{ reset_token: string; expires_at: string }>('/auth/password/reset-issue', { user_id: user.id, password, code }); setPassword(''); setCode(''); setResult(response); } catch (error) { setError(message(error)); } finally { setBusy(false); } }
  const link = result ? `${location.origin}${location.pathname}#reset?token=${encodeURIComponent(result.reset_token)}` : '';
  return <Modal title="Restablecer acceso de usuario" onClose={onClose}>{result ? <div className="form-body"><div className="notice"><ShieldCheck size={18} /><span>Entrega este enlace únicamente al titular por un canal privado. Se muestra una vez y no se envía correo automáticamente.</span></div><label>Enlace privado de recuperación<input readOnly autoComplete="off" value={link} onFocus={event => event.currentTarget.select()} /></label><p className="form-intro">Vence: {fullDate(result.expires_at)}, hora de Chile. El usuario define su contraseña nueva; su segundo factor permanece activo.</p><div className="form-actions"><button className="button primary" onClick={onClose}>Cerrar</button></div></div> : <form className="form-body" onSubmit={submit}><p className="form-intro">Titular: {user.full_name || user.email || user.username}. {user.email || user.username}</p><label>Tu contraseña de administrador<input required type="password" autoComplete="current-password" maxLength={256} value={password} onChange={event => setPassword(event.target.value)} /></label><label>Código nuevo de tu aplicación autenticadora<input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ''))} /></label><ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cancelar</button><Submit busy={busy}>Generar enlace privado</Submit></div></form>}</Modal>;
}
