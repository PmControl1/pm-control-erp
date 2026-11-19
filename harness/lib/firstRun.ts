import type { Page } from '@playwright/test';

/**
 * The owner's first-run "What will you use?" wizard (features/processes)
 * opens over every page until the choice is recorded on the server, and it
 * blocks clicks. stack.sh records the choice when the stack comes up, so this
 * is a fallback: close it the way an owner who decides later does.
 */
export async function closeFirstRunWizard(page: Page, waitMs = 10_000): Promise<boolean> {
  const wizard = page.getByTestId('processes-wizard');
  try {
    await wizard.waitFor({ state: 'visible', timeout: waitMs });
  } catch {
    return false; // Already recorded, or not an owner: nothing to close.
  }
  // Its only header button is the close button, whatever its label says.
  await wizard.locator('header button').first().click();
  await wizard.waitFor({ state: 'detached', timeout: 15_000 });
  return true;
}
