// Browser-side custom SEC store (IndexedDB). Used by sec_edit / sec_map.
(function (global) {
  const DB_NAME = 'mra_custom_secs';
  const STORE = 'secs';
  const PENDING_KEY = 'mra_sec_place_pending';

  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'filename' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function putSec(rec) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(rec);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async function getSec(filename) {
    if (!filename) return null;
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).get(filename);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  }

  async function listSecs() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  function setPendingPlace(place) {
    localStorage.setItem(PENDING_KEY, JSON.stringify(place));
  }

  function takePendingPlace() {
    try {
      const raw = localStorage.getItem(PENDING_KEY);
      if (!raw) return null;
      localStorage.removeItem(PENDING_KEY);
      return JSON.parse(raw);
    } catch (_e) {
      try { localStorage.removeItem(PENDING_KEY); } catch (_e2) {}
      return null;
    }
  }

  function bytesToBase64(u8) {
    let s = '';
    const chunk = 0x8000;
    for (let i = 0; i < u8.length; i += chunk) {
      s += String.fromCharCode.apply(null, u8.subarray(i, i + chunk));
    }
    return btoa(s);
  }

  function base64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  /** Normalize record so bytes are always ArrayBuffer-backed Uint8Array-friendly. */
  function normalizeRecord(rec) {
    if (!rec) return null;
    let bytes = rec.bytes;
    if (typeof bytes === 'string') bytes = base64ToBytes(bytes).buffer;
    else if (bytes instanceof Uint8Array) bytes = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    else if (bytes instanceof ArrayBuffer) { /* ok */ }
    else if (bytes && bytes.buffer) bytes = bytes.buffer;
    return Object.assign({}, rec, { bytes });
  }

  global.CustomSecs = {
    put: putSec,
    get: async (fn) => normalizeRecord(await getSec(fn)),
    list: async () => (await listSecs()).map(normalizeRecord),
    setPendingPlace,
    takePendingPlace,
    bytesToBase64,
    base64ToBytes,
    PENDING_KEY
  };
})(window);
