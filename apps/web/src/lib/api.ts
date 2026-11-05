const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export async function nexusFetch<T>(
  endpoint: string,
  token: string,
  orgId: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      'X-Organization-Id': orgId,
      ...(options.headers || {}),
    },
  });
  const body = await res.json();
  if (!res.ok || !body.success) {
    throw new Error(body.message || `API Error: ${res.status}`);
  }
  return body.data as T;
}
