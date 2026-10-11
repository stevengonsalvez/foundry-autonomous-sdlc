// Hash routes. The query string of the page (?data=...) is untouched by navigation because every
// link is fragment-only.

import { positiveInt } from './safe.js';

export const NAV = Object.freeze([
  { name: 'board', hash: '#/', label: 'Board', title: 'Ticket board' },
  { name: 'environments', hash: '#/environments', label: 'Environments', title: 'Environments' },
  { name: 'cost', hash: '#/cost', label: 'Cost', title: 'Cost' },
  { name: 'agents', hash: '#/agents', label: 'Agents', title: 'Agents' },
  { name: 'escalations', hash: '#/escalations', label: 'Escalations', title: 'Escalations' },
  { name: 'flow', hash: '#/flow', label: 'Flow', title: 'Flow metrics' },
  { name: 'trail', hash: '#/trail', label: 'Trail', title: 'Questions and reviews' },
]);

const BY_SEGMENT = Object.freeze({ environments: 'environments', cost: 'cost', agents: 'agents', escalations: 'escalations', flow: 'flow', trail: 'trail' });

/** '#/ticket/24' -> { name: 'ticket', issue: 24 }. Anything unknown is { name: 'not-found' }. */
export function parseRoute(hash) {
  const path = String(hash ?? '').replace(/^#\/?/, '').split('?')[0].replace(/\/+$/, '');
  if (path === '') return { name: 'board' };
  const parts = path.split('/');
  if (parts[0] === 'ticket') {
    const issue = parts.length === 2 ? positiveInt(parts[1]) : null;
    return issue === null ? { name: 'not-found' } : { name: 'ticket', issue };
  }
  if (parts.length === 1 && Object.hasOwn(BY_SEGMENT, parts[0])) return { name: BY_SEGMENT[parts[0]] };
  return { name: 'not-found' };
}

export function routeTitle(route) {
  if (route.name === 'ticket') return `Ticket #${route.issue}`;
  if (route.name === 'not-found') return 'Not found';
  return NAV.find((n) => n.name === route.name)?.title ?? 'Control Center';
}
