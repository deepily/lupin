/**
 * IndexedDB cache kit
 *
 * Shared by hybrid-tts.js, job-completion-cache.js and tts-audio-cache.js.
 * It holds a SHA-256 hex key, a database open with one object store, and a read of one row.
 * Load this script before any of them; it defines the global LupinIdbKit.
 */
const LupinIdbKit = {

    /**
     * Returns the SHA-256 hash of the text as a 64-character hex string, for use as a cache key.
     */
    async sha256Hex(text) {
        const data       = new TextEncoder().encode(text);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        return Array.from(new Uint8Array(hashBuffer)).map(b => b.toString(16).padStart(2, '0')).join('');
    },

    /**
     * Opens the database, creating the store when missing.
     *
     * Adds one non-unique index per name in indexNames, on the field of the same name.
     * Resolves with the database handle; rejects with the request error.
     */
    openStore(dbName, dbVersion, storeName, keyPath, indexNames) {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(dbName, dbVersion);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains(storeName)) {
                    const store = db.createObjectStore(storeName, { keyPath });
                    indexNames.forEach(name => store.createIndex(name, name, { unique: false }));
                }
            };
        });
    },

    /**
     * Reads one row by key from the named store; resolves undefined when absent.
     */
    getOne(db, storeName, key) {
        return new Promise((resolve, reject) => {
            const request = db.transaction([storeName], 'readonly').objectStore(storeName).get(key);

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }
};

if (typeof module !== 'undefined' && module.exports) {
    globalThis.LupinIdbKit = LupinIdbKit;
    module.exports = LupinIdbKit;
}
