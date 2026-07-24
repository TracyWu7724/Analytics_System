import { useState, useRef, useEffect, useCallback } from 'react';
import { streamQuery } from '../services/chatService';
import { submitFeedback } from '../services/feedbackService';
import { sessionHistoryService } from '../services/queryHistoryService';
import { useAuth } from './useAuth';
import type { ChatMessage } from '../types/chat';
import type { QueryResult } from '../types/database';
import type { FeedbackRequest } from '../types/api';

interface UseChatOptions {
  initialQuery?: string;
  initialLlmModel?: string;
  sessionIdProp?: string;
}

export function useChat({ initialQuery = '', initialLlmModel, sessionIdProp }: UseChatOptions = {}) {
  const { user } = useAuth();
  const sessionId = useRef<string>(
    sessionIdProp ?? (
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
    ),
  );

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState('');
  const [progressSteps, setProgressSteps] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>(initialLlmModel ?? 'gpt-4o');
  const [feedbackSent, setFeedbackSent] = useState<Record<string, 'good' | 'bad'>>({});
  const [retryMessage, setRetryMessage] = useState<string | null>(null);

  const lastProcessedQuery = useRef<string>('');

  // Restore session from history
  useEffect(() => {
    if (!sessionIdProp || !user) return;
    const stored = sessionHistoryService.getSession(user.username, sessionIdProp);
    if (!stored || stored.messages.length === 0) return;

    const msgs = stored.messages;
    const lastAssistant = [...msgs].reverse().find(m => m.type === 'assistant' && !m.isLoading);
    const lastUser = [...msgs].reverse().find(m => m.type === 'user');

    if (lastAssistant?.error && lastUser) {
      setMessages(msgs.filter(m => m.id !== lastAssistant.id));
      setRetryMessage(lastUser.content);
    } else {
      setMessages(msgs);
    }
  }, [sessionIdProp, user?.username]);

  // Persist session to history after each complete exchange
  useEffect(() => {
    if (!user) return;
    if (messages.some(m => m.isLoading)) return;
    const userMsgs = messages.filter(m => m.type === 'user');
    if (userMsgs.length === 0) return;

    sessionHistoryService.upsertSession({
      session_id: sessionId.current,
      user_id: user.username,
      title: userMsgs[0].content.slice(0, 60),
      messages,
      created_at: new Date(userMsgs[0].timestamp ?? Date.now()).toISOString(),
      updated_at: new Date().toISOString(),
    });
    window.dispatchEvent(new Event('queryHistoryUpdated'));

    if (!sessionIdProp) {
      window.history.replaceState(null, '', `/agent?session=${encodeURIComponent(sessionId.current)}`);
    }
  }, [messages, user?.username]);

  const sendMessage = useCallback(async (messageContent: string) => {
    if (!messageContent.trim()) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      type: 'user',
      content: messageContent.trim(),
      timestamp: new Date(),
    };
    const loadingMsg: ChatMessage = {
      id: (Date.now() + 1).toString(),
      type: 'assistant',
      content: 'Thinking...',
      timestamp: new Date(),
      isLoading: true,
    };

    setMessages(prev => [...prev, userMsg, loadingMsg]);
    setIsLoading(true);
    setLoadingStep('Understanding context...');
    setProgressSteps([]);

    const history = messages
      .filter(m => !m.isLoading)
      .map(m => ({ role: m.type === 'user' ? 'user' : 'assistant', content: m.content }))
      .slice(-10);

    try {
      const data = await new Promise<any>((resolve) => {
        streamQuery(
          { question: messageContent, llm_model: selectedModel, history, session_id: sessionId.current },
          {
            onProgress: (_step, label) => {
              setLoadingStep(label);
              setProgressSteps(prev => (prev[prev.length - 1] === label ? prev : [...prev, label]));
            },
            onResult: (d) => { setLoadingStep(''); resolve(d); },
            onError: (msg) => { setLoadingStep(''); resolve({ error: msg }); },
          },
        );
      });

      let results: QueryResult[] | undefined;
      if (data.sql_rows && data.sql_rows.length > 0) {
        const columns = Object.keys(data.sql_rows[0]);
        results = [{ columns, values: data.sql_rows.map((row: Record<string, unknown>) => columns.map(c => row[c])) }];
      }

      let content: string;
      if (data.route === 'rag' || data.route === 'both') {
        content = data.final_answer || (data.error ? `Error: ${data.error}` : 'No answer generated.');
      } else if (data.error && !data.final_answer) {
        content = 'I encountered an error processing your request.';
      } else {
        content = results && results[0].values.length > 0
          ? `Found ${results[0].values.length} result${results[0].values.length !== 1 ? 's' : ''}.`
          : data.final_answer || 'Query executed successfully.';
      }

      const assistantMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content,
        timestamp: new Date(),
        route: data.route,
        route_reasoning: data.route_reasoning,
        results,
        sql_query: data.sql_query,
        sql_rows: data.sql_rows,
        rag_answer: data.final_answer ?? undefined,
        rag_verification: data.rag_verification,
        error: data.error,
        trace_url: data.trace_url,
      };

      setMessages(prev => prev.slice(0, -1).concat(assistantMsg));
    } catch {
      setMessages(prev => prev.slice(0, -1).concat({
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: 'An unexpected error occurred.',
        timestamp: new Date(),
        error: 'Connection failed',
      }));
    } finally {
      setIsLoading(false);
      setLoadingStep('');
      setProgressSteps([]);
    }
  }, [messages, selectedModel]);

  // Fire initial query
  useEffect(() => {
    if (initialQuery && initialQuery !== lastProcessedQuery.current) {
      lastProcessedQuery.current = initialQuery;
      sendMessage(initialQuery);
    }
  }, [initialQuery]);

  // Fire retry after restore
  useEffect(() => {
    if (!retryMessage) return;
    setRetryMessage(null);
    sendMessage(retryMessage);
  }, [retryMessage]);

  const sendFeedback = useCallback((params: FeedbackRequest) => {
    const msgId = params.message_id;
    setFeedbackSent(prev => ({ ...prev, [msgId]: params.rating }));
    submitFeedback(params);
  }, []);

  const dismissResult = useCallback((messageId: string) => {
    setMessages(prev => prev.map(m =>
      m.id === messageId ? { ...m, results: undefined, error: undefined, sql_query: undefined } : m,
    ));
  }, []);

  return {
    messages,
    isLoading,
    loadingStep,
    progressSteps,
    selectedModel,
    setSelectedModel,
    feedbackSent,
    sessionId: sessionId.current,
    sendMessage,
    sendFeedback,
    dismissResult,
  };
}
