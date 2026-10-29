export type GatewayPoint = [number, number];
export function gatewayPoint(latitude: string, longitude: string): GatewayPoint | null {
  if (!latitude.trim() || !longitude.trim()) return null;
  const lat=Number(latitude),lon=Number(longitude);
  return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat)<=90 && Math.abs(lon)<=180 ? [lat,lon] : null;
}
export function hasGatewayPosition(gateway: {latitude?: number | null; longitude?: number | null}): boolean {
  return gateway.latitude!=null && gateway.longitude!=null && Number.isFinite(gateway.latitude) && Number.isFinite(gateway.longitude) && Math.abs(gateway.latitude)<=90 && Math.abs(gateway.longitude)<=180;
}
export const gatewayStatus: Record<string,string> = { installed:'Instalado',maintenance:'Mantenimiento',retired:'Retirado' };
