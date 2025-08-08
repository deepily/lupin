/**
 * TTS Audio Cache Module
 * 
 * Lightweight audio caching system extracted from HybridTTS for Fresh Queue UI.
 * Provides persistent audio caching without the complexity of full TTS management.
 * 
 * Features:
 * - SHA-256 text-based cache keys for consistency
 * - Dual cache: In-memory Map + IndexedDB persistence  
 * - Time-based expiration (24 hour default)
 * - Size-based limits (50MB default)
 * - Proper blob URL cleanup to prevent memory leaks
 * - Cross-mode compatibility (works with instant + reliable TTS)
 * 
 * Usage:
 *   const cache = new TTSAudioCache();
 *   await cache.initialize();
 *   
 *   // Before TTS generation
 *   const cached = await cache.checkCache(text);
 *   if (cached) { playAudioBlob(cached); return; }
 *   
 *   // After TTS generation
 *   await cache.saveToCache(text, audioBlob);
 */

class TTSAudioCache {
    constructor( options = {} ) {
        // Configuration
        this.cacheEnabled = options.cacheEnabled !== false; // Default true
        this.maxAge = options.maxAge || 24 * 60 * 60 * 1000; // 24 hours
        this.maxSize = options.maxSize || 50 * 1024 * 1024; // 50MB
        this.debug = options.debug || false;
        
        // In-memory cache for quick access
        this.memoryCache = new Map();
        
        // IndexedDB persistence
        this.dbName = 'TTSAudioCache';
        this.dbVersion = 1;
        this.db = null;
        
        // Statistics
        this.stats = {
            hits: 0,
            misses: 0,
            stores: 0,
            totalSize: 0
        };
        
        if ( this.debug ) console.log( 'TTSAudioCache: Initialized with', options );
    }
    
    async initialize() {
        if ( !this.cacheEnabled ) {
            if ( this.debug ) console.log( 'TTSAudioCache: Caching disabled' );
            return;
        }
        
        try {
            await this.initializeIndexedDB();
            this.scheduleCleanup();
            if ( this.debug ) console.log( 'TTSAudioCache: Ready' );
        } catch ( error ) {
            console.warn( 'TTSAudioCache: IndexedDB failed, using memory-only cache:', error );
        }
    }
    
    async generateCacheKey( text ) {
        const encoder = new TextEncoder();
        const data = encoder.encode( text.trim().toLowerCase() ); // Normalize text
        const hashBuffer = await crypto.subtle.digest( 'SHA-256', data );
        const hashArray = Array.from( new Uint8Array( hashBuffer ) );
        return hashArray.map( b => b.toString( 16 ).padStart( 2, '0' ) ).join( '' );
    }
    
    async initializeIndexedDB() {
        return new Promise( ( resolve, reject ) => {
            const request = indexedDB.open( this.dbName, this.dbVersion );
            
            request.onerror = () => reject( request.error );
            request.onsuccess = () => {
                this.db = request.result;
                resolve();
            };
            
            request.onupgradeneeded = ( event ) => {
                const db = event.target.result;
                if ( !db.objectStoreNames.contains( 'audioCache' ) ) {
                    const store = db.createObjectStore( 'audioCache', { keyPath: 'key' } );
                    store.createIndex( 'timestamp', 'timestamp', { unique: false } );
                }
            };
        } );
    }
    
    async checkCache( text ) {
        if ( !this.cacheEnabled ) return null;
        
        try {
            const key = await this.generateCacheKey( text );
            
            // Check in-memory cache first (fastest)
            if ( this.memoryCache.has( key ) ) {
                const entry = this.memoryCache.get( key );
                if ( !this.isExpired( entry ) ) {
                    this.stats.hits++;
                    if ( this.debug ) console.log( 'TTSAudioCache: Memory hit for', text.substring( 0, 30 ) + '...' );
                    return entry.audioBlob; // Return the Blob directly
                } else {
                    // Remove expired entry
                    this.memoryCache.delete( key );
                }
            }
            
            // Check IndexedDB (persistent)
            if ( this.db ) {
                const entry = await this.getFromIndexedDB( key );
                if ( entry && !this.isExpired( entry ) ) {
                    // Add back to memory cache
                    this.memoryCache.set( key, entry );
                    this.stats.hits++;
                    if ( this.debug ) console.log( 'TTSAudioCache: IndexedDB hit for', text.substring( 0, 30 ) + '...' );
                    return entry.audioBlob; // Return the Blob directly
                }
            }
            
            // Cache miss
            this.stats.misses++;
            if ( this.debug ) console.log( 'TTSAudioCache: Miss for', text.substring( 0, 30 ) + '...' );
            return null;
            
        } catch ( error ) {
            console.error( 'TTSAudioCache: Check failed:', error );
            return null;
        }
    }
    
    async saveToCache( text, audioBlob ) {
        if ( !this.cacheEnabled || !audioBlob ) return;
        
        try {
            const key = await this.generateCacheKey( text );
            const entry = {
                key,
                text: text.substring( 0, 100 ), // Store truncated text for debugging
                audioBlob,
                timestamp: Date.now(),
                size: audioBlob.size
            };
            
            // Store in memory cache
            this.memoryCache.set( key, entry );
            
            // Store in IndexedDB
            if ( this.db ) {
                await this.saveToIndexedDB( entry );
            }
            
            // Update stats
            this.stats.stores++;
            this.stats.totalSize += audioBlob.size;
            
            if ( this.debug ) console.log( `TTSAudioCache: Stored ${audioBlob.size} bytes for "${text.substring( 0, 30 )}..."` );
            
            // Cleanup if needed
            await this.cleanupIfNeeded();
            
        } catch ( error ) {
            console.error( 'TTSAudioCache: Save failed:', error );
        }
    }
    
    async getFromIndexedDB( key ) {
        if ( !this.db ) return null;
        
        return new Promise( ( resolve ) => {
            const transaction = this.db.transaction( ['audioCache'], 'readonly' );
            const store = transaction.objectStore( 'audioCache' );
            const request = store.get( key );
            
            request.onsuccess = () => resolve( request.result );
            request.onerror = () => resolve( null );
        } );
    }
    
    async saveToIndexedDB( entry ) {
        if ( !this.db ) return;
        
        return new Promise( ( resolve, reject ) => {
            const transaction = this.db.transaction( ['audioCache'], 'readwrite' );
            const store = transaction.objectStore( 'audioCache' );
            const request = store.put( entry );
            
            request.onsuccess = () => resolve();
            request.onerror = () => reject( request.error );
        } );
    }
    
    isExpired( entry ) {
        return Date.now() - entry.timestamp > this.maxAge;
    }
    
    async cleanupIfNeeded() {
        // Simple cleanup: remove expired entries when total size exceeds limit
        if ( this.stats.totalSize > this.maxSize ) {
            await this.cleanup();
        }
    }
    
    async cleanup() {
        const beforeSize = this.stats.totalSize;
        let removedSize = 0;
        
        // Clean memory cache
        for ( const [key, entry] of this.memoryCache ) {
            if ( this.isExpired( entry ) ) {
                this.memoryCache.delete( key );
                removedSize += entry.size;
            }
        }
        
        // Clean IndexedDB (remove expired entries)
        if ( this.db ) {
            const transaction = this.db.transaction( ['audioCache'], 'readwrite' );
            const store = transaction.objectStore( 'audioCache' );
            const request = store.openCursor();
            
            request.onsuccess = ( event ) => {
                const cursor = event.target.result;
                if ( cursor ) {
                    const entry = cursor.value;
                    if ( this.isExpired( entry ) ) {
                        cursor.delete();
                        removedSize += entry.size || 0;
                    }
                    cursor.continue();
                }
            };
        }
        
        this.stats.totalSize = Math.max( 0, beforeSize - removedSize );
        if ( this.debug && removedSize > 0 ) {
            console.log( `TTSAudioCache: Cleaned up ${removedSize} bytes` );
        }
    }
    
    scheduleCleanup() {
        // Run cleanup every 30 minutes
        setInterval( () => this.cleanup(), 30 * 60 * 1000 );
    }
    
    getStats() {
        const hitRate = this.stats.hits + this.stats.misses > 0 
            ? ( this.stats.hits / ( this.stats.hits + this.stats.misses ) * 100 ).toFixed( 1 )
            : 0;
            
        return {
            enabled: this.cacheEnabled,
            hits: this.stats.hits,
            misses: this.stats.misses,
            stores: this.stats.stores,
            hitRate: `${hitRate}%`,
            totalSize: `${( this.stats.totalSize / 1024 / 1024 ).toFixed( 2 )} MB`,
            entries: this.memoryCache.size
        };
    }
    
    clearCache() {
        // Clear memory cache
        this.memoryCache.clear();
        
        // Clear IndexedDB
        if ( this.db ) {
            const transaction = this.db.transaction( ['audioCache'], 'readwrite' );
            transaction.objectStore( 'audioCache' ).clear();
        }
        
        // Reset stats
        this.stats = { hits: 0, misses: 0, stores: 0, totalSize: 0 };
        
        if ( this.debug ) console.log( 'TTSAudioCache: Cache cleared' );
    }
}

// Export for use in other modules
if ( typeof module !== 'undefined' && module.exports ) {
    module.exports = TTSAudioCache;
}