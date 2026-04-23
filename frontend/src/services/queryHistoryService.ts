export interface RecentQuery {
  id: string;
  query: string;
  timestamp: Date;
  executionCount: number;
  lastExecuted: Date;
  favorite?: boolean;
}

export interface QueryHistorySettings {
  maxRecentQueries: number;
  enableAutoSave: boolean;
  enableFavorites: boolean;
}

class QueryHistoryService {
  private readonly STORAGE_KEY = 'query_history';
  private readonly SETTINGS_KEY = 'query_history_settings';
  private readonly DEFAULT_SETTINGS: QueryHistorySettings = {
    maxRecentQueries: 20,
    enableAutoSave: true,
    enableFavorites: true,
  };

  private cache: RecentQuery[] | null = null;
  private settings: QueryHistorySettings;

  constructor() {
    this.settings = this.loadSettings();
  }

  /**
   * Add a new query to recent history
   */
  addQuery(query: string): RecentQuery {
    if (!this.settings.enableAutoSave || !query.trim()) {
      throw new Error('Auto-save disabled or empty query');
    }

    const queries = this.getRecentQueries();
    const normalizedQuery = query.trim().toLowerCase();
    
    // Check if query already exists
    const existingQueryIndex = queries.findIndex(
      q => q.query.toLowerCase() === normalizedQuery
    );

    let updatedQuery: RecentQuery;

    if (existingQueryIndex >= 0) {
      // Update existing query
      updatedQuery = {
        ...queries[existingQueryIndex],
        query: query.trim(), // Keep original casing
        executionCount: queries[existingQueryIndex].executionCount + 1,
        lastExecuted: new Date(),
      };
      
      // Remove from current position and add to beginning
      queries.splice(existingQueryIndex, 1);
      queries.unshift(updatedQuery);
    } else {
      // Create new query
      updatedQuery = {
        id: this.generateId(),
        query: query.trim(),
        timestamp: new Date(),
        executionCount: 1,
        lastExecuted: new Date(),
        favorite: false,
      };
      
      // Add to beginning
      queries.unshift(updatedQuery);
    }

    // Trim to max size
    if (queries.length > this.settings.maxRecentQueries) {
      queries.splice(this.settings.maxRecentQueries);
    }

    this.saveQueries(queries);
    return updatedQuery;
  }

  /**
   * Get all recent queries sorted by most recent
   */
  getRecentQueries(): RecentQuery[] {
    if (this.cache === null) {
      this.cache = this.loadQueries();
    }
    return [...this.cache];
  }

  /**
   * Get frequent queries sorted by execution count
   */
  getFrequentQueries(limit: number = 10): RecentQuery[] {
    return this.getRecentQueries()
      .filter(q => q.executionCount > 1)
      .sort((a, b) => b.executionCount - a.executionCount)
      .slice(0, limit);
  }

  /**
   * Get favorite queries
   */
  getFavoriteQueries(): RecentQuery[] {
    if (!this.settings.enableFavorites) return [];
    
    return this.getRecentQueries()
      .filter(q => q.favorite)
      .sort((a, b) => b.lastExecuted.getTime() - a.lastExecuted.getTime());
  }

  /**
   * Search queries by text
   */
  searchQueries(searchTerm: string, limit: number = 10): RecentQuery[] {
    if (!searchTerm.trim()) return [];
    
    const term = searchTerm.toLowerCase();
    return this.getRecentQueries()
      .filter(q => q.query.toLowerCase().includes(term))
      .slice(0, limit);
  }

  /**
   * Toggle favorite status of a query
   */
  toggleFavorite(queryId: string): boolean {
    if (!this.settings.enableFavorites) return false;
    
    const queries = this.getRecentQueries();
    const queryIndex = queries.findIndex(q => q.id === queryId);
    
    if (queryIndex >= 0) {
      queries[queryIndex].favorite = !queries[queryIndex].favorite;
      this.saveQueries(queries);
      return queries[queryIndex].favorite!;
    }
    
    return false;
  }

  /**
   * Remove a specific query from history
   */
  removeQuery(queryId: string): boolean {
    const queries = this.getRecentQueries();
    const queryIndex = queries.findIndex(q => q.id === queryId);
    
    if (queryIndex >= 0) {
      queries.splice(queryIndex, 1);
      this.saveQueries(queries);
      return true;
    }
    
    return false;
  }

  /**
   * Clear all query history
   */
  clearHistory(): void {
    this.cache = [];
    localStorage.removeItem(this.STORAGE_KEY);
  }

  /**
   * Clear only non-favorite queries
   */
  clearNonFavorites(): void {
    if (!this.settings.enableFavorites) {
      this.clearHistory();
      return;
    }
    
    const favorites = this.getFavoriteQueries();
    this.saveQueries(favorites);
  }

  /**
   * Get query by ID
   */
  getQueryById(queryId: string): RecentQuery | null {
    return this.getRecentQueries().find(q => q.id === queryId) || null;
  }

  /**
   * Update settings
   */
  updateSettings(newSettings: Partial<QueryHistorySettings>): void {
    this.settings = { ...this.settings, ...newSettings };
    localStorage.setItem(this.SETTINGS_KEY, JSON.stringify(this.settings));
    
    // Apply max query limit if changed
    if (newSettings.maxRecentQueries !== undefined) {
      const queries = this.getRecentQueries();
      if (queries.length > newSettings.maxRecentQueries) {
        const trimmedQueries = queries.slice(0, newSettings.maxRecentQueries);
        this.saveQueries(trimmedQueries);
      }
    }
  }

  /**
   * Get current settings
   */
  getSettings(): QueryHistorySettings {
    return { ...this.settings };
  }

  /**
   * Export query history as JSON
   */
  exportHistory(): string {
    return JSON.stringify({
      queries: this.getRecentQueries(),
      settings: this.settings,
      exportDate: new Date().toISOString(),
    }, null, 2);
  }

  /**
   * Import query history from JSON
   */
  importHistory(jsonData: string): boolean {
    try {
      const data = JSON.parse(jsonData);
      
      if (data.queries && Array.isArray(data.queries)) {
        // Validate and convert date strings back to Date objects
        const queries: RecentQuery[] = data.queries.map((q: any) => ({
          ...q,
          timestamp: new Date(q.timestamp),
          lastExecuted: new Date(q.lastExecuted),
        }));
        
        this.saveQueries(queries);
        
        if (data.settings) {
          this.updateSettings(data.settings);
        }
        
        return true;
      }
    } catch (error) {
      console.error('Failed to import query history:', error);
    }
    
    return false;
  }

  private loadQueries(): RecentQuery[] {
    try {
      const stored = localStorage.getItem(this.STORAGE_KEY);
      if (stored) {
        const queries = JSON.parse(stored);
        // Convert date strings back to Date objects
        return queries.map((q: any) => ({
          ...q,
          timestamp: new Date(q.timestamp),
          lastExecuted: new Date(q.lastExecuted),
        }));
      }
    } catch (error) {
      console.error('Failed to load query history:', error);
    }
    
    return [];
  }

  private saveQueries(queries: RecentQuery[]): void {
    try {
      this.cache = queries;
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(queries));
    } catch (error) {
      console.error('Failed to save query history:', error);
    }
  }

  private loadSettings(): QueryHistorySettings {
    try {
      const stored = localStorage.getItem(this.SETTINGS_KEY);
      if (stored) {
        return { ...this.DEFAULT_SETTINGS, ...JSON.parse(stored) };
      }
    } catch (error) {
      console.error('Failed to load query history settings:', error);
    }
    
    return { ...this.DEFAULT_SETTINGS };
  }

  private generateId(): string {
    return `query_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
  }
}

// Export singleton instance
export const queryHistoryService = new QueryHistoryService(); 
