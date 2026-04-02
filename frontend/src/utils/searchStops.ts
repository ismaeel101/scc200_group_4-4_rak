import { Stop } from "../types/stop";

export async function searchStops(query: string, limit = 10): Promise<Stop[]> {
    if (!query || query.length < 2) return [];
    const url = `/stops?query=${encodeURIComponent(query)}&limit=${limit}`;
    const res = await fetch(url, { credentials: "same-origin" });

    if (res.status === 404) return [];
    if (!res.ok) throw new Error(`Search failed: ${res.status}`);

    const data = (await res.json()) as Stop[];
    return data;
}
