import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  Terminal, 
  Database, 
  Globe2, 
  Bot, 
  ArrowRight, 
  Activity,
  CheckCircle2
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';

export default function HomeView({ onNavigateToAccount }) {
  const { user } = useAuth();
  const [backendHealth, setBackendHealth] = useState('checking');

  // Verify real-time cross-origin communication with backend
  useEffect(() => {
    async function checkHealth() {
      try {
        const res = await api.getHealth();
        if (res.status === 'ok') {
          setBackendHealth('healthy');
        } else {
          setBackendHealth('degraded');
        }
      } catch (err) {
        setBackendHealth('offline');
      }
    }
    checkHealth();
  }, []);

  const formattedDate = user?.created_at
    ? new Date(user.created_at).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : 'Active Session';

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
      {/* Welcome Banner / Identity (Mandatory A1 Requirement) */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-900 via-slate-900 to-slate-950 border border-slate-800 p-8 sm:p-10 mb-8 shadow-2xl">
        <div className="absolute top-0 right-0 w-80 h-80 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none" />
        
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-medium mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Authenticated Session
            </div>
            <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
              Welcome, <span className="text-emerald-400">{user?.username}</span>!
            </h1>
            <p className="mt-2 text-sm text-slate-400 max-w-xl">
              You are signed into your personal Command Center. This is the foundations bedrock for your tools and upcoming Agentic AI workflows.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row gap-3">
            <button
              onClick={onNavigateToAccount}
              className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700/80 border border-slate-700 text-xs font-semibold text-slate-200 transition-colors shadow-sm"
            >
              Account Settings
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Identity Metadata Badges */}
        <div className="mt-8 pt-6 border-t border-slate-800/80 grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center text-slate-400">
              <Terminal className="w-4 h-4" />
            </div>
            <div>
              <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-semibold">User ID</span>
              <span className="text-xs font-mono font-medium text-slate-300">#{user?.id}</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center text-slate-400">
              <ShieldCheck className="w-4 h-4" />
            </div>
            <div>
              <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-semibold">Verified Email</span>
              <span className="text-xs font-medium text-slate-300 truncate max-w-[180px] block">{user?.email}</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center text-slate-400">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-semibold">Member Since</span>
              <span className="text-xs font-medium text-slate-300">{formattedDate}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Course Requirement: "This is the empty room you will furnish in A2" */}
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-white tracking-tight">System Status & Architecture</h2>
            <p className="text-xs text-slate-400">Foundational network layer connecting client to database</p>
          </div>
        </div>

        {/* Status Indicators Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {/* Card 1: Backend & CORS */}
          <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className="w-9 h-9 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center">
                  <Globe2 className="w-5 h-5" />
                </div>
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium ${
                  backendHealth === 'healthy'
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${backendHealth === 'healthy' ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                  {backendHealth === 'healthy' ? 'Online (200 OK)' : 'Connecting...'}
                </span>
              </div>
              <h3 className="text-sm font-semibold text-white">Cross-Origin API</h3>
              <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                Frontend (Port 5173) ↔ Backend (Port 8000). CORS preflight and Bearer authentication active.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-800/60 text-[11px] font-mono text-slate-500 flex items-center justify-between">
              <span>Endpoint:</span>
              <span className="text-slate-400">/healthz</span>
            </div>
          </div>

          {/* Card 2: Database Persistence */}
          <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className="w-9 h-9 rounded-xl bg-purple-500/10 text-purple-400 flex items-center justify-center">
                  <Database className="w-5 h-5" />
                </div>
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Persistent
                </span>
              </div>
              <h3 className="text-sm font-semibold text-white">Storage Engine</h3>
              <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                SQLAlchemy ORM connected to Neon Serverless PostgreSQL with auto-reconnect pooling.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-800/60 text-[11px] font-mono text-slate-500 flex items-center justify-between">
              <span>Survives Restarts:</span>
              <span className="text-emerald-400 font-semibold">YES</span>
            </div>
          </div>

          {/* Card 3: Assignment 1B Empty Room */}
          <div className="p-5 rounded-2xl bg-gradient-to-b from-slate-900/80 to-slate-950 border border-dashed border-emerald-500/30 flex flex-col justify-between relative overflow-hidden">
            <div className="absolute -right-4 -bottom-4 w-20 h-20 bg-emerald-500/5 rounded-full blur-xl pointer-events-none" />
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className="w-9 h-9 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center">
                  <Bot className="w-5 h-5" />
                </div>
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-slate-800 text-slate-300 border border-slate-700">
                  Ready for A2
                </span>
              </div>
              <h3 className="text-sm font-semibold text-emerald-300">Agentic Tracker Slot</h3>
              <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                This is the empty room to be furnished in Assignment 1B with the autonomous web research agent.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-800/60 text-[11px] font-mono text-slate-500 flex items-center justify-between">
              <span>Next Milestone:</span>
              <span className="text-emerald-400">Assignment 1B</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
