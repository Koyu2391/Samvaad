import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { api } from '../services/api';

export type UserRole = 'admin' | 'analyst' | 'viewer';

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  organization_id: string;
}

interface AuthContextType {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string, orgName?: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchMe = async (): Promise<AuthUser | null> => {
    try {
      const res = await api.get('/auth/me');
      const u = res.data as AuthUser;
      setUser(u);
      localStorage.setItem('user', JSON.stringify(u));
      return u;
    } catch {
      setUser(null);
      return null;
    }
  };

  useEffect(() => {
    const init = async () => {
      const token = localStorage.getItem('access_token');
      if (!token) {
        setIsLoading(false);
        return;
      }
      const cached = localStorage.getItem('user');
      if (cached) {
        try { setUser(JSON.parse(cached)); } catch {}
      }
      await fetchMe();
      setIsLoading(false);
    };
    init();
  }, []);

  const storeTokens = (accessToken: string, refreshToken: string) => {
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
  };

  const login = async (email: string, password: string) => {
    const res = await api.post('/auth/login', { email, password });
    storeTokens(res.data.access_token, res.data.refresh_token);
    await fetchMe();
  };

  const register = async (
    email: string,
    password: string,
    fullName: string,
    orgName?: string,
  ) => {
    const res = await api.post('/auth/register', {
      email,
      password,
      full_name: fullName,
      organization_name: orgName || null,
    });
    storeTokens(res.data.access_token, res.data.refresh_token);
    await fetchMe();
  };

  const logout = () => {
    api.post('/auth/logout').catch(() => {});
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    setUser(null);
    window.location.href = '/login';
  };

  const refreshUser = async () => {
    await fetchMe();
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
