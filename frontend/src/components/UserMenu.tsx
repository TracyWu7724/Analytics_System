import React, { useState, useRef, useEffect } from 'react';
import { User, LogOut, LogIn, Shield, ChevronDown } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

const UserMenu: React.FC = () => {
  const { user, loading, error, login, logout, ROLE_PERMISSIONS, ROLE_COLORS } = useAuth();
  const [open, setOpen] = useState(false);
  const [showLogin, setShowLogin] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const menuRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
        setShowLogin(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = await login(username, password);
    if (ok) { setShowLogin(false); setOpen(true); setUsername(''); setPassword(''); }
  };

  const roleColors = user ? (ROLE_COLORS[user.role] ?? ROLE_COLORS.viewer) : null;
  const permissions = user ? (ROLE_PERMISSIONS[user.role] ?? []) : [];
  const initials = user ? user.username.slice(0, 2).toUpperCase() : '?';

  return (
    <div className="relative" ref={menuRef}>
      {/* Trigger button */}
      <button
        onClick={() => { setOpen(o => !o); setShowLogin(false); }}
        className="flex items-center gap-1.5 p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
        title={user ? `${user.username} (${user.role})` : 'Sign in'}
      >
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold text-white"
          style={{ backgroundColor: user ? '#113D73' : '#9ca3af' }}
        >
          {user ? initials : <User className="w-4 h-4" />}
        </div>
        <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute right-0 mt-2 w-72 bg-white rounded-xl shadow-lg border border-gray-200 z-50 overflow-hidden">
          {user ? (
            <>
              {/* User info */}
              <div className="px-4 py-3 border-b border-gray-100">
                <div className="flex items-center gap-3">
                  <div
                    className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold text-white flex-shrink-0"
                    style={{ backgroundColor: '#113D73' }}
                  >
                    {initials}
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-gray-900 truncate">{user.username}</p>
                    <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full mt-0.5 ${roleColors!.bg} ${roleColors!.text}`}>
                      {user.role}
                    </span>
                  </div>
                </div>
              </div>

              {/* Permissions */}
              <div className="px-4 py-3 border-b border-gray-100">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                  <Shield className="w-3 h-3" /> Permissions
                </p>
                <ul className="space-y-1">
                  {(['SQL Query', 'RAG Query', 'File Upload', 'PDF Upload', 'Admin Access'] as const).map(perm => {
                    const granted = permissions.includes(perm);
                    return (
                      <li key={perm} className="flex items-center gap-2 text-sm">
                        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${granted ? 'bg-green-500' : 'bg-gray-300'}`} />
                        <span className={granted ? 'text-gray-700' : 'text-gray-400 line-through'}>{perm}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>

              {/* Logout */}
              <button
                onClick={() => { logout(); setOpen(false); }}
                className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors"
              >
                <LogOut className="w-4 h-4" />
                Sign out
              </button>
            </>
          ) : showLogin ? (
            /* Login form */
            <form onSubmit={handleLogin} className="px-4 py-4 space-y-3">
              <p className="text-sm font-semibold text-gray-900">Sign in</p>
              {error && <p className="text-xs text-red-600 bg-red-50 rounded px-2 py-1">{error}</p>}
              <input
                type="text"
                placeholder="Username"
                value={username}
                onChange={e => setUsername(e.target.value)}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-200"
                autoFocus
              />
              <input
                type="password"
                placeholder="Password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              <button
                type="submit"
                disabled={loading || !username || !password}
                className="w-full py-2 text-sm text-white rounded-lg font-medium disabled:opacity-50 transition-opacity"
                style={{ backgroundColor: '#113D73' }}
              >
                {loading ? 'Signing in…' : 'Sign in'}
              </button>
              {/* <p className="text-xs text-gray-400 text-center">
                Demo: admin / alice / bob / carol
              </p> */}
            </form>
          ) : (
            /* Not logged in */
            <div className="p-4 space-y-3">
              <div className="flex items-center gap-2 text-gray-500">
                <User className="w-4 h-4" />
                <span className="text-sm">Not signed in</span>
              </div>
              <button
                onClick={() => setShowLogin(true)}
                className="w-full flex items-center justify-center gap-2 py-2 text-sm text-white rounded-lg font-medium"
                style={{ backgroundColor: '#113D73' }}
              >
                <LogIn className="w-4 h-4" />
                Sign in
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default UserMenu;
