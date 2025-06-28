/**
 * Job Completion Cache Module
 * 
 * Advanced caching system for job completion messages with features matching hybrid-tts.js:
 * - Dual cache: In-memory Map + IndexedDB persistence
 * - SHA-256 hash-based keys for consistency
 * - LRU eviction with configurable size limits
 * - Analytics tracking and popular phrase monitoring
 * - Automatic cache expiration
 * 
 * Usage:
 *   const cache = new JobCompletionCache();
 *   await cache.initialize();
 *   await cache.store(jobId, text, timestamp);
 *   const message = await cache.get(jobId);
 */

class JobCompletionCache {
    constructor(options = {}) {
        // Configuration options
        this.cacheEnabled = options.cacheEnabled !== false; // Default true
        this.cacheMaxSize = options.cacheMaxSize || 10 * 1024 * 1024; // 10MB default for text
        this.cacheMaxAge = options.cacheMaxAge || 30 * 24 * 60 * 60 * 1000; // 30 days
        this.maxEntries = options.maxEntries || 1000; // Maximum number of job entries
        
        // In-memory cache
        this.messageCache = new Map();
        
        // IndexedDB setup
        this.dbName = 'JobCompletionCache';
        this.dbVersion = 1;
        this.db = null;
        
        // Analytics
        this.analytics = {
            totalStores: 0,
            totalRetrieves: 0,
            cacheHits: 0,
            cacheMisses: 0,
            totalCacheSize: 0,
            popularPhrases: new Map(), // Track frequency of phrases
            topJobs: new Map() // Track most replayed jobs
        };
        
        // Initialize IndexedDB if caching is enabled
        if (this.cacheEnabled) {
            this.initializeIndexedDB().catch(err => {
                console.warn('JobCompletionCache: IndexedDB initialization failed, using memory cache only:', err);
            });
        }
    }
    
    async generateCacheKey(text) {
        // Use SHA-256 hash for consistent cache keys
        const encoder = new TextEncoder();
        const data = encoder.encode(text);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }
    
    async initializeIndexedDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.dbVersion);
            
            request.onerror = () => reject(request.error);
            request.onsuccess = () => {
                this.db = request.result;
                console.log('JobCompletionCache: IndexedDB initialized');
                resolve();
            };
            
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains('jobMessages')) {
                    const store = db.createObjectStore('jobMessages', { keyPath: 'jobId' });
                    store.createIndex('timestamp', 'timestamp', { unique: false });
                    store.createIndex('textHash', 'textHash', { unique: false });
                    store.createIndex('userId', 'userId', { unique: false });
                }
            };
        });
    }
    
    async store(jobId, text, timestamp = null, userId = null, metadata = {}) {
        if (!this.cacheEnabled) return;
        
        const ts = timestamp || new Date().toISOString();
        const textHash = await this.generateCacheKey(text);
        
        const cacheEntry = {
            jobId,
            text,
            textHash,
            timestamp: ts,
            timestampMs: Date.now(),
            userId,
            size: new Blob([text]).size,
            replayCount: 0,
            lastReplayed: null,
            metadata
        };
        
        // Update analytics
        this.analytics.totalStores++;
        this.analytics.totalCacheSize += cacheEntry.size;
        this.updatePhraseFrequency(text);
        
        // Save to in-memory cache
        this.messageCache.set(jobId, cacheEntry);
        
        // Save to IndexedDB
        if (this.db) {
            await this.saveToIndexedDB(cacheEntry);
        }
        
        // Manage cache size
        await this.evictOldEntries();
        
        console.log(`JobCompletionCache: Stored job ${jobId} (${cacheEntry.size} bytes)`);
    }
    
    async get(jobId) {
        if (!this.cacheEnabled) return null;
        
        this.analytics.totalRetrieves++;
        
        // Check in-memory cache first
        if (this.messageCache.has(jobId)) {
            const cached = this.messageCache.get(jobId);
            if (!this.isCacheExpired(cached)) {
                this.analytics.cacheHits++;
                
                // Update replay statistics
                cached.replayCount++;
                cached.lastReplayed = new Date().toISOString();
                this.analytics.topJobs.set(jobId, cached.replayCount);
                
                return cached;
            } else {
                // Remove expired entry
                this.messageCache.delete(jobId);
                this.analytics.totalCacheSize -= cached.size;
            }
        }
        
        // Check IndexedDB
        if (this.db) {
            const cached = await this.getFromIndexedDB(jobId);
            if (cached && !this.isCacheExpired(cached)) {
                // Add back to in-memory cache
                this.messageCache.set(jobId, cached);
                this.analytics.cacheHits++;
                
                // Update replay statistics
                cached.replayCount++;
                cached.lastReplayed = new Date().toISOString();
                this.analytics.topJobs.set(jobId, cached.replayCount);
                
                return cached;
            }
        }
        
        this.analytics.cacheMisses++;
        return null;
    }
    
    async getByText(text) {
        if (!this.cacheEnabled) return null;
        
        const textHash = await this.generateCacheKey(text);
        
        // Search in-memory cache
        for (const [jobId, entry] of this.messageCache) {
            if (entry.textHash === textHash && !this.isCacheExpired(entry)) {
                return entry;
            }
        }
        
        // Search IndexedDB by textHash index
        if (this.db) {
            const transaction = this.db.transaction(['jobMessages'], 'readonly');
            const store = transaction.objectStore('jobMessages');
            const index = store.index('textHash');
            
            return new Promise((resolve) => {
                const request = index.get(textHash);
                request.onsuccess = () => {
                    const result = request.result;
                    if (result && !this.isCacheExpired(result)) {
                        // Add back to in-memory cache
                        this.messageCache.set(result.jobId, result);
                        resolve(result);
                    } else {
                        resolve(null);
                    }
                };
                request.onerror = () => resolve(null);
            });
        }
        
        return null;
    }
    
    async delete(jobId) {
        const entry = this.messageCache.get(jobId);
        if (entry) {
            this.messageCache.delete(jobId);
            this.analytics.totalCacheSize -= entry.size;
        }
        
        if (this.db) {
            const transaction = this.db.transaction(['jobMessages'], 'readwrite');
            transaction.objectStore('jobMessages').delete(jobId);
        }
        
        console.log(`JobCompletionCache: Deleted job ${jobId}`);
    }
    
    async getFromIndexedDB(jobId) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['jobMessages'], 'readonly');
            const store = transaction.objectStore('jobMessages');
            const request = store.get(jobId);
            
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }
    
    async saveToIndexedDB(entry) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['jobMessages'], 'readwrite');
            const store = transaction.objectStore('jobMessages');
            const request = store.put(entry);
            
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }
    
    isCacheExpired(entry) {
        return Date.now() - entry.timestampMs > this.cacheMaxAge;
    }
    
    async evictOldEntries() {
        let totalSize = 0;
        const entries = Array.from(this.messageCache.values());
        
        // Sort by timestamp (oldest first)
        entries.sort((a, b) => a.timestampMs - b.timestampMs);
        
        // Calculate total size and remove expired entries
        const validEntries = entries.filter(entry => {
            if (this.isCacheExpired(entry)) {
                this.messageCache.delete(entry.jobId);
                this.analytics.totalCacheSize -= entry.size;
                return false;
            }
            totalSize += entry.size;
            return true;
        });
        
        // Remove oldest entries if over size limit or entry count limit
        while ((totalSize > this.cacheMaxSize || validEntries.length > this.maxEntries) && validEntries.length > 0) {
            const oldest = validEntries.shift();
            this.messageCache.delete(oldest.jobId);
            totalSize -= oldest.size;
            this.analytics.totalCacheSize -= oldest.size;
            
            // Also remove from IndexedDB
            if (this.db) {
                const transaction = this.db.transaction(['jobMessages'], 'readwrite');
                transaction.objectStore('jobMessages').delete(oldest.jobId);
            }
        }
    }
    
    // Analytics Methods
    updatePhraseFrequency(text) {
        // Normalize text for phrase frequency tracking
        const normalizedText = text.toLowerCase().trim();
        const count = this.analytics.popularPhrases.get(normalizedText) || 0;
        this.analytics.popularPhrases.set(normalizedText, count + 1);
    }
    
    getAnalytics() {
        const hitRate = this.analytics.totalRetrieves > 0 
            ? (this.analytics.cacheHits / this.analytics.totalRetrieves * 100).toFixed(2) 
            : 0;
            
        // Get top 10 popular phrases
        const popularPhrases = Array.from(this.analytics.popularPhrases.entries())
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10)
            .map(([phrase, count]) => ({
                phrase: phrase.substring(0, 50) + (phrase.length > 50 ? '...' : ''),
                count
            }));
            
        // Get top 10 most replayed jobs
        const topJobs = Array.from(this.analytics.topJobs.entries())
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10)
            .map(([jobId, replayCount]) => ({
                jobId: jobId.substring(0, 20) + (jobId.length > 20 ? '...' : ''),
                replayCount
            }));
        
        return {
            totalStores: this.analytics.totalStores,
            totalRetrieves: this.analytics.totalRetrieves,
            cacheHits: this.analytics.cacheHits,
            cacheMisses: this.analytics.cacheMisses,
            hitRate: `${hitRate}%`,
            totalCacheSize: `${(this.analytics.totalCacheSize / 1024).toFixed(2)} KB`,
            cacheEntries: this.messageCache.size,
            popularPhrases,
            topJobs
        };
    }
    
    async getAllJobs(userId = null) {
        const jobs = [];
        
        // Get from in-memory cache
        for (const entry of this.messageCache.values()) {
            if (!userId || entry.userId === userId) {
                if (!this.isCacheExpired(entry)) {
                    jobs.push(entry);
                }
            }
        }
        
        // Get from IndexedDB if we need more comprehensive results
        if (this.db && jobs.length < 50) { // Only query DB if we don't have many in memory
            const transaction = this.db.transaction(['jobMessages'], 'readonly');
            const store = transaction.objectStore('jobMessages');
            
            const dbJobs = await new Promise((resolve) => {
                const request = store.getAll();
                request.onsuccess = () => {
                    const results = request.result.filter(entry => {
                        const matchesUser = !userId || entry.userId === userId;
                        const notExpired = !this.isCacheExpired(entry);
                        const notInMemory = !this.messageCache.has(entry.jobId);
                        return matchesUser && notExpired && notInMemory;
                    });
                    resolve(results);
                };
                request.onerror = () => resolve([]);
            });
            
            jobs.push(...dbJobs);
        }
        
        // Sort by timestamp (newest first)
        return jobs.sort((a, b) => b.timestampMs - a.timestampMs);
    }
    
    clearCache() {
        // Clear in-memory cache
        this.messageCache.clear();
        
        // Clear IndexedDB
        if (this.db) {
            const transaction = this.db.transaction(['jobMessages'], 'readwrite');
            transaction.objectStore('jobMessages').clear();
        }
        
        // Reset analytics
        this.analytics.totalCacheSize = 0;
        this.analytics.popularPhrases.clear();
        this.analytics.topJobs.clear();
        
        console.log('JobCompletionCache: Cache cleared');
    }
    
    // Clean up method
    destroy() {
        this.clearCache();
        if (this.db) {
            this.db.close();
        }
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = JobCompletionCache;
}