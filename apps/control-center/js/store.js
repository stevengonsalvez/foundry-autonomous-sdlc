// What the page currently knows: the newest state document, which source gave it, pending intake,
// and which sources are having trouble. No DOM and no fetching, so it is unit tested directly.

import { isNewer } from './model.js';

const sameIssues = (a, b) => a.length === b.length && a.every((t, i) => t.issue === b[i].issue && t.title === b[i].title);

export function createStore(now) {
  let snap = { phase: 'loading', state: null, source: null, receivedAt: null, pending: [], problems: {}, notFound: [], message: null };
  const listeners = new Set();
  const set = (patch, change) => {
    snap = { ...snap, ...patch };
    for (const fn of listeners) fn(snap, change);
  };

  return {
    snapshot: () => snap,

    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },

    /** A parsed document from `source`. Kept only when newer than the one on show. */
    acceptState({ state, source }) {
      const problems = withoutKey(snap.problems, source);
      if (!isNewer(state, snap.state)) {
        set({ problems }, 'problems');
        return false;
      }
      set({ phase: 'ok', state, source, receivedAt: now(), problems, notFound: [], message: null }, 'state');
      return true;
    },

    acceptPending(pending) {
      const problems = withoutKey(snap.problems, 'issues');
      if (sameIssues(pending, snap.pending)) {
        if (problems !== snap.problems) set({ problems }, 'problems');
        return false;
      }
      set({ pending, problems }, 'pending');
      return true;
    },

    ok({ source }) {
      if (source in snap.problems) set({ problems: withoutKey(snap.problems, source) }, 'problems');
    },

    problem({ source, message }) {
      set({ problems: { ...snap.problems, [source]: message } }, 'problems');
    },

    notFound({ source }) {
      if (!snap.notFound.includes(source)) set({ notFound: [...snap.notFound, source] }, 'problems');
    },

    /** After a polling round: with nothing to show yet, decide between "nothing published" and "failed". */
    endRound() {
      if (snap.phase !== 'loading') return;
      const messages = Object.values(snap.problems);
      if (snap.notFound.length > 0 && messages.length === 0) {
        set({ phase: 'empty' }, 'state');
      } else if (messages.length > 0 || snap.notFound.length > 0) {
        set({ phase: 'error', message: messages.join(' ') || 'No state file was found.' }, 'state');
      }
    },

    reset() {
      set({ phase: 'loading', problems: {}, notFound: [], message: null }, 'state');
    },
  };
}

function withoutKey(obj, key) {
  if (!(key in obj)) return obj;
  const { [key]: _removed, ...rest } = obj;
  return rest;
}
