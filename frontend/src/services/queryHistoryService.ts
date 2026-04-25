/**
 * queryHistoryService — stores full conversation sessions per user.
 *
 * Each session holds all messages exchanged. The sidebar shows sessions
 * as a history list; clicking one restores the full conversation.
 */

import type { ChatMessage } from '../types/chat';

export interface ConversationSession {
  session_id: string;
  user_id: string;
  title: string;       // first user message, truncated
  messages: ChatMessage[];
  created_at: string;  // ISO string
  updated_at: string;  // ISO string
  pinned?: boolean;    // pinned sessions sort to the top
}

const SESSION_KEY = (userId: string) => `ds_sessions_${userId}`;
const MAX_SESSIONS = 30;

function reviveMessages(messages: any[]): ChatMessage[] {
  return messages.map(m => ({
    ...m,
    timestamp: m.timestamp ? new Date(m.timestamp) : new Date(),
  }));
}

function getSessions(userId: string): ConversationSession[] {
  try {
    const raw = localStorage.getItem(SESSION_KEY(userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ConversationSession[];
    const sessions = parsed.map(s => ({ ...s, messages: reviveMessages(s.messages) }));
    // Pinned sessions always sort to the top, preserving relative order within each group
    return sessions.sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
  } catch {
    return [];
  }
}

function getSession(userId: string, sessionId: string): ConversationSession | null {
  return getSessions(userId).find(s => s.session_id === sessionId) ?? null;
}

function upsertSession(session: ConversationSession): void {
  // Preserve pinned flag from existing session if caller didn't set it
  const existing = getSessions(session.user_id).find(s => s.session_id === session.session_id);
  const all = getSessions(session.user_id).filter(s => s.session_id !== session.session_id);
  all.unshift({ ...session, pinned: session.pinned ?? existing?.pinned, updated_at: new Date().toISOString() });
  try {
    localStorage.setItem(SESSION_KEY(session.user_id), JSON.stringify(all.slice(0, MAX_SESSIONS)));
  } catch {
    // storage full — keep newest half
    localStorage.setItem(SESSION_KEY(session.user_id), JSON.stringify(all.slice(0, MAX_SESSIONS / 2)));
  }
}

function deleteSession(userId: string, sessionId: string): void {
  const all = getSessions(userId).filter(s => s.session_id !== sessionId);
  localStorage.setItem(SESSION_KEY(userId), JSON.stringify(all));
}

function pinSession(userId: string, sessionId: string, pinned: boolean): void {
  const all = getSessions(userId).map(s =>
    s.session_id === sessionId ? { ...s, pinned } : s
  );
  localStorage.setItem(SESSION_KEY(userId), JSON.stringify(all));
}

export const sessionHistoryService = { getSessions, getSession, upsertSession, deleteSession, pinSession };

// ── Legacy no-op stub so existing imports don't break ────────────────────────
export const queryHistoryService = {
  addQuery: () => {},
  getRecentQueries: () => [],
  getSessionQueries: () => [],
};
