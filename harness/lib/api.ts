import { expect, type APIRequestContext } from '@playwright/test';

/** Sign in through the API and return a bearer token. */
export async function signIn(request: APIRequestContext, email: string, password: string): Promise<string> {
  const response = await request.post('/api/v1/users/auth/login/', { data: { email, password } });
  expect(response.status(), `sign-in for ${email}: ${await response.text()}`).toBe(200);
  const body = (await response.json()) as { access_token: string };
  return body.access_token;
}

export function bearer(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}
