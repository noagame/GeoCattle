import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let source = readFileSync(new URL('../src/DeviceCandidates.tsx', import.meta.url), 'utf8');
source = source.replace(/from ['"]\.\/api['"];/, "from './mockApi.mjs';");
source = source.replace(/from ['"]\.\/ui['"];/, "from './mockUi.mjs';");

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
    jsx: ts.JsxEmit.React,
  },
}).outputText;

const compiledPath = new URL('./_deviceCandidates_compiled.mjs', import.meta.url);
writeFileSync(compiledPath, compiled, 'utf8');

let validateCandidateApproval;
let DeviceCandidatesPanel;

try {
  const mod = await import(compiledPath.href);
  validateCandidateApproval = mod.validateCandidateApproval;
  DeviceCandidatesPanel = mod.DeviceCandidatesPanel;
} finally {
  try {
    unlinkSync(compiledPath);
  } catch {}
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
      onDismissed: () => {},
    })
  );

  assert.ok(html.includes('Collares detectados'));
  assert.ok(html.includes('Sin collares detectados pendientes'));
  assert.ok(!html.includes('Agregar al sistema'));
});

test('DeviceCandidatesPanel: renders candidate list with all required fields', () => {
  const html = renderToStaticMarkup(
    React.createElement(DeviceCandidatesPanel, {
      canWrite: true,
      notify: () => {},
      candidates: {
        data: { items: [sampleCandidateRadio, sampleCandidateUsb] },
        loading: false,
        error: '',
        reload: () => {},
      },
      onApproved: () => {},
      onDismissed: () => {},
    })
  );

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
  assert.ok(html.includes('Descartar'));
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
      onDismissed: () => {},
    })
  );

  assert.ok(html.includes('COLLAR-RADIO-01'));
  assert.ok(!html.includes('Agregar al sistema'));
  assert.ok(!html.includes('Descartar'));
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
