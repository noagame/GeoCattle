import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

function moduleUrl(filename, imports = {}) {
  let source = readFileSync(new URL(`../src/${filename}.ts`, import.meta.url), 'utf8');
  for (const [specifier, url] of Object.entries(imports)) {
    source = source.replace(`from '${specifier}'`, `from ${JSON.stringify(url)}`);
  }
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  });
  return `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
}

const mirrorUrl = moduleUrl('mirror');
const { canWrite, freshnessText, isQueuedWrite, queuedMessage, submissionLabels, supportQueuedMessage, supportRequestsPath } = await import(mirrorUrl);
const { ApiError, write } = await import(moduleUrl('api', { './mirror': mirrorUrl, react: import.meta.resolve('react') }));

test('modo espejo cruza modo, perfil y acción con los permisos existentes', () => {
  const vetChanges = ['animal_profile', 'health_record', 'health_schedule'];
  const personal = ['notice_read', 'support_request'];
  const features = ['farm', 'hardware', 'account', 'admin', 'change', 'decision', 'draft', ...personal, ...vetChanges];
  const replicaAllowed = {
    admin: ['admin', 'change', 'decision', ...personal, ...vetChanges],
    veterinarian: ['draft', ...personal, ...vetChanges],
    owner: personal, operator: personal, worker: personal, viewer: personal,
  };
  for (const [role, allowed] of Object.entries(replicaAllowed)) {
    for (const feature of features) {
      assert.equal(canWrite('replica', role, feature), allowed.includes(feature), `${role} / ${feature}`);
      assert.equal(canWrite('off', role, feature), true);
      assert.equal(canWrite('field', role, feature), true);
      assert.equal(canWrite(undefined, role, feature), false);
    }
  }
  assert.equal(canWrite('replica', undefined, 'notice_read'), false);
  assert.equal(canWrite('replica', undefined, 'support_request'), false);
});

test('el cliente entrega la respuesta 202 encolada y emite el aviso pendiente', async t => {
  const receipt = { queued: true, outbox_id: '7e29915a-0031-42cc-8e6c-c510d431ef9a', status: 'queued' };
  const calls = [];
  const restoreFetch = globalThis.fetch;
  const restoreWindow = globalThis.window;
  globalThis.window = new EventTarget();
  window.addEventListener('mirror-queued', event => calls.push(event.detail));
  t.after(() => { globalThis.fetch = restoreFetch; globalThis.window = restoreWindow; });

  globalThis.fetch = async () => Response.json(receipt, { status: 202 });
  const result = await write('/v3/changes', { action: 'animal_profile' });
  assert.deepEqual(result, receipt);
  assert.equal(isQueuedWrite(result), true);
  assert.deepEqual(calls, [queuedMessage]);

  assert.deepEqual(await write(supportRequestsPath, { kind: 'access_issue', description: 'QA' }), receipt);
  assert.deepEqual(calls, [queuedMessage, supportQueuedMessage]);

  globalThis.fetch = async () => Response.json({ request_id: receipt.outbox_id, status: 'pending' }, { status: 201 });
  assert.equal(isQueuedWrite(await write(supportRequestsPath, {})), false);
  assert.deepEqual(calls, [queuedMessage, supportQueuedMessage]);

  globalThis.fetch = async () => Response.json({ delivery: 'queued' }, { status: 202 });
  assert.equal(isQueuedWrite(await write('/v3/invitations', {})), false);
  assert.deepEqual(calls, [queuedMessage, supportQueuedMessage]);

  const denied = 'Modo espejo: registra este cambio en el PC del campo';
  globalThis.fetch = async () => Response.json({ detail: denied }, { status: 403 });
  await assert.rejects(write('/devices', {}), error => error instanceof ApiError && error.status === 403 && error.message === denied);
  assert.deepEqual(calls, [queuedMessage, supportQueuedMessage]);
});

test('Mis envíos traduce todos los estados de la bandeja', () => {
  assert.deepEqual(submissionLabels, {
    queued: 'En cola para el campo', delivered: 'Recibido por el campo', applied: 'Aplicado',
    pending_owner: 'Pendiente del dueño', rejected: 'Rechazado', conflict: 'Conflicto: revisa tus borradores', failed: 'Falló al aplicar',
  });
});

test('el banner muestra el pulso con hora de Chile y distingue conexión y ausencia de pulso', () => {
  const info = { mode: 'replica', source_environment: 'development', field_online: true, heartbeat_at: '2026-11-26T17:32:10Z' };
  const now = Date.parse(info.heartbeat_at) + 8000;
  assert.equal(freshnessText(info, now), 'Espejo del campo · datos al 14:32:10 (hace 8 s)');
  assert.equal(freshnessText(info, now + 1000), 'Espejo del campo · datos al 14:32:10 (hace 9 s)');
  assert.equal(freshnessText({ ...info, field_online: false }, now), 'Campo sin conexión desde 14:32 · mostrando lo último recibido');
  assert.equal(freshnessText({ ...info, heartbeat_at: null, field_online: false }, now), 'Campo sin conexión · esperando el primer registro');
  assert.equal(freshnessText({ ...info, mode: 'field' }, now), '');
  assert.equal(freshnessText({ mode: 'off' }, now), '');
});
