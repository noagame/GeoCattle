export type CollarDescriptor = {
  hardware_id: string;
  transport: 'academic';
  interval_seconds: number;
  firmware_version?: string;
};

type CollarLine = { kind: 'collar'; descriptor: CollarDescriptor } | { kind: 'receiver' };
type CollarPort = {
  open(options: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  readable: ReadableStream<Uint8Array> | null;
  writable: WritableStream<Uint8Array> | null;
};
type CollarSerial = { requestPort(): Promise<CollarPort> };

const maxLineBytes = 1024;
const identify = new TextEncoder().encode('\nGEOCATTLE_IDENTIFY_V1\n');
const hardwareId = /^[A-Za-z0-9_-]{1,16}$/;
const maxUint32 = 2 ** 32 - 1;
const legacyFields = ['v', 'id', 's', 'q', 'u', 'g', 't', 'a', 'm', 'b', 'p', 'f', 'e'];
const unsupported = 'Web Serial no está disponible. Usa Chrome o Edge en este equipo y abre GeoCattle en localhost o por HTTPS. En Windows también puedes usar Registrar-Collar-USB.cmd.';
const permissionDenied = 'No se concedió acceso al puerto USB. Permite el acceso al puerto serie en Chrome o Edge y vuelve a intentarlo.';
const floatToken = Symbol('float');

function whole(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

function measurement(value: unknown, min: number, max: number) {
  const amount = value !== null && typeof value === 'object' && floatToken in value ? value[floatToken] : value;
  return amount === null || (typeof amount === 'number' && Number.isFinite(amount) && amount >= min && amount <= max);
}

function vector(value: unknown, length: number): value is unknown[] {
  return Array.isArray(value) && value.length === length;
}

function duplicateKeys(line: string) {
  const keys = new Set<string>();
  for (const [, token, colon] of line.matchAll(/("(?:[^"\\]|\\.)*")(\s*:)?/g)) {
    if (!colon) continue;
    const key: string = JSON.parse(token);
    if (keys.has(key)) return true;
    keys.add(key);
  }
  return false;
}

function legacyDescriptor(item: Record<string, unknown>, line: string): CollarDescriptor | null {
  const { v, id, s, q, u, g, t, a, m, b, p, f, e, d } = item;
  if (!legacyFields.every(field => Object.hasOwn(item, field)) ||
      Object.keys(item).some(field => field !== 'd' && !legacyFields.includes(field)) || duplicateKeys(line) ||
      v !== 5 || typeof id !== 'string' || !hardwareId.test(id) ||
      typeof s !== 'string' || !/^[0-9A-Fa-f]{16}$/.test(s) || !whole(q, 0, maxUint32) || !whole(u, 0, maxUint32) ||
      !whole(p, 30000, 45000) || !whole(f, 0, 7) || !whole(e, 0, 2) ||
      !vector(g, 5) || !measurement(t, -60, 100) || !vector(a, 3) || !a.every(axis => measurement(axis, -32, 32)) ||
      !vector(m, 2) || !vector(b, 5) || !(d == null || (vector(d, 3) && d.every(value => whole(value, 0, maxUint32))))) return null;

  const [lat, lon, age, sats, hdop] = g;
  const fix = lat !== null;
  if (!measurement(lat, -90, 90) || !measurement(lon, -180, 180) || fix !== (lon !== null) ||
      !whole(age, -1, maxUint32) || (fix && !whole(age, 0, 4999)) || !whole(sats, -1, 99) || !measurement(hdop, 0, 999.99)) return null;

  const missingAxis = a.includes(null);
  const [state, score] = m;
  if (!whole(state, -1, 1) || !measurement(score, 0, 100) || (state !== -1 && (score === null || missingAxis))) return null;
  if (f !== ((fix ? 0 : 1) | (t === null ? 2 : 0) | (missingAxis ? 4 : 0))) return null;

  const [mv, pct, present, charging, reported] = b;
  if (!whole(mv, -1, 4350) || (mv !== -1 && mv < 2500) || !whole(pct, -1, 100) ||
      !whole(present, -1, 1) || !whole(charging, -1, 1) || !whole(reported, -1, 1) ||
      (mv === -1) !== (pct === -1) || (mv !== -1 && present === 0) || (charging === 1 && present !== 1)) return null;

  return { hardware_id: id, transport: 'academic', interval_seconds: Math.ceil(p / 1000) };
}

export function parseCollarLine(line: Uint8Array): CollarLine | null {
  if (line.length > maxLineBytes) return null;
  let text: string;
  let parsed: unknown;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(line);
    parsed = JSON.parse(text, (_key, value: unknown, context?: { source?: string }) =>
      typeof value === 'number' && /[.eE]/.test(context?.source ?? '') ? { [floatToken]: value } : value);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const item = parsed as Record<string, unknown>;
  if (Object.hasOwn(item, 'radio') || Object.hasOwn(item, 'packet')) return { kind: 'receiver' };
  if (item.type === 'geocattle_collar') {
    const { version, hardware_id, transport, interval_seconds, firmware_version } = item;
    if (version !== 1 || typeof hardware_id !== 'string' || !hardwareId.test(hardware_id) ||
        transport !== 'academic' || !whole(interval_seconds, 30, 86400)) return null;
    const descriptor: CollarDescriptor = { hardware_id, transport, interval_seconds };
    if (typeof firmware_version === 'string' && firmware_version && [...firmware_version].length <= 100) {
      descriptor.firmware_version = firmware_version;
    }
    return { kind: 'collar', descriptor };
  }
  const descriptor = legacyDescriptor(item, text);
  return descriptor ? { kind: 'collar', descriptor } : null;
}

async function readCollar(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<CollarDescriptor> {
  const line = new Uint8Array(maxLineBytes);
  let size = 0;
  const connectionLost = () => new Error('Se interrumpió la conexión USB. Reconecta el collar y vuelve a intentarlo.');
  while (true) {
    const { done, value } = await reader.read().catch(() => { throw connectionLost(); });
    if (done) throw connectionLost();
    for (const byte of value) {
      if (size < maxLineBytes) line[size] = byte;
      size = Math.min(size + 1, maxLineBytes + 1);
      if (byte !== 10) continue;
      const result = size <= maxLineBytes ? parseCollarLine(line.subarray(0, size)) : null;
      size = 0;
      if (result?.kind === 'receiver') {
        throw new Error('Seleccionaste la receptora USB. Conecta y selecciona el puerto del collar, no el de la receptora.');
      }
      if (result?.kind === 'collar') return result.descriptor;
    }
  }
}

type DetectionOptions = {
  signal: AbortSignal;
  onProgress: (stage: 'selecting' | 'identifying' | 'legacy') => void;
  timeoutMs?: number;
  queryWindowMs?: number;
  queryEveryMs?: number;
};

function errorName(error: unknown) {
  return error instanceof Error ? error.name : '';
}

export async function detectUsbCollar({ signal, onProgress, timeoutMs = 55000, queryWindowMs = 12000, queryEveryMs = 1000 }: DetectionOptions): Promise<CollarDescriptor> {
  const serial = (globalThis.navigator as (Navigator & { serial?: CollarSerial }) | undefined)?.serial;
  if (!serial) throw new Error(unsupported);
  signal.throwIfAborted();
  onProgress('selecting');
  let port: CollarPort;
  try {
    port = await serial.requestPort();
  } catch (error) {
    if (errorName(error) === 'NotFoundError') throw new Error('No se seleccionó un puerto. Conecta el collar con un cable USB de datos y selecciona su puerto.');
    throw new Error(permissionDenied);
  }

  signal.throwIfAborted();
  try {
    await port.open({ baudRate: 115200 });
  } catch (error) {
    if (['SecurityError', 'NotAllowedError'].includes(errorName(error))) throw new Error(permissionDenied);
    throw new Error('No se pudo abrir el puerto USB. Si está ocupado, cierra el Monitor Serie o el Plotter de Arduino y cualquier captura que use ese puerto.');
  }

  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  let writer: WritableStreamDefaultWriter<Uint8Array> | undefined;
  let cancel = () => {};
  let deadline: ReturnType<typeof setTimeout> | undefined;
  let queryTimer: ReturnType<typeof setInterval> | undefined;
  let legacyTimer: ReturnType<typeof setTimeout> | undefined;
  try {
    signal.throwIfAborted();
    reader = port.readable?.getReader();
    writer = port.writable?.getWriter();
    if (!reader || !writer) throw new Error('El puerto USB no está disponible. Reconecta el collar y vuelve a intentarlo.');
    const portWriter = writer;
    const stopped = new Promise<never>((_resolve, reject) => {
      cancel = () => reject(signal.reason);
      signal.addEventListener('abort', cancel, { once: true });
      deadline = setTimeout(() => reject(new Error('El collar no respondió en 55 segundos. Verifica que esté encendido, selecciona su puerto y vuelve a intentarlo.')), timeoutMs);
      const queryUntil = performance.now() + queryWindowMs;
      let writing = false;
      const sendQuery = () => {
        if (signal.aborted || writing || performance.now() >= queryUntil) return;
        writing = true;
        portWriter.write(identify).catch(() => reject(new Error('No se pudo enviar la consulta USB. Reconecta el collar y vuelve a intentarlo.')))
          .finally(() => { writing = false; });
      };
      onProgress('identifying');
      sendQuery();
      queryTimer = setInterval(sendQuery, queryEveryMs);
      legacyTimer = setTimeout(() => {
        clearInterval(queryTimer);
        onProgress('legacy');
      }, queryWindowMs);
    });
    return await Promise.race([readCollar(reader), stopped]);
  } finally {
    signal.removeEventListener('abort', cancel);
    clearTimeout(deadline);
    clearInterval(queryTimer);
    clearTimeout(legacyTimer);
    await Promise.allSettled([reader?.cancel(), writer?.abort()]);
    reader?.releaseLock();
    writer?.releaseLock();
    await port.close().catch(() => {});
  }
}
