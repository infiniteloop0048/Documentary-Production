// Regression test for the manual-upload slideshow thumbnail file:// URL bug.
// Not part of the pytest suite (this project has no JS/npm test harness) —
// run directly with: node tests/unit/test_slideshow_thumbnail_url.test.mjs
//
// Loads docu_studio/gui/web/app.js in a vm sandbox with minimal DOM stubs
// (the file registers a DOMContentLoaded listener at load time, so
// document.addEventListener must exist) and exercises the pure
// _toFileUrl(path) helper directly — no real DOM/browser needed since the
// helper does its own percent-encoding rather than relying on the browser
// to normalize the string.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const appJsPath = path.join(__dirname, '../../docu_studio/gui/web/app.js');
const src = fs.readFileSync(appJsPath, 'utf8');

function loadAppJsSandbox() {
  const sandbox = {
    document: { addEventListener: () => {}, getElementById: () => null },
    window: {},
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: 'app.js' });
  return sandbox;
}

test('_toFileUrl encodes a space so the pathname is not corrupted', () => {
  const { _toFileUrl } = loadAppJsSandbox();
  const url = _toFileUrl('/mnt/F/beach photo.jpg');
  assert.equal(url, 'file:///mnt/F/beach%20photo.jpg');
  assert.equal(decodeURIComponent(new URL(url).pathname), '/mnt/F/beach photo.jpg');
});

test('_toFileUrl encodes # so it is not read as a URL fragment', () => {
  const { _toFileUrl } = loadAppJsSandbox();
  const url = _toFileUrl('/mnt/F/photo #1.jpg');
  // Un-encoded, "file:///mnt/F/photo #1.jpg" truncates to pathname
  // "/mnt/F/photo " with "#1.jpg" read as a fragment — that's the bug.
  assert.equal(url, 'file:///mnt/F/photo%20%231.jpg');
  assert.equal(decodeURIComponent(new URL(url).pathname), '/mnt/F/photo #1.jpg');
});

test('_toFileUrl encodes ? so it is not read as a query separator', () => {
  const { _toFileUrl } = loadAppJsSandbox();
  const url = _toFileUrl('/mnt/F/a?b=1.jpg');
  // Un-encoded, everything from "?" onward is dropped from the pathname —
  // the more severe half of the same bug class as "#".
  assert.equal(url, 'file:///mnt/F/a%3Fb%3D1.jpg');
  assert.equal(decodeURIComponent(new URL(url).pathname), '/mnt/F/a?b=1.jpg');
});

test('_toFileUrl encodes & so it cannot be misread alongside a query separator', () => {
  const { _toFileUrl } = loadAppJsSandbox();
  const url = _toFileUrl('/mnt/F/rock & roll.jpg');
  assert.equal(url, 'file:///mnt/F/rock%20%26%20roll.jpg');
  assert.equal(decodeURIComponent(new URL(url).pathname), '/mnt/F/rock & roll.jpg');
});

test('_toFileUrl encodes a literal % so it is not read as a percent-escape', () => {
  const { _toFileUrl } = loadAppJsSandbox();
  const url = _toFileUrl('/mnt/F/100% off.jpg');
  assert.equal(url, 'file:///mnt/F/100%25%20off.jpg');
  assert.equal(decodeURIComponent(new URL(url).pathname), '/mnt/F/100% off.jpg');
});

test('_toFileUrl percent-encodes non-ASCII characters', () => {
  const { _toFileUrl } = loadAppJsSandbox();
  const url = _toFileUrl('/mnt/F/café.jpg');
  assert.equal(url, 'file:///mnt/F/caf%C3%A9.jpg');
  assert.equal(decodeURIComponent(new URL(url).pathname), '/mnt/F/café.jpg');
});

test('_toFileUrl preserves a Windows drive letter unencoded', () => {
  const { _toFileUrl } = loadAppJsSandbox();
  const url = _toFileUrl('C:\\Users\\name\\beach photo.jpg');
  assert.equal(url, 'file:///C:/Users/name/beach%20photo.jpg');
  assert.equal(decodeURIComponent(new URL(url).pathname), '/C:/Users/name/beach photo.jpg');
});

test('_toFileUrl leaves an already-plain path unchanged in meaning', () => {
  const { _toFileUrl } = loadAppJsSandbox();
  const url = _toFileUrl('/mnt/F/plainname.jpg');
  assert.equal(url, 'file:///mnt/F/plainname.jpg');
});
