import React, { useState, useEffect, useRef } from 'react';
import { 
  Bot, 
  Play, 
  RotateCcw, 
  ShieldCheck, 
  ShieldAlert, 
  ExternalLink, 
  Clock, 
  Sparkles, 
  CheckCircle2, 
  AlertTriangle, 
  Layers, 
  RefreshCw, 
  Loader2, 
  Building2, 
  MapPin, 
  DollarSign, 
  Globe, 
  Calendar, 
  TrendingUp,
  History,
  FileCheck2,
  Info,
  XCircle,
  HelpCircle
} from 'lucide-react';
import { api } from '../api/client';

/**
 * Validates that an external URL strictly uses safe http: or https: protocols.
 * Neutralizes javascript:, data:, and other malicious URI payloads.
 */
const isSafeUrl = (url) => {
  if (!url || typeof url !== 'string') return false;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
};

export default function TrackerView() {
  const [runs, setRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [resetFlag, setResetFlag] = useState(false);
  const [message, setMessage] = useState(null);
  const [apiError, setApiError] = useState(null);

  // Polling management
  const pollingRef = useRef(null);

  // Clear polling interval on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  /**
   * Fetches all runs and history summary from backend via api client.
   * Strictly distinguishes empty database, API error, and active execution states.
   * Never falls back to sample runs.
   */
  const fetchTrackerData = async () => {
    setLoading(true);
    setApiError(null);
    try {
      const fetchedRuns = await api.getTrackerRuns();

      try {
        const fetchedStats = await api.getTrackerHistory();
        if (fetchedStats) {
          setStats(fetchedStats);
        }
      } catch (statsErr) {
        console.warn('Failed to fetch history stats:', statsErr);
      }

      setRuns(fetchedRuns || []);

      // Automatically select latest run or maintain selection
      if (fetchedRuns && fetchedRuns.length > 0) {
        setSelectedRunId(prevId => {
          if (prevId && fetchedRuns.some(r => r.id === prevId)) {
            return prevId;
          }
          return fetchedRuns[0].id;
        });

        // Resume polling if any run is actively running
        const activeRunning = fetchedRuns.find(r => r.status === 'running');
        if (activeRunning) {
          startPolling(activeRunning.id);
        }
      } else {
        setSelectedRunId(null);
      }
    } catch (err) {
      console.error('Failed to load tracker runs from backend:', err);
      setApiError(err.message || 'Unable to connect to backend server on port 8000.');
      setRuns([]);
      setSelectedRunId(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTrackerData();
  }, []);

  /**
   * Polls a specific run ID every 2 seconds until terminal status ('complete' or 'partial').
   * Replaces fixed-delay refresh to ensure cold-start or slow workers stay visibly running.
   */
  const startPolling = (runId) => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }

    setTriggering(true);

    pollingRef.current = setInterval(async () => {
      try {
        const runData = await api.getTrackerRunById(runId);

        if (runData) {
          // Update the run record in state
          setRuns(prevRuns => {
            const idx = prevRuns.findIndex(r => r.id === runId);
            if (idx >= 0) {
              const updated = [...prevRuns];
              updated[idx] = runData;
              return updated;
            }
            return [runData, ...prevRuns];
          });

          // Check for terminal status
          if (runData.status === 'complete' || runData.status === 'partial') {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
            setTriggering(false);
            setSelectedRunId(runData.id);

            // Refresh aggregate history stats
            api.getTrackerHistory().then(setStats).catch(() => {});

            setMessage({
              type: 'success',
              text: `Tracker run ${runData.run_number} finished with status: ${runData.status.toUpperCase()}.`
            });
          }
        }
      } catch (pollErr) {
        console.warn(`Polling error for run ${runId}:`, pollErr);
      }
    }, 2000);
  };

  /**
   * Triggers a new research run via POST /api/tracker/trigger.
   * Handles 409 Conflict when an active run is in progress.
   */
  const handleTriggerRun = async () => {
    setTriggering(true);
    setMessage(null);
    try {
      const payload = { reset: resetFlag };
      const res = await api.triggerTracker(payload);

      setMessage({
        type: 'success',
        text: res?.message || `Tracker run ${res?.run_number || ''} admitted! Orchestration running...`
      });

      if (res?.run_id) {
        // Optimistically add running record
        const placeholderRun = {
          id: res.run_id,
          run_uuid: res.run_uuid || '',
          run_number: res.run_number || 1,
          topic: "Top 10 newest entry-level and new grad AI/ML engineering roles",
          target_k: 10,
          status: 'running',
          step_count: 0,
          fetch_count: 0,
          tokens_spent: 0,
          created_at: new Date().toISOString(),
          developments: [],
          articles: []
        };
        setRuns(prev => [placeholderRun, ...prev.filter(r => r.id !== res.run_id)]);
        setSelectedRunId(res.run_id);
        startPolling(res.run_id);
      } else {
        fetchTrackerData();
      }
    } catch (err) {
      if (err.status === 409) {
        setMessage({
          type: 'warning',
          text: 'Conflict: An active tracker run is already in progress. Polling current run...'
        });
        fetchTrackerData();
      } else {
        setMessage({
          type: 'error',
          text: err.message || 'Failed to trigger tracker execution.'
        });
        setTriggering(false);
      }
    }
  };

  // Find currently active run
  const activeRun = runs.find(r => r.id === selectedRunId) || runs[0];

  /**
   * Helper: Multi-run differential badges ([NEW], [STILL IN TOP 10], [DROPPED])
   */
  const renderStatusBadge = (status) => {
    const s = (status || '').toLowerCase();
    if (s.includes('new')) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
          <Sparkles className="w-3 h-3 text-emerald-400" />
          [NEW]
        </span>
      );
    }
    if (s.includes('still') || s.includes('retained')) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-sky-500/15 text-sky-400 border border-sky-500/30">
          <TrendingUp className="w-3 h-3 text-sky-400" />
          [STILL IN TOP 10]
        </span>
      );
    }
    if (s.includes('drop')) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30">
          <AlertTriangle className="w-3 h-3 text-rose-400" />
          [DROPPED]
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
        {status}
      </span>
    );
  };

  /**
   * Helper: Claim verdict badge renderer.
   * Supports: supported, unsupported, unreachable, unverified
   */
  const renderClaimVerdictBadge = (verdict) => {
    const v = (verdict || 'unverified').toLowerCase();
    if (v === 'supported') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
          [SUPPORTED]
        </span>
      );
    }
    if (v === 'unsupported') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/15 text-rose-400 border border-rose-500/30">
          <XCircle className="w-3 h-3 text-rose-400" />
          [UNSUPPORTED]
        </span>
      );
    }
    if (v === 'unreachable') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 text-amber-400 border border-amber-500/30">
          <AlertTriangle className="w-3 h-3 text-amber-400" />
          [UNREACHABLE]
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-purple-500/15 text-purple-400 border border-purple-500/30">
        <HelpCircle className="w-3 h-3 text-purple-400" />
        [UNVERIFIED]
      </span>
    );
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-8">
      {/* 1. Header Banner & Trigger Control */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-900 via-slate-900 to-slate-950 border border-slate-800 p-6 sm:p-8 shadow-2xl">
        <div className="absolute top-0 right-0 w-96 h-96 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold">
              <Bot className="w-3.5 h-3.5 text-emerald-400" />
              Autonomous Agentic Research Engine
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              Top 10 Entry-Level & New Grad AI/ML Roles
            </h1>
            <p className="text-xs sm:text-sm text-slate-400 max-w-2xl leading-relaxed">
              Decoupled three-service architecture: plain-code Orchestrator coordinates independent Researcher and Verifier over authenticated HTTP contracts with strict SSRF network guardrails and verified claims.
            </p>
          </div>

          {/* Trigger Actions */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-300 bg-slate-800/80 hover:bg-slate-800 border border-slate-700 px-3.5 py-2.5 rounded-xl cursor-pointer transition-colors">
              <input
                type="checkbox"
                checked={resetFlag}
                onChange={(e) => setResetFlag(e.target.checked)}
                className="w-3.5 h-3.5 text-emerald-500 rounded border-slate-700 bg-slate-900 focus:ring-0"
              />
              <RotateCcw className="w-3.5 h-3.5 text-slate-400" />
              <span>--reset (Clean Lineage)</span>
            </label>

            <button
              onClick={handleTriggerRun}
              disabled={triggering || activeRun?.status === 'running'}
              className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition-all shadow-lg shadow-emerald-950/50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {triggering || activeRun?.status === 'running' ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin text-white" />
                  <span>Agent Running...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  <span>Run Tracker Now</span>
                </>
              )}
            </button>

            <button
              onClick={fetchTrackerData}
              disabled={loading}
              title="Refresh telemetry"
              className="inline-flex items-center justify-center p-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Real-time Toast/Message */}
        {message && (
          <div className={`mt-4 p-3 rounded-xl border text-xs font-medium flex items-center gap-2 ${
            message.type === 'success' 
              ? 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300' 
              : message.type === 'warning'
              ? 'bg-amber-950/40 border-amber-500/30 text-amber-300'
              : 'bg-rose-950/40 border-rose-500/30 text-rose-300'
          }`}>
            {message.type === 'success' && <CheckCircle2 className="w-4 h-4 shrink-0" />}
            {message.type === 'warning' && <AlertTriangle className="w-4 h-4 shrink-0" />}
            {message.type === 'error' && <XCircle className="w-4 h-4 shrink-0" />}
            <span>{message.text}</span>
          </div>
        )}

        {/* Global Telemetry Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6 pt-6 border-t border-slate-800/80">
          <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
            <div className="text-[10px] font-semibold tracking-wider uppercase text-slate-400">Total Runs</div>
            <div className="text-lg font-extrabold text-white mt-0.5">
              {stats?.total_runs ?? runs.length}
            </div>
          </div>
          <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
            <div className="text-[10px] font-semibold tracking-wider uppercase text-slate-400">Total Steps</div>
            <div className="text-lg font-extrabold text-emerald-400 mt-0.5">
              {stats?.total_steps ?? runs.reduce((acc, r) => acc + (r.step_count || 0), 0)}
            </div>
          </div>
          <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
            <div className="text-[10px] font-semibold tracking-wider uppercase text-slate-400">Articles Inspected</div>
            <div className="text-lg font-extrabold text-sky-400 mt-0.5">
              {stats?.total_fetches ?? runs.reduce((acc, r) => acc + (r.fetch_count || 0), 0)}
            </div>
          </div>
          <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
            <div className="text-[10px] font-semibold tracking-wider uppercase text-slate-400">Tokens Invested</div>
            <div className="text-lg font-extrabold text-indigo-400 mt-0.5">
              {(stats?.total_tokens ?? runs.reduce((acc, r) => acc + (r.tokens_spent || 0), 0)).toLocaleString()}
            </div>
          </div>
        </div>
      </div>

      {/* 2. Active Run Progress / Cold Start Banner (Visibly Running State) */}
      {(activeRun?.status === 'running' || triggering) && (
        <div className="p-4 rounded-2xl bg-amber-950/20 border border-amber-500/40 text-amber-200 flex items-center gap-3">
          <Loader2 className="w-5 h-5 animate-spin text-amber-400 shrink-0" />
          <div className="text-xs space-y-0.5">
            <div className="font-bold text-amber-300">
              Run #{activeRun?.run_number || '1'} Orchestration In Progress
            </div>
            <div className="text-amber-200/80">
              Worker services are executing over HTTP (handling cold start & attempt deadlines). Polling persisted run state every 2 seconds...
            </div>
          </div>
        </div>
      )}

      {/* 3. Stale Baseline Fallback Banner */}
      {activeRun?.stale_source_run_uuid && (
        <div className="p-4 rounded-2xl bg-sky-950/30 border border-sky-500/40 text-sky-200 flex items-start gap-3">
          <Info className="w-5 h-5 text-sky-400 shrink-0 mt-0.5" />
          <div className="text-xs space-y-1">
            <div className="font-bold text-sky-300 flex items-center gap-2 flex-wrap">
              <span>[STALE BASELINE FALLBACK]</span>
              <span className="font-mono text-[11px] text-sky-400 font-normal">
                Origin Run UUID: {activeRun.stale_source_run_uuid}
              </span>
              {activeRun.stale_source_created_at && (
                <span className="text-[11px] text-slate-400 font-normal">
                  • Baseline Created: {new Date(activeRun.stale_source_created_at).toLocaleString()}
                </span>
              )}
            </div>
            <p className="text-slate-300 leading-relaxed">
              Researcher encountered budget or connectivity limits. Displaying latest valid baseline jobs for this user/topic/K scope. Historical verdicts and claim citations are preserved from the original run.
            </p>
          </div>
        </div>
      )}

      {/* 4. Worker Failure Attribution on Partial Runs */}
      {activeRun?.status === 'partial' && (
        <div className="p-4 rounded-2xl bg-rose-950/20 border border-rose-500/30 text-rose-200 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div className="text-xs space-y-1">
            <div className="font-bold text-rose-300">
              Partial Execution Summary (Worker Failure Attribution)
            </div>
            <div className="text-slate-300 space-y-0.5">
              {activeRun.researcher_status !== 'complete' && (
                <div>
                  <span className="font-semibold text-rose-400">Researcher: </span>
                  <span className="font-mono text-xs">{activeRun.researcher_status || 'unknown'}</span>
                  {activeRun.researcher_error && <span> — {activeRun.researcher_error}</span>}
                </div>
              )}
              {activeRun.verifier_status !== 'complete' && (
                <div>
                  <span className="font-semibold text-amber-400">Verifier: </span>
                  <span className="font-mono text-xs">{activeRun.verifier_status || 'unknown'}</span>
                  {activeRun.verifier_error && <span> — {activeRun.verifier_error}</span>}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 5. API Error State (Task 6.4) */}
      {apiError && runs.length === 0 && (
        <div className="rounded-3xl bg-slate-900 border border-rose-500/30 p-8 text-center space-y-4">
          <AlertTriangle className="w-12 h-12 text-rose-400 mx-auto" />
          <div className="space-y-1">
            <h3 className="text-lg font-bold text-white">Unable to Load Tracker History</h3>
            <p className="text-xs text-slate-400 max-w-md mx-auto">{apiError}</p>
          </div>
          <button
            onClick={fetchTrackerData}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold border border-slate-700 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Retry Connection</span>
          </button>
        </div>
      )}

      {/* 6. Honest Empty Database State (Task 6.4) */}
      {!loading && !apiError && runs.length === 0 && (
        <div className="rounded-3xl bg-slate-900 border border-slate-800 p-12 text-center space-y-4">
          <Bot className="w-12 h-12 text-slate-500 mx-auto" />
          <div className="space-y-1">
            <h3 className="text-lg font-bold text-white">No Research Runs Found</h3>
            <p className="text-xs text-slate-400 max-w-md mx-auto">
              The database currently contains no tracker runs. Click &quot;Run Tracker Now&quot; to admit and orchestrate your first autonomous research run.
            </p>
          </div>
          <button
            onClick={handleTriggerRun}
            disabled={triggering}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition-all"
          >
            <Play className="w-4 h-4 fill-white" />
            <span>Start Initial Run</span>
          </button>
        </div>
      )}

      {/* 7. Loading State */}
      {loading && runs.length === 0 && (
        <div className="rounded-3xl bg-slate-900 border border-slate-800 p-12 text-center space-y-3">
          <Loader2 className="w-8 h-8 animate-spin text-emerald-400 mx-auto" />
          <p className="text-xs text-slate-400">Loading research runs from backend...</p>
        </div>
      )}

      {/* 8. Run History Selector Timeline */}
      {runs.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-bold text-white">
              <History className="w-4 h-4 text-emerald-400" />
              <span>Execution Run History</span>
            </div>
            <span className="text-xs text-slate-400">Select run to view Top K discoveries & verified claims</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {runs.map((run) => {
              const isSelected = run.id === activeRun?.id;
              const isComplete = run.status === 'complete';
              const isRunning = run.status === 'running';

              return (
                <button
                  key={run.id}
                  onClick={() => setSelectedRunId(run.id)}
                  className={`text-left p-3.5 rounded-2xl border transition-all ${
                    isSelected
                      ? 'bg-emerald-950/20 border-emerald-500/50 shadow-lg shadow-emerald-950/30'
                      : 'bg-slate-900/60 hover:bg-slate-800/80 border-slate-800 text-slate-400'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-md ${
                      isSelected ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-300'
                    }`}>
                      RUN {run.run_number}
                    </span>
                    <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${
                      isComplete 
                        ? 'text-emerald-400 bg-emerald-500/10' 
                        : isRunning
                        ? 'text-amber-400 bg-amber-500/10 animate-pulse'
                        : 'text-rose-400 bg-rose-500/10'
                    }`}>
                      {run.status}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-400 space-y-1">
                    <div className="flex justify-between">
                      <span>Researcher:</span>
                      <span className="font-semibold text-slate-200">{run.researcher_status || run.status}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Verifier:</span>
                      <span className="font-semibold text-slate-200">{run.verifier_status || 'n/a'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Steps / Fetches:</span>
                      <span className="font-semibold text-slate-200">{run.step_count || 0} / {run.fetch_count || 0}</span>
                    </div>
                  </div>
                  <div className="mt-2 pt-2 border-t border-slate-800/80 text-[10px] text-slate-500 flex items-center justify-between">
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3 h-3 text-slate-500" />
                      {run.created_at ? new Date(run.created_at).toLocaleDateString() : 'Active'}
                    </span>
                    {run.stale_source_run_uuid && (
                      <span className="text-[9px] font-bold text-sky-400 uppercase">Stale</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* 9. Top 10 Job Cards Section with Verified Claims */}
      {runs.length > 0 && activeRun && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2.5">
              <Layers className="w-5 h-5 text-emerald-400" />
              <h2 className="text-lg font-bold text-white">
                Synthesized Top 10 Job Openings (Run {activeRun?.run_number})
              </h2>
              <span className="px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 text-xs font-medium">
                Target K = {activeRun?.target_k || 10}
              </span>
            </div>
            <div className="text-xs text-slate-400">
              Showing {activeRun?.developments?.length || 0} canonical opportunities (Rankings unchanged)
            </div>
          </div>

          {/* Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[...(activeRun?.developments || [])]
              .sort((a, b) => (a.rank || 0) - (b.rank || 0))
              .map((job, idx) => (
              <div
                key={job.id || idx}
                className="group relative rounded-2xl bg-slate-900 border border-slate-800/90 hover:border-slate-700/80 p-5 transition-all shadow-md hover:shadow-xl flex flex-col justify-between space-y-4"
              >
                <div className="space-y-3">
                  {/* Header: Rank + Differential Status Badge */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="w-6 h-6 rounded-lg bg-slate-800 text-slate-200 text-xs font-black flex items-center justify-center">
                        #{job.rank ?? (idx + 1)}
                      </span>
                      <div className="flex items-center gap-1.5 text-xs font-bold text-slate-300">
                        <Building2 className="w-3.5 h-3.5 text-slate-400" />
                        {/* Zero-Trust: Plain text node rendering */}
                        <span>{job.company}</span>
                      </div>
                    </div>
                    {renderStatusBadge(job.recrawl_status)}
                  </div>

                  {/* Role Title (Zero-Trust: Pure Plain Text Node, neutralizing Stored-XSS) */}
                  <h3 className="text-base font-extrabold text-white group-hover:text-emerald-400 transition-colors leading-snug">
                    {job.title}
                  </h3>

                  {/* Metadata Pills: Location & Compensation */}
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    {job.location && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-800/80 text-slate-300 border border-slate-700/60">
                        <MapPin className="w-3 h-3 text-slate-400" />
                        <span>{job.location}</span>
                      </span>
                    )}
                    {job.compensation && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-800/80 text-slate-300 border border-slate-700/60 font-medium">
                        <DollarSign className="w-3 h-3 text-emerald-400" />
                        <span>{job.compensation}</span>
                      </span>
                    )}
                  </div>

                  {/* Summary / Qualifications Snippet */}
                  <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">
                    {job.qualifications_summary || job.snippet || "No qualifications snippet available."}
                  </p>

                  {/* Verified Atomic Claims Section (Task 6.3) */}
                  {job.claims && job.claims.length > 0 && (
                    <div className="pt-2 border-t border-slate-800/60 space-y-2">
                      <div className="text-[11px] font-bold text-slate-300 flex items-center justify-between">
                        <span>Audited Claims ({job.claims.length}):</span>
                      </div>
                      <div className="space-y-2">
                        {job.claims.map((claim, cIdx) => {
                          const isSupported = (claim.verdict || '').toLowerCase() === 'supported';
                          return (
                            <div
                              key={claim.claim_id || cIdx}
                              className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800 text-xs space-y-1.5"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-mono text-[10px] text-slate-400">
                                  {claim.claim_id || `C-${cIdx + 1}`}
                                </span>
                                {renderClaimVerdictBadge(claim.verdict)}
                              </div>
                              {/* Claim text rendered strictly as plain text */}
                              <div className="text-slate-200 font-medium text-[11px] leading-snug">
                                {claim.text}
                              </div>
                              {/* Supported evidence excerpt ONLY for supported claims (Task 6.3) */}
                              {isSupported && claim.evidence && (
                                <div className="p-2 rounded bg-slate-900 border border-emerald-500/20 text-[11px] text-emerald-300 font-mono leading-relaxed">
                                  <span className="text-slate-400 font-sans font-semibold">Evidence: </span>
                                  &quot;{claim.evidence}&quot;
                                </div>
                              )}
                              {/* Source link strictly validated for safe HTTP(S) protocols */}
                              {claim.source_url && (
                                <div className="pt-1 text-[10px]">
                                  {isSafeUrl(claim.source_url) ? (
                                    <a
                                      href={claim.source_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="inline-flex items-center gap-1 text-slate-400 hover:text-emerald-400 transition-colors truncate max-w-full"
                                    >
                                      <ExternalLink className="w-3 h-3 shrink-0" />
                                      <span className="truncate">{claim.source_url}</span>
                                    </a>
                                  ) : (
                                    <span className="text-slate-500 font-mono truncate max-w-full">
                                      {claim.source_url}
                                    </span>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>

                {/* Provenance & Primary Source Citation Footer */}
                <div className="pt-3 border-t border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  {isSafeUrl(job.primary_url || job.url) ? (
                    <a
                      href={job.primary_url || job.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-400 hover:text-emerald-300 transition-colors"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      <span>Verify Primary ATS Posting</span>
                    </a>
                  ) : (
                    <span className="text-xs text-slate-500 font-mono">
                      {job.primary_url || job.url || "No source URL"}
                    </span>
                  )}

                  {/* Supporting Source Badges */}
                  {job.supporting_sources && job.supporting_sources.length > 0 && (
                    <div className="flex items-center gap-1 text-[11px] text-slate-400">
                      <Globe className="w-3 h-3 text-slate-500" />
                      <span>{job.supporting_sources.length} supporting citations</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 10. Network Fetch Audit Log Table */}
      {runs.length > 0 && activeRun && (
        <div className="rounded-2xl bg-slate-900 border border-slate-800 p-5 space-y-4 shadow-lg">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FileCheck2 className="w-4 h-4 text-emerald-400" />
              <h3 className="text-sm font-bold text-white">Network Fetch Audit Log</h3>
              <span className="text-xs text-slate-400">(Hop-by-hop SSRF Guardrail validation & byte limits)</span>
            </div>
            <span className="text-xs text-slate-400">
              {activeRun?.articles?.length || 0} requests recorded in Run {activeRun?.run_number}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="pb-2.5 font-semibold">Article Title</th>
                  <th className="pb-2.5 font-semibold">Target URL</th>
                  <th className="pb-2.5 font-semibold">Worker</th>
                  <th className="pb-2.5 font-semibold">SSRF Guardrail Status</th>
                  <th className="pb-2.5 font-semibold">Payload Size</th>
                  <th className="pb-2.5 font-semibold">Latency</th>
                  <th className="pb-2.5 font-semibold">Security Audit Log</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {(activeRun?.articles || []).map((art, i) => {
                  const isRejected = art.status === 'rejected';
                  const isSkipped = art.status === 'skipped as already seen';
                  return (
                    <tr key={art.id || i} className="hover:bg-slate-800/30 transition-colors">
                      <td className="py-2.5 pr-3 max-w-xs truncate font-medium text-white" title={art.title || 'Untitled Source'}>
                        {art.title || <span className="text-slate-500 italic">Untitled Source</span>}
                      </td>
                      <td className="py-2.5 pr-3 max-w-xs truncate font-mono text-[11px] text-slate-300" title={art.url}>
                        {isSafeUrl(art.url) ? (
                          <a href={art.url} target="_blank" rel="noopener noreferrer" className="hover:text-emerald-400 hover:underline">
                            {art.url}
                          </a>
                        ) : (
                          art.url
                        )}
                      </td>
                      <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-400">
                        {art.worker || 'researcher'}
                      </td>
                      <td className="py-2.5 pr-3">
                        {isRejected ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                            <ShieldAlert className="w-3 h-3 text-rose-400" />
                            [SSRF BLOCKED]
                          </span>
                        ) : isSkipped ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-sky-500/10 text-sky-400 border border-sky-500/20">
                            <Clock className="w-3 h-3 text-sky-400" />
                            [SKIPPED - CACHED]
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            <ShieldCheck className="w-3 h-3 text-emerald-400" />
                            [SAFE FETCHED]
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-400">
                        {art.byte_size ? `${(art.byte_size / 1024).toFixed(1)} KB` : '0 KB'}
                      </td>
                      <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-400">
                        {art.fetch_time_ms ? `${art.fetch_time_ms} ms` : '< 1 ms'}
                      </td>
                      <td className="py-2.5 text-slate-400">
                        {isSkipped ? (
                          <span className="text-sky-400 font-mono text-[11px]">
                            {art.error_message || "URL seen in previous run • 0 network I/O"}
                          </span>
                        ) : art.error_message ? (
                          <span className="text-rose-400 font-mono text-[11px]">{art.error_message}</span>
                        ) : (
                          <span className="text-slate-500">DNS pre-resolution passed • HTML extracted</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
