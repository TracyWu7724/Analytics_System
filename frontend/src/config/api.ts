// API Configuration
export const API_CONFIG = {
  // Change this to your FastAPI server URL
  BASE_URL: process.env.REACT_APP_API_URL || 'http://localhost:8000',
  
  // Request timeout in milliseconds
  TIMEOUT: 300000, // 5 minutes for AI-powered queries
  QUICK_TIMEOUT: 10000, // 10 seconds for simple operations
  
  // Default headers
  HEADERS: {
    'Content-Type': 'application/json',
  },
  
  // Enable/disable API logging
  DEBUG: process.env.NODE_ENV === 'development',
};

// Helper function to get full API URL
export const getApiUrl = (endpoint: string): string => {
  return `${API_CONFIG.BASE_URL}${endpoint}`;
}; 
