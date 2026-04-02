export type Stop = {
    id: string;
    name: string;
    type: "bus" | "rail";
    lat: number;
    lon: number;
};
