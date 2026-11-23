import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/collarSerial.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { detectUsbCollar, parseCollarLine } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const encoder = new TextEncoder();
const wire = value => encoder.encode(`${JSON.stringify(value)}\r\n`);
const descriptor = { hardware_id: 'REAL_01', transport: 'academic', interval_seconds: 45, firmware_version: '1.2' };
const descriptorV1 = { ...descriptor, type: 'geocattle_collar', version: 1 };
const legacy = {
  v: 5, id: 'REAL_01', s: 'AA34567890ABCDEF', q: 15, u: 42000, g: [null, null, -1, -1, null],
  t: 20.5, a: [0.1, -0.2, 1], m: [0, 10], b: [4000, 75, -1, -1, -1], p: 44001, f: 1, e: 0,
};
const receiver = { packet: legacy, radio: { rssi_dbm: -89, snr_db: 7 } };

test('parses the v1 descriptor and optional firmware', () => {
  assert.deepEqual(parseCollarLine(wire(descriptorV1)), { kind: 'collar', descriptor });
  assert.equal(parseCollarLine(wire({ ...descriptorV1, firmware_version: 'x'.repeat(101) })).descriptor.firmware_version, undefined);
});

test('parses direct JSON V5 and rounds its period up to seconds', () => {
  assert.deepEqual(parseCollarLine(wire(legacy)), {
    kind: 'collar', descriptor: { hardware_id: 'REAL_01', transport: 'academic', interval_seconds: 45 },
  });
});

test('distinguishes receiver envelopes from collar lines', () => {
  assert.deepEqual(parseCollarLine(wire(receiver)), { kind: 'receiver' });
  assert.deepEqual(parseCollarLine(wire({ ...legacy, radio: {} })), { kind: 'receiver' });
});

test('rejects oversized UTF-8 lines, invalid descriptor fields and invalid intervals', () => {
  assert.equal(parseCollarLine(wire({ ...descriptorV1, padding: 'á'.repeat(512) })), null);
  for (const interval_seconds of [29, 86401, 45.5, '45', true]) {
    assert.equal(parseCollarLine(wire({ ...descriptorV1, interval_seconds })), null);
  }
  assert.equal(parseCollarLine(wire({ ...descriptorV1, transport: 'lorawan' })), null);
  assert.equal(parseCollarLine(wire({ ...descriptorV1, hardware_id: 'COLLAR.1' })), null);
  assert.equal(parseCollarLine(wire({ ...legacy, p: 45001 })), null);
  assert.equal(parseCollarLine(encoder.encode(JSON.stringify(legacy).replace('44001', '44001.0'))), null);
});

test('rejects incoherent V5 flags, GPS, movement and battery', () => {
  for (const invalid of [
    { f: 0 }, { g: [null, -71, 100, 4, 10] }, { g: [-39, -71, 5000, 4, 10], f: 0 },
    { a: [null, 0, 1], f: 5 }, { b: [2499, 75, -1, -1, -1] }, { b: [4000, 75, 0, -1, -1] },
    { q: 2 ** 32 }, { extra: true },
  ]) assert.equal(parseCollarLine(wire({ ...legacy, ...invalid })), null);
  assert.equal(parseCollarLine(encoder.encode(`{"id":"OTHER",${JSON.stringify(legacy).slice(1)}`)), null);
});

function mockNavigator(context, serial) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { serial } });
  context.after(() => {
    if (original) Object.defineProperty(globalThis, 'navigator', original);
    else Reflect.deleteProperty(globalThis, 'navigator');
  });
}

function mockPort(context, { respond, openError, requestError } = {}) {
  const commands = [];
  const calls = [];
  let input;
  const port = {
    async open(options) {
      calls.push('open');
      assert.deepEqual(options, { baudRate: 115200 });
      if (openError) throw openError;
    },
    readable: new ReadableStream({
      start(controller) { input = controller; },
      cancel() { calls.push('cancel'); },
    }),
    writable: new WritableStream({
      write(value) {
        commands.push(new TextDecoder().decode(value));
        respond?.(input, commands.length);
      },
      abort() { calls.push('abort'); },
    }),
    async close() {
      calls.push(port.readable.locked || port.writable.locked ? 'close while locked' : 'close');
    },
  };
  mockNavigator(context, {
    async requestPort(...args) {
      assert.deepEqual(args, []);
      calls.push('request');
      if (requestError) throw requestError;
      return port;
    },
  });
  return { commands, calls };
}

const options = (stages, controller = new AbortController()) => ({
  signal: controller.signal, onProgress: stage => stages.push(stage),
});

test('sends identification repeatedly, skips a long line and closes the selected port', async context => {
  const { commands, calls } = mockPort(context, { respond(input, count) {
    if (count !== 2) return;
    const line = wire(descriptorV1);
    input.enqueue(encoder.encode(' '.repeat(1024)));
    input.enqueue(line);
    input.enqueue(line.subarray(0, 40));
    input.enqueue(line.subarray(40));
  } });
  const stages = [];
  assert.deepEqual(await detectUsbCollar({ ...options(stages), queryEveryMs: 5 }), descriptor);
  assert.deepEqual(commands, Array(2).fill('\nGEOCATTLE_IDENTIFY_V1\n'));
  assert.deepEqual(calls, ['request', 'open', 'cancel', 'abort', 'close']);
  assert.deepEqual(stages, ['selecting', 'identifying']);
});

test('shows legacy progress then times out and releases the port', async context => {
  const { calls } = mockPort(context);
  const stages = [];
  await assert.rejects(detectUsbCollar({ ...options(stages), queryWindowMs: 5, timeoutMs: 25 }), /no respondió/);
  assert.deepEqual(stages, ['selecting', 'identifying', 'legacy']);
  assert.deepEqual(calls, ['request', 'open', 'cancel', 'abort', 'close']);
});

test('recognizes a connected receiver and closes its port', async context => {
  const { calls } = mockPort(context, { respond: input => input.enqueue(wire(receiver)) });
  await assert.rejects(detectUsbCollar(options([])), /Seleccionaste la receptora USB/);
  assert.deepEqual(calls, ['request', 'open', 'cancel', 'abort', 'close']);
});

test('cancellation stops reading and releases the port', async context => {
  const controller = new AbortController();
  const { calls } = mockPort(context, { respond: () => controller.abort() });
  await assert.rejects(detectUsbCollar(options([], controller)), { name: 'AbortError' });
  assert.deepEqual(calls, ['request', 'open', 'cancel', 'abort', 'close']);
});

test('an open error points to the tools that can occupy the USB port', async context => {
  const { calls } = mockPort(context, { openError: new DOMException('Port busy', 'NetworkError') });
  await assert.rejects(detectUsbCollar(options([])), /Monitor Serie o el Plotter de Arduino/);
  assert.deepEqual(calls, ['request', 'open']);
});

test('a denied picker does not try to open the port', async context => {
  const { calls } = mockPort(context, { requestError: new DOMException('Denied', 'SecurityError') });
  await assert.rejects(detectUsbCollar(options([])), /No se concedió acceso/);
  assert.deepEqual(calls, ['request']);
});

test('without Web Serial, recommends Chrome or Edge and the Windows script', async context => {
  mockNavigator(context, undefined);
  await assert.rejects(detectUsbCollar(options([])), /Usa Chrome o Edge.*Registrar-Collar-USB\.cmd/);
});
