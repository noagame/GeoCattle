import { HardwarePage } from './HardwarePage';
import { useEffect, useState, lazy, Suspense, type FormEvent } from 'react';
import { Activity, ArrowDownLeft, ArrowRight, Bell, Building2, Check, ChevronRight, CircleHelp, ClipboardList, Fence, FileHeart, LayoutDashboard, LogOut, MapPin, Menu, Radio, RefreshCw, Search, Settings2, ShieldCheck, Sprout, UserRound, Users, Wifi, WifiOff, X } from 'lucide-react';
import { api, ApiError, age, date, message, setSession, useData, write } from './api';
import type { Animal, List, Geofence, Overview, Session } from './types';
import { Badge, Empty, ErrorNotice, Loading, Panel, PanelTitle, PageTitle, eventLabels } from './ui';
import { CattleMap } from './Map';
import { AnimalsPage, AnimalDetail, AnimalForm } from './PagesAnimals';
import { DevicesPage, GeofencesPage, SettingsPage } from './PagesManagement';
import { EventsPage, OperationsPage } from './PagesEvents';



import { EnrolPage, ProfilePage, ResetPasswordPage } from './V3Account';
import { roleLabels } from './v3types';
import type { Gateway } from './v3types';

const AdminDashboard = lazy(() => import('./V3Admin').then(module => ({ default: module.AdminDashboard })));
const AdminOwners = lazy(() => import('./V3Admin').then(module => ({ default: module.AdminOwners })));
const AdminUsers = lazy(() => import('./V3Admin').then(module => ({ default: module.AdminUsers })));
const AuditPage = lazy(() => import('./V3Admin').then(module => ({ default: module.AuditPage })));
const FarmsPage = lazy(() => import('./V3Farm').then(module => ({ default: module.FarmsPage })));
const GatewaysPage = lazy(() => import('./V3Farm').then(module => ({ default: module.GatewaysPage })));
const TeamPage = lazy(() => import('./V3Farm').then(module => ({ default: module.TeamPage })));
const UserNotifications = lazy(() => import('./V3Farm').then(module => ({ default: module.UserNotifications })));
const ChangesPage = lazy(() => import('./V3Health').then(module => ({ default: module.ChangesPage })));
const HealthPage = lazy(() => import('./V3Health').then(module => ({ default: module.HealthPage })));

type Page = 'hardware' | 'overview' | 'animals' | 'devices' | 'geofences' | 'events' | 'operations' | 'settings' | 'admin' | 'owners' | 'users' | 'farms' | 'team' | 'changes' | 'health' | 'gateways' | 'profile' | 'notices' | 'audit';
export type Notify = (message: string) => void;
const allNavigation = [
  { id: 'hardware' as Page, title: 'Recepción de collares', icon: Radio },
  { id: 'admin' as Page, title: 'Panel administrador', icon: LayoutDashboard, global: true },
  { id: 'owners' as Page, title: 'Dueños y clientes', icon: Building2, global: true },
  { id: 'users' as Page, title: 'Usuarios de plataforma', icon: Users, global: true },
  { id: 'overview' as Page, title: 'Panel del predio', icon: LayoutDashboard },
  { id: 'farms' as Page, title: 'Mis predios', icon: Building2 },
  { id: 'animals' as Page, title: 'Bovinos y monitoreo', icon: Sprout },
  { id: 'health' as Page, title: 'Fichas y agenda sanitaria', icon: FileHeart },
  { id: 'changes' as Page, title: 'Aprobaciones', icon: ClipboardList },
  { id: 'team' as Page, title: 'Equipo y permisos', icon: Users },
  { id: 'devices' as Page, title: 'Collares y dispositivos', icon: Radio },
  { id: 'gateways' as Page, title: 'Gateways instalados', icon: Radio },
  { id: 'geofences' as Page, title: 'Sectores y geocercas', icon: Fence },
  { id: 'events' as Page, title: 'Alertas y atención', icon: Bell },
  { id: 'operations' as Page, title: 'Operación del predio', icon: Activity },
  { id: 'settings' as Page, title: 'Reglas del predio', icon: Settings2 },
  { id: 'audit' as Page, title: 'Auditoría', icon: ShieldCheck },
  { id: 'notices' as Page, title: 'Mis avisos', icon: Bell },
  { id: 'profile' as Page, title: 'Mi perfil', icon: UserRound },
];
function Brand({ light = false }: { light?: boolean }) {
  return <div className={`brand ${light ? 'brand-light' : ''}`}><div className="brand-icon"><svg viewBox="0 0 36 36" fill="none" aria-hidden="true"><path d="M8 15 5 8l8 4M28 15l3-7-8 4M11 12c2-3 12-3 14 0l3 10-6 9h-8l-6-9 3-10Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /><path d="M14 22h8M14 18h.01M22 18h.01M17 27h2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg></div><span>GeoCattle<small>INTELIGENCIA PREDIAL</small></span></div>;
}
type MfaChallenge = { mfa_required: true; challenge_token: string; setup_required: boolean; secret?: string; otpauth_uri?: string };
function Login({ onLogin, initialError, initialNotice = '' }: { onLogin: (session: Session) => void; initialError: string; initialNotice?: string }) {
  const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [code, setCode] = useState(''); const [challenge, setChallenge] = useState<MfaChallenge | null>(null);
  const [usingRecovery, setUsingRecovery] = useState(false); const [recoveryCode, setRecoveryCode] = useState('');
  const [error, setError] = useState(initialError); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = usingRecovery ? await write<Session>('/auth/mfa/recovery-login', { username, password, recovery_code: recoveryCode }) : challenge ? await write<Session>('/auth/mfa/verify', { challenge_token: challenge.challenge_token, code }) : await write<Session | MfaChallenge>('/auth/login', { username, password });
      if ('mfa_required' in result) { setChallenge(result); setPassword(''); } else { setPassword(''); setCode(''); setRecoveryCode(''); setSession(result); onLogin(result); }
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  function chooseRecovery() { setUsingRecovery(value => !value); setChallenge(null); setCode(''); setRecoveryCode(''); setError(''); }
  return <div className="login-layout"><div className="login-visual"><Brand light /><div className="login-copy"><span className="eyebrow">CERCA DE TU REBAÑO</span><h1>Cada animal.<br />Un lugar seguro.</h1><p>Ubicación, salud y trabajo en equipo. Una vista para cada responsabilidad dentro de GeoCattle.</p><div className="login-features"><span><MapPin size={17} />Localización y geocercas</span><span><FileHeart size={17} />Fichas y agenda sanitaria</span><span><ShieldCheck size={17} />Identidades y cambios trazables</span></div></div><div className="login-landscape" aria-hidden="true"><svg viewBox="0 0 580 260"><path d="M-20 240 200 80 350 120 540 20 640 80V290H-20Z" fill="#35614b" /><path d="m-20 270 200-140 140 80L540 50l90 40v210H-20Z" fill="#416c51" /><path d="m120 245 80-60 120 50 230-100" stroke="#bad6a2" strokeWidth="2" strokeDasharray="6 8" fill="none" /><circle cx="204" cy="190" r="10" fill="#c7e2b0" /><circle cx="376" cy="195" r="7" fill="#c7e2b0" /></svg></div><span className="login-footer">Tecnología al servicio de la ganadería.</span></div>
    <main className="login-form-panel"><div className="login-form-content"><span className="eyebrow">ACCESO PERSONAL</span><h2>{usingRecovery ? 'Recupera tu acceso.' : challenge ? 'Verifica tu identidad.' : 'Tu equipo, conectado.'}</h2><p>{usingRecovery ? 'Usa tu contraseña y uno de tus códigos de recuperación guardados.' : challenge ? 'Completa el segundo factor para abrir tu panel.' : 'Ingresa con tus credenciales para acceder a tu panel.'}</p>
      {initialNotice && <div className="notice" role="status"><Check size={18} /><span>{initialNotice}</span></div>}
      <form onSubmit={submit}>{challenge ? <>{challenge.setup_required && <div className="v3-mfa-setup"><p>Configura esta clave en tu aplicación autenticadora TOTP e ingresa su primer código.</p><label>Clave de configuración<input readOnly value={challenge.secret ?? ''} onFocus={event => event.currentTarget.select()} /></label><small>Guarda el factor de forma privada antes de continuar.</small></div>}<label>Código de verificación<input autoFocus inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ''))} /></label></> : <><label>Correo de acceso<input type="email" autoComplete="username" required value={username} onChange={event => setUsername(event.target.value)} autoFocus /></label><label>Contraseña<input type="password" autoComplete="current-password" required maxLength={256} value={password} onChange={event => setPassword(event.target.value)} /></label>{usingRecovery && <label>Código de recuperación<input autoComplete="off" spellCheck={false} required maxLength={100} value={recoveryCode} onChange={event => setRecoveryCode(event.target.value)} /><small>Cada código se utiliza una sola vez. Tu segundo factor continúa activo.</small></label>}</>}
        <ErrorNotice error={error} /><button className="button primary login-submit" disabled={busy}>{busy ? 'Verificando…' : challenge ? 'Verificar y continuar' : 'Iniciar sesión'}<ArrowRight size={18} /></button>
        {challenge && <button type="button" className="text-button" disabled={busy} onClick={() => { setChallenge(null); setCode(''); setError(''); }}>Volver al acceso</button>}
        <button type="button" className="text-button" disabled={busy} onClick={chooseRecovery}>{usingRecovery ? 'Usar la aplicación autenticadora' : 'Usar un código de recuperación'}</button>
      </form>
      <details className="v3-login-recovery"><summary>Olvidé mi contraseña</summary><p>Solicita al administrador un enlace privado para restablecerla. El cambio de contraseña conserva la doble verificación.</p></details>
      <div className="login-help"><CircleHelp size={18} /><p>El acceso de trabajadores y veterinarios se habilita mediante una invitación del dueño. Cada persona utiliza su cuenta.</p></div></div><span className="login-bottom">GeoCattle · Supervisión predial local</span></main>
  </div>;
}
function readPublicToken(kind: 'enrol' | 'reset') {
  const fragment = location.hash.slice(1);
  if (fragment.startsWith(`${kind}?`)) return new URLSearchParams(fragment.slice(kind.length + 1)).get('token') ?? '';
  if (fragment.startsWith(`${kind}=`)) { try { return decodeURIComponent(fragment.slice(kind.length + 1)); } catch { return ''; } }
  return '';
}
export default function App() {
  const [session, updateSession] = useState<Session | null>(null); const [checking, setChecking] = useState(true); const [authError, setAuthError] = useState(''); const [authNotice, setAuthNotice] = useState('');
  const [page, setPage] = useState<Page>(() => (allNavigation.find(nav => nav.id === location.hash.slice(1))?.id ?? 'overview')); const [enrolToken, setEnrolToken] = useState(() => readPublicToken('enrol')); const [resetToken, setResetToken] = useState(() => readPublicToken('reset'));
  const [mobileMenu, setMobileMenu] = useState(false); const [connected, setConnected] = useState(true); const [contextBusy, setContextBusy] = useState(false); const [contextError, setContextError] = useState(''); const [search, setSearch] = useState(''); const [toast, setToast] = useState('');
  const admin = session?.user.role === 'admin'; const hasFarm = !!session?.user.farm_id;
  const role = session?.user.role; const owner = role === 'owner' || admin; const worker = role === 'worker' || role === 'operator';
  const overview = useData<Overview>(session && hasFarm ? '/dashboard' : null, session && hasFarm ? 30000 : 0, session?.user.farm_id ?? '');
  const allowed = new Set<Page>(['profile']);
  if (hasFarm) allowed.add('notices');
  if (admin) ['admin', 'owners', 'users', 'audit', 'farms'].forEach(p => allowed.add(p as Page));
  if (role === 'owner') allowed.add('farms');
  if (hasFarm) {
    ['overview', 'animals', 'events'].forEach(p => allowed.add(p as Page));
    if (role !== 'viewer') allowed.add('health');
    if (owner) ['hardware', 'devices', 'gateways', 'geofences', 'team', 'changes', 'operations', 'settings', 'audit'].forEach(p => allowed.add(p as Page));
    if (worker) allowed.add('changes');
  }
  const navigation = allNavigation.filter(item => allowed.has(item.id)).map(item => item.id === 'farms' && admin ? { ...item, title: 'Predios de plataforma' } : item.id === 'changes' && worker ? { ...item, title: 'Mis reportes y solicitudes' } : item.id === 'overview' ? { ...item, title: role === 'owner' ? 'Panel dueño' : role === 'veterinarian' ? 'Panel veterinario' : worker ? 'Panel trabajador' : 'Panel del predio' } : item);
  const defaultPage: Page = admin ? 'admin' : hasFarm ? 'overview' : role === 'owner' ? 'farms' : 'profile'; const activePage = allowed.has(page) ? page : defaultPage;
  const refreshSession = () => api<Session>('/auth/me').then(result => { setSession(result); updateSession(result); }).catch(err => setToast(message(err)));
  useEffect(() => {
    let alive = true;
    api<Session>('/auth/me').then(result => { if (alive) { setSession(result); updateSession(result); } }).catch(err => { if (alive && (!(err instanceof ApiError) || err.status !== 401)) setAuthError(message(err)); }).finally(() => { if (alive) setChecking(false); });
    const expired = () => { setSession(null); updateSession(null); setAuthError('La sesión ha caducado. Ingresa nuevamente.'); setAuthNotice(''); };
    const connectivity = (event: Event) => setConnected((event as CustomEvent<boolean>).detail);
    const route = () => { setPage(allNavigation.find(nav => nav.id === location.hash.slice(1))?.id ?? 'overview'); setEnrolToken(readPublicToken('enrol')); setResetToken(readPublicToken('reset')); };
    window.addEventListener('session-expired', expired); window.addEventListener('api-connectivity', connectivity); window.addEventListener('hashchange', route);
    return () => { alive = false; window.removeEventListener('session-expired', expired); window.removeEventListener('api-connectivity', connectivity); window.removeEventListener('hashchange', route); };
  }, []);
  useEffect(() => { if (!toast) return; const timeout = setTimeout(() => setToast(''), 6000); return () => clearTimeout(timeout); }, [toast]);
  function navigate(next: Page) { location.hash = next; setPage(next); setMobileMenu(false); }
  async function switchFarm(farmId: string) { if ((!farmId && !admin) || farmId === (session?.user.farm_id ?? '')) return; setContextBusy(true); setContextError(''); try { const result = await write<Session>('/auth/context', { farm_id: farmId || null }); setSession(result); updateSession(result); setSearch(''); navigate('overview'); } catch (err) { setContextError(message(err)); } finally { setContextBusy(false); } }
  async function logout() { try { await api('/auth/logout', { method: 'POST' }); setSession(null); updateSession(null); setAuthError(''); } catch (err) { setToast(message(err)); } }
  if (checking) return <div className="app-start"><Brand /><Loading label="Conectando con GeoCattle…" /></div>;
  if (resetToken) return <ResetPasswordPage token={resetToken} onBack={() => { setSession(null); updateSession(null); setAuthError(''); setAuthNotice(''); location.hash = ''; setResetToken(''); }} />;
  if (enrolToken) return <EnrolPage token={enrolToken} onBack={() => { location.hash = ''; setEnrolToken(''); }} />;
  if (!session) return <Login onLogin={result => { updateSession(result); setAuthNotice(''); setAuthError(''); setPage(result.user.role === 'admin' ? 'admin' : 'overview'); }} initialError={authError} initialNotice={authNotice} />;
  const farmName = session.user.farms?.find(f => f.id === session.user.farm_id)?.name ?? overview.data?.farm.name ?? 'Selecciona un predio';
  return <div className="app-shell v3-shell"><a className="v3-skip-link" href="#main-content" onClick={e => { e.preventDefault(); document.getElementById('main-content')?.focus(); }}>Saltar al contenido</a>{mobileMenu && <button className="sidebar-overlay" aria-label="Cerrar navegación" onClick={() => setMobileMenu(false)} />}
    <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`}><div className="sidebar-brand"><Brand light /><button className="icon-button mobile-close" aria-label="Cerrar menú" onClick={() => setMobileMenu(false)}><X size={20} /></button></div><div className="farm-switch v3-farm-switch"><label><span>{admin ? 'CONTEXTO DE SOPORTE' : 'PREDIO ACTUAL'}</span><select aria-label="Cambiar predio autorizado" value={session.user.farm_id ?? ''} disabled={contextBusy || !session.user.farms?.length} onChange={e => switchFarm(e.target.value)}><option value="">{admin ? 'Panel global' : 'Selecciona un predio'}</option>{session.user.farms?.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label></div><span className="nav-label">{admin ? 'PLATAFORMA Y PREDIOS' : roleLabels[role ?? ''] ?? 'SUPERVISIÓN'}</span><nav aria-label="Navegación principal">{navigation.map(item => <button key={item.id} onClick={() => navigate(item.id)} className={`nav-item ${activePage === item.id ? 'nav-active' : ''}`} aria-current={activePage === item.id ? 'page' : undefined}><item.icon size={18} /><span>{item.title}</span>{item.id === 'events' && !!overview.data?.summary.active_events && <span className="nav-count">{overview.data.summary.active_events}</span>}</button>)}</nav><div className="sidebar-bottom"><div className="local-status"><span className={`connection-dot ${connected ? 'green' : 'red'}`} /><div><strong>{connected ? 'Servidor conectado' : 'Servidor no disponible'}</strong><small>{overview.data?.farm.environment === 'simulation' ? 'Entorno de simulación' : 'Sesión personal'}</small></div></div><div className="sidebar-user"><span className="avatar">{(session.user.full_name || session.user.username).slice(0, 2).toUpperCase()}</span><div><strong>{session.user.full_name || session.user.username}</strong><small>{roleLabels[role ?? ''] ?? role}</small></div><button className="icon-button" onClick={logout} aria-label="Cerrar sesión" title="Cerrar sesión"><LogOut size={17} /></button></div></div></aside>
    <div className="app-body"><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Abrir menú" onClick={() => setMobileMenu(true)}><Menu size={22} /></button><span>{admin && ['admin', 'owners', 'users', 'audit'].includes(activePage) ? 'Plataforma' : farmName}</span><ChevronRight size={15} /><strong>{navigation.find(nav => nav.id === activePage)?.title}</strong></div>{hasFarm && <form className="global-search" onSubmit={e => { e.preventDefault(); navigate('animals'); }}><Search size={16} /><input aria-label="Buscar animales por nombre o DIIO" placeholder="Buscar nombre o DIIO…" value={search} onChange={e => setSearch(e.target.value)} /><kbd>↵</kbd></form>}{hasFarm && <button className="top-notification icon-button" aria-label="Ver mis avisos" onClick={() => navigate('notices')}><Bell size={20} /></button>}</header>
      {!connected && <div className="connectivity-banner" role="alert"><WifiOff size={17} /><span>Conexión interrumpida. La información visible puede estar desactualizada.</span><button onClick={overview.reload}>Reintentar</button></div>}
      {overview.data?.farm.environment === 'simulation' && <div className="simulation-banner"><span className="simulation-tag">SIMULACIÓN</span><span>Predio de demostración. Las lecturas con origen <strong>sim</strong> son simuladas.</span></div>}
      <main className="main-content" id="main-content" tabIndex={-1}><ErrorNotice error={contextError} />{contextBusy ? <Loading label="Cambiando al predio autorizado…" /> : <Suspense fallback={<Loading label="Abriendo panel…" />}><div key={`${session.user.id}-${session.user.farm_id}-${role}`}>
        {!hasFarm && !admin && activePage !== 'farms' && <div className="notice"><Building2 size={18} /><span>{session.user.farms?.length ? 'Selecciona un predio para abrir tu panel.' : 'Tu cuenta aún no tiene un predio activo. Contacta al dueño o administrador.'}</span></div>}
        {activePage === 'admin' && <AdminDashboard />}{activePage === 'owners' && <AdminOwners notify={setToast} />}{activePage === 'users' && <AdminUsers notify={setToast} />}
        {activePage === 'overview' && <><div className="v3-role-heading"><div><span className="eyebrow">{roleLabels[role ?? '']}</span><p>{role === 'veterinarian' ? 'Las fichas técnicas y sanitarias se aplican directamente y conservan tu autoría.' : worker ? 'Reporta cambios del predio y consulta la decisión del dueño.' : role === 'viewer' ? 'Consulta el mapa y el monitoreo del predio con tu acceso de lectura.' : 'Gestiona el predio, el equipo y las decisiones de tu rebaño.'}</p></div><div className="v3-inline-actions">{role !== 'viewer' && <button className="button secondary small" onClick={() => navigate('health')}><FileHeart size={16} />{worker ? 'Consultar fichas' : 'Fichas y agenda'}</button>}{worker && <button className="button primary small" onClick={() => navigate('changes')}>Registrar reporte</button>}{owner && <button className="button primary small" onClick={() => navigate('changes')}>Revisar aprobaciones</button>}</div></div><OverviewPage overview={overview} canWrite={owner} notify={setToast} navigate={navigate} /></>}
        {activePage === 'farms' && <FarmsPage admin={admin} notify={setToast} onUpdated={refreshSession} />}
        {activePage === 'animals' && <AnimalsPage search={search} setSearch={setSearch} canWrite={owner} notify={setToast} />}
        {activePage === 'health' && <HealthPage worker={worker} actorId={session.user.id} notify={setToast} />}
        {activePage === 'changes' && <ChangesPage worker={worker} notify={setToast} />}
        {activePage === 'team' && <TeamPage admin={admin} notify={setToast} />}
        {activePage === 'gateways' && <GatewaysPage notify={setToast} />}
        {activePage === 'hardware' && <HardwarePage farmId={session.user.farm_id ?? ''} />}{activePage === 'devices' && <DevicesPage canWrite={owner} notify={setToast} />}
        {activePage === 'geofences' && <GeofencesPage canWrite={owner} notify={setToast} />}
        {activePage === 'events' && <EventsPage canWrite={role !== 'viewer'} canConfigure={owner} simulation={overview.data?.farm.environment === 'simulation'} farmName={farmName} notify={setToast} />}
        {activePage === 'operations' && <OperationsPage canWrite={owner} canAudit={owner} notify={setToast} simulation={overview.data?.farm.environment === 'simulation'} onChange={overview.reload} />}
        {activePage === 'settings' && <SettingsPage canWrite={owner} notify={setToast} simulation={overview.data?.farm.environment === 'simulation'} farmName={farmName} />}
        {activePage === 'audit' && <AuditPage global={admin} />}
        {activePage === 'notices' && <UserNotifications notify={setToast} />}
        {activePage === 'profile' && <ProfilePage notify={setToast} mfaEnabled={session.user.mfa_enabled} onUpdated={refreshSession} onSignedOut={() => { setSession(null); updateSession(null); setAuthError(''); setAuthNotice('Contraseña actualizada. Inicia sesión con tu nueva clave.'); location.hash = ''; }} />}
      </div></Suspense>}</main><footer className="app-footer"><span>GeoCattle <span>·</span> {roleLabels[role ?? '']}</span><span><span className={`connection-dot ${connected ? 'green' : 'red'}`} />{connected ? 'Red local' : 'Conexión interrumpida'}<span className="footer-separator">|</span>Hora de Chile</span></footer>
    </div>{toast && <div className="toast" role="status"><Check size={18} /><span>{toast}</span><button className="icon-button" aria-label="Cerrar aviso" onClick={() => setToast('')}><X size={16} /></button></div>}
  </div>;
}
function OverviewPage({ overview, canWrite, notify, navigate }: { overview: ReturnType<typeof useData<Overview>>; canWrite: boolean; notify: Notify; navigate: (page: Page) => void }) {
  const geofences = useData<List<Geofence>>('/geofences');
  const gateways = useData<List<Gateway>>('/v3/gateways');
  const [sector, setSector] = useState('');
  const [selected, setSelected] = useState<Animal | null>(null);
  const [adding, setAdding] = useState(false);
  const data = overview.data;
  const filteredAnimals = data?.animals.filter(animal => !sector || animal.sector_id === sector) ?? [];
  const activeFences = geofences.data?.items.filter(fence => fence.active && (!sector || fence.sector_id === sector)) ?? [];
  const outstanding = data?.events.filter(event => event.attention !== 'concluded').slice(0, 4) ?? [];
  const fresh = data?.animals.filter(a => a.position_status === 'fresh').length ?? 0;
  return <>
    <PageTitle eyebrow="TU PREDIO, DE UN VISTAZO" title="Todo el rebaño, cerca." description="Supervisa la ubicación y el estado de tus animales." actions={<><button className="button secondary" onClick={() => { overview.reload(); geofences.reload(); gateways.reload(); }} disabled={overview.loading}><RefreshCw size={16} className={overview.loading ? 'spin' : ''} />Actualizar</button>{canWrite && <button className="button primary" onClick={() => setAdding(true)}>+ Registrar animal</button>}</>} />
    <ErrorNotice error={overview.error} retry={overview.reload} />
    {!data && overview.loading ? <Loading /> : data && <>
      <div className="metrics"><div className="metric metric-total"><div className="metric-top"><span>Total de animales</span><Sprout size={19} /></div><strong>{data.summary.total}<small>en el predio</small></strong><div className="metric-foot"><span className="connection-dot green" />{fresh} con posición vigente</div></div><div className="metric"><div className="metric-top"><span>En estado normal</span><span className="metric-dot normal" /></div><strong>{data.summary.normal}<small>animales</small></strong><div className="metric-foot">Lecturas vigentes y sin alertas</div></div><div className="metric"><div className="metric-top"><span>Necesitan atención</span><Bell size={18} className="amber-text" /></div><strong>{data.summary.warning + data.summary.critical}<small>animales</small></strong><div className="metric-foot"><span className="critical-text">{data.summary.critical} críticos</span><span className="metric-foot-dot">·</span>{data.summary.warning} con precaución</div></div><div className="metric"><div className="metric-top"><span>Sin información</span><Radio size={18} className="muted" /></div><strong>{data.summary.unknown}<small>animales</small></strong><div className="metric-foot">No equivale a un estado normal</div></div></div>
      <div className="overview-grid"><Panel className="map-panel"><PanelTitle title="Mapa del predio" subtitle="Última posición recibida y geocercas" action={<select className="compact-select" aria-label="Filtrar mapa por sector" value={sector} onChange={e => setSector(e.target.value)}><option value="">Todos los sectores</option>{data.sectors.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>} /><ErrorNotice error={geofences.error || gateways.error} retry={() => { geofences.reload(); gateways.reload(); }} /><CattleMap animals={filteredAnimals} geofences={activeFences} gateways={gateways.data?.items ?? []} onAnimal={setSelected} /><div className="map-panel-foot"><span><MapPin size={15} />{filteredAnimals.filter(a => a.last_position?.gnss_valid && a.last_position.latitude != null).length} posiciones de {filteredAnimals.length} animales</span><span>Las posiciones vencidas se muestran en gris.</span></div></Panel><Panel className="events-panel"><PanelTitle title="Atención pendiente" subtitle={`${data.summary.active_events} eventos con condición activa`} action={<button className="icon-button" title="Ver todos los eventos" aria-label="Ver todos los eventos" onClick={() => navigate('events')}><ArrowRight size={18} /></button>} />{outstanding.length ? <div className="event-cards">{outstanding.map(event => <button key={event.id} className="event-card" onClick={() => navigate('events')}><span className={`event-icon ${event.severity}`}><Bell size={17} /></span><div><div className="event-card-top"><strong>{eventLabels[event.type] ?? event.type.replaceAll('_', ' ')}</strong><span className={`mini-dot ${event.severity}`} /></div><p>{event.animal_name || event.diio}<span> · DIIO {event.diio}</span></p><small>{date(event.opened_at)}<span> · {event.condition === 'active' ? 'Condición activa' : 'Condición resuelta'}</span></small></div><ChevronRight size={15} /></button>)}</div> : <Empty title="Sin atención pendiente" description="Los eventos nuevos aparecerán aquí." />}<div className="panel-bottom"><button className="text-button" onClick={() => navigate('events')}>Ir a eventos y seguimiento <ArrowRight size={16} /></button></div><div className="attention-note"><ShieldCheck size={17} /><p>La atención es independiente de la condición del evento. Revisa cada caso y registra las acciones.</p></div></Panel></div>
      <Panel className="herd-panel"><PanelTitle title="Tu rebaño" subtitle="Información reciente de los animales del predio" action={<button className="text-button" onClick={() => navigate('animals')}>Ver todos los animales <ArrowRight size={16} /></button>} />{data.animals.length ? <div className="table-scroll"><table><thead><tr><th>Animal / DIIO</th><th>Sector</th><th>Estado</th><th>Última posición</th><th>Comunicación</th><th aria-label="Abrir ficha" /></tr></thead><tbody>{data.animals.slice(0, 5).map(animal => <tr key={animal.id}><td><div className="animal-cell"><span className={`animal-avatar ${animal.status}`}><Sprout size={19} /></span><div><button className="row-title" onClick={() => setSelected(animal)}>{animal.name || 'Sin nombre'}</button><small>{animal.diio}</small></div></div></td><td>{animal.sector_name ?? 'Sin sector'}</td><td><Badge status={animal.status} /></td><td><span className={animal.position_status !== 'fresh' ? 'muted' : ''}>{age(animal.position_age_seconds)}</span><small>{animal.position_status === 'fresh' ? 'Vigente' : animal.position_status === 'stale' ? 'Vencida' : 'Desconocida'}</small></td><td><span className={`table-dot ${animal.communication_status === 'recent' ? 'green' : 'gray'}`} />{animal.communication_status === 'recent' ? 'Reciente' : animal.communication_status === 'absent' ? 'Ausente' : 'Sin registro'}</td><td><button className="icon-button" aria-label={`Ver ficha de ${animal.name || animal.diio}`} onClick={() => setSelected(animal)}><ArrowDownLeft size={17} /></button></td></tr>)}</tbody></table></div> : <Empty title="El rebaño aún no tiene animales" description="Registra el primer animal y asocia un collar para comenzar la supervisión." />}</Panel>
    </>}
    {selected && <AnimalDetail animalId={selected.id} onClose={() => setSelected(null)} canWrite={canWrite} notify={notify} onChanged={overview.reload} />}
    {adding && <AnimalForm onClose={() => setAdding(false)} onSaved={() => { setAdding(false); overview.reload(); notify('Animal registrado correctamente.'); }} />}
  </>;
}
