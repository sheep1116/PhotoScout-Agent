import {test, expect} from '@playwright/test';

test.use({timezoneId:'Asia/Shanghai'});

test('today uses current minute through end of day without automatic research',async({page})=>{
  await page.clock.install({time:new Date('2026-09-11T15:40:00Z')});
  await page.addInitScript(()=>{navigator.geolocation.getCurrentPosition=(_ok,fail)=>fail?.({code:1,message:'denied'} as GeolocationPositionError);});
  await page.route('**/v1/location/ip',route=>route.fulfill({json:{city:'南京市',note:'IP 城市，请核对'}}));
  let searches=0;
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/photo-research'))searches++;});
  await page.goto('/');
  await expect(page.getByLabel('目的地',{exact:true})).toHaveValue('南京市');
  await expect(page.getByLabel('拍摄日期',{exact:true})).toHaveValue('2026-09-11');
  await expect(page.getByLabel('开始时间',{exact:true})).toHaveValue('23:40');
  await expect(page.getByLabel('结束时间',{exact:true})).toHaveValue('23:59');
  await expect(page.getByLabel('结束日期',{exact:true})).toHaveValue('2026-09-11');
  await expect(page.getByText('手机主摄',{exact:true})).toHaveCount(0);
  expect(searches).toBe(0);
});

test('late location never overwrites a manually entered destination',async({page})=>{
  await page.addInitScript(()=>{navigator.geolocation.getCurrentPosition=(_ok,fail)=>fail?.({code:1,message:'denied'} as GeolocationPositionError);});
  let release:()=>void=()=>{};
  const ready=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/v1/location/ip',async route=>{await ready;await route.fulfill({json:{city:'南京市',note:'IP 城市'}});});
  await page.goto('/');
  await page.getByLabel('目的地',{exact:true}).fill('苏州博物馆');
  release();
  await expect(page.locator('.auto-location')).toHaveCount(0);
  await expect(page.getByLabel('目的地',{exact:true})).toHaveValue('苏州博物馆');
});

test('browser location takes priority and defaults end on the selected day',async({page,context})=>{
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({latitude:32.06,longitude:118.79});
  await page.clock.install({time:new Date('2026-09-11T14:10:00Z')});
  let fallback=0;
  await page.route('**/v1/location/ip',route=>{fallback++;return route.fulfill({json:{city:'无锡市',note:'IP'}});});
  await page.route('**/v1/location/reverse',route=>route.fulfill({json:{city:'南京市',note:'浏览器定位'}}));
  await page.goto('/');
  await expect(page.getByLabel('目的地',{exact:true})).toHaveValue('南京市');
  await expect(page.getByLabel('开始时间',{exact:true})).toHaveValue('22:10');
  await expect(page.getByLabel('结束时间',{exact:true})).toHaveValue('23:59');
  await expect(page.getByLabel('拍摄日期',{exact:true})).toHaveValue('2026-09-11');
  await expect(page.getByLabel('结束日期',{exact:true})).toHaveValue('2026-09-11');
  expect(fallback).toBe(0);
});

test('automatic dates follow the selected day and explicit times survive date changes',async({page})=>{
  await page.clock.install({time:new Date('2026-09-11T07:32:45Z')});
  await page.route('**/v1/location/**',route=>route.fulfill({json:{city:'南京市',note:'IP'}}));
  await page.goto('/');
  const date=page.getByLabel('拍摄日期',{exact:true}),start=page.getByLabel('开始时间',{exact:true}),end=page.getByLabel('结束时间',{exact:true});
  await expect(start).toHaveValue('15:32');
  await expect(end).toHaveValue('23:59');
  await date.fill('2026-09-12');
  await expect(start).toHaveValue('00:00');
  await expect(end).toHaveValue('23:59');
  await date.fill('2026-09-11');
  await expect(start).toHaveValue('15:32');
  await start.fill('16:00');
  await end.fill('22:00');
  await date.fill('2026-09-14');
  await expect(start).toHaveValue('16:00');
  await expect(end).toHaveValue('22:00');
  await expect(page.locator('.auto-badge')).toHaveCount(0);
  await page.getByLabel('结束日期',{exact:true}).fill('2026-09-15');
  await end.fill('02:00');
  await date.fill('2026-09-13');
  await expect(page.getByLabel('结束日期',{exact:true})).toHaveValue('2026-09-15');
  await expect(end).toHaveValue('02:00');
});

test('default calculation uses the planning timezone, including DST',async()=>{
  const {defaultWindow,updateBrief}=await import('../lib/defaults');
  expect(defaultWindow(new Date('2026-09-11T07:32:50Z'),undefined,'Asia/Shanghai')).toMatchObject({travel_date:'2026-09-11',start_local:'15:32',end_local:'23:59'});
  expect(defaultWindow(new Date('2026-09-11T00:32:50Z'),undefined,'America/Los_Angeles')).toMatchObject({travel_date:'2026-09-10',start_local:'17:32'});
  expect(defaultWindow(new Date('2026-03-08T10:15:00Z'),undefined,'America/Los_Angeles').start_local).toBe('03:15');
  expect(defaultWindow(new Date('2026-09-11T15:59:55Z'),undefined,'Asia/Shanghai')).toMatchObject({start_local:'23:59',end_local:'23:59'});
  // A matching explicit value must not regain automatic ownership.
  const brief={...defaultWindow(new Date('2026-09-11T07:32:00Z'),undefined,'Asia/Shanghai'),auto_time_fields:['start_local','end_local','end_date']} as import('../lib/types').Brief;
  const edited=updateBrief(brief,{end_local:'23:59'});
  expect(edited.auto_time_fields).not.toContain('end_local');
});

test('contextual hints work with hover, keyboard and mobile taps without moving fields',async({page})=>{
  await page.route('**/v1/location/**',route=>route.fulfill({json:{city:'南京市',note:'IP'}}));
  await page.goto('/');
  await expect(page.locator('.auto-location')).toHaveText('自动定位');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  const hint=page.getByRole('button',{name:'拍摄描述说明'});
  const before=await page.getByLabel('目的地',{exact:true}).boundingBox();
  await hint.hover();
  await expect(page.getByRole('tooltip')).toContainText('手动修改优先');
  expect(await page.getByLabel('目的地',{exact:true}).boundingBox()).toEqual(before);
  await hint.focus();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('heading',{level:1}).click();
  await page.getByRole('button',{name:'拍摄时间说明'}).click();
  await expect(page.getByRole('tooltip')).toContainText('跨午夜');
  const box=await page.getByRole('tooltip').boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x+box!.width).toBeLessThanOrEqual(390);
  await page.getByRole('heading',{level:1}).click();
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await expect(page.getByText('先解析并确认需求，再开始搜索 · Live 描述解析也会调用模型',{exact:true})).toHaveCount(0);
  await page.screenshot({path:'test-results/compact-form-mobile.png',fullPage:true});
});
