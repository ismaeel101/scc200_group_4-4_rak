export default function isRoutableStop(id?: string | null): boolean {
    if (!id) return false;
    try {
        if (!/^\d+$/.test(String(id))) return false;
        return id.startsWith('250') || id.startsWith('450') || id.startsWith('340');
    } catch (e) {
        return false;
    }
}
