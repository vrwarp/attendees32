import { test, expect } from '@playwright/test';

import { signInAsJack } from './seed';

test.describe('AttendingMeet Report List View', () => {

  test.beforeEach(async ({ page }) => {
    await signInAsJack(page);
  });

  test('David should be in same family as Abigail and Chileab, single and double clicks work', async ({ page }) => {
    test.setTimeout(60000); // give it plenty of time
    
    // 1. Navigate to the report
    // The report wires up its click handler only once Paged.js has laid it
    // out, and says so with a count alert; a click before then is lost.
    const counted = page.waitForEvent('dialog');
    await page.goto('/persons/attendingmeet_report/?meet=d7c8Fd_cfcch_congregation_member&showPaused=true&divisions=cfcch_children_ministry&divisions=cfcch_crossing_ministry&divisions=cfcch_chinese_ministry&divisions=cfcch_unspecified&divisions=cfcch_special_conference&divisions=cfcch_data_management');
    
    await (await counted).dismiss();
    
    // 2. Locate David's member div
    const davidAttendeeId = '0498c414-abd3-4173-add1-5e42053760e4';
    const davidLocator = page.locator(`div.member[data-attendee-id="${davidAttendeeId}"]`);
    await expect(davidLocator).toBeVisible();
    
    // 3. Verify David is in the same family as Abigail and Chileab
    // Get the parent .members-container
    const membersContainer = davidLocator.locator('xpath=..');
    
    // Check that Abigail is in this container
    await expect(membersContainer).toContainText('Abigail');
    
    // Check that Chileab is in this container
    await expect(membersContainer).toContainText('Chileab');
    
    // Check that David is also in this container
    await expect(membersContainer).toContainText('David');
    
    // 4. Test Single Click (Toggle Pause)
    const initialTextDecoration = await davidLocator.evaluate(el => window.getComputedStyle(el).textDecoration);
    const initialHasPausedClass = await davidLocator.evaluate(el => el.classList.contains('paused'));
    
    // Click on the member
    await davidLocator.click();
    
    // Wait for network response (PATCH)
    const patchResponse = await page.waitForResponse(response => 
      response.url().includes('/persons/api/datagrid_data_attendingmeet/') && response.request().method() === 'PATCH'
    );
    expect(patchResponse.status()).toBe(200);
    
    // Wait for class toggled
    if (initialHasPausedClass) {
      await expect(davidLocator).not.toHaveClass(/paused/);
    } else {
      await expect(davidLocator).toHaveClass(/paused/);
    }
    
    // 5. Test Double Click (Add Note)
    const noteText = 'Test Note Added from E2E';
    
    // Handle the prompt dialog automatically
    page.on('dialog', async dialog => {
      console.log(`Dialog message: ${dialog.message()}`);
      if (dialog.type() === 'prompt') {
        await dialog.accept(noteText);
      } else {
        await dialog.accept();
      }
    });
    
    // Double click the member
    await davidLocator.dblclick();
    
    // Wait for the second PATCH network response
    const secondPatchResponse = await page.waitForResponse(response => 
      response.url().includes('/persons/api/datagrid_data_attendingmeet/') && response.request().method() === 'PATCH'
    );
    expect(secondPatchResponse.status()).toBe(200);
    
    // Verify the title attribute is updated to the note text
    await expect(davidLocator).toHaveAttribute('title', noteText);
    
    // Ensure the pause state did NOT change during the double click
    if (initialHasPausedClass) {
      // It was initially paused, single click unpaused it, so now it should still be unpaused
      await expect(davidLocator).not.toHaveClass(/paused/);
    } else {
      // It was initially unpaused, single click paused it, so now it should still be paused
      await expect(davidLocator).toHaveClass(/paused/);
    }
  });
});
