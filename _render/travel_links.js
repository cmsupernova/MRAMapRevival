// Named custom travel / teleport links (holes, stairs, warps).
// Sidecar metadata - destinations are NOT in .SEC bytes (CRT was lost).
// Shared by sec_edit.html and sec_map.html; stored in mra_unified_v1.travelLinks.
(function (global) {
  const LS_KEY = 'mra_unified_v1';

  function readBag() {
    try {
      return JSON.parse(localStorage.getItem(LS_KEY) || '{}') || {};
    } catch (_e) {
      return {};
    }
  }

  function writeBag(bag) {
    localStorage.setItem(LS_KEY, JSON.stringify(bag));
  }

  function load() {
    const bag = readBag();
    return Array.isArray(bag.travelLinks) ? bag.travelLinks : [];
  }

  function save(list) {
    const bag = readBag();
    bag.travelLinks = Array.isArray(list) ? list : [];
    writeBag(bag);
  }

  function newId() {
    return 'tl_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
  }

  function normalizeEnd(end) {
    if (!end || typeof end !== 'object') return null;
    return {
      name: String(end.name || '').trim(),
      filename: end.filename || null,
      col: end.col != null ? +end.col : null,
      row: end.row != null ? +end.row : null,
      level: end.level != null ? +end.level : null,
      r: end.r != null ? +end.r : null,
      c: end.c != null ? +end.c : null
    };
  }

  function normalizeLink(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const from = normalizeEnd(raw.from);
    const to = normalizeEnd(raw.to);
    if (!from || !to) return null;
    return {
      id: raw.id || newId(),
      name: String(raw.name || '').trim() || (from.name && to.name ? from.name + '->' + to.name : 'unnamed'),
      kind: raw.kind || 'custom',
      bidirectional: !!raw.bidirectional,
      from,
      to,
      updated: raw.updated || Date.now()
    };
  }

  function upsert(link) {
    const n = normalizeLink(link);
    if (!n) return null;
    const list = load();
    const i = list.findIndex((x) => x.id === n.id);
    if (i >= 0) list[i] = n;
    else list.push(n);
    save(list);
    return n;
  }

  function remove(id) {
    const list = load().filter((x) => x.id !== id);
    save(list);
    return list;
  }

  function endMatches(end, opts) {
    if (!end || !opts) return false;
    if (opts.filename && end.filename !== opts.filename) return false;
    if (opts.col != null && end.col != null && +end.col !== +opts.col) return false;
    if (opts.row != null && end.row != null && +end.row !== +opts.row) return false;
    if (opts.level != null && end.level != null && +end.level !== +opts.level) return false;
    if (opts.r != null && end.r != null && +end.r !== +opts.r) return false;
    if (opts.c != null && end.c != null && +end.c !== +opts.c) return false;
    if (opts.name && String(end.name || '').toLowerCase() !== String(opts.name).toLowerCase()) return false;
    return true;
  }

  function linksTouching(opts) {
    return load().filter((L) => endMatches(L.from, opts) || endMatches(L.to, opts));
  }

  function linksAtMapCell(col, row, level) {
    return load().filter((L) => {
      const hit = (end) =>
        end && end.col != null && end.row != null &&
        +end.col === +col && +end.row === +row &&
        (end.level == null || +end.level === +level);
      return hit(L.from) || hit(L.to);
    });
  }

  function describeEnd(end) {
    if (!end) return '?';
    const nm = end.name || '(unnamed)';
    const fn = end.filename ? end.filename.replace(/\.SEC$/i, '') : '?';
    const map =
      end.col != null && end.row != null
        ? ' @(' + end.col + ',' + end.row + ') L' + (end.level > 0 ? '+' : '') + (end.level != null ? end.level : '?')
        : '';
    const cell = end.r != null && end.c != null ? ' r' + end.r + 'c' + end.c : '';
    return nm + ' · ' + fn + map + cell;
  }

  global.TravelLinks = {
    LS_KEY,
    load,
    save,
    newId,
    normalizeLink,
    upsert,
    remove,
    linksTouching,
    linksAtMapCell,
    describeEnd,
    KINDS: [
      { id: 'custom', label: 'Custom' },
      { id: 'fall', label: 'Fall / hole' },
      { id: 'stair', label: 'Stairs' },
      { id: 'warp', label: 'Warp' }
    ]
  };
})(typeof window !== 'undefined' ? window : globalThis);
