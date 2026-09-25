// =============================================================
// API Service Client: Handles all network HTTP communication
// with the FastAPI backend running on http://localhost:8000
// =============================================================

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/**
 * Universal HTTP request wrapper.
 * Automatically injects the Authorization: Bearer <token> header,
 * handles JSON encoding/decoding, and catches 401 Unauthorized errors.
 */
async function apiRequest(endpoint, options = {}) {
  const token = localStorage.getItem('access_token');
  
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  // Inject Bearer token if user is authenticated
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const config = {
    ...options,
    headers,
  };

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);

    // Parse JSON payload if present
    let data = null;
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      data = await response.json();
    }

    // Handle error status codes
    if (!response.ok) {
      const errorMessage = data?.detail || `HTTP Error ${response.status}: ${response.statusText}`;
      
      // If server returned 401 (Rule 2), token is missing, expired, or invalid
      if (response.status === 401) {
        localStorage.removeItem('access_token');
      }

      const error = new Error(errorMessage);
      error.status = response.status;
      error.data = data;
      throw error;
    }

    return data;
  } catch (err) {
    // Re-throw with status if network was unreachable
    if (!err.status) {
      err.status = 0;
      err.message = 'Unable to reach backend server. Please verify backend is running on port 8000.';
    }
    throw err;
  }
}

// -------------------------------------------------------------
// Exposed API Endpoints
// -------------------------------------------------------------

export const api = {
  // Public Healthcheck
  getHealth: () => apiRequest('/healthz', { method: 'GET' }),

  // Authentication
  register: (payload) => 
    apiRequest('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  login: (payload) => 
    apiRequest('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getMe: () => 
    apiRequest('/api/auth/me', { method: 'GET' }),

  // User Management
  getUser: (id) => 
    apiRequest(`/api/users/${id}`, { method: 'GET' }),

  updateUser: (id, payload) => 
    apiRequest(`/api/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  deleteUser: (id) => 
    apiRequest(`/api/users/${id}`, { method: 'DELETE' }),
};
