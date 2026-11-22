export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}
export function date(value) {
  return value ? '22 nov, 10:45' : 'Sin registro';
}
export async function write(url, body) {
  return { url, body };
}
