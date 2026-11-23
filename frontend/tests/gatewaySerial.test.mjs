import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

function asModule(filename, replacement) {
  let source = readFileSync(new URL(`../src/${filename}.ts`, import.meta.url), 'utf8');
  if (replacement) source = source.replace("'./collarSerial'", JSON.stringify(replacement));
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText;
  return `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`;
}

const { parseGatewayLine, withUsbGateway } = await import(asModule('gatewaySerial', asModule('collarSerial')));
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const wire = item => encoder.encode(`${JSON.stringify(item)}\r\n`);
const eui = '021122fffe334455';
const descriptor = { type: 'geocattle_gateway', version: 1, gateway_eui: eui, node_id: null, provisioned: false, firmware: 'test-v1' };

test('solo identifica gateways con un nodo coherente y nunca una receptora', () => {
  assert.deepEqual(parseGatewayLine(wire(descriptor)), { kind: 'gateway', descriptor: { gateway_eui: eui, node_id: null, firmware: 'test-v1' } });
  assert.equal(parseGatewayLine(wire({ ...descriptor, node_id: 2, provisioned: true })).descriptor.node_id, 2);
  for (const changes of [{ node_id: true }, { node_id: 3 }, { node_id: '1' }, { gateway_eui: 'incorrecto' }, { provisioned: true }]) {
    assert.equal(parseGatewayLine(wire({ ...descriptor, ...changes })), null);
  }
  assert.deepEqual(parseGatewayLine(wire({ gc_bus: 1 })), { kind: 'other' });
  assert.deepEqual(parseGatewayLine(wire({ type: 'geocattle_receiver' })), { kind: 'other' });
});

function fakeSerial(tape, answer) {
  let reader;
  const readable = new ReadableStream({ start(controller) { reader = controller; } });
  const writable = new WritableStream({ write(bytes) {
    const command = decoder.decode(bytes); tape.push(command);
    if (command.includes('IDENTIFY')) {
      const reply = wire(descriptor);
      reader.enqueue(reply.slice(0, 8)); reader.enqueue(reply.slice(8));
    } else {
      reader.enqueue(wire({ type: 'geocattle_gateway_node', version: 1, gateway_eui: 'deadbeefdeadbeef', node_id: 2, provisioned: true }));
      reader.enqueue(wire(answer));
    }
  } });
  const port = { readable, writable, async open(options) { assert.equal(options.baudRate, 115200); },
    async close() { assert.equal(readable.locked, false); assert.equal(writable.locked, false); tape.push('closed'); } };
  Object.defineProperty(globalThis.navigator, 'serial', { configurable: true, value: { async requestPort() { return port; } } });
}

test('configura solo el gateway identificado y exige respuesta coincidente', async () => {
  const tape = [];
  fakeSerial(tape, { type: 'geocattle_gateway_node', version: 1, gateway_eui: eui, node_id: 2, provisioned: true });
  const node = await withUsbGateway(new AbortController().signal, (item, setNode) => {
    assert.equal(item.gateway_eui, eui);
    return setNode(2);
  });
  assert.equal(node, 2);
  assert.deepEqual(tape, ['\nGEOCATTLE_IDENTIFY_V1\n', `\nGEOCATTLE_SET_NODE_V1 ${eui} 2\n`, 'closed']);
});

test('propaga un error de memoria y libera el puerto', async () => {
  const tape = [];
  fakeSerial(tape, { type: 'geocattle_gateway_error', version: 1, error: 'nvs' });
  await assert.rejects(withUsbGateway(new AbortController().signal, (_item, setNode) => setNode(2)), /memoria/);
  assert.equal(tape.at(-1), 'closed');
});
