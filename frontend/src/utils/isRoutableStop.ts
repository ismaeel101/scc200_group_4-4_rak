/**
 * Check whether a stop ID looks like a valid routable stop.
 *
 * NaPTAN ATCO codes extracted from TransXChange timetable data are
 * alphanumeric strings (e.g. "1290BOB20410", "1980SN120553").
 * Rail stops use a "RAIL:CRS" format (e.g. "RAIL:LAN").
 *
 * We accept any non-empty string that is at least 3 characters long.
 * The actual routability is validated server-side against bus.stop_times.
 */
export default function isRoutableStop(id?: string | null): boolean {
    if (!id) return false;
    try {
        const s = String(id).trim();
        // Minimum length and basic sanity — no prefix restrictions
        return s.length >= 3;
    } catch (e) {
        return false;
    }
}
