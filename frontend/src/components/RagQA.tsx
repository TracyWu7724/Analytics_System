import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, ArrowLeft, Bot, Settings, ChevronDown, ExternalLink } from 'lucide-react';
import Sidebar from './Sidebar';
import { DebugPanel } from './DebugPanel';
import { ApiService } from '../services/api';

interface RagMessage {
  id: string;
  type: 'user' | 'assistant';
  content: string;
  sources?: string[];
  isLoading?: boolean;
  trace_url?: string;
}

const RagQA: React.FC = () => {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<RagMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState('');
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>('gemini-2.5-flash');
  const [availableModels, setAvailableModels] = useState<{ id: string; display_name: string; provider: string; available: boolean }[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    ApiService.getLlmModels().then(({ models, default: defaultModel }) => {
      setAvailableModels(models);
      setSelectedModel(defaultModel);
    });
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    }
  }, [inputValue]);

  const handleSendMessage = async (text: string = inputValue) => {
    if (!text.trim() || isLoading) return;

    const userMsg: RagMessage = {
      id: Date.now().toString(),
      type: 'user',
      content: text.trim(),
    };

    const loadingMsg: RagMessage = {
      id: (Date.now() + 1).toString(),
      type: 'assistant',
      content: '',
      isLoading: true,
    };

    setMessages(prev => [...prev, userMsg, loadingMsg]);
    setInputValue('');
    setIsLoading(true);

    // Build history from current messages for multi-turn context
    const history = messages
      .filter(m => !m.isLoading)
      .map(m => ({ role: m.type === 'user' ? 'user' : 'assistant', content: m.content }));

    try {
      setLoadingStep('Searching documents…');
      await new Promise(r => setTimeout(r, 100));
      setLoadingStep('Generating answer…');

      const data = await ApiService.executeAgentQuery(text.trim(), undefined, selectedModel, history);

      const sources = data.rag_chunks
        ? Array.from(new Set(data.rag_chunks.map((c: any) => c.source).filter(Boolean)))
        : undefined;

      const assistantMsg: RagMessage = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: data.final_answer || data.error || 'No answer generated.',
        sources: sources as string[] | undefined,
        trace_url: data.trace_url,
      };
      setMessages(prev => [...prev.slice(0, -1), assistantMsg]);
    } catch {
      setMessages(prev => [
        ...prev.slice(0, -1),
        {
          id: (Date.now() + 1).toString(),
          type: 'assistant',
          content: 'Could not reach the backend. Make sure the server is running.',
        },
      ]);
    } finally {
      setIsLoading(false);
      setLoadingStep('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="flex h-screen bg-white text-gray-900 overflow-hidden">
      <Sidebar />

      <div className="flex-1 flex flex-col">
        {/* Header */}
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
          <button
            onClick={() => navigate('/')}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <div>
            <h1 className="font-semibold text-gray-900">RAG Q&amp;A Assistant</h1>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {availableModels.length > 0 && (
              <div className="relative">
                <select
                  value={selectedModel}
                  onChange={e => setSelectedModel(e.target.value)}
                  className="appearance-none pl-3 pr-8 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-700 cursor-pointer hover:border-gray-300 focus:outline-none focus:ring-2 focus:border-transparent"
                >
                  {availableModels.map(m => (
                    <option key={m.id} value={m.id} disabled={!m.available}>
                      {m.display_name}{!m.available ? ' (no API key)' : ''}
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
              </div>
            )}
            <button
              onClick={() => setShowDebugPanel(true)}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              title="Debug API Connection"
            >
              <Settings className="w-5 h-5 text-gray-600" />
            </button>
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <AnimatePresence>
            {messages.length === 0 && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-12"
              >
                <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <Bot className="w-8 h-8" style={{ color: '#113D73' }} />
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">
                  Ready to answer your questions
                </h3>
                <p className="text-gray-500">
                  Ask anything — answers will be grounded in your documents.
                </p>
              </motion.div>
            )}

            {messages.map(message => (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div className="max-w-3xl space-y-2">
                  <div
                    className={`rounded-2xl px-4 py-3 ${
                      message.type === 'user'
                        ? 'text-white'
                        : 'bg-white border border-gray-200'
                    }`}
                    style={message.type === 'user' ? { backgroundColor: '#113D73' } : {}}
                  >
                    {message.isLoading ? (
                      <>
                        <p className="text-gray-500 text-sm">{loadingStep}</p>
                        <div className="flex items-center gap-2 mt-2">
                          <div className="flex space-x-1">
                            <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
                            <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
                            <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                          </div>
                        </div>
                      </>
                    ) : (
                      <p className="whitespace-pre-wrap">{message.content}</p>
                    )}
                  </div>

                  {/* Sources */}
                  {message.sources && message.sources.length > 0 && (
                    <div className="px-1">
                      <p className="text-xs text-gray-400 mb-1">Sources:</p>
                      <div className="flex flex-wrap gap-1">
                        {message.sources.map((src, i) => (
                          <span
                            key={i}
                            className="text-xs bg-blue-50 text-blue-700 border border-blue-200 px-2 py-0.5 rounded-full"
                          >
                            {src}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* LangSmith trace link */}
                  {message.trace_url && (
                    <div className="px-1 mt-1">
                      <a
                        href={message.trace_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                      >
                        <ExternalLink className="w-3 h-3" />
                        View trace in LangSmith
                      </a>
                    </div>
                  )}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-200 bg-white p-4">
          <div className="flex items-center gap-4 max-w-4xl mx-auto">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question about your documents…"
                className="w-full px-4 py-3 border border-gray-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:border-transparent"
                style={{ minHeight: '48px', maxHeight: '120px' }}
                disabled={isLoading}
              />
            </div>
            <button
              onClick={() => handleSendMessage()}
              disabled={!inputValue.trim() || isLoading}
              className="px-4 py-3 text-white rounded-xl hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
              style={{ backgroundColor: '#113D73', height: '48px' }}
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>

      {showDebugPanel && <DebugPanel onClose={() => setShowDebugPanel(false)} />}
    </div>
  );
};

export default RagQA;
