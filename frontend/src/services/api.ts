import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

export const API_BASE = '/api';

export const api = axios.create({
  baseURL: API_BASE,
});

// Inject JWT into every request
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('access_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401 → try refresh, else redirect to /login
let isRefreshing = false;
let refreshQueue: Array<(token: string | null) => void> = [];

const drainQueue = (token: string | null) => {
  refreshQueue.forEach(cb => cb(token));
  refreshQueue = [];
};

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && !original._retry) {
      const refreshToken = localStorage.getItem('refresh_token');
      if (!refreshToken) {
        forceLogout();
        return Promise.reject(error);
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          refreshQueue.push((token) => {
            if (token && original.headers) {
              original.headers.Authorization = `Bearer ${token}`;
              resolve(api(original));
            } else {
              reject(error);
            }
          });
        });
      }

      original._retry = true;
      isRefreshing = true;
      try {
        const res = await axios.post(`${API_BASE}/auth/refresh`, null, {
          params: { refresh_token: refreshToken },
        });
        const newAccess = res.data.access_token;
        const newRefresh = res.data.refresh_token;
        localStorage.setItem('access_token', newAccess);
        localStorage.setItem('refresh_token', newRefresh);
        drainQueue(newAccess);
        if (original.headers) {
          original.headers.Authorization = `Bearer ${newAccess}`;
        }
        return api(original);
      } catch (refreshErr) {
        drainQueue(null);
        forceLogout();
        return Promise.reject(refreshErr);
      } finally {
        isRefreshing = false;
      }
    }
    return Promise.reject(error);
  }
);

export function forceLogout() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user');
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}
