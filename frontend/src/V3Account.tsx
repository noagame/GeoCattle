import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { Check, KeyRound, LockKeyhole, ShieldCheck, UserRound } from 'lucide-react';
import qrcode from 'qrcode-generator';
import { PasswordInput } from './PasswordInput';
import { date, message, setSession, useData, write } from './api';
import { Empty, ErrorNotice, Loading, Modal, PageTitle, Panel, PanelTitle, Submit } from './ui';
import type { Notify } from './App';
import type { Session } from './types';
import type { Profile } from './v3types';
import { roleLabels } from './v3types';

export function StepUpGate({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const [expires, setExpires] = useState(''); const [password, setPassword] = useState(''); const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  useEffect(() => { if (!expires) return; const remaining = new Date(expires).getTime() - Date.now(); if (remaining <= 0) { setExpires(''); return; } const timer = setTimeout(() => setExpires(''), remaining); return () => clearTimeout(timer); }, [expires]);
  async function verify(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { const result = await write<{ verified: boolean; expires_at: string }>('/auth/step-up', { password, code }); if (!result.verified) throw new Error('No se pudo verificar tu identidad.'); setExpires(result.expires_at); setPassword(''); setCode(''); } catch (err) { setError(message(err)); } finally { setBusy(false); } }

  return <>{expires ? <><div className="v3-verification"><ShieldCheck size={18} /><span>Identidad verificada hasta {date(expires)}.</span><button className="text-button" onClick={() => setExpires('')}>Bloquear gestión</button></div>{children}</> : <Panel><PanelTitle title="Verifica tu identidad" subtitle="El acceso a colaboradores y permisos requiere contraseña y segundo factor." /><form className="form-body v3-narrow" onSubmit={verify}><p className="form-intro">Usa el código de tu aplicación autenticadora. Las operaciones se validan también en el servidor.</p><PasswordInput label="Contraseña" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /><label>Código de verificación<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} /></label><ErrorNotice error={error} /><div className="form-actions"><Submit busy={busy}>Verificar identidad</Submit></div></form></Panel>}</>;
}
export function ProfilePage({ notify, onUpdated, onSignedOut, mfaEnabled = false }: { notify: Notify; mfaEnabled?: boolean; onUpdated: () => void; onSignedOut: (notice?: string) => void }) {
  const profile = useData<Profile>('/v3/profile'); const [setup, setSetup] = useState(false);
  const [securityAction, setSecurityAction] = useState<'password' | 'recovery' | 'closure' | 'replace' | 'remove' | null>(null);
  return <>
    <PageTitle eyebrow="TU CUENTA" title="Mi perfil" description="Mantén actualizados tus datos de contacto." actions={!mfaEnabled && <button className="button secondary" onClick={() => setSetup(true)}><ShieldCheck size={17} />Activar doble verificación</button>} />
    <ErrorNotice error={profile.error} retry={profile.reload} />{profile.loading ? <Loading /> : profile.data && <ProfileForm initial={profile.data} onSaved={() => { profile.reload(); onUpdated(); notify('Datos personales actualizados.'); }} />}
    <Panel>
      <PanelTitle title="Seguridad y acceso" />
      <div className="form-body">
        <p className="form-intro">{mfaEnabled ? 'Doble verificación activa. Cada código de recuperación se usa una vez junto con tu contraseña.' : 'Activa la doble verificación para disponer de códigos de recuperación.'}</p>
        <div className="v3-inline-actions">
          <button className="button secondary" onClick={() => setSecurityAction('password')}><KeyRound size={17} />Cambiar contraseña</button>
          {mfaEnabled && <>
            <button className="button secondary" onClick={() => setSecurityAction('replace')}><ShieldCheck size={17} />Reemplazar autenticador</button>
            <button className="button secondary" onClick={() => setSecurityAction('remove')}>Quitar autenticador</button>
            <button className="button secondary" onClick={() => setSecurityAction('recovery')}>Generar códigos de recuperación</button>
          </>}
          <button className="button secondary" onClick={() => setSecurityAction('closure')}>Solicitar cierre de cuenta</button>
        </div>
      </div>
    </Panel>
    {setup && <MfaSetup onClose={() => setSetup(false)} onSaved={() => { setSetup(false); onUpdated(); notify('Doble verificación activada.'); }} />}
    {securityAction === 'password' && <PasswordChangeForm mfaEnabled={mfaEnabled} onClose={() => setSecurityAction(null)} onSaved={onSignedOut} />}
    {securityAction === 'recovery' && <RecoveryCodesForm onClose={() => setSecurityAction(null)} />}
    {securityAction === 'closure' && <CloseAccountForm mfaEnabled={mfaEnabled} onClose={() => setSecurityAction(null)} />}
    {(securityAction === 'replace' || securityAction === 'remove') && <AuthenticatorChangeForm
      action={securityAction} onClose={() => setSecurityAction(null)}
      onReplaced={() => { setSecurityAction(null); onUpdated(); notify('Autenticador reemplazado. Puedes generar códigos de recuperación nuevos.'); }}
      onRemoved={required => onSignedOut(required ? 'Autenticador retirado. Inicia sesión para inscribir uno nuevo.' : 'Autenticador retirado. Vuelve a iniciar sesión.')}
    />}
  </>;
}
function ProfileForm({ initial, onSaved }: { initial: Profile; onSaved: () => void }) {
  const [name, setName] = useState(initial.full_name ?? ''); const [phone, setPhone] = useState(initial.phone ?? ''); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { await write('/v3/profile', { full_name: name, phone: phone || null }, 'PATCH'); onSaved(); } catch (err) { setError(message(err)); } finally { setBusy(false); } }
  return <Panel><PanelTitle title="Datos personales" action={<UserRound size={21} />} /><form className="form-body v3-narrow" onSubmit={submit}><label>Correo de acceso<input type="email" value={initial.email ?? initial.username} disabled autoComplete="email" /><small><a href="#support?kind=change_email">Solicitar cambio de correo a soporte</a></small></label><label>Nombre completo<input required maxLength={150} autoComplete="name" value={name} onChange={e => setName(e.target.value)} /></label><label>Teléfono<input type="tel" maxLength={40} autoComplete="tel" value={phone} onChange={e => setPhone(e.target.value)} /></label><ErrorNotice error={error} /><div className="form-actions"><Submit busy={busy}>Actualizar perfil</Submit></div></form></Panel>;
}
type EnrolPreview = { email: string; role_code: 'worker' | 'veterinarian'; farm_name: string; expires_at: string; account_exists: boolean };
export function EnrolPage({ token, onBack }: { token: string; onBack: () => void }) {
  const [preview, setPreview] = useState<EnrolPreview | null>(null); const [previewBusy, setPreviewBusy] = useState(true); const [previewError, setPreviewError] = useState(''); const [retry, setRetry] = useState(0);
  const [name, setName] = useState(''); const [password, setPassword] = useState(''); const [repeat, setRepeat] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [done, setDone] = useState(false);
  useEffect(() => {
    let alive = true;
    setPreview(null); setPreviewBusy(true); setPreviewError(''); setError(''); setDone(false); setName(''); setPassword(''); setRepeat('');
    write<EnrolPreview>('/v3/enrol/preview', { token }).then(result => { if (alive) setPreview(result); })
      .catch(err => { if (alive) setPreviewError(message(err)); }).finally(() => { if (alive) setPreviewBusy(false); });
    return () => { alive = false; };
  }, [token, retry]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!preview || previewBusy) return;
    if (!preview.account_exists && password !== repeat) { setError('Las contraseñas no coinciden.'); return; }
    setBusy(true); setError('');
    try { await write('/v3/enrol', { token, password, ...(!preview.account_exists ? { full_name: name } : {}) }); setPassword(''); setRepeat(''); setDone(true); }
    catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  return <main className="v3-enrol"><Panel><PanelTitle title="Invitación a GeoCattle" subtitle="Revisa el acceso que te ofrece el dueño antes de aceptarlo." action={<KeyRound size={22} />} />{done ? <Empty title="Acceso activado" description={`Ya puedes iniciar sesión con ${preview?.email ?? 'el correo de la invitación'} y tu contraseña.`} action={<button className="button primary" onClick={onBack}><Check size={17} />Ir al inicio de sesión</button>} /> : previewBusy ? <Loading label="Validando la invitación…" /> : !preview ? <div className="form-body"><ErrorNotice error={previewError || 'La invitación no está disponible.'} /><p>No se puede crear el acceso hasta validar una invitación vigente del dueño.</p><div className="form-actions"><button type="button" className="button secondary" onClick={onBack}>Volver</button><button type="button" className="button primary" onClick={() => setRetry(value => value + 1)}>Volver a comprobar</button></div></div> : <form className="form-body" onSubmit={submit}>
    <label>Correo invitado<input type="email" readOnly value={preview.email} autoComplete="username" /></label><dl className="enrol-invitation-summary"><div><dt>Perfil asignado por el dueño</dt><dd>{roleLabels[preview.role_code]}</dd></div><div><dt>Predio autorizado</dt><dd>{preview.farm_name}</dd></div><div><dt>Válida hasta</dt><dd>{date(preview.expires_at)}</dd></div></dl>
    {preview.account_exists ? <p className="notice">Ya tienes una cuenta. Usa tu contraseña actual para incorporar este predio. Tu nombre y contraseña se conservan.</p> : <label>Nombre completo<input required autoComplete="name" maxLength={150} value={name} onChange={e => setName(e.target.value)} /></label>}
    <PasswordInput label={preview.account_exists ? 'Contraseña actual' : 'Crea tu contraseña'} required autoComplete={preview.account_exists ? 'current-password' : 'new-password'} minLength={preview.account_exists ? 1 : 12} maxLength={256} value={password} onChange={e => setPassword(e.target.value)} hint={preview.account_exists ? 'La contraseña no se modifica al aceptar la invitación.' : 'Usa al menos 12 caracteres.'} />
    {!preview.account_exists && <PasswordInput label="Repite la contraseña" required autoComplete="new-password" minLength={12} maxLength={256} value={repeat} onChange={e => setRepeat(e.target.value)} />}
    <ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={onBack}>Volver</button><Submit busy={busy}>Aceptar invitación</Submit></div></form>}</Panel><p><LockKeyhole size={14} />El dueño define el perfil y el predio. La invitación tiene vigencia limitada y se utiliza una sola vez.</p></main>;
}

type Enrollment = { challenge_token: string; secret: string; otpauth_uri: string };

export function AuthenticatorEnrollment({ secret, otpauth_uri }: { secret: string; otpauth_uri?: string }) {
  const qr = useMemo(() => {
    if (!otpauth_uri) return null;
    const code = qrcode(0, 'M');
    code.addData(otpauth_uri);
    code.make();
    return code.createDataURL(4, 16);
  }, [otpauth_uri]);
  return <div className="v3-mfa-setup">
    <p>Escanea el QR en tu aplicación autenticadora o ingresa la clave manual.</p>
    {qr && <img src={qr} width={224} height={224} alt="QR para inscribir el autenticador de GeoCattle" />}
    <label>Clave de configuración<input readOnly value={secret} autoComplete="off" spellCheck={false} onFocus={event => event.currentTarget.select()} /></label>
  </div>;
}

function AuthenticatorChangeForm({ action, onClose, onReplaced, onRemoved }: {
  action: 'replace' | 'remove'; onClose: () => void; onReplaced: () => void; onRemoved: (required: boolean) => void;
}) {
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [useRecovery, setUseRecovery] = useState(false);
  const [challenge, setChallenge] = useState<Enrollment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const removing = action === 'remove';
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      if (challenge) {
        const session = await write<Session>('/auth/mfa/verify', { challenge_token: challenge.challenge_token, code });
        setSession(session);
        onReplaced();
      } else {
        const credentials = { password, ...(useRecovery ? { recovery_code: code } : { code }) };
        if (removing) {
          const result = await write<{ enrollment_required: boolean }>('/auth/mfa/remove', credentials);
          onRemoved(result.enrollment_required);
        } else {
          setChallenge(await write<Enrollment>('/auth/mfa/replace', credentials));
        }
      }
      setPassword('');
      setCode('');
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }
  return <Modal title={removing ? 'Quitar autenticador' : 'Reemplazar autenticador'} onClose={onClose}>
    <form className="form-body" onSubmit={submit}>
      {challenge ? <>
        <AuthenticatorEnrollment secret={challenge.secret} otpauth_uri={challenge.otpauth_uri} />
        <p className="form-intro">Confirma en cinco minutos con un código del autenticador nuevo. Al activarlo se cerrarán las demás sesiones y caducarán los códigos de recuperación anteriores.</p>
        <label>Código del autenticador nuevo<input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ''))} /></label>
      </> : <>
        <p className="form-intro">{removing ? 'Se cerrarán todas las sesiones y caducarán los códigos de recuperación. Si tu acceso requiere doble verificación, inscribirás un autenticador en el siguiente ingreso.' : 'Tu autenticador actual seguirá activo hasta que confirmes el nuevo.'}</p>
        <PasswordInput label="Contraseña actual" autoComplete="current-password" required maxLength={256} value={password} onChange={event => setPassword(event.target.value)} />
        {useRecovery
          ? <label>Código de recuperación<input required autoComplete="off" spellCheck={false} minLength={20} maxLength={64} value={code} onChange={event => setCode(event.target.value)} /></label>
          : <label>Código del autenticador actual<input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ''))} /></label>}
        <button type="button" className="text-button" disabled={busy} onClick={() => { setUseRecovery(!useRecovery); setCode(''); }}>
          {useRecovery ? 'Usar código del autenticador' : 'Usar un código de recuperación'}
        </button>
      </>}
      <ErrorNotice error={error} />
      <div className="form-actions">
        <button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cancelar</button>
        <Submit busy={busy}>{removing ? 'Quitar y cerrar sesiones' : challenge ? 'Activar nuevo autenticador' : 'Continuar'}</Submit>
      </div>
    </form>
  </Modal>;
}

function MfaSetup({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [password, setPassword] = useState(''); const [code, setCode] = useState(''); const [challenge, setChallenge] = useState<{ challenge_token: string; secret: string; otpauth_uri: string } | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(''); try { if (!challenge) { setChallenge(await write('/auth/mfa/setup', { password })); setPassword(''); } else { const session = await write<Session>('/auth/mfa/verify', { challenge_token: challenge.challenge_token, code }); setSession(session); onSaved(); } } catch (err) { setError(message(err)); } finally { setBusy(false); } }
  return <Modal title="Activar doble verificación" onClose={onClose}><form className="form-body" onSubmit={submit}>{challenge ? <><AuthenticatorEnrollment secret={challenge.secret} otpauth_uri={challenge.otpauth_uri} /><label>Código de la aplicación<input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} /></label></> : <PasswordInput label="Confirma tu contraseña" required autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} />}<ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose}>Cancelar</button><Submit busy={busy}>{challenge ? 'Verificar y activar' : 'Configurar segundo factor'}</Submit></div></form></Modal>;
}

function PasswordChangeForm({ mfaEnabled, onClose, onSaved }: { mfaEnabled: boolean; onClose: () => void; onSaved: () => void }) {
  const [current, setCurrent] = useState(''); const [next, setNext] = useState(''); const [repeat, setRepeat] = useState(''); const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event: FormEvent) { event.preventDefault(); if (next !== repeat) { setError('Las contraseñas nuevas no coinciden.'); return; } setBusy(true); setError(''); try { await write('/auth/password/change', { current_password: current, new_password: next, ...(mfaEnabled ? { code } : {}) }); setCurrent(''); setNext(''); setRepeat(''); setCode(''); onSaved(); } catch (error) { setError(message(error)); } finally { setBusy(false); } }
  return <Modal title="Cambiar contraseña" onClose={onClose}><form className="form-body" onSubmit={submit}><p className="form-intro">Al guardar se cerrarán todas tus sesiones. Después inicia sesión con la contraseña nueva y tu segundo factor si está activo.</p><PasswordInput label="Contraseña actual" autoComplete="current-password" maxLength={256} required value={current} onChange={event => setCurrent(event.target.value)} /><PasswordInput label="Nueva contraseña" autoComplete="new-password" minLength={12} maxLength={256} required value={next} onChange={event => setNext(event.target.value)} /><PasswordInput label="Repite la nueva contraseña" autoComplete="new-password" minLength={12} maxLength={256} required value={repeat} onChange={event => setRepeat(event.target.value)} />{mfaEnabled && <label>Código nuevo de la aplicación autenticadora<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ''))} /></label>}<ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cancelar</button><Submit busy={busy}>Cambiar y cerrar sesiones</Submit></div></form></Modal>;
}
function RecoveryCodesForm({ onClose }: { onClose: () => void }) {
  const [password, setPassword] = useState(''); const [code, setCode] = useState(''); const [codes, setCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { const result = await write<{ recovery_codes: string[] }>('/auth/mfa/recovery-codes', { password, code }); setPassword(''); setCode(''); setCodes(result.recovery_codes); } catch (error) { setError(message(error)); } finally { setBusy(false); } }
  return <Modal title="Códigos de recuperación" onClose={onClose}>{codes ? <div className="form-body"><div className="notice"><ShieldCheck size={18} /><span>Estos códigos se muestran una sola vez. Guárdalos en un lugar privado antes de cerrar. Cada uno permite un acceso junto con tu contraseña.</span></div><label>Códigos generados<textarea autoComplete="off" readOnly rows={8} value={codes.join('\n')} onFocus={event => event.currentTarget.select()} /></label><p className="form-intro">La aplicación autenticadora continúa activa. Los códigos no se guardan en el navegador.</p><div className="form-actions"><button className="button primary" onClick={onClose}>Cerrar después de guardar</button></div></div> : <form className="form-body" onSubmit={submit}><p className="form-intro">Verifica tu identidad con un código que aún no hayas utilizado. Generar códigos nuevos invalida los anteriores.</p><PasswordInput label="Contraseña" autoComplete="current-password" maxLength={256} required value={password} onChange={event => setPassword(event.target.value)} /><label>Código nuevo de la aplicación autenticadora<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ''))} /></label><ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cancelar</button><Submit busy={busy}>Generar códigos</Submit></div></form>}</Modal>;
}
function CloseAccountForm({ mfaEnabled, onClose }: { mfaEnabled: boolean; onClose: () => void }) {
  const [password, setPassword] = useState(''); const [code, setCode] = useState(''); const [reason, setReason] = useState(''); const [confirmed, setConfirmed] = useState(false); const [requestId, setRequestId] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { const result = await write<{ requested: boolean; request_id: string }>('/auth/account/close-request', { password, ...(mfaEnabled ? { code } : {}), reason }); setPassword(''); setCode(''); setRequestId(result.request_id); } catch (error) { setError(message(error)); } finally { setBusy(false); } }
  return <Modal title="Solicitar cierre de cuenta" onClose={onClose}>{requestId ? <div className="form-body"><div className="notice"><Check size={18} /><span>Solicitud registrada para revisión. Tu acceso y los datos se conservan durante la revisión.</span></div><p className="form-intro">Folio {requestId}</p><div className="form-actions"><a className="button primary" href="#support" onClick={onClose}>Ver mis solicitudes a soporte</a></div></div> : <form className="form-body" onSubmit={submit}><p className="form-intro">Administración debe revisar los predios, las responsabilidades y la conservación del historial antes de resolver la solicitud.</p><label>Motivo<textarea rows={3} maxLength={2000} required value={reason} onChange={event => setReason(event.target.value)} /></label><PasswordInput label="Confirma tu contraseña" autoComplete="current-password" required maxLength={256} value={password} onChange={event => setPassword(event.target.value)} />{mfaEnabled && <label>Código nuevo de la aplicación autenticadora<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ''))} /></label>}<label className="checkbox-field"><input type="checkbox" required checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />Solicito que administración revise el cierre de mi cuenta.</label><ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cancelar</button><Submit busy={busy}>Enviar solicitud</Submit></div></form>}</Modal>;
}
export function ResetPasswordPage({ token, onBack }: { token: string; onBack: () => void }) {
  const [password, setPassword] = useState(''); const [repeat, setRepeat] = useState(''); const [done, setDone] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event: FormEvent) { event.preventDefault(); if (password !== repeat) { setError('Las contraseñas no coinciden.'); return; } setBusy(true); setError(''); try { await write('/auth/password/reset', { token, new_password: password }); setPassword(''); setRepeat(''); setDone(true); } catch (error) { setError(message(error)); } finally { setBusy(false); } }
  return <main className="v3-enrol"><Panel><PanelTitle title="Restablecer contraseña" subtitle="Utiliza el enlace privado entregado por administración." action={<KeyRound size={22} />} />{done ? <Empty title="Contraseña actualizada" description="Se cerraron las sesiones anteriores. Inicia sesión y completa la doble verificación si está activa." action={<button className="button primary" onClick={onBack}>Ir al inicio de sesión</button>} /> : <form className="form-body" onSubmit={submit}><PasswordInput label="Nueva contraseña" autoComplete="new-password" required minLength={12} maxLength={256} value={password} onChange={event => setPassword(event.target.value)} /><PasswordInput label="Repite la nueva contraseña" autoComplete="new-password" required minLength={12} maxLength={256} value={repeat} onChange={event => setRepeat(event.target.value)} /><ErrorNotice error={error} /><div className="form-actions"><button type="button" className="button secondary" disabled={busy} onClick={onBack}>Volver al acceso</button><Submit busy={busy}>Restablecer contraseña</Submit></div></form>}</Panel><p><LockKeyhole size={14} />El enlace tiene vigencia limitada y se utiliza una sola vez.</p></main>;
}
