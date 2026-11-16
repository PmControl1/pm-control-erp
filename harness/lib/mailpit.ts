import { MAIL_URL } from './env';

type Summary = { ID: string; To: Array<{ Address: string }>; Subject: string };
export type Email = { subject: string; text: string; html: string };

/** Wait for the newest email to `address` that the app sent to Mailpit. */
export async function waitForEmail(address: string, timeoutMs = 30_000): Promise<Email> {
  const deadline = Date.now() + timeoutMs;
  const wanted = address.toLowerCase();
  while (Date.now() < deadline) {
    const list = (await (await fetch(`${MAIL_URL}/api/v1/messages?limit=50`)).json()) as { messages: Summary[] };
    const hit = list.messages.find((m) => m.To.some((t) => t.Address.toLowerCase() === wanted));
    if (hit) {
      const full = (await (await fetch(`${MAIL_URL}/api/v1/message/${hit.ID}`)).json()) as {
        Subject: string;
        Text: string;
        HTML: string;
      };
      return { subject: full.Subject, text: full.Text ?? '', html: full.HTML ?? '' };
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`No email to ${address} arrived within ${timeoutMs / 1000}s (Mailpit: ${MAIL_URL})`);
}

/** The first link in an email whose path starts with `pathPrefix`. */
export function linkIn(email: Email, pathPrefix: string): string {
  const source = `${email.text}\n${email.html.replaceAll('&amp;', '&')}`;
  for (const match of source.matchAll(/https?:\/\/[^\s"'<>]+/g)) {
    const url = new URL(match[0]);
    if (url.pathname.startsWith(pathPrefix)) return url.toString();
  }
  throw new Error(`The email "${email.subject}" has no link to ${pathPrefix}`);
}
