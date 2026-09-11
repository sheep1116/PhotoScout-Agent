import {test, expect, Page} from '@playwright/test';

test.beforeEach(async({page})=>{
  await page.route('**/v1/location/**',route=>route.fulfill({json:{city:'南京市',note:'测试定位默认值'}}));
});

async function generate(page:Page) {
  await page.getByRole('button',{name:'发现值得拍的机位',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('让我们对齐这次出发');
  await page.getByRole('button',{name:'确认需求，开始侦察'}).click();
  await expect(page.getByRole('heading',{name:'值得拍的候选机位',exact:true})).toBeVisible();
  await expect(page.locator('.task-card')).toHaveCount(4);
}

test('portrait: generate, inspect evidence, reject, approve and undo', async({page})=>{
  await page.goto('/'); await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click();
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
  await page.goto('/'); await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click();
  await page.getByRole('button',{name:'蓝调时刻的南京 南京 · 城市夜景'}).click();
  await generate(page);
  await expect(page.locator('.camera-strip').first()).toContainText('100');
  await expect(page.locator('.task-card').first()).toContainText('蓝调');
  await page.locator('.result-tabs').getByRole('button',{name:/证据与来源/}).click();
  await expect(page.locator('.source-card').first()).toContainText('离线示例');
});

test('missing date asks before generation', async({page})=>{
  await page.goto('/'); await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click();
  await page.getByLabel('拍摄日期',{exact:true}).fill('');
  await page.getByRole('button',{name:'发现值得拍的机位',exact:true}).click();
  await expect(page.getByRole('alert').first()).toContainText('请确认具体拍摄日期');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('coordinate edits require approval and preserve other tasks', async({page})=>{
  await page.goto('/'); await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click(); await generate(page);
  await page.getByRole('button',{name:'记录站位 / 入口 ↗'}).click();
  await page.getByLabel('确认纬度',{exact:true}).fill('32.0525');
  await page.getByRole('button',{name:'生成位置修改提案'}).click();
  await expect(page.getByRole('dialog')).toContainText('/spots/0/camera/lat');
  await expect(page.locator('.version')).toHaveText('V1');
  await page.getByRole('button',{name:'批准并保存'}).click();
  await expect(page.locator('.version')).toHaveText('V2');
});

test('mobile 390px: no horizontal overflow and full generation',async({page})=>{
  await page.goto('/'); await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click(); await page.setViewportSize({width:390,height:844});
  await generate(page);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.getByRole('button',{name:'天气变差',exact:true}).first().click();
  await expect(page.getByRole('button',{name:'批准并保存'})).toBeVisible();
});

test('mock generates with all third party requests blocked',async({page})=>{
  await page.route('**/*', route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  await page.goto('/'); await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click(); await generate(page);
  await expect(page.locator('.task-card').first()).toContainText('演示数据');
});

test('composable intent persists all conditions and supports every candidate', async({page})=>{
  await page.goto('/'); await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click();
  await page.getByRole('button',{name:'风光',exact:true}).click();
  await page.getByRole('button',{name:'人像',exact:true}).click();
  await page.getByRole('button',{name:'建筑',exact:true}).click();
  await page.getByText('组合你的画面与光线',{exact:true}).click();
  await page.getByLabel('拍摄主体',{exact:true}).fill('湖面，古建筑');
  await page.getByLabel('画面风格',{exact:true}).fill('极简，倒影');
  await page.getByLabel('偏好光线',{exact:true}).selectOption('daylight');
  const response = page.waitForResponse(r=>r.url().endsWith('/v1/notebook'));
  await generate(page);
  const notebook = await (await response).json();
  expect(notebook.brief.intent.categories).toEqual(['architecture','landscape']);
  expect(notebook.brief.intent.styles).toEqual(['极简','倒影']);
  expect(notebook.brief.intent.subjects).toEqual(['湖面','古建筑']);
  expect(notebook.brief.intent.equipment.lenses).toHaveLength(2);
  expect(notebook.brief.intent.preferences.max_walk_km).toBe(2);
  expect(notebook.brief.profile).toBeUndefined();
  await page.getByRole('button',{name:/候选机位/}).click();
  await expect(page.locator('.task-card')).toHaveCount(4);
  await expect(page.locator('.photo-empty').first()).toContainText('暂无真实参考图');
});

test('reference gallery attribution, switching and broken-image fallback', async({page})=>{
  // Explicit UI-only fixtures; live images are verified separately by product_acceptance.py.
  await page.route('**/v1/plans/*', async route=>{
    if(route.request().method()!=='GET')return route.continue();
    const response = await route.fetch();
    const plan = await response.json();
    if(!plan.spots)return route.fulfill({response});
    plan.spots[0].photo_references = [1,2].map(i=>({id:`fixture-photo-${i}`,provider:'wikimedia',
      source_url:'https://commons.wikimedia.org/wiki/Commons:Licensing',title:`测试夹具图片 ${i}（非现场）`,
      author:'UI 测试夹具',license:'仅供自动化测试',retrieved_at:'2026-09-10T00:00:00Z',captured_at:null,
      relation:'nearby',latitude:null,longitude:null,exif:{},evidence_ids:plan.spots[0].camera.evidence_ids}));
    await route.fulfill({response,json:plan});
  });
  await page.route('**/photos/fixture-photo-*', async route=>{
    if(route.request().url().endsWith('-2'))return route.fulfill({status:502,body:'unavailable'});
    await route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64')});
  });
  await page.goto('/'); await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click(); await generate(page);
  const gallery=page.locator('.photo-gallery').first();
  await expect(gallery.getByRole('img')).toBeVisible();
  await expect(gallery).toContainText('附近参考 · 非精确站位样片');
  await gallery.getByRole('button',{name:'展开完整图片',exact:true}).click();
  await expect(gallery.locator('.photo-cover')).toHaveClass(/full/);
  await gallery.getByText('作者、授权与拍摄信息',{exact:true}).click();
  await expect(gallery).toContainText('UI 测试夹具');
  await expect(gallery.getByRole('link',{name:'查看原始来源 ↗'})).toHaveAttribute('href',/commons.wikimedia.org/);
  await gallery.getByRole('button',{name:'2 · wikimedia',exact:true}).click();
  await expect(gallery).toContainText('图片暂时无法加载');
  await expect(page.locator('.task-card')).toHaveCount(4);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});
