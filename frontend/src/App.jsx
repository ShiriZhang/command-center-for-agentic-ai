import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import AuthCard from './components/AuthCard';
import Navbar from './components/Navbar';
import HomeView from './components/HomeView';
import AccountView from './components/AccountView';
import { Loader2 } from 'lucide-react';

function MainLayout() {
  const { isAuthenticated, loading } = useAuth();
  const [currentTab, setCurrentTab] = useState('home');

  // Loading spinner during initial session check (GET /api/auth/me)
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-slate-950 text-slate-400">
        <Loader2 className="w-8 h-8 animate-spin text-emerald-400 mb-3" />
        <span className="text-xs font-mono tracking-wider">INITIALIZING SESSION...</span>
      </div>
    );
  }

  // Unauthenticated: Screen 1 (Register) & Screen 2 (Login)
  if (!isAuthenticated) {
    return <AuthCard />;
  }

  // Authenticated: Header + Screen 3 (Home) or Screen 4 (Account)
  return (
    <div className="min-h-screen bg-slate-950 flex flex-col text-slate-100">
      <Navbar currentTab={currentTab} onSelectTab={setCurrentTab} />
      <main className="flex-1 pb-16">
        {currentTab === 'home' && (
          <HomeView onNavigateToAccount={() => setCurrentTab('account')} />
        )}
        {currentTab === 'account' && <AccountView />}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <MainLayout />
    </AuthProvider>
  );
}
