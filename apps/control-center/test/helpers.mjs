import { readFile } from 'node:fs/promises';

import { parseState } from '../js/schema.js';

const read = async (name) => JSON.parse(await readFile(new URL(`./fixtures/${name}`, import.meta.url), 'utf8'));

export const rawSample = await read('state.sample.json');
export const rawIssues = await read('issues.sample.json');

/** The sample, parsed and normalised. A fresh copy each call so tests can edit it. */
export function sampleState() {
  const result = parseState(structuredClone(rawSample));
  if (result.status !== 'ok') throw new Error(result.message);
  return result.state;
}

export const NOW = Date.parse('2026-10-11T20:07:00Z');
