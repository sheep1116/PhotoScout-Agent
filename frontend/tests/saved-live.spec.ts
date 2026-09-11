import {test, expect} from '@playwright/test';

test('saved Live result renders real candidate, source and images after restart',async({page,request})=>{
  const id=process.env.E2E_LIVE_PLAN;
  test.skip(!id,'Explicit saved Live result required; this test never creates paid research.');
  const result=await request.get(`/v1/plans/${id}`);
  expect(result.ok()).toBeTruthy();
  const plan=await result.json();
  expect(plan.presentation).toBe('candidates');
  expect(plan.brief.mode).toBe('live');
  const history=await (await request.get('/v1/plans')).json();
  const index=history.findIndex((item:{id:string})=>item.id===id);
  expect(index).toBeGreaterThanOrEqual(0);
  await page.route('**/v1/location/**',route=>route.fulfill({json:{city:null,note:'验收使用已保存结果'}}));
  await page.goto('/');
  // Wait for hydration, rather than clicking the server-rendered shell.
  await expect(page.getByLabel('开始时间',{exact:true})).not.toHaveValue('');
  await page.getByRole('button',{name:'我的发现',exact:true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.locator('.history-row')).toHaveCount(history.length);
  await page.locator('.history-row').nth(index).click();
  await expect(page.getByRole('heading',{name:'值得拍的候选机位',exact:true})).toBeVisible();
  await expect(page.locator('.task-card')).toHaveCount(plan.tasks.length);
  await expect(page.locator('.task-card').first()).toContainText(plan.spots.find((s:{id:string})=>s.id===plan.tasks[0].spot_id).name);
  const photo=page.locator('.photo-gallery img').first();
  await expect(photo).toBeVisible();
  await expect.poll(()=>photo.evaluate((el:HTMLImageElement)=>el.complete&&el.naturalWidth>0)).toBeTruthy();
  await page.screenshot({path:'test-results/saved-live-candidates.png',fullPage:true});
  await page.locator('.result-tabs').getByRole('button',{name:/证据与来源/}).click();
  await expect(page.locator('.source-card')).toHaveCount(plan.sources.length);
});
