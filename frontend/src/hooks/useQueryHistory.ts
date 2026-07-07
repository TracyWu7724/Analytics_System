import { useState, useEffect, useCallback } from 'react';
import { sessionHistoryService, type ConversationSession } from '../services/queryHistoryService';
import { useAuth } from './useAuth';

export function useQueryHistory() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<ConversationSession[]>([]);

  const refresh = useCallback(() => {
    if (!user) { setSessions([]); return; }
    setSessions(sessionHistoryService.getSessions(user.username));
  }, [user?.username]);

  useEffect(() => {
    refresh();
    window.addEventListener('queryHistoryUpdated', refresh);
    return () => window.removeEventListener('queryHistoryUpdated', refresh);
  }, [refresh]);

  const deleteSession = useCallback((sessionId: string) => {
    if (!user) return;
    sessionHistoryService.deleteSession(user.username, sessionId);
    refresh();
  }, [user?.username, refresh]);

  const pinSession = useCallback((sessionId: string, pinned = true) => {
    if (!user) return;
    sessionHistoryService.pinSession(user.username, sessionId, pinned);
    refresh();
  }, [user?.username, refresh]);

  return { sessions, deleteSession, pinSession, refresh };
}
