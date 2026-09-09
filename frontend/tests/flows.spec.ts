import {test, expect, Page} from '@playwright/test';

async function generate(page:Page) {
  await page.getByRole('button',{name:'生成我的拍摄计划',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('让我们对齐这次出发');
  await page.getByRole('button',{name:'确认需求，开始侦察'}).click();
  await expect(page.getByRole('heading',{name:'你的拍摄计划',exact:true})).toBeVisible();
  await expect(page.locator('.task-card')).toHaveCount(4);
}

test('portrait: generate, inspect evidence, reject, approve and undo', async({page})=>{
  await page.goto('/');
  await generate(page);
  await page.getByRole('button',{name:'规则依据 ↗'}).first().click();
  await expect(page.getByRole('dialog')).toContainText('曝光建议起点');
  await page.getByRole('button',{name:'关闭证据'}).click();
  const original = await page.locator('.task-card').nth(1).innerText();
  await page.getByRole('button',{name:'天气变差',exact:true}).first().click();
  await expect(page.getByRole('dialog')).toContainText('正式计划尚未修改');
  await page.getByRole('button',{name:'拒绝，保留原计划'}).click();
  await expect(page.locator('.version')).toHaveText('V1');
  await page.getByRole('button',{name:'天气变差',exact:true}).first().click();
  await page.getByRole('button',{name:'批准并保存'}).click();
  await expect(page.locator('.version')).toHaveText('V2');
  await expect(page.locator('.task-card').first()).toContainText('已取消');
  expect(await page.locator('.task-card').nth(1).innerText()).toBe(original);
  await page.getByRole('button',{name:'撤销修改'}).click();
  await expect(page.locator('.version')).toHaveText('V3');
  await expect(page.locator('.task-card').first()).not.toContainText('已取消');
});

test('cityscape seed: tripod advice and offline sources', async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'蓝调时刻的南京 南京 · 城市夜景'}).click();
  await generate(page);
  await expect(page.locator('.camera-strip').first()).toContainText('100');
  await expect(page.locator('.plan-summary')).toContainText('蓝调');
  await page.locator('.result-tabs').getByRole('button',{name:/证据与来源/}).click();
  await expect(page.locator('.source-card').first()).toContainText('离线示例');
});

test('missing date asks before generation', async({page})=>{
  await page.goto('/');
  await page.getByLabel('拍摄日期',{exact:true}).fill('');
  await page.getByRole('button',{name:'生成我的拍摄计划',exact:true}).click();
  await expect(page.getByRole('alert').first()).toContainText('请确认具体拍摄日期');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('coordinate edits require approval and preserve other tasks', async({page})=>{
  await page.goto('/'); await generate(page);
  await page.getByRole('button',{name:'记录站位 / 入口 ↗'}).click();
  await page.getByLabel('确认纬度',{exact:true}).fill('32.0525');
  await page.getByRole('button',{name:'生成位置修改提案'}).click();
  await expect(page.getByRole('dialog')).toContainText('/spots/0/camera/lat');
  await expect(page.locator('.version')).toHaveText('V1');
  await page.getByRole('button',{name:'批准并保存'}).click();
  await expect(page.locator('.version')).toHaveText('V2');
});

test('mobile 390px: no horizontal overflow and full generation',async({page})=>{
  await page.setViewportSize({width:390,height:844}); await page.goto('/');
  await generate(page);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.getByRole('button',{name:'天气变差',exact:true}).first().click();
  await expect(page.getByRole('button',{name:'批准并保存'})).toBeVisible();
});

test('mock generates with all third party requests blocked',async({page})=>{
  await page.route('**/*', route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  await page.goto('/'); await generate(page);
  await expect(page.locator('.task-card').first()).toContainText('演示数据');
});
