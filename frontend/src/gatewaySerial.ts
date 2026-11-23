import { parseCollarLine } from './collarSerial';

export type GatewayNode = 1 | 2;
export type GatewayDescriptor = { gateway_eui: string; node_id: GatewayNode | null; firmware: string };
type SerialPort = {
  open(options: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  readable: ReadableStream<Uint8Array> | null;
  writable: WritableStream<Uint8Array> | null;
};

const maxLine = 1024;
const decoder = new TextDecoder('utf-8', { fatal: true });
const encoder = new TextEncoder();

export function parseGatewayLine(bytes: Uint8Array) {
  if (bytes.length > maxLine) return null;
  let item: Record<string, unknown>;
  try { item = JSON.parse(decoder.decode(bytes)); } catch { return null; }
  if (!item || typeof item !== 'object' || Array.isArray(item)) return null;
  if (item.type === 'geocattle_receiver' || 'gc_bus' in item || parseCollarLine(bytes)) return { kind: 'other' } as const;
  if (item.version !== 1) return null;
  if (item.type === 'geocattle_gateway_error' && item.error === 'nvs') return { kind: 'storage' } as const;
  if (typeof item.gateway_eui !== 'string' || !/^[a-f0-9]{16}$/.test(item.gateway_eui)) return null;
  const node = item.node_id === 0 ? null : item.node_id;
  if (node !== 1 && node !== 2 && node !== null) return null;
  if (item.provisioned !== (node !== null)) return null;
  if (item.type === 'geocattle_gateway_node' && node !== null) {
    return { kind: 'confirmed', eui: item.gateway_eui, node } as const;
  }
  if (item.type === 'geocattle_gateway' && typeof item.firmware === 'string' && item.firmware.length <= 100 && item.firmware.trim()) {
    return { kind: 'gateway', descriptor: { gateway_eui: item.gateway_eui, node_id: node, firmware: item.firmware } } as const;
  }
  return null;
}

async function readSerial<T>(reader: ReadableStreamDefaultReader<Uint8Array>, accept: (bytes: Uint8Array) => T | undefined) {
  const line = new Uint8Array(maxLine);
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) throw new Error('El USB se desconectó. Reconecta el gateway y vuelve a intentarlo.');
    for (const byte of value) {
      if (byte === 10) {
        const result = size <= maxLine ? accept(line.subarray(0, size)) : undefined;
        size = 0;
        if (result !== undefined) return result;
      } else if (size <= maxLine) {
        if (size < maxLine) line[size] = byte;
        size++;
      }
    }
  }
}

async function exchange<T>(reader: ReadableStreamDefaultReader<Uint8Array>, writer: WritableStreamDefaultWriter<Uint8Array>, signal: AbortSignal,
  command: string, accept: (bytes: Uint8Array) => T | undefined, timeout: string) {
  signal.throwIfAborted();
  let deadline: ReturnType<typeof setTimeout> | undefined;
  let repeat: ReturnType<typeof setInterval> | undefined;
  let abort = () => {};
  try {
    const stopped = new Promise<never>((_resolve, reject) => {
      abort = () => reject(signal.reason);
      signal.addEventListener('abort', abort, { once: true });
      deadline = setTimeout(() => reject(new Error(timeout)), 12000);
      let writing = false;
      const send = () => {
        if (writing || signal.aborted) return;
        writing = true;
        writer.write(encoder.encode(`\n${command}\n`)).catch(reject).finally(() => { writing = false; });
      };
      repeat = setInterval(send, 1000);
      send();
    });
    return await Promise.race([readSerial(reader, accept), stopped]);
  } finally {
    clearTimeout(deadline);
    clearInterval(repeat);
    signal.removeEventListener('abort', abort);
  }
}

export async function withUsbGateway<T>(signal: AbortSignal,
  action: (descriptor: GatewayDescriptor, setNode: (node: GatewayNode) => Promise<GatewayNode>) => Promise<T>, opened?: () => void) {
  const serial = (globalThis.navigator as (Navigator & { serial?: { requestPort(): Promise<SerialPort> } }) | undefined)?.serial;
  if (!serial) throw new Error('Web Serial requiere Chrome o Edge en localhost o HTTPS. En Windows puedes usar Registrar-Gateway-USB.cmd.');
  signal.throwIfAborted();
  let port: SerialPort;
  try { port = await serial.requestPort(); } catch { throw new Error('No se seleccionó un puerto USB con acceso.'); }
  signal.throwIfAborted();
  try { await port.open({ baudRate: 115200 }); } catch { throw new Error('No se pudo abrir el puerto. Cierra Arduino y cualquier captura que lo esté usando.'); }
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  let writer: WritableStreamDefaultWriter<Uint8Array> | undefined;
  try {
    reader = port.readable?.getReader();
    writer = port.writable?.getWriter();
    if (!reader || !writer) throw new Error('No se pudo leer el puerto USB. Reconecta la placa.');
    const input = reader, output = writer;
    opened?.();
    const descriptor = await exchange(input, output, signal, 'GEOCATTLE_IDENTIFY_V1', bytes => {
      const result = parseGatewayLine(bytes);
      if (result?.kind === 'other') throw new Error('Este puerto pertenece a una receptora o collar. Selecciona el gateway XIAO.');
      if (result?.kind === 'gateway') return result.descriptor;
    }, 'El gateway no respondió. Comprueba el puerto y que el XIAO tenga el firmware GeoCattle_Gateway.');
    const setNode = (node: GatewayNode) => exchange(input, output, signal,
      `GEOCATTLE_SET_NODE_V1 ${descriptor.gateway_eui} ${node}`, bytes => {
        const result = parseGatewayLine(bytes);
        if (result?.kind === 'storage') throw new Error('El gateway no pudo guardar el nodo en su memoria.');
        if (result?.kind === 'confirmed' && result.node === node && result.eui === descriptor.gateway_eui) return node;
      }, 'El gateway no confirmó el nodo. La reserva sigue activa: reconecta la misma placa y reintenta.');
    return await action(descriptor, setNode);
  } finally {
    await Promise.allSettled([reader?.cancel(), writer?.abort()]);
    reader?.releaseLock();
    writer?.releaseLock();
    await port.close().catch(() => {});
  }
}
