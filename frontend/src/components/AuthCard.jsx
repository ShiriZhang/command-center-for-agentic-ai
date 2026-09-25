import React, { useState } from 'react';
import { Layers } from 'lucide-react';
import LoginView from './LoginView';
import RegisterView from './RegisterView';

export default function AuthCard({ initialTab = 'login' }) {
  const [activeTab, setActiveTab] = useState(initialTab);

  return (
    <div className="relative flex flex-col items-center justify-center min-h-[calc(100vh-4rem)] p-4 sm:p-6">
      {/* Background Decorative Ambient Glows */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 left-1/3 w-64 h-64 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

      {/* Brand Header */}
      <div className="flex items-center gap-2.5 mb-8 z-10">
        <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-400 text-white shadow-lg shadow-emerald-500/20">
          <Layers className="w-5 h-5" />
        </div>
        <div className="text-left">
          <span className="text-base font-extrabold text-white tracking-tight block">
            FNMS Platform
          </span>
          <span className="text-xs text-emerald-400 font-mono">
            Agentic AI Foundation • A1
          </span>
        </div>
      </div>

      {/* Mode Switcher Tabs */}
      <div className="inline-flex p-1 mb-6 rounded-xl bg-slate-900/80 border border-slate-800 z-10 shadow-inner">
        <button
          type="button"
          onClick={() => setActiveTab('login')}
          className={`px-6 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeTab === 'login'
              ? 'bg-emerald-600 text-white shadow-md shadow-emerald-600/30'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          Sign In
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('register')}
          className={`px-6 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeTab === 'register'
              ? 'bg-emerald-600 text-white shadow-md shadow-emerald-600/30'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          Create Account
        </button>
      </div>

      {/* Render Active View */}
      <div className="z-10 w-full flex justify-center">
        {activeTab === 'login' ? (
          <LoginView onSwitchToRegister={() => setActiveTab('register')} />
        ) : (
          <RegisterView onSwitchToLogin={() => setActiveTab('login')} />
        )}
      </div>
    </div>
  );
}
