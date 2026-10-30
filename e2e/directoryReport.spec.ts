import { test, expect } from '@playwright/test';

import { signInAsJack } from './seed';

test.describe('Directory Report List View', () => {

  test.beforeEach(async ({ page }) => {
    await signInAsJack(page);
  });

  test('Should print Isaac twice because he is in both his own family and parents family', async ({ page }) => {
    // Navigate to the directory report with specific divisions
    await page.goto('/persons/directory_report/?divisionSelector=0&divisionSelector=1&divisionSelector=2&divisionSelector=3&divisionSelector=5&divisionSelector=6');
    
    // The page is laid out by Paged.js, which moves the content into
    // .pagedjs_pages; wait for the first laid-out page rather than for <body>.
    await page.waitForSelector('.pagedjs_pages .pagedjs_page');
    
    // Wait until "Isaac" or "Isaac" appears in the DOM
    await page.waitForFunction(() => document.body.innerText.includes('Isaac'));
    
    // Evaluate the page text to count how many times "Isaac" appears.
    const elementsWithIsaac = await page.evaluate(() => {
      const bodyText = document.body.innerText;
      const count = (bodyText.match(/Isaac/g) || []).length;
      return count;
    });

    console.log(`Found ${elementsWithIsaac} occurrences of "Isaac"`);
    
    // The test passes if Isaac appears at least twice (once in parents' family, once in his own family)
    expect(elementsWithIsaac).toBeGreaterThanOrEqual(2);
  });
});
