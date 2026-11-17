import type { Page } from '@playwright/test';

/**
 * The owner's first-run "What will you use?" wizard (features/processes)
 * opens over every page until the choice is recorded on the server, and it
 * blocks clicks. Close it the way an owner who decides later does: that
 * records the choice with nothing extra started, so it does not come back.
 */
export async function closeFirstRunWizard(page: Page, waitMs = 10_000): Promise<boolean> {
  const wizard = page.getByTestId('processes-wizard');
  try {
    await wizard.waitFor({ state: 'visible', timeout: waitMs });
  } catch {
    return false; // Already recorded, or not an owner: nothing to close.
  }
  await wizard.getByRole('button', { name: /^(Затваряне|Close)$/ }).first().click();
  await wizard.waitFor({ state: 'detached', timeout: 15_000 });
  return true;
}
