import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Search, PanelRightOpen, PanelLeftClose, MessageSquare, Pin, PinOff, Trash2 } from "lucide-react";
import { sessionHistoryService, type ConversationSession } from "../services/queryHistoryService";
import { useAuth } from "../hooks/useAuth";


const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [sessions, setSessions] = useState<ConversationSession[]>([]);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  useEffect(() => {
    loadSessions();

    const refresh = () => loadSessions();
    window.addEventListener('queryHistoryUpdated', refresh);
    window.addEventListener('storage', refresh);
    return () => {
      window.removeEventListener('queryHistoryUpdated', refresh);
      window.removeEventListener('storage', refresh);
    };
  }, [user?.username]);

  const loadSessions = () => {
    if (!user) { setSessions([]); return; }
    setSessions(sessionHistoryService.getSessions(user.username).slice(0, 15));
  };

  const handleSessionClick = (session: ConversationSession) => {
    navigate(`/agent?session=${encodeURIComponent(session.session_id)}`);
  };

  const handleDelete = (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (confirmDeleteId === sessionId) {
      sessionHistoryService.deleteSession(user!.username, sessionId);
      setConfirmDeleteId(null);
      loadSessions();
      window.dispatchEvent(new Event('queryHistoryUpdated'));
    } else {
      setConfirmDeleteId(sessionId);
    }
  };

  const handlePin = (e: React.MouseEvent, session: ConversationSession) => {
    e.stopPropagation();
    sessionHistoryService.pinSession(user!.username, session.session_id, !session.pinned);
    loadSessions();
  };

  const truncate = (text: string, max = 35) =>
    text.length > max ? `${text.slice(0, max)}…` : text;

  const frequentQueries = [
    "What is the totalUSD by category of operationsExpenses.projectedOPEX?",
    "What is the totalUSD by location of operationsExpenses.projectedOPEX?",
    "Show me all records of operationsExpenses.projectedOPEX",
    "Show me records of DAS_NPI_Development_Cost_EBR",
  ];

  // Find a session where the first user message matches this query exactly.
  // If found, open it like a recent conversation; otherwise start a new one.
  const handleFrequentQueryClick = (query: string) => {
    const normalised = query.trim().toLowerCase();
    const existing = sessions.find(s => {
      const firstUser = s.messages.find(m => m.type === 'user');
      return firstUser?.content.trim().toLowerCase() === normalised;
    });
    if (existing) {
      navigate(`/agent?session=${encodeURIComponent(existing.session_id)}`);
    } else {
      navigate(`/agent?query=${encodeURIComponent(query)}`);
    }
  };

  // ── Collapsed view ────────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <aside className="w-14 bg-gray-100 text-gray-700 min-h-screen flex flex-col items-center pt-4 gap-3 flex-shrink-0">
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 rounded-lg hover:bg-gray-200 transition-colors"
          title="Expand sidebar"
        >
          <PanelRightOpen className="w-5 h-5" style={{ color: '#113D73' }} />
        </button>
        <button
          onClick={() => navigate('/')}
          className="p-2 rounded-lg hover:bg-gray-200 transition-colors"
          title="New Data Query"
        >
          <Search className="w-5 h-5" style={{ color: '#113D73' }} />
        </button>
      </aside>
    );
  }

  // ── Expanded view ─────────────────────────────────────────────────────────
  return (
    <aside className="w-72 bg-gray-100 text-gray-700 min-h-screen flex flex-col flex-shrink-0">
      {/* Collapse button */}
      <div className="flex justify-end px-4 pt-4">
        <button
          onClick={() => setCollapsed(true)}
          className="p-1.5 rounded-lg hover:bg-gray-200 transition-colors"
          title="Collapse sidebar"
        >
          <PanelLeftClose className="w-5 h-5 text-gray-500" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-8 pb-8 pt-2">
        <nav className="flex flex-col space-y-8">

          {/* New Data Query */}
          <div className="space-y-2">
            <button
              onClick={() => navigate('/agent')}
              className="flex items-center space-x-3 hover:text-gray-900 transition-colors w-full text-left"
            >
              <svg className="w-6 h-6 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
              </svg>
              <span className="font-bold" style={{ color: '#113D73' }}>New Data Query</span>
            </button>
          </div>

          {/* Frequently Searched */}
          {/* <div className="space-y-2">
            <div className="flex items-center space-x-3">
              <svg className="w-6 h-6 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
              </svg>
              <span className="font-bold" style={{ color: '#113D73' }}>Frequently Searched</span>
            </div>
            {frequentQueries.map((query, index) => (
              <button
                key={index}
                onClick={() => handleFrequentQueryClick(query)}
                className="block hover:text-gray-900 hover:bg-gray-200 transition-colors text-sm pl-9 py-1 rounded w-full text-left"
                title={query}
              >
                {truncate(query)}
              </button>
            ))}
          </div> */}

          {/* Recent Conversations */}
          <div className="space-y-1">
            <div className="flex items-center space-x-3 mb-2">
              <MessageSquare className="w-6 h-6 flex-shrink-0" style={{ color: '#113D73' }} />
              <span className="font-bold" style={{ color: '#113D73' }}>Recent Conversations</span>
            </div>
            {!user ? (
              <p className="text-sm text-gray-400 pl-9">Sign in to see history</p>
            ) : sessions.length === 0 ? (
              <p className="text-sm text-gray-500 pl-9">No conversations yet</p>
            ) : (
              sessions.map(session => (
                <div
                  key={session.session_id}
                  className="relative group"
                  onMouseEnter={() => { setHoveredId(session.session_id); setConfirmDeleteId(null); }}
                  onMouseLeave={() => { setHoveredId(null); setConfirmDeleteId(null); }}
                >
                  <button
                    onClick={() => handleSessionClick(session)}
                    className="flex items-center gap-1.5 w-full text-left text-sm py-1 px-2 rounded hover:bg-gray-200 transition-colors pr-16"
                    title={session.title}
                  >
                    {session.pinned && (
                      <Pin className="w-3 h-3 flex-shrink-0 text-blue-500 rotate-45" />
                    )}
                    <span className="truncate">{truncate(session.title)}</span>
                  </button>

                  {/* Action buttons — visible on hover */}
                  {hoveredId === session.session_id && (
                    <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
                      {/* Pin / Unpin */}
                      <button
                        onClick={(e) => handlePin(e, session)}
                        className="p-1 rounded hover:bg-gray-300 transition-colors"
                        title={session.pinned ? 'Unpin' : 'Pin to top'}
                      >
                        {session.pinned
                          ? <PinOff className="w-3.5 h-3.5 text-blue-500" />
                          : <Pin className="w-3.5 h-3.5 text-gray-500" />
                        }
                      </button>

                      {/* Delete */}
                      {confirmDeleteId === session.session_id ? (
                        <button
                          onClick={(e) => handleDelete(e, session.session_id)}
                          className="px-1.5 py-0.5 rounded bg-red-500 text-white text-xs hover:bg-red-600 transition-colors"
                          title="Confirm delete"
                        >
                          Confirm
                        </button>
                      ) : (
                        <button
                          onClick={(e) => handleDelete(e, session.session_id)}
                          className="p-1 rounded hover:bg-gray-300 transition-colors"
                          title="Delete conversation"
                        >
                          <Trash2 className="w-3.5 h-3.5 text-gray-500 hover:text-red-500" />
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

        </nav>
      </div>
    </aside>
  );
};

export default Sidebar;
