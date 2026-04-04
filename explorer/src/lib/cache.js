/**
 * Client-side data cache.
 * Prevents redundant API calls when switching tabs.
 * Cache entries are invalidated on explicit refresh or after a TTL.
 */

const DEFAULT_TTL = 5 * 60 * 1000; // 5 minutes

const cache = new Map();

/**
 * Get a cached value, or fetch it if missing/stale.
 * @param {string} key - Cache key
 * @param {Function} fetcher - Async function that returns the value
 * @param {number} ttl - Time-to-live in ms (default 5 min)
 * @returns {Promise<any>}
 */
export async function cachedFetch(key, fetcher, ttl = DEFAULT_TTL) {
  const entry = cache.get(key);
  if (entry && Date.now() - entry.ts < ttl) {
    return entry.value;
  }

  // If there's already an inflight request for this key, return it.
  if (entry?.promise) {
    return entry.promise;
  }

  const promise = fetcher().then(value => {
    cache.set(key, { value, ts: Date.now(), promise: null });
    return value;
  }).catch(err => {
    // Remove failed promise so next call retries.
    if (cache.get(key)?.promise === promise) {
      cache.delete(key);
    }
    throw err;
  });

  cache.set(key, { ...(entry || {}), promise });
  return promise;
}

/**
 * Invalidate a specific cache key or all keys matching a prefix.
 */
export function invalidateCache(keyOrPrefix) {
  if (!keyOrPrefix) {
    cache.clear();
    return;
  }
  for (const key of cache.keys()) {
    if (key === keyOrPrefix || key.startsWith(keyOrPrefix + ':')) {
      cache.delete(key);
    }
  }
}

/**
 * Check if a key is cached and fresh.
 */
export function isCached(key) {
  const entry = cache.get(key);
  return entry && Date.now() - entry.ts < DEFAULT_TTL;
}
