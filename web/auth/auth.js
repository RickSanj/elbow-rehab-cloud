// Shared authentication utilities

/**
 * Get API base URL from environment or use localhost
 */
function getApiUrl() {
  return (
    localStorage.getItem('apiUrl') || 'http://localhost:8000'
  );
}

/**
 * Set API URL (for switching between environments)
 */
function setApiUrl(url) {
  localStorage.setItem('apiUrl', url);
}

/**
 * Validate email format
 */
function isValidEmail(email) {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

/**
 * Get stored authentication token
 */
function getAuthToken() {
  return localStorage.getItem('token');
}

/**
 * Get stored refresh token
 */
function getRefreshToken() {
  return localStorage.getItem('refreshToken');
}

/**
 * Get stored doctor info
 */
function getDoctorInfo() {
  const doctorData = localStorage.getItem('doctor');
  return doctorData ? JSON.parse(doctorData) : null;
}

/**
 * Check if user is authenticated
 */
function isAuthenticated() {
  return !!getAuthToken();
}

/**
 * Logout user
 */
function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('refreshToken');
  localStorage.removeItem('doctor');
  window.location.href = 'auth/login.html';
}

/**
 * Redirect to login if not authenticated
 */
function requireAuth() {
  if (!isAuthenticated()) {
    window.location.href = '../auth/login.html';
  }
}

/**
 * Make authenticated API request
 */
async function apiCall(endpoint, options = {}) {
  const url = `${getApiUrl()}${endpoint}`;
  const token = getAuthToken();

  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    // Handle 401 (token expired)
    if (response.status === 401) {
      // Try to refresh token
      const refreshed = await refreshAuthToken();
      if (refreshed) {
        // Retry request with new token
        return apiCall(endpoint, options);
      } else {
        // Redirect to login
        logout();
        return null;
      }
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `API error: ${response.status}`);
    }

    return data;
  } catch (error) {
    console.error('API call failed:', error);
    throw error;
  }
}

/**
 * Refresh authentication token
 */
async function refreshAuthToken() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  try {
    const response = await fetch(`${getApiUrl()}/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        refreshToken,
      }),
    });

    if (!response.ok) {
      logout();
      return false;
    }

    const data = await response.json();
    localStorage.setItem('token', data.token);

    return true;
  } catch (error) {
    console.error('Token refresh failed:', error);
    logout();
    return false;
  }
}

/**
 * Format error message for display
 */
function formatErrorMessage(error) {
  if (typeof error === 'string') {
    return error;
  }
  if (error.message) {
    return error.message;
  }
  return 'An error occurred. Please try again.';
}

/**
 * Validate form field
 */
function validateField(fieldId, validator) {
  const field = document.getElementById(fieldId);
  if (!field) return false;

  const isValid = validator(field.value);
  if (isValid) {
    field.classList.remove('error');
  } else {
    field.classList.add('error');
  }
  return isValid;
}

/**
 * Clear form errors
 */
function clearFormErrors(formId) {
  const form = document.getElementById(formId);
  if (form) {
    form.querySelectorAll('.error').forEach((el) => {
      el.classList.remove('error');
    });
  }
}

/**
 * Set up API URL configuration
 */
window.addEventListener('load', () => {
  // You can add logic here to detect environment and set API URL
  // For now, it defaults to localhost:8000

  // Example: Check for environment in URL
  const params = new URLSearchParams(window.location.search);
  const apiUrlParam = params.get('api');
  if (apiUrlParam) {
    setApiUrl(apiUrlParam);
  }
});
