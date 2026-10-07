import { useEffect, useState, type FormEvent } from 'react';
import { Activity, ArrowDownLeft, ArrowRight, Bell, Check, ChevronRight, CircleHelp, Fence, LayoutDashboard, LogOut, MapPin, Menu, Radio, RefreshCw, Search, Settings2, ShieldCheck, Sprout, Wifi, WifiOff, X } from 'lucide-react';
import { api, ApiError, age, date, setSession, useData, write } from './api';
import type { Animal, List, Geofence, Overview, Session } from './types';
import { Badge, Empty, ErrorNotice, Loading, Panel, PanelTitle, PageTitle, eventLabels } from './ui';
import { CattleMap } from './Map';
import { AnimalsPage, AnimalDetail, AnimalForm } from './PagesAnimals';
import { DevicesPage, GeofencesPage, SettingsPage } from './PagesManagement';
import { EventsPage, OperationsPage } from './PagesEvents';

type Page = 'overview' | 'animals' | 'devices' | 'geofences' | 'events' | 'operations' | 'settings';
export type Notify = (message: string) => void;
const navigation = [
  { id: 'overview' as Page, title: 'Vista general', icon: LayoutDashboard },
  { id: 'animals' as Page, title: 'Mis animales', icon: Sprout },
  { id: 'devices' as Page, title: 'Collares y dispositivos', icon: Radio },
  { id: 'geofences' as Page, title: 'Sectores y geocercas', icon: Fence },
  { id: 'events' as Page, title: 'Eventos y atención', icon: Bell },
  { id: 'operations' as Page, title: 'Operación y auditoría', icon: ShieldCheck },
  { id: 'settings' as Page, title: 'Reglas del predio', icon: Settings2 },
];
function Brand({ light = false }: { light?: boolean }) {
  return <div className={`brand ${light ? 'brand-light' : ''}`}><div className="brand-icon"><svg viewBox="0 0 36 36" fill="none" aria-hidden="true"><path d="M8 15 5 8l8 4M28 15l3-7-8 4M11 12c2-3 12-3 14 0l3 10-6 9h-8l-6-9 3-10Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /><path d="M14 22h8M14 18h.01M22 18h.01M17 27h2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg></div><span>GeoCattle<small>INTELIGENCIA PREDIAL</small></span></div>;
}
function Login({ onLogin, initialError }: { onLogin: (session: Session) => void; initialError: string }) {
  const [username, setUsername] = useState('demo@geocattle.local');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const result = await write<Session>('/auth/login', { username, password }); setSession(result); onLogin(result); }
    catch (err) { setError(err instanceof Error ? err.message : 'No se pudo iniciar sesión.'); }
    finally { setBusy(false); }
  }
  return <div className="login-layout"><div className="login-visual"><Brand light /><div className="login-copy"><span className="eyebrow">CERCA DE TU REBAÑO</span><h1>Cada animal.<br />Un lugar seguro.</h1><p>La información del predio, reunida en un solo lugar. Ubicación, collares y seguimiento para tomar decisiones a tiempo.</p><div className="login-features"><span><MapPin size={17} />Localización y geocercas</span><span><Wifi size={17} />Operación en la red local</span><span><ShieldCheck size={17} />Historial trazable</span></div></div><div className="login-landscape" aria-hidden="true"><svg viewBox="0 0 580 260"><path d="M-20 240 200 80 350 120 540 20 640 80V290H-20Z" fill="#35614b" /><path d="m-20 270 200-140 140 80L540 50l90 40v210H-20Z" fill="#416c51" /><path d="m120 245 80-60 120 50 230-100" stroke="#bad6a2" strokeWidth="2" strokeDasharray="6 8" fill="none" /><circle cx="204" cy="190" r="10" fill="#c7e2b0" /><circle cx="376" cy="195" r="7" fill="#c7e2b0" /><circle cx="499" cy="153" r="7" fill="#c7e2b0" /></svg></div><span className="login-footer">Tecnología al servicio de la ganadería.</span></div><main className="login-form-panel"><div className="login-form-content"><span className="eyebrow">BIENVENIDO A GEOCATTLE</span><h2>Tu predio, conectado.</h2><p>Ingresa con tu cuenta para supervisar el rebaño.</p><form onSubmit={submit}><label>Correo de acceso<input type="email" autoComplete="username" required value={username} onChange={e => setUsername(e.target.value)} autoFocus /></label><label>Contraseña<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></label><ErrorNotice error={error} /><button className="button primary login-submit" disabled={busy}>{busy ? 'Conectando…' : 'Ingresar al predio'}<ArrowRight size={18} /></button></form><div className="login-help"><CircleHelp size={18} /><p>Utiliza las credenciales configuradas en el servidor. La cuenta de demostración pertenece a un predio con datos simulados.</p></div></div><span className="login-bottom">GeoCattle · Supervisión predial local</span></main></div>;
}
export default function App() {
  const [session, updateSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [authError, setAuthError] = useState('');
  const [page, setPage] = useState<Page>(() => (navigation.find(nav => nav.id === location.hash.slice(1))?.id ?? 'overview'));
  const [mobileMenu, setMobileMenu] = useState(false);
  const [connected, setConnected] = useState(true);
  const [search, setSearch] = useState('');
  const [toast, setToast] = useState('');
  const overview = useData<Overview>(session ? '/dashboard' : null, session ? 30000 : 0);
  useEffect(() => {
    let alive = true;
    api<Session>('/auth/me').then(result => { if (alive) { setSession(result); updateSession(result); } })
      .catch(err => { if (alive && (!(err instanceof ApiError) || err.status !== 401)) setAuthError(err.message); })
      .finally(() => { if (alive) setChecking(false); });
    const expired = () => { setSession(null); updateSession(null); setAuthError('La sesión ha caducado. Ingresa nuevamente.'); };
    const connectivity = (event: Event) => setConnected((event as CustomEvent<boolean>).detail);
    const route = () => setPage(navigation.find(nav => nav.id === location.hash.slice(1))?.id ?? 'overview');
    window.addEventListener('session-expired', expired); window.addEventListener('api-connectivity', connectivity); window.addEventListener('hashchange', route);
    return () => { alive = false; window.removeEventListener('session-expired', expired); window.removeEventListener('api-connectivity', connectivity); window.removeEventListener('hashchange', route); };
  }, []);
  useEffect(() => { if (!toast) return; const timeout = setTimeout(() => setToast(''), 6000); return () => clearTimeout(timeout); }, [toast]);
  function navigate(next: Page) { location.hash = next; setPage(next); setMobileMenu(false); }
  const canWrite = session?.user.role !== 'viewer';
  const canManage = session?.user.role === 'owner';
  async function logout() {
    try { await api('/auth/logout', { method: 'POST' }); setSession(null); updateSession(null); setAuthError(''); }
    catch (err) { setToast(err instanceof Error ? err.message : 'No se pudo cerrar la sesión.'); }
  }
  if (checking) return <div className="app-start"><Brand /><Loading label="Conectando con GeoCattle…" /></div>;
  if (!session) return <Login onLogin={updateSession} initialError={authError} />;
  return <div className="app-shell">
    {mobileMenu && <button className="sidebar-overlay" aria-label="Cerrar navegación" onClick={() => setMobileMenu(false)} />}
    <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`}><div className="sidebar-brand"><Brand light /><button className="icon-button mobile-close" aria-label="Cerrar menú" onClick={() => setMobileMenu(false)}><X size={20} /></button></div><div className="farm-switch"><span className="farm-icon"><Sprout size={19} /></span><div><small>PREDIO ACTUAL</small><strong>{overview.data?.farm.name ?? 'Cargando predio…'}</strong></div><ChevronRight size={15} /></div><span className="nav-label">SUPERVISIÓN</span><nav aria-label="Navegación principal">{navigation.map((item, i) => <button key={item.id} onClick={() => navigate(item.id)} className={`nav-item ${page === item.id ? 'nav-active' : ''} ${i === 5 ? 'nav-divider' : ''}`} aria-current={page === item.id ? 'page' : undefined}><item.icon size={19} /><span>{item.title}</span>{item.id === 'events' && !!overview.data?.summary.active_events && <span className="nav-count">{overview.data.summary.active_events}</span>}</button>)}</nav><div className="sidebar-bottom"><div className="local-status"><span className={`connection-dot ${connected ? 'green' : 'red'}`} /><div><strong>{connected ? 'Servidor local conectado' : 'Servidor no disponible'}</strong><small>{overview.data?.farm.environment === 'simulation' ? 'Entorno de simulación' : 'Supervisión del predio'}</small></div></div><div className="sidebar-user"><span className="avatar">{session.user.username.slice(0, 2).toUpperCase()}</span><div><strong>{session.user.username}</strong><small>{session.user.role === 'owner' ? 'Administrador del predio' : session.user.role === 'operator' ? 'Operador' : 'Sólo lectura'}</small></div><button className="icon-button" onClick={logout} aria-label="Cerrar sesión" title="Cerrar sesión"><LogOut size={17} /></button></div></div></aside>
    <div className="app-body"><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Abrir menú" onClick={() => setMobileMenu(true)}><Menu size={22} /></button><span>Mi predio</span><ChevronRight size={15} /><strong>{navigation.find(nav => nav.id === page)?.title}</strong></div><form className="global-search" onSubmit={e => { e.preventDefault(); navigate('animals'); }}><Search size={16} /><input aria-label="Buscar animales por nombre o DIIO" placeholder="Buscar nombre o DIIO…" value={search} onChange={e => setSearch(e.target.value)} /><kbd>↵</kbd></form><button className="top-notification icon-button" aria-label="Ver eventos" onClick={() => navigate('events')}><Bell size={20} />{!!overview.data?.summary.active_events && <i />}</button></header>
      {!connected && <div className="connectivity-banner" role="alert"><WifiOff size={17} /><span>Conexión con el servidor interrumpida. La información visible puede estar desactualizada.</span><button onClick={overview.reload}>Reintentar</button></div>}
      {overview.data?.farm.environment === 'simulation' && <div className="simulation-banner"><span className="simulation-tag">SIMULACIÓN</span><span>Predio de demostración. Las lecturas con origen <strong>sim</strong> son simuladas.</span></div>}
      <main className="main-content" id="main-content">
        {page === 'overview' && <OverviewPage overview={overview} canWrite={canManage} notify={setToast} navigate={navigate} />}
        {page === 'animals' && <AnimalsPage search={search} setSearch={setSearch} canWrite={canManage} notify={setToast} />}
        {page === 'devices' && <DevicesPage canWrite={canManage} notify={setToast} />}
        {page === 'geofences' && <GeofencesPage canWrite={canManage} notify={setToast} />}
        {page === 'events' && <EventsPage canWrite={canWrite} notify={setToast} />}
        {page === 'operations' && <OperationsPage canWrite={canWrite} canAudit={canManage} notify={setToast} simulation={overview.data?.farm.environment === 'simulation'} onChange={overview.reload} />}
        {page === 'settings' && <SettingsPage canWrite={canManage} notify={setToast} simulation={overview.data?.farm.environment === 'simulation'} />}
      </main><footer className="app-footer"><span>GeoCattle <span>·</span> Supervisión predial</span><span><span className={`connection-dot ${connected ? 'green' : 'red'}`} />{connected ? 'Red local' : 'Conexión interrumpida'}<span className="footer-separator">|</span>Hora de Chile</span></footer>
    </div>{toast && <div className="toast" role="status"><Check size={18} /><span>{toast}</span><button className="icon-button" aria-label="Cerrar aviso" onClick={() => setToast('')}><X size={16} /></button></div>}
  </div>;
}
function OverviewPage({ overview, canWrite, notify, navigate }: { overview: ReturnType<typeof useData<Overview>>; canWrite: boolean; notify: Notify; navigate: (page: Page) => void }) {
  const geofences = useData<List<Geofence>>('/geofences');
  const [sector, setSector] = useState('');
  const [selected, setSelected] = useState<Animal | null>(null);
  const [adding, setAdding] = useState(false);
  const data = overview.data;
  const filteredAnimals = data?.animals.filter(animal => !sector || animal.sector_id === sector) ?? [];
  const activeFences = geofences.data?.items.filter(fence => fence.active && (!sector || fence.sector_id === sector)) ?? [];
  const outstanding = data?.events.filter(event => event.attention !== 'concluded').slice(0, 4) ?? [];
  const fresh = data?.animals.filter(a => a.position_status === 'fresh').length ?? 0;
  return <>
    <PageTitle eyebrow="TU PREDIO, DE UN VISTAZO" title="Todo el rebaño, cerca." description="Supervisa la ubicación y el estado de tus animales." actions={<><button className="button secondary" onClick={() => { overview.reload(); geofences.reload(); }} disabled={overview.loading}><RefreshCw size={16} className={overview.loading ? 'spin' : ''} />Actualizar</button>{canWrite && <button className="button primary" onClick={() => setAdding(true)}>+ Registrar animal</button>}</>} />
    <ErrorNotice error={overview.error} retry={overview.reload} />
    {!data && overview.loading ? <Loading /> : data && <>
      <div className="metrics"><div className="metric metric-total"><div className="metric-top"><span>Total de animales</span><Sprout size={19} /></div><strong>{data.summary.total}<small>en el predio</small></strong><div className="metric-foot"><span className="connection-dot green" />{fresh} con posición vigente</div></div><div className="metric"><div className="metric-top"><span>En estado normal</span><span className="metric-dot normal" /></div><strong>{data.summary.normal}<small>animales</small></strong><div className="metric-foot">Lecturas vigentes y sin alertas</div></div><div className="metric"><div className="metric-top"><span>Necesitan atención</span><Bell size={18} className="amber-text" /></div><strong>{data.summary.warning + data.summary.critical}<small>animales</small></strong><div className="metric-foot"><span className="critical-text">{data.summary.critical} críticos</span><span className="metric-foot-dot">·</span>{data.summary.warning} con precaución</div></div><div className="metric"><div className="metric-top"><span>Sin información</span><Radio size={18} className="muted" /></div><strong>{data.summary.unknown}<small>animales</small></strong><div className="metric-foot">No equivale a un estado normal</div></div></div>
      <div className="overview-grid"><Panel className="map-panel"><PanelTitle title="Mapa del predio" subtitle="Última posición recibida y geocercas" action={<select className="compact-select" aria-label="Filtrar mapa por sector" value={sector} onChange={e => setSector(e.target.value)}><option value="">Todos los sectores</option>{data.sectors.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>} /><ErrorNotice error={geofences.error} retry={geofences.reload} /><CattleMap animals={filteredAnimals} geofences={activeFences} onAnimal={setSelected} /><div className="map-panel-foot"><span><MapPin size={15} />{filteredAnimals.filter(a => a.last_position?.gnss_valid && a.last_position.latitude != null).length} posiciones de {filteredAnimals.length} animales</span><span>Las posiciones vencidas se muestran en gris.</span></div></Panel><Panel className="events-panel"><PanelTitle title="Atención pendiente" subtitle={`${data.summary.active_events} eventos con condición activa`} action={<button className="icon-button" title="Ver todos los eventos" aria-label="Ver todos los eventos" onClick={() => navigate('events')}><ArrowRight size={18} /></button>} />{outstanding.length ? <div className="event-cards">{outstanding.map(event => <button key={event.id} className="event-card" onClick={() => navigate('events')}><span className={`event-icon ${event.severity}`}><Bell size={17} /></span><div><div className="event-card-top"><strong>{eventLabels[event.type] ?? event.type.replaceAll('_', ' ')}</strong><span className={`mini-dot ${event.severity}`} /></div><p>{event.animal_name || event.diio}<span> · DIIO {event.diio}</span></p><small>{date(event.opened_at)}<span> · {event.condition === 'active' ? 'Condición activa' : 'Condición resuelta'}</span></small></div><ChevronRight size={15} /></button>)}</div> : <Empty title="Sin atención pendiente" description="Los eventos nuevos aparecerán aquí." />}<div className="panel-bottom"><button className="text-button" onClick={() => navigate('events')}>Ir a eventos y seguimiento <ArrowRight size={16} /></button></div><div className="attention-note"><ShieldCheck size={17} /><p>La atención es independiente de la condición del evento. Revisa cada caso y registra las acciones.</p></div></Panel></div>
      <Panel className="herd-panel"><PanelTitle title="Tu rebaño" subtitle="Información reciente de los animales del predio" action={<button className="text-button" onClick={() => navigate('animals')}>Ver todos los animales <ArrowRight size={16} /></button>} />{data.animals.length ? <div className="table-scroll"><table><thead><tr><th>Animal / DIIO</th><th>Sector</th><th>Estado</th><th>Última posición</th><th>Comunicación</th><th aria-label="Abrir ficha" /></tr></thead><tbody>{data.animals.slice(0, 5).map(animal => <tr key={animal.id}><td><div className="animal-cell"><span className={`animal-avatar ${animal.status}`}><Sprout size={19} /></span><div><button className="row-title" onClick={() => setSelected(animal)}>{animal.name || 'Sin nombre'}</button><small>{animal.diio}</small></div></div></td><td>{animal.sector_name ?? 'Sin sector'}</td><td><Badge status={animal.status} /></td><td><span className={animal.position_status !== 'fresh' ? 'muted' : ''}>{age(animal.position_age_seconds)}</span><small>{animal.position_status === 'fresh' ? 'Vigente' : animal.position_status === 'stale' ? 'Vencida' : 'Desconocida'}</small></td><td><span className={`table-dot ${animal.communication_status === 'recent' ? 'green' : 'gray'}`} />{animal.communication_status === 'recent' ? 'Reciente' : animal.communication_status === 'absent' ? 'Ausente' : 'Sin registro'}</td><td><button className="icon-button" aria-label={`Ver ficha de ${animal.name || animal.diio}`} onClick={() => setSelected(animal)}><ArrowDownLeft size={17} /></button></td></tr>)}</tbody></table></div> : <Empty title="El rebaño aún no tiene animales" description="Registra el primer animal y asocia un collar para comenzar la supervisión." />}</Panel>
    </>}
    {selected && <AnimalDetail animalId={selected.id} onClose={() => setSelected(null)} canWrite={canWrite} notify={notify} onChanged={overview.reload} />}
    {adding && <AnimalForm onClose={() => setAdding(false)} onSaved={() => { setAdding(false); overview.reload(); notify('Animal registrado correctamente.'); }} />}
  </>;
}
