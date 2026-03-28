import L from "leaflet";
import { Stop } from "../types/stop";

export function displayStops(map: L.Map, stops: Stop[]) {
    const markers: L.Marker[] = [];
    if (!map) return markers;

    stops.forEach((s) => {
        try {
            const marker = L.marker([s.lat, s.lon]).addTo(map).bindPopup(s.name);
            markers.push(marker);
        } catch (e) {
            // skip invalid coords
        }
    });

    return markers;
}
