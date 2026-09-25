import React, { useState } from 'react';
import { 
  User, 
  Mail, 
  KeyRound, 
  Trash2, 
  AlertTriangle, 
  CheckCircle2, 
  AlertCircle, 
  Loader2, 
  ShieldAlert
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function AccountView() {
  const { user, updateProfile, deleteAccount } = useAuth();

  // State for email update
  const [email, setEmail] = useState(user?.email || '');
  const [emailLoading, setEmailLoading] = useState(false);
  const [emailSuccess, setEmailSuccess] = useState('');
  const [emailError, setEmailError] = useState('');

  // State for password update
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordSuccess, setPasswordSuccess] = useState('');
  const [passwordError, setPasswordError] = useState('');

  // State for account deletion modal
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [confirmDeleteUsername, setConfirmDeleteUsername] = useState('');
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  // 1. Handle Update Email (PATCH /api/users/:id)
  const handleUpdateEmail = async (e) => {
    e.preventDefault();
    setEmailSuccess('');
    setEmailError('');

    if (email === user?.email) {
      setEmailError('New email is identical to current email.');
      return;
    }

    setEmailLoading(true);
    try {
      await updateProfile({ email });
      setEmailSuccess('Email address updated successfully!');
    } catch (err) {
      setEmailError(err.message || 'Failed to update email.');
    } finally {
      setEmailLoading(false);
    }
  };

  // 2. Handle Change Password (PATCH /api/users/:id)
  const handleChangePassword = async (e) => {
    e.preventDefault();
    setPasswordSuccess('');
    setPasswordError('');

    if (newPassword.length < 6) {
      setPasswordError('New password must be at least 6 characters.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setPasswordError('Passwords do not match.');
      return;
    }

    setPasswordLoading(true);
    try {
      await updateProfile({ password: newPassword });
      setPasswordSuccess('Password changed successfully!');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      setPasswordError(err.message || 'Failed to update password.');
    } finally {
      setPasswordLoading(false);
    }
  };

  // 3. Handle Delete Account (DELETE /api/users/:id)
  const handleDeleteAccount = async () => {
    if (confirmDeleteUsername !== user?.username) {
      setDeleteError(`Please type "${user?.username}" to confirm deletion.`);
      return;
    }

    setDeleteLoading(true);
    setDeleteError('');
    try {
      await deleteAccount();
      // AuthContext will automatically redirect to unauthenticated view
    } catch (err) {
      setDeleteError(err.message || 'Failed to delete account.');
      setDeleteLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-white tracking-tight">Account Management</h1>
        <p className="mt-1 text-sm text-slate-400">
          Manage your credentials, profile details, and account lifecycle
        </p>
      </div>

      <div className="space-y-6">
        {/* Section 1: Update Email */}
        <div className="p-6 sm:p-8 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center">
              <Mail className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">Email Address</h2>
              <p className="text-xs text-slate-400">Update the primary email linked to your account</p>
            </div>
          </div>

          {emailSuccess && (
            <div className="mb-4 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center gap-2 text-xs text-emerald-300">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>{emailSuccess}</span>
            </div>
          )}

          {emailError && (
            <div className="mb-4 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center gap-2 text-xs text-rose-300">
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{emailError}</span>
            </div>
          )}

          <form onSubmit={handleUpdateEmail} className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-slate-950/80 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-colors"
              />
            </div>
            <button
              type="submit"
              disabled={emailLoading}
              className="px-5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-white transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {emailLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Save Email'}
            </button>
          </form>
        </div>

        {/* Section 2: Change Password */}
        <div className="p-6 sm:p-8 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center">
              <KeyRound className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">Change Password</h2>
              <p className="text-xs text-slate-400">Encrypt and update your login password (bcrypt 12 rounds)</p>
            </div>
          </div>

          {passwordSuccess && (
            <div className="mb-4 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center gap-2 text-xs text-emerald-300">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>{passwordSuccess}</span>
            </div>
          )}

          {passwordError && (
            <div className="mb-4 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center gap-2 text-xs text-rose-300">
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{passwordError}</span>
            </div>
          )}

          <form onSubmit={handleChangePassword} className="space-y-3.5 max-w-md">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">New Password (min 6 characters)</label>
              <input
                type="password"
                required
                minLength={6}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full px-3.5 py-2 bg-slate-950/80 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-colors"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Confirm New Password</label>
              <input
                type="password"
                required
                minLength={6}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full px-3.5 py-2 bg-slate-950/80 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={passwordLoading}
              className="px-5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-white transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {passwordLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Update Password'}
            </button>
          </form>
        </div>

        {/* Section 3: Danger Zone - Delete Account */}
        <div className="p-6 sm:p-8 rounded-2xl bg-rose-950/10 border border-rose-900/30 shadow-xl">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-xl bg-rose-500/10 text-rose-400 flex items-center justify-center">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-rose-300">Danger Zone</h2>
              <p className="text-xs text-rose-400/80">Permanent, irreversible account actions</p>
            </div>
          </div>

          <p className="text-xs text-slate-400 mb-5 leading-relaxed">
            Deleting your account will permanently purge your user profile, credentials, and associated data from the database. Active tokens will be immediately invalidated.
          </p>

          <button
            type="button"
            onClick={() => setShowDeleteModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-rose-600/20 hover:bg-rose-600 text-rose-300 hover:text-white border border-rose-500/30 text-xs font-semibold transition-all shadow-sm"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Delete Account
          </button>
        </div>
      </div>

      {/* Confirmation Modal for Deletion */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="w-full max-w-md p-6 bg-slate-900 border border-rose-500/30 rounded-2xl shadow-2xl">
            <div className="flex items-center gap-3 mb-4 text-rose-400">
              <AlertTriangle className="w-6 h-6" />
              <h3 className="text-lg font-bold text-white">Confirm Account Deletion</h3>
            </div>

            <p className="text-xs text-slate-300 mb-4 leading-relaxed">
              This action cannot be undone. To confirm, please type your username <strong className="text-white font-mono bg-slate-800 px-1.5 py-0.5 rounded">{user?.username}</strong> below:
            </p>

            {deleteError && (
              <div className="mb-4 p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-400">
                {deleteError}
              </div>
            )}

            <input
              type="text"
              value={confirmDeleteUsername}
              onChange={(e) => setConfirmDeleteUsername(e.target.value)}
              placeholder={user?.username}
              className="w-full px-3.5 py-2 mb-5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-600 focus:outline-none focus:border-rose-500 transition-colors"
            />

            <div className="flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => {
                  setShowDeleteModal(false);
                  setConfirmDeleteUsername('');
                  setDeleteError('');
                }}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleteLoading || confirmDeleteUsername !== user?.username}
                onClick={handleDeleteAccount}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-xs font-semibold text-white transition-colors"
              >
                {deleteLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Confirm Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
