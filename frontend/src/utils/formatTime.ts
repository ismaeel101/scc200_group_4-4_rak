export function formatTime(isoString: string): string {
    try {
        const date = new Date(isoString);
        if (Number.isNaN(date.getTime())) return '';
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        return `${hours}:${minutes}`;
    } catch (e) {
        console.warn('formatTime: invalid isoString', isoString);
        return '';
    }
}
