import { Stop } from "../types/stop";

type CacheEntry = { at: number; rows: Stop[] };
const SEARCH_TTL_MS = 60_000;
const searchCache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<Stop[]>>();

export async function searchStops(query: string, limit = 10): Promise<Stop[]> {
    if (!query || query.length < 2) return [];
    const key = `${query.trim().toLowerCase()}|${limit}`;
    const cached = searchCache.get(key);
    if (cached && Date.now() - cached.at < SEARCH_TTL_MS) {
        return cached.rows;
    }

    if (inflight.has(key)) {
        return inflight.get(key)!;
    }

    const backendBase = `${window.location.protocol}//${window.location.hostname}:8000`;
    const promise = (async () => {
        const url = `${backendBase}/stops?query=${encodeURIComponent(query)}&limit=${limit}`;
        const res = await fetch(url);

        if (res.status === 404) return [];
        if (res.ok) {
            const data = (await res.json()) as Stop[];
            return data;
        }

        // Fallback: use /api/stops with regional bbox and filter client-side
        const fallbackUrl = `${backendBase}/api/stops?min_lat=53.0&max_lat=55.2&min_lon=-4.8&max_lon=-1.0&limit=500`;
        const fallbackRes = await fetch(fallbackUrl);
        if (!fallbackRes.ok) throw new Error(`Search failed: ${res.status}`);

        const rows = (await fallbackRes.json()) as any[];
        const q = query.toLowerCase();
        return (Array.isArray(rows) ? rows : [])
            .filter((s) => String(s?.name || '').toLowerCase().includes(q))
            .slice(0, limit)
            .map((s) => ({
                id: String(s.id),
                name: String(s.name),
                type: s.type === 'rail' ? 'rail' : 'bus',
                lat: Number(s.lat),
                lon: Number(s.lon),
            }));
    })();

    inflight.set(key, promise);
    try {
        const rows = await promise;
        searchCache.set(key, { at: Date.now(), rows });
        return rows;
    } finally {
        inflight.delete(key);
    }
}
