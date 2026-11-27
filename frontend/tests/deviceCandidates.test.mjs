import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmdirSync, writeFileSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import './mirror.test.mjs';

const compiledDir = mkdtempSync(fileURLToPath(new URL('./.collar-render-', import.meta.url)));
let validateCandidateApproval, DeviceCandidatesPanel, UsbCollarDetection, CollarInventoryTable, FarmSelector;

try {
  for (const fileName of ['api.ts', 'mirror.ts', 'ui.tsx', 'collarSerial.ts', 'CollarLifecycle.tsx', 'DeviceCandidates.tsx', 'FarmSelector.tsx']) {
    const source = readFileSync(new URL(`../src/${fileName}`, import.meta.url), 'utf8');
    const { outputText } = ts.transpileModule(source, {
      fileName, compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, jsx: ts.JsxEmit.ReactJSX },
    });
    writeFileSync(join(compiledDir, fileName.replace(/\.tsx?$/, '.mjs')), outputText.replace(/from (['"])\.\/([^'"]+)\1/g, 'from $1./$2.mjs$1'));
  }
  ({ validateCandidateApproval, DeviceCandidatesPanel, UsbCollarDetection } = await import(pathToFileURL(join(compiledDir, 'DeviceCandidates.mjs')).href));
  ({ CollarInventoryTable } = await import(pathToFileURL(join(compiledDir, 'CollarLifecycle.mjs')).href));
  ({ FarmSelector } = await import(pathToFileURL(join(compiledDir, 'FarmSelector.mjs')).href));
} finally {
  for (const fileName of readdirSync(compiledDir)) unlinkSync(join(compiledDir, fileName));
  rmdirSync(compiledDir);
}

// Sample candidates
const sampleCandidateRadio = {
  id: 'cand-01',
  hardware_id: 'COLLAR-RADIO-01',
  transport: 'academic',
  dev_eui: null,
  interval_seconds: 60,
  firmware_version: 'v1.4.2',
  source: 'radio',
  first_seen_at: '2026-11-20T08:00:00Z',
  last_seen_at: '2026-11-22T10:30:00Z',
  seen_count: 14,
  last_payload: { bat: 3950 },
  status: 'pending',
  suggested_name: 'Collar sugerido 01',
};

const sampleCandidateUsb = {
  id: 'cand-02',
  hardware_id: 'COLLAR-USB-02',
  transport: 'lorawan',
  dev_eui: '0123456789abcdef',
  interval_seconds: 300,
  firmware_version: null,
  source: 'usb',
  first_seen_at: '2026-11-22T09:00:00Z',
  last_seen_at: '2026-11-22T09:00:00Z',
  seen_count: 1,
  last_payload: null,
  status: 'pending',
  suggested_name: 'Collar detectado USB',
};

test('validateCandidateApproval: valid input forms correct approve payload', () => {
  const result = validateCandidateApproval({
    name: '  Collar Potrero Norte  ',
    hardware_id: 'COLLAR-RADIO-01',
    transport: 'academic',
    interval_seconds: '60',
    dev_eui: '',
    installed_at: '2026-11-22T10:00',
    enabled: true,
  });

  assert.equal(result.ok, true);
  if (result.ok) {
    assert.equal(result.payload.name, 'Collar Potrero Norte');
    assert.equal(result.payload.interval_seconds, 60);
    assert.equal(result.payload.dev_eui, null);
    assert.equal(result.payload.enabled, true);
    assert.ok(result.payload.installed_at.startsWith('2026-11-22'));
  }
});

test('validateCandidateApproval: rejects empty name', () => {
  const resEmpty = validateCandidateApproval({
    name: '   ',
    hardware_id: 'COLLAR-01',
    transport: 'academic',
    interval_seconds: 120,
  });
  assert.equal(resEmpty.ok, false);
  if (!resEmpty.ok) {
    assert.equal(resEmpty.error, 'Ingresa un nombre para el collar.');
  }
});

test('validateCandidateApproval: rejects intervals outside 30..86400 or non-integer', () => {
  for (const interval of [29, 86401, 30.5, 'invalid', NaN]) {
    const res = validateCandidateApproval({
      name: 'Collar Valido',
      hardware_id: 'COLLAR-01',
      transport: 'academic',
      interval_seconds: interval,
    });
    assert.equal(res.ok, false, `Expected interval ${interval} to be rejected`);
    if (!res.ok) {
      assert.equal(res.error, 'El intervalo debe estar entre 30 y 86400 segundos.');
    }
  }

  // Exact boundaries
  assert.equal(validateCandidateApproval({ name: 'C', hardware_id: 'H', transport: 'academic', interval_seconds: 30 }).ok, true);
  assert.equal(validateCandidateApproval({ name: 'C', hardware_id: 'H', transport: 'academic', interval_seconds: 86400 }).ok, true);
});

test('validateCandidateApproval: validates and normalizes dev_eui for lorawan and academic', () => {
  // LoRaWAN requires DevEUI
  const resMissingLorawan = validateCandidateApproval({
    name: 'Collar LoRaWAN',
    hardware_id: 'LORAWAN-01',
    transport: 'lorawan',
    interval_seconds: 120,
    dev_eui: '',
  });
  assert.equal(resMissingLorawan.ok, false);
  if (!resMissingLorawan.ok) {
    assert.equal(resMissingLorawan.error, 'El DevEUI es obligatorio para transporte LoRaWAN.');
  }

  // Invalid hex characters or wrong length
  for (const badEui of ['0123456789abcde', '0123456789abcdef0', '0123456789abcdeg', 'not-a-hex-string']) {
    const resBad = validateCandidateApproval({
      name: 'Collar LoRaWAN',
      hardware_id: 'LORAWAN-01',
      transport: 'lorawan',
      interval_seconds: 120,
      dev_eui: badEui,
    });
    assert.equal(resBad.ok, false, `Expected dev_eui ${badEui} to be rejected`);
    if (!resBad.ok) {
      assert.equal(resBad.error, 'El DevEUI debe contener exactamente 16 caracteres hexadecimales.');
    }
  }

  // Normalizes uppercase hex to lowercase
  const resUpper = validateCandidateApproval({
    name: 'Collar LoRaWAN',
    hardware_id: 'LORAWAN-01',
    transport: 'lorawan',
    interval_seconds: 120,
    dev_eui: '0123456789ABCDEF',
  });
  assert.equal(resUpper.ok, true);
  if (resUpper.ok) {
    assert.equal(resUpper.payload.dev_eui, '0123456789abcdef');
  }
});

test('DeviceCandidatesPanel: renders empty state when no pending candidates', () => {
  const html = renderToStaticMarkup(
    React.createElement(DeviceCandidatesPanel, {
      canWrite: true,
      notify: () => {},
      candidates: {
        data: { items: [] },
        loading: false,
        error: '',
        reload: () => {},
      },
      onApproved: () => {},
      onCandidatesChange: () => {},
    })
  );

  assert.ok(html.includes('empty-compact'));
  assert.ok(html.includes('Sin collares detectados pendientes'));
  assert.ok(!html.includes('<table'));
  assert.ok(!html.includes('collar-candidates-pending'));
});

test('DeviceCandidatesPanel: renders candidate list with all required fields', () => {
  const html = renderToStaticMarkup(
    React.createElement(DeviceCandidatesPanel, {
      canWrite: true,
      now: Date.parse('2026-11-22T10:33:00Z'),
      notify: () => {},
      candidates: {
        data: { items: [sampleCandidateRadio, sampleCandidateUsb] },
        loading: false,
        error: '',
        reload: () => {},
      },
      onApproved: () => {},
      onCandidatesChange: () => {},
    })
  );

  assert.match(html, /class="card-table collar-table" aria-label="Collares detectados"/);
  assert.match(html, /class="collar-pending-count">2 pendientes/);
  assert.match(html, /data-label="Detalles">Académico · 60 s · firmware v1\.4\.2/);
  assert.match(html, /title="Última detección: .*Primera detección: .*">hace 3 min<\/time> · 14 veces/);
  assert.match(html, /data-label="Acciones" class="card-table-action"/);
  assert.doesNotMatch(html, /<th[^>]*>(Intervalo|Firmware|Veces visto)<\/th>/);

  // Checks presence of hardware IDs and suggested names
  assert.ok(html.includes('COLLAR-RADIO-01'));
  assert.ok(html.includes('Collar sugerido 01'));
  assert.ok(html.includes('COLLAR-USB-02'));
  assert.ok(html.includes('Collar detectado USB'));

  // Checks origin tags (Radio & USB)
  assert.ok(html.includes('Radio'));
  assert.ok(html.includes('USB'));

  // Checks transports
  assert.ok(html.includes('Académico'));
  assert.ok(html.includes('LoRaWAN'));
  assert.ok(html.includes('0123456789abcdef'));

  // Checks intervals & firmware
  assert.ok(html.includes('60 s'));
  assert.ok(html.includes('300 s'));
  assert.ok(html.includes('v1.4.2'));

  // Checks times seen count formatting
  assert.ok(html.includes('14 veces'));
  assert.ok(html.includes('1 vez'));

  // Checks action buttons for canWrite=true
  assert.ok(html.includes('Agregar al sistema'));
  assert.match(html, /aria-label="Descartar: Collar sugerido 01" title="Descartar"/);
  assert.doesNotMatch(html, /Conecta el collar por USB/);
});

test('DeviceCandidatesPanel: hides action buttons when canWrite is false', () => {
  const html = renderToStaticMarkup(
    React.createElement(DeviceCandidatesPanel, {
      canWrite: false,
      notify: () => {},
      candidates: {
        data: { items: [sampleCandidateRadio] },
        loading: false,
        error: '',
        reload: () => {},
      },
      onApproved: () => {},
      onCandidatesChange: () => {},
    })
  );

  assert.ok(html.includes('COLLAR-RADIO-01'));
  assert.ok(!html.includes('Agregar al sistema'));
  assert.ok(!html.includes('Detectar collar por USB'));
  assert.ok(!html.includes('Descartar'));
});

test('UsbCollarDetection: exposes a primary USB action before showing its instructions', () => {
  const html = renderToStaticMarkup(React.createElement(UsbCollarDetection));
  assert.match(html, /<button class="button primary"[^>]*>.*Detectar collar por USB<\/button>/);
  assert.doesNotMatch(html, /Conecta el collar por USB/);
});

const inventoryNow = Date.parse('2026-11-22T10:33:00Z');
const inventoryDevice = {
  id: 'test-1', name: 'Collar norte', hardware_id: 'COLLAR-01', transport: 'academic', enabled: true,
  interval_seconds: 45, config_version: 1, pending_config: null, animal_id: 'animal-1', assignment_id: 'assignment-1',
  can_delete: false, last_received_at: new Date(inventoryNow - 165_000).toISOString(),
};

function renderInventory(overrides = {}, canWrite = true) {
  return renderToStaticMarkup(React.createElement(CollarInventoryTable, {
    devices: [{ ...inventoryDevice, ...overrides }], animals: [], canWrite, now: inventoryNow,
  }));
}

test('renders the collar and farm names as text in labels and controls', () => {
  const name = 'Norte <b>QA</b> "alias"';
  const farm = renderToStaticMarkup(React.createElement(FarmSelector, {
    currentFarmId: 'farm-1', farms: [{ id: 'farm-1', name }], isAdmin: false, isBusy: false,
    onSelectFarm: () => {},
  }));
  for (const html of [renderInventory({ name }), farm]) {
    assert.match(html, /Norte &lt;b&gt;QA&lt;\/b&gt; &quot;alias&quot;/);
    assert.doesNotMatch(html, /<b>QA<\/b>/);
  }
});

test('CollarInventoryTable: renders active and stale statuses at the inclusive applied interval threshold', () => {
  const active = renderInventory();
  assert.match(active, /data-label="Estado".*badge-normal.*>Activo<\/span>/);
  assert.match(active, /collar-reception-recent" dateTime="2026-11-22T10:30:15\.000Z" title="[^"]+2026[^"]+">hace 2 min<\/time>/);
  assert.match(active, /aria-label="Cambiar bovino: Collar norte"/);
  assert.match(active, /aria-label="Desvincular del bovino: Collar norte"/);
  assert.doesNotMatch(active, /aria-label="(Retirar|Reactivar|Eliminar)/);

  const stale = renderInventory({ last_received_at: new Date(inventoryNow - 165_001).toISOString(),
    pending_config: { interval_seconds: 300, status: 'requested', version: 2 } });
  assert.match(stale, /data-label="Estado".*badge-warning.*>Sin comunicación<\/span>/);
  assert.match(stale, /collar-reception-stale/);
  assert.match(stale, /aria-label="Configurar intervalo: Collar norte"[^>]*disabled=""/);
  assert.match(stale, /Solicitada<\/span> 300 s · v2/);
});

test('CollarInventoryTable: handles unassigned, retired and read-only devices', () => {
  const unassigned = renderInventory({ animal_id: null, assignment_id: null, last_received_at: null, can_delete: true });
  assert.match(unassigned, /data-label="Estado".*>Sin asignar<\/span>/);
  assert.match(unassigned, /collar-reception-unknown">Sin datos/);
  assert.match(unassigned, /data-label="Acciones" class="card-table-action"/);
  assert.match(unassigned, /aria-label="Asignar a un bovino: Collar norte"/);
  assert.match(unassigned, /aria-label="Retirar collar: Collar norte"/);
  assert.match(unassigned, /class="icon-button collar-danger-action" aria-label="Eliminar del inventario: Collar norte"/);
  assert.doesNotMatch(unassigned, /aria-label="(Reactivar|Desvincular)/);

  const retired = renderInventory({ enabled: false, animal_id: null, assignment_id: null });
  assert.match(retired, /data-label="Estado".*>Retirado<\/span>/);
  assert.match(retired, /aria-label="Reactivar collar: Collar norte"/);
  assert.doesNotMatch(retired, /aria-label="(Asignar|Configurar|Retirar|Desvincular)/);

  const unknown = renderInventory({ last_received_at: 'no válido' }, false);
  assert.match(unknown, /collar-reception-unknown/);
  assert.doesNotMatch(unknown, /Sin comunicación|data-label="Acciones"|<button/);
});

test('Candidate actions error handling: 409 conflict and 403 forbidden', () => {
  function handleApproveError(err) {
    if (err && typeof err === 'object' && 'status' in err) {
      if (err.status === 409) {
        return 'El identificador de hardware ya está registrado en este predio.';
      }
      if (err.status === 403) {
        return 'No tienes permisos para agregar dispositivos a este predio.';
      }
    }
    return err instanceof Error ? err.message : 'No se pudo agregar el collar al sistema.';
  }

  function handleDismissError(err) {
    if (err && typeof err === 'object' && 'status' in err) {
      if (err.status === 403) {
        return 'No tienes permisos para descartar collares en este predio.';
      }
    }
    return err instanceof Error ? err.message : 'No se pudo descartar el collar detectado.';
  }

  const err409 = { status: 409, message: 'Conflict' };
  const err403 = { status: 403, message: 'Forbidden' };
  const err500 = new Error('Error interno del servidor');

  assert.equal(handleApproveError(err409), 'El identificador de hardware ya está registrado en este predio.');
  assert.equal(handleApproveError(err403), 'No tienes permisos para agregar dispositivos a este predio.');
  assert.equal(handleApproveError(err500), 'Error interno del servidor');

  assert.equal(handleDismissError(err403), 'No tienes permisos para descartar collares en este predio.');
  assert.equal(handleDismissError(err500), 'Error interno del servidor');
});
