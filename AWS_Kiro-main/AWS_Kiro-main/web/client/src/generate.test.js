import test from 'node:test';
import assert from 'node:assert/strict';
import { validateForm, buildBody, cleanPrompt, promptLength, generateStatusText, DEFAULT_FORM, SCENE_OPTIONS, CUSTOM, PROMPT_MAX } from './generate.js';
import { statusText } from './verify.js';

test('validateForm: presets válidos; personalizada exige texto de hasta 300 caracteres', () => {
  assert.equal(validateForm(DEFAULT_FORM), null);
  for (const [v] of SCENE_OPTIONS.filter(([v]) => v !== CUSTOM)) assert.equal(validateForm({ ...DEFAULT_FORM, escena: v }), null);
  assert.match(validateForm({ ...DEFAULT_FORM, logo: 'AMBIGUO' }), /marca/);
  assert.match(validateForm({ ...DEFAULT_FORM, tipo: 'gif' }), /tipo/);
  assert.match(validateForm({ ...DEFAULT_FORM, escena: CUSTOM, prompt: '  \n ' }), /Describe/);
  assert.match(validateForm({ ...DEFAULT_FORM, escena: CUSTOM, prompt: 'x'.repeat(PROMPT_MAX + 1) }), /300/);
  assert.equal(validateForm({ ...DEFAULT_FORM, escena: CUSTOM, prompt: 'x'.repeat(PROMPT_MAX) }), null);
});

test('buildBody: escena o prompt limpio (sin saltos de línea), verify booleano', () => {
  assert.deepEqual(buildBody({ ...DEFAULT_FORM, escena: 'atm', logo: 'INCORRECTO' }), { logo: 'INCORRECTO', tipo: 'imagen', verify: true, escena: 'atm' });
  assert.deepEqual(buildBody({ ...DEFAULT_FORM, escena: CUSTOM, prompt: ' Un autobús\nurbano ', verify: false }), { logo: 'CORRECTO', tipo: 'imagen', verify: false, prompt: 'Un autobús urbano' });
  assert.equal(cleanPrompt('a\u0000b\tc'), 'ab c');
  assert.equal(promptLength('😀 ab'), 4); // cuenta caracteres, no unidades UTF-16
});

test('textos de estado: fases de la generación y verificación sin cambios', () => {
  assert.equal(generateStatusText({ status: 'running', phase: 'generating' }), 'Generando en ComfyUI…');
  assert.equal(generateStatusText({ status: 'running', phase: 'verifying' }), 'Verificando con Bedrock…');
  assert.equal(generateStatusText({ status: 'succeeded', params: { verify: true } }), 'Activo generado y verificado');
  assert.equal(generateStatusText({ status: 'failed', exit_code: 3 }), 'Activo generado; la verificación ha fallado');
  assert.equal(generateStatusText({ status: 'failed', exit_code: 2 }), 'La generación ha fallado');
  assert.equal(statusText({ kind: 'generate', status: 'running', phase: 'generating' }), 'Generando en ComfyUI…');
  assert.equal(statusText({ kind: 'verify', status: 'running' }), 'Verificando…');
  assert.equal(statusText({ status: 'running' }), 'Verificando…');
});
