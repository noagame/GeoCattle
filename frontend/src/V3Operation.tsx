import { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { api, write } from './api';

type ProtectedMethod = 'POST' | 'PATCH' | 'DELETE';

/** One authorization is bound to the exact mutation and consumed by the server. */
export function useVerifiedOperation(busy: boolean) {
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');

  async function perform<T>(path: string, payload: Record<string, unknown>, method: ProtectedMethod = 'POST'): Promise<T> {
    // Capture a single JSON representation before authorizing or dispatching the mutation.
    const serialized = JSON.stringify(payload);
    const authorization = await write<{ operation_token: string; expires_at: string }>('/auth/operation', {
      password,
      code,
      method,
      path: `/api/v1${path}`,
      payload: JSON.parse(serialized),
    });
    setPassword('');
    setCode('');
    return api<T>(path, {
      method,
      body: serialized,
      headers: { 'X-Operation-Token': authorization.operation_token },
    });
  }

  const fields = <fieldset className="v3-operation-verification" disabled={busy}>
    <legend><ShieldCheck size={16} />Verificación de esta operación</legend>
    <p>Introduce tu contraseña y un código nuevo de seis dígitos de la aplicación autenticadora. Cada código se usa una sola vez. Si acabas de verificar el acceso, espera al siguiente código.</p>
    <label>Contraseña de verificación<input type="password" autoComplete="current-password" required maxLength={256} value={password} onChange={event => setPassword(event.target.value)} /></label>
    <label>Código nuevo para esta operación<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" minLength={6} maxLength={6} required value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ''))} /></label>
    <small>La autorización queda ligada a los datos y al destino de este cambio.</small>
  </fieldset>;

  return { perform, fields };
}
