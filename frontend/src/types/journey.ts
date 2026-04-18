// Official Journey data contract used by the app

export type TransportMode =
    | 'train'
    | 'rail'
    | 'bus'
    | 'tram'
    | 'ferry'
    | 'coach'
    | 'metro'
    | 'walk';

export type Coordinates = [number, number]; // [lat, lng]

export interface Leg {
    id: string;
    mode: TransportMode;
    origin: string; // human readable name of the leg start
    destination: string; // human readable name of the leg end
    departureTime: string; // ISO 8601 timestamp or HH:MM
    arrivalTime: string; // ISO 8601 timestamp or HH:MM
    durationMinutes: number;
    routeNumber?: string;
    // legacy aliases sometimes present in mocks
    from?: string;
    to?: string;
    coordinates: {
        from: Coordinates;
        to: Coordinates;
        polyline?: Coordinates[]; // optional intermediate points (lat,lng tuples)
    };
    details?: string; // optional extra info (operator, line name)
}

export interface Journey {
    id: string;
    origin: string;
    destination: string;
    departureTime: string;
    arrivalTime: string;
    totalDurationMinutes: number;
    reliability: 'High' | 'Medium' | 'Low';
    legs: Leg[];
}
