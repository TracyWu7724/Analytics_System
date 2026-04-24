import { useState, useCallback } from 'react';
import { getApiUrl } from '../config/api';

const TOKEN_KEY = 'ds_auth_token';

export interface AuthUser {
  user_id: string;
  username: string;
  role: string;
  exp: number;
}

const ROLE_PERMISSIONS: Record<string, string[]> = {
  admin:   ['SQL Query', 'RAG Query', 'File Upload', 'PDF Upload', 'Admin Access'],
  analyst: ['SQL Query', 'RAG Query', 'File Upload', 'PDF Upload'],
  manager: ['SQL Query', 'RAG Query'],
  viewer:  ['SQL Query'],
};

const ROLE_COLORS: Record<string, { bg: string; text: string }> = {
  admin:   { bg: 'bg-purple-100', text: 'text-purple-700' },
  analyst: { bg: 'bg-blue-100',   text: 'text-blue-700'   },
  manager: { bg: 'bg-green-100',  text: 'text-green-700'  },
  viewer:  { bg: 'bg-gray-100',   text: 'text-gray-600'   },
};

function decodeToken(token: string): AuthUser | null {
  try {
    const [payloadB64] = token.split('.');
    const padding = 4 - (payloadB64.length % 4);
    const padded = padding < 4 ? payloadB64 + '='.repeat(padding) : payloadB64;
    const json = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
    const payload = JSON.parse(json);
    if (Date.now() / 1000 > payload.exp) return null; // expired
    return { user_id: String(payload.sub), username: payload.username, role: payload.role, exp: payload.exp };
  } catch {
    return null;
  }
}

function loadUser(): AuthUser | null {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? decodeToken(token) : null;
}

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(loadUser);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const login = useCallback(async (username: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      const body = new FormData();
      body.append('username', username);
      body.append('password', password);
      const res = await fetch(getApiUrl('/login'), { method: 'POST', body });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Invalid credentials');
      }
      const { access_token } = await res.json();
      localStorage.setItem(TOKEN_KEY, access_token);
      const decoded = decodeToken(access_token);
      setUser(decoded);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Login failed');
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
    setError(null);
  }, []);

  const getToken = useCallback(() => localStorage.getItem(TOKEN_KEY), []);

  return { user, loading, error, login, logout, getToken, ROLE_PERMISSIONS, ROLE_COLORS };
}
