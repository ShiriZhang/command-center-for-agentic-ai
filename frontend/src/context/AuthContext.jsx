import React, { createContext, useContext, useState, useEffect } from 'react';
import { api } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('access_token'));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // -------------------------------------------------------------
  // Initial Session Hydration on Browser Mount
  // If a JWT token exists in localStorage, verify it by calling GET /api/auth/me.
  // If the token is valid, hydrate user state; if invalid/expired (401), clean up.
  // -------------------------------------------------------------
  useEffect(() => {
    async function loadUserSession() {
      const storedToken = localStorage.getItem('access_token');
      if (storedToken) {
        try {
          const profile = await api.getMe();
          setUser(profile);
          setToken(storedToken);
        } catch (err) {
          // Token expired or server rejected with 401: clear local state
          console.warn('Stored session invalid or expired:', err.message);
          localStorage.removeItem('access_token');
          setUser(null);
          setToken(null);
        }
      }
      setLoading(false);
    }

    loadUserSession();
  }, []);

  // -------------------------------------------------------------
  // Authentication Actions
  // -------------------------------------------------------------

  const login = async (username, password) => {
    setError(null);
    try {
      const data = await api.login({ username, password });
      localStorage.setItem('access_token', data.access_token);
      setToken(data.access_token);
      setUser(data.user);
      return data.user;
    } catch (err) {
      setError(err.message);
      throw err;
    }
  };

  const register = async (username, email, password) => {
    setError(null);
    try {
      // 1. Create account on backend
      await api.register({ username, email, password });
      // 2. Automatically log in to retrieve JWT access token
      return await login(username, password);
    } catch (err) {
      setError(err.message);
      throw err;
    }
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    setToken(null);
    setUser(null);
    setError(null);
  };

  const updateProfile = async (updateData) => {
    if (!user) throw new Error('No authenticated user session');
    setError(null);
    try {
      const updatedUser = await api.updateUser(user.id, updateData);
      setUser(updatedUser);
      return updatedUser;
    } catch (err) {
      setError(err.message);
      throw err;
    }
  };

  const deleteAccount = async () => {
    if (!user) throw new Error('No authenticated user session');
    setError(null);
    try {
      await api.deleteUser(user.id);
      logout();
    } catch (err) {
      setError(err.message);
      throw err;
    }
  };

  const value = {
    user,
    token,
    loading,
    error,
    login,
    register,
    logout,
    updateProfile,
    deleteAccount,
    isAuthenticated: !!user && !!token,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
