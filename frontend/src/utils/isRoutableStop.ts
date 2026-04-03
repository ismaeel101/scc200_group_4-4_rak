/**
 * Returns true if the given stop ID looks like a valid NaPTAN ATCO code
 * (alphanumeric, 8-12 chars) or a rail ID ("RAIL:...").  This is used by
 * the frontend to gate whether a stop can be sent to the planner.
 *
 * NaPTAN ATCO codes are NOT purely numeric — examples:
 *   0170SGB20753, 1800NF30701, 340000006R1, RAIL:MAN
 */
export default function isRoutableStop(id?: string | null): boolean {
    if (!id) return false;
    try {
        const s = String(id).trim();
        if (s.length === 0) return false;
        // Rail station IDs
        if (s.startsWith('RAIL:')) return s.length > 5;
        // NaPTAN ATCO codes: alphanumeric, 8-12 characters
        if (/^[A-Za-z0-9]{8,12}$/.test(s)) return true;
        // Legacy numeric-only codes
        if (/^\d{9,12}$/.test(s)) return true;
        return false;
    } catch (e) {
        return false;
    }
}
